"""Lab helpers: drive local ComfyUI directly with FLUX 3 Klein and LTX-2.5 graphs built in code.
Throwaway research code for the motion/space control tests; not product code."""
import json, time, uuid, urllib.request
from pathlib import Path

C = "http://127.0.0.1:8188"
LAB = Path(__file__).resolve().parent
OUT = LAB / "out"; OUT.mkdir(exist_ok=True)


def _call(path, body=None):
    req = urllib.request.Request(C + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def upload(path, kind="image"):
    """Upload an image or video to ComfyUI input/; returns the stored name."""
    path = Path(path); boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + \
           f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(C + "/upload/image", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.load(urllib.request.urlopen(req))["name"]


def run(graph, dest_stem):
    """Queue a graph, wait, download the first image/video output to OUT/dest_stem.<ext>; returns (path, seconds)."""
    t0 = time.time()
    resp = _call("/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})
    if resp.get("node_errors"):
        raise RuntimeError(json.dumps(resp["node_errors"])[:1500])
    pid = resp["prompt_id"]
    while True:
        h = _call(f"/history/{pid}")
        if pid in h:
            break
        time.sleep(2)
    entry = h[pid]
    if entry["status"].get("status_str") != "success":
        msgs = [m for m in entry["status"].get("messages", []) if m[0] == "execution_error"]
        raise RuntimeError(json.dumps(msgs)[:1500])
    for out in entry["outputs"].values():
        for key in ("images", "videos", "gifs"):
            for item in out.get(key, []):
                if item.get("type") != "output":
                    continue
                ext = Path(item["filename"]).suffix
                dest = OUT / f"{dest_stem}{ext}"
                q = f"/view?filename={item['filename']}&subfolder={item['subfolder']}&type={item['type']}"
                dest.write_bytes(urllib.request.urlopen(C + q).read())
                return dest, time.time() - t0
    raise RuntimeError("no output")


def free():
    """Unload ComfyUI's models (the endpoint answers with an empty body)."""
    req = urllib.request.Request(C + "/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=60).read()


# ---------------- FLUX 3 Klein ----------------
def klein(prompt, seed, refs=(), width=1280, height=704, steps=50, cfg=4.0, megapixels=1.0):
    """Text-to-image, or reference editing when refs (uploaded names) are given (official mi2i wiring)."""
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux3-image-klein-base-int8-convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_4b_int8_convrot.safetensors", "type": "flux3", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "6": {"class_type": "ModelSamplingFlux", "inputs": {"model": ["1", 0], "max_shift": 2.77259, "base_shift": 2.77259, "width": width, "height": height}},
        "7": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "lab_klein"}},
    }
    pos, neg = ["4", 0], ["5", 0]
    if refs:
        ref = {"positive": pos, "negative": neg, "vae": ["3", 0], "resolution": "resize", "resolution.megapixels": megapixels}
        for i, name in enumerate(refs):
            g[f"r{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
            ref[f"images.image{i}"] = [f"r{i}", 0]
        g["11"] = {"class_type": "ReferenceMultiLatent", "inputs": ref}
        pos, neg = ["11", 0], ["11", 1]
    g["8"] = {"class_type": "KSampler", "inputs": {"model": ["6", 0], "positive": pos, "negative": neg, "latent_image": ["7", 0],
                                                   "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple", "denoise": 1}}
    return g


# ---------------- LTX-2.5 ----------------
def ltx(prompt, seed, *, first=None, first_strength=1.0, guides=(), latent_guides=(), init_video=None, denoise=1.0,
        width=1280, height=704, length=97, steps=8, negative="low quality, blurry, jittery, distorted, watermark", audio=True):
    """LTX-2.5 22B distilled. first: start image (LTXVImgToVideo, inplace). guides: [(name, frame_idx, strength, is_video)]
    appended with LTXVAddGuide and cropped after sampling. init_video: video whose latent seeds sampling (V2V, use denoise<1)."""
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors", "weight_dtype": "default"}},
        "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors", "type": "ltxv", "device": "default"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": "ltx-2.5-video-vae-bf16.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 0]}},
        "9": {"class_type": "LTXVConditioning", "inputs": {"positive": ["6", 0], "negative": ["7", 0], "frame_rate": 24}},
        "13": {"class_type": "VAELoader", "inputs": {"vae_name": "ltx-2.5-audio-vae-bf16.safetensors"}},
        "14": {"class_type": "LTXVEmptyLatentAudio", "inputs": {"audio_vae": ["13", 0], "frames_number": length, "frame_rate": 24, "batch_size": 1}},
    }
    pos, neg = ["9", 0], ["9", 1]
    if init_video:
        g["20"] = {"class_type": "VHS_LoadVideo", "inputs": {"video": init_video, "force_rate": 24, "custom_width": width, "custom_height": height,
                                                             "frame_load_cap": length, "skip_first_frames": 0, "select_every_nth": 1, "format": "LTXV"}}
        g["21"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["20", 0], "vae": ["5", 0]}}
        latent = ["21", 0]
    else:
        g["21"] = {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": width, "height": height, "length": length, "batch_size": 1}}
        latent = ["21", 0]
    if first:
        g["30"] = {"class_type": "LoadImage", "inputs": {"image": first}}
        g["31"] = {"class_type": "LTXVImgToVideoInplace", "inputs": {"vae": ["5", 0], "image": ["30", 0], "latent": latent, "strength": first_strength, "bypass": False}}
        latent = ["31", 0]
    for i, (name, idx, strength, is_video) in enumerate(guides):
        src = f"4{i}0"
        if is_video:
            g[src] = {"class_type": "VHS_LoadVideo", "inputs": {"video": name, "force_rate": 24, "custom_width": width, "custom_height": height,
                                                                "frame_load_cap": length, "skip_first_frames": 0, "select_every_nth": 1, "format": "LTXV"}}
        else:
            g[src] = {"class_type": "LoadImage", "inputs": {"image": name}}
        node = f"4{i}1"
        g[node] = {"class_type": "LTXVAddGuide", "inputs": {"positive": pos, "negative": neg, "vae": ["5", 0], "latent": latent,
                                                            "image": [src, 0], "frame_idx": idx, "strength": strength}}
        pos, neg, latent = [node, 0], [node, 1], [node, 2]
    for i, (name, lidx, strength) in enumerate(latent_guides):
        g[f"5{i}0"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g[f"5{i}1"] = {"class_type": "ImageScale", "inputs": {"image": [f"5{i}0", 0], "upscale_method": "lanczos", "width": width, "height": height, "crop": "center"}}
        g[f"5{i}2"] = {"class_type": "VAEEncode", "inputs": {"pixels": [f"5{i}1", 0], "vae": ["5", 0]}}
        g[f"5{i}3"] = {"class_type": "LTXVAddLatentGuide", "inputs": {"positive": pos, "negative": neg, "vae": ["5", 0], "latent": latent,
                                                                    "guiding_latent": [f"5{i}2", 0], "latent_idx": lidx, "strength": strength}}
        pos, neg, latent = [f"5{i}3", 0], [f"5{i}3", 1], [f"5{i}3", 2]
    g["15"] = {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": latent, "audio_latent": ["14", 0]}}
    g["3"] = {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": pos, "negative": neg, "latent_image": ["15", 0], "seed": seed,
                                                   "steps": steps, "cfg": 1, "sampler_name": "euler", "scheduler": "simple", "denoise": denoise}}
    g["16"] = {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["3", 0]}}
    video = ["16", 0]
    if guides or latent_guides:
        g["17"] = {"class_type": "LTXVCropGuides", "inputs": {"positive": pos, "negative": neg, "latent": ["16", 0]}}
        video = ["17", 2]
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": video, "vae": ["5", 0]}}
    g["18"] = {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["16", 1], "audio_vae": ["13", 0]}}
    g["11"] = {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": 24, **({"audio": ["18", 0]} if audio else {})}}
    g["12"] = {"class_type": "SaveVideo", "inputs": {"video": ["11", 0], "filename_prefix": "lab_ltx", "format": "mp4", "codec": "h264"}}
    return g


def sheet(video, dest=None):
    """8-frame timestamped contact sheet, using ZeroField's own grader sheet builder."""
    import subprocess, sys
    sys.path.insert(0, "C:/ai_project/ZeroField")
    from project_assistant.studio.media_prep import build_video_frame_sheet
    video = Path(video); dest = Path(dest or video.with_suffix(".sheet.png"))
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)]).strip())
    out, _ = build_video_frame_sheet(video, dur, dest.parent, {"timeout": 120, "probe_timeout": 60})
    dest.write_bytes(out.read_bytes())
    return dest
