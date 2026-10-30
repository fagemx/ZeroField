"""Direct ComfyUI LTX-2.5 image-to-video trial (seam experiments).

python -X utf8 ltx_trial.py <name> <first_frame.png> <frames> <seed> <prompt.txt> [out_dir]
Writes <out_dir>/<name>.mp4 and prints the time.
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import klein_trial as kt

REPO = kt.REPO


def graph(first, frames, seed, prompt, name):
    g = json.load(open(os.path.join(REPO, "workflows", "ltx25_cinema_shot.json"), encoding="utf-8"))
    g.pop("21", None)  # the optional motion-structure loader is not wired
    g["2"]["inputs"]["image"] = kt.upload(first)
    g["6"]["inputs"]["text"] = prompt
    g["3"]["inputs"]["seed"] = seed
    g["10"]["inputs"]["length"] = frames
    g["14"]["inputs"]["frames_number"] = frames
    g["12"]["inputs"]["filename_prefix"] = "zf21seam_" + name
    return g


def run(name, first, frames, seed, prompt, out_dir):
    g = graph(first, frames, seed, prompt, name)
    pid = json.loads(kt.call("/prompt", json.dumps({"prompt": g, "client_id": "zf21seam"}).encode(),
                             {"Content-Type": "application/json"}))["prompt_id"]
    start = time.time()
    while True:
        hist = json.loads(kt.call(f"/history/{pid}"))
        if pid in hist:
            entry = hist[pid]
            if entry.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(entry["status"])[:2000])
            files = [f for out in entry["outputs"].values() for key in ("images", "videos", "gifs") for f in out.get(key, [])
                     if str(f.get("filename", "")).endswith(".mp4")]
            if files:
                f = files[0]
                data = kt.call(f"/view?filename={f['filename']}&subfolder={f['subfolder']}&type={f['type']}")
                path = os.path.join(out_dir, name + ".mp4")
                open(path, "wb").write(data)
                return path, time.time() - start
        time.sleep(3)


if __name__ == "__main__":
    name, first, frames, seed, prompt_file = sys.argv[1:6]
    out_dir = sys.argv[6] if len(sys.argv) > 6 else "out"
    os.makedirs(out_dir, exist_ok=True)
    path, secs = run(name, first, int(frames), int(seed), open(prompt_file, encoding="utf-8").read(), out_dir)
    print(f"{name}: {secs:.0f}s -> {path}")
