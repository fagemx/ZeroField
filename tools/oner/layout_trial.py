"""Direct ComfyUI Layout Render trial (the product's ltx25_layout_render.json) for chained previs slices.

python -X utf8 layout_trial.py <name> <previs.mp4> <matte.mp4> <skeleton.mp4> <key.png> <seed> <prompt.txt> [--pin first.png] [--end last.png] [--mid frame:img.png ...] [--grow px] [out_dir]
The key is the product's anchor keyframe (out-of-clip reference). --pin also pins frame 0 to an image in place
(LTXVImgToVideoInplace), so a slice can start on the previous slice's last frame exactly. --end guides the last frame
toward an image (LTXVAddGuide at frame -1, strength 0.9), for a slice that must land on a planned key. --mid (repeatable)
guides an inner frame (a multiple of 8) toward an image at strength 0.8, e.g. a face key that holds a character's identity
halfway through a push-in.
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import klein_trial as kt


def graph(name, previs, matte, skeleton, key, seed, prompt, pin=None, frames=193, end=None, grow=None, mids=()):
    g = json.load(open(os.path.join(kt.REPO, "workflows", "ltx25_layout_render.json"), encoding="utf-8"))
    g["20"]["inputs"]["video"] = kt.upload(previs)
    g["20"]["inputs"]["frame_load_cap"] = frames
    g["24"]["inputs"]["video"] = kt.upload(matte)
    g["44"]["inputs"]["video"] = kt.upload(skeleton)
    g["2"]["inputs"]["image"] = kt.upload(key)
    g["30"]["inputs"]["string_a"] = prompt
    g["50"]["inputs"]["noise_seed"] = seed
    g["12"]["inputs"]["filename_prefix"] = "zf21layout_" + name
    if grow is not None:  # actor matte dilation in px: 24 frees too much around a small, distant figure
        g["26"]["inputs"]["expand"] = grow
    if pin:
        g["70"] = {"class_type": "LoadImage", "inputs": {"image": kt.upload(pin)}}
        g["71"] = {"class_type": "ImageScale", "inputs": {"image": ["70", 0], "upscale_method": "lanczos", "width": 1280, "height": 704, "crop": "center"}}
        g["72"] = {"class_type": "LTXVImgToVideoInplace", "inputs": {"vae": ["5", 0], "image": ["71", 0], "latent": ["21", 0], "strength": 1.0, "bypass": False}}
        g["40"]["inputs"]["latent"] = ["72", 0]
    guides = ([(-1, end, 0.9)] if end else []) + [(idx, img, 0.8) for idx, img in mids]
    src = "42"
    for k, (idx, img, strength) in enumerate(guides):  # each guide chains on the conditioning and latent of the one before
        load, scale, node = str(73 + 3 * k), str(74 + 3 * k), "45" if k == 0 else str(75 + 3 * k)
        g[load] = {"class_type": "LoadImage", "inputs": {"image": kt.upload(img)}}
        g[scale] = {"class_type": "ImageScale", "inputs": {"image": [load, 0], "upscale_method": "lanczos", "width": 1280, "height": 704, "crop": "center"}}
        g[node] = {"class_type": "LTXVAddGuide", "inputs": {"positive": [src, 0], "negative": [src, 1], "vae": ["5", 0], "latent": [src, 2],
                                                            "image": [scale, 0], "frame_idx": idx, "strength": strength}}
        src = node
    if guides:
        g["15"]["inputs"]["video_latent"] = [src, 2]
        for node in ("53", "17"):
            g[node]["inputs"]["positive"], g[node]["inputs"]["negative"] = [src, 0], [src, 1]
    return g


def run(g, name, out_dir):
    pid = json.loads(kt.call("/prompt", json.dumps({"prompt": g, "client_id": "zf21layout"}).encode(),
                             {"Content-Type": "application/json"}))["prompt_id"]
    start = time.time()
    while True:
        hist = json.loads(kt.call(f"/history/{pid}"))
        if pid in hist:
            entry = hist[pid]
            if entry.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(entry["status"])[:2000])
            files = [f for out in entry["outputs"].values() for k in ("images", "videos", "gifs") for f in out.get(k, [])
                     if str(f.get("filename", "")).endswith(".mp4")]
            if files:
                f = files[0]
                path = os.path.join(out_dir, name + ".mp4")
                open(path, "wb").write(kt.call(f"/view?filename={f['filename']}&subfolder={f['subfolder']}&type={f['type']}"))
                return path, time.time() - start
        time.sleep(3)


if __name__ == "__main__":
    args = sys.argv[1:]
    pin = end = None
    if "--pin" in args:
        i = args.index("--pin"); pin = args[i + 1]; del args[i:i + 2]
    if "--end" in args:
        i = args.index("--end"); end = args[i + 1]; del args[i:i + 2]
    mids = []
    while "--mid" in args:
        i = args.index("--mid"); idx, img = args[i + 1].split(":", 1); mids.append((int(idx), img)); del args[i:i + 2]
    grow = None
    if "--grow" in args:
        i = args.index("--grow"); grow = int(args[i + 1]); del args[i:i + 2]
    name, previs, matte, skeleton, key, seed, prompt_file = args[:7]
    out_dir = args[7] if len(args) > 7 else "out"
    os.makedirs(out_dir, exist_ok=True)
    g = graph(name, previs, matte, skeleton, key, int(seed), open(prompt_file, encoding="utf-8").read(), pin, end=end, grow=grow, mids=mids)
    path, secs = run(g, name, out_dir)
    print(f"{name}: {secs:.0f}s -> {path}")
