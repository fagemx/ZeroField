"""Direct ComfyUI trial of SPEC_21 asset panels with FLUX 3 Klein.

Usage: python -X utf8 klein_trial.py <job.json> <out_dir>
job.json: {"jobs": [{"name", "kind": "t2i"|"ref", "prompt", "seed", "width", "height", "refs": [paths]}]}
"""
import json, mimetypes, os, sys, time, urllib.request, uuid

BASE = os.environ.get("COMFY_BASE_URL", "http://127.0.0.1:8188").rstrip("/")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/oner/ -> the repo root


def call(path, data=None, headers=None):
    req = urllib.request.Request(BASE + path, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.read()


def upload(path):
    boundary = uuid.uuid4().hex
    name = "zf21_" + os.path.basename(path)
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
        f"Content-Type: {mimetypes.guess_type(path)[0] or 'image/png'}\r\n\r\n".encode(), open(path, "rb").read(), b"\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode()])
    return json.loads(call("/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}))["name"]


def t2i_graph(job):
    g = json.load(open(os.path.join(REPO, "workflows", "flux3_klein_soul_cast.json"), encoding="utf-8"))
    g["6"]["inputs"]["text"] = job["prompt"]
    g["3"]["inputs"]["seed"] = job["seed"]
    g["5"]["inputs"]["width"], g["5"]["inputs"]["height"] = job["width"], job["height"]
    g["9"]["inputs"]["filename_prefix"] = "zf21_" + job["name"]
    return g


def ref_graph(job):
    g = json.load(open(os.path.join(REPO, "workflows", "flux3_klein_look_key.json"), encoding="utf-8"))
    for key in ("20", "23", "21", "22"):
        g.pop(key, None)
    ref = g["11"]["inputs"]
    for key in [k for k in ref if k.startswith("images.")]:
        del ref[key]
    for i, path in enumerate(job["refs"]):
        node = str(40 + i)
        g[node] = {"class_type": "LoadImage", "inputs": {"image": upload(path)}}
        ref[f"images.image{i}"] = [node, 0]
    g["6"]["inputs"]["text"] = job["prompt"]
    g["3"]["inputs"]["seed"] = job["seed"]
    g["10"]["inputs"]["width"], g["10"]["inputs"]["height"] = job["width"], job["height"]
    g["7"]["inputs"]["width"], g["7"]["inputs"]["height"] = job["width"], job["height"]
    g["9"]["inputs"]["filename_prefix"] = "zf21_" + job["name"]
    return g


def run(job, out_dir):
    graph = t2i_graph(job) if job["kind"] == "t2i" else ref_graph(job)
    pid = json.loads(call("/prompt", json.dumps({"prompt": graph, "client_id": "zf21"}).encode(),
                          {"Content-Type": "application/json"}))["prompt_id"]
    start = time.time()
    while True:
        hist = json.loads(call(f"/history/{pid}"))
        if pid in hist:
            entry = hist[pid]
            if entry.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(entry["status"])[:2000])
            images = [img for out in entry["outputs"].values() for img in out.get("images", [])]
            if images:
                img = images[0]
                data = call(f"/view?filename={img['filename']}&subfolder={img['subfolder']}&type={img['type']}")
                path = os.path.join(out_dir, job["name"] + ".png")
                open(path, "wb").write(data)
                return path, time.time() - start
        time.sleep(1.5)


def main():
    spec, out_dir = json.load(open(sys.argv[1], encoding="utf-8")), sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    for job in spec["jobs"]:
        path, secs = run(job, out_dir)
        print(f"{job['name']}: {secs:.1f}s -> {path}", flush=True)


if __name__ == "__main__":
    main()
