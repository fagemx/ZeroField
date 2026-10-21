"""IC-LoRA motion pass vs the current grey-init V2V (d0.75) on 3D Stage previs renders.

The 2026-10-20 lab fed the grey render through plain LTXVAddGuide and got a copy of the guide; that is keyframe pixel
conditioning without an IC-LoRA. Here the previs goes in as an IC-LoRA reference with core ComfyUI 0.42.1 nodes:
LoraLoaderModelOnly -> GetICLoRAParameters -> LTXVAddGuide(previs, frame 0, iclora_parameters[, attention_mask]),
a FLUX 3 Klein first frame in place (LTXVImgToVideoInplace 1.0) or as an out-of-clip reference ("ref"), full denoise,
cfg 1, euler_ancestral on the distilled sigmas, LTXVCropGuides after sampling. Same seed, size and frame count as the
baseline. Findings: docs/research/2026-10-20-motion-control-lab.md, "Layout-To-Render IC-LoRA". Best recipe:
SHOT_first_grey, SHOT_free_actor (stage matte), SHOT_layout_mask_ref.

usage: python iclora.py RUN [RUN ...]      (RUN names in RUNS; "metrics" scores every finished clip;
                                            "board:SHOT:STEM:clip1,clip2" writes docs/verification/motion-lab/STEM.jpg/.mp4)
"""
import json, subprocess, sys
from pathlib import Path

import zf

ROOT = Path(__file__).resolve().parents[2]
IC = zf.OUT / "ic"; IC.mkdir(exist_ok=True)
SEED, KLEIN_SEED, W, H = 48291, 5502, 1280, 704
LAYOUT = r"ltx\ltx-2.5-22b-ic-lora-layout-to-render-1.0.safetensors"  # ComfyUI lists subfolder LoRAs with "\" on Windows
UNION = r"ltx\ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors"
SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"  # ltx_pipelines DISTILLED_SIGMA_VALUES
STYLE = json.loads((ROOT / "workflows/ltx25_previs_motion.json").read_text())["30"]["inputs"]["string_b"]
LOOK_KEY = json.loads((ROOT / "workflows/flux3_klein_look_key.json").read_text())["6"]["inputs"]["text"]

SHOTS = {
    "s03": dict(previs="s03_previs.webm", frames=145, prompt=(
        "Inside a circular glass-dome observatory at dawn, rain streaks the curved glass above a ring of brass consoles with "
        "amber instrument lights. Kael, a man in his thirties with short dark hair, light stubble and a charcoal field jacket, "
        "stands with his back to the camera facing the glass. The camera tilts down from the dome ribs and pushes in behind his "
        "shoulder as he reaches out and turns the large brass dial; far beyond the glass a beacon light blinks on. He holds still. "
        "One person only. No text.")),
    "crane": dict(previs="crane_previs.webm", frames=145, prompt=(
        "Inside a circular glass-dome observatory at dawn, rain streaks the curved glass above a ring of brass consoles with "
        "amber instrument lights. The camera starts high above Kael, a man in his thirties with short dark hair and a charcoal "
        "field jacket, looking straight down at him by the console, then cranes down and around to eye level behind his "
        "shoulder as he reaches for the large brass dial; far beyond the glass a beacon light glows. One person only. No text.")),
}
# The same plans re-rendered by the current scene.js with the human-proportion mannequin (stage_render.py); the camera
# between keys also follows the smooth multi-key path from 919ee7d, so these get their own baselines.
SHOTS["s03m"] = dict(SHOTS["s03"], previs="s03m_previs.webm")
SHOTS["cranem"] = dict(SHOTS["crane"], previs="cranem_previs.webm")
GREY_TO_PHOTO = (
    "Turn the first image, a grey 3D blockout, into a photographic live-action film still. Keep the exact camera angle, "
    "framing, horizon, dome ribs and console ring, and the person's exact position, size, pose and facing. The person is the "
    "man of the second image: same face, short dark hair, light stubble, charcoal field jacket. The room is the glass-dome "
    "observatory of the third image: thin dark metal ribs, rain-streaked glass, brass consoles with warm amber instrument "
    "lights, dawn light. Only one person. No text.")


def text(shot):
    return SHOTS[shot]["prompt"] + " " + STYLE  # what the baseline encodes: string_a + " " + string_b (node 30)


def baseline(shot):
    """The product graph unchanged (grey previs as the init latent, denoise 0.75); only prompt, seed and video bound."""
    g = json.loads((ROOT / "workflows/ltx25_previs_motion.json").read_text())
    g["30"]["inputs"]["string_a"] = SHOTS[shot]["prompt"]
    g["3"]["inputs"]["seed"] = SEED
    g["20"]["inputs"]["video"] = zf.upload(IC / SHOTS[shot]["previs"])
    return g


def ic(shot, first, lora, *, strength=1.0, guide_strength=1.0, guide=None, mask=None, canny=False, first_mode="inplace"):
    """LTX-2.5 distilled + IC-LoRA. guide: video to use as the reference (default the previs). mask: grey video whose
    luma becomes the guide's attention mask (white = follow the guide, black = free). first_mode "inplace" pins the
    first frame (LTXVImgToVideoInplace, as ReAngle does); "ref" attends to it outside the clip, like the official graph's
    LTXAddVideoICLoRAGuide frame_idx -1 (core LTXVAddLatentGuide latent_idx -1 sits one latent step earlier, at -8)."""
    n = SHOTS[shot]["frames"]
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors", "weight_dtype": "default"}},
        "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors", "type": "ltxv", "device": "default"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": "ltx-2.5-video-vae-bf16.safetensors"}},
        "13": {"class_type": "VAELoader", "inputs": {"vae_name": "ltx-2.5-audio-vae-bf16.safetensors"}},
        "60": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": lora, "strength_model": strength}},
        "61": {"class_type": "GetICLoRAParameters", "inputs": {"iclora_model": ["60", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": text(shot), "clip": ["4", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality, blurry, jittery, distorted, watermark", "clip": ["4", 0]}},
        "9": {"class_type": "LTXVConditioning", "inputs": {"positive": ["6", 0], "negative": ["7", 0], "frame_rate": 24}},
        "20": {"class_type": "VHS_LoadVideo", "inputs": {"video": zf.upload(IC / (guide or SHOTS[shot]["previs"])), "force_rate": 24, "custom_width": W,
                                                         "custom_height": H, "frame_load_cap": n, "skip_first_frames": 0, "select_every_nth": 1, "format": "LTXV"}},
        "21": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": W, "height": H, "length": n, "batch_size": 1}},
        "30": {"class_type": "LoadImage", "inputs": {"image": first and zf.upload(first)}},
        "32": {"class_type": "ImageScale", "inputs": {"image": ["30", 0], "upscale_method": "lanczos", "width": W, "height": H, "crop": "center"}},
        "31": {"class_type": "LTXVImgToVideoInplace", "inputs": {"vae": ["5", 0], "image": ["32", 0], "latent": ["21", 0], "strength": 1.0, "bypass": False}},
        "40": {"class_type": "LTXVAddGuide", "inputs": {"positive": ["9", 0], "negative": ["9", 1], "vae": ["5", 0], "latent": ["31", 0], "image": ["20", 0],
                                                        "frame_idx": 0, "strength": guide_strength, "iclora_parameters": ["61", 0]}},
        "14": {"class_type": "LTXVEmptyLatentAudio", "inputs": {"audio_vae": ["13", 0], "frames_number": n, "frame_rate": 24, "batch_size": 1}},
        "15": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["40", 2], "audio_latent": ["14", 0]}},
        "50": {"class_type": "RandomNoise", "inputs": {"noise_seed": SEED}},
        "51": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}},
        "52": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS}},
        "53": {"class_type": "CFGGuider", "inputs": {"model": ["60", 0], "positive": ["40", 0], "negative": ["40", 1], "cfg": 1.0}},
        "3": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["50", 0], "guider": ["53", 0], "sampler": ["51", 0], "sigmas": ["52", 0], "latent_image": ["15", 0]}},
        "16": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["3", 0]}},
        "17": {"class_type": "LTXVCropGuides", "inputs": {"positive": ["40", 0], "negative": ["40", 1], "latent": ["16", 0]}},
        "8": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["17", 2], "vae": ["5", 0], "tile_size": 1536, "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}},
        "18": {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["16", 1], "audio_vae": ["13", 0]}},
        "11": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "audio": ["18", 0], "fps": 24}},
        "12": {"class_type": "SaveVideo", "inputs": {"video": ["11", 0], "filename_prefix": "lab_ic", "format": "mp4", "codec": "h264"}},
    }
    if first is None:  # text only: same inputs as the product motion pass (previs + prompt)
        for k in ("30", "32", "31"):
            del g[k]
        g["40"]["inputs"]["latent"] = ["21", 0]
    elif first_mode == "ref":
        g["33"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["32", 0], "vae": ["5", 0]}}
        g["41"] = {"class_type": "LTXVAddLatentGuide", "inputs": {"positive": ["40", 0], "negative": ["40", 1], "vae": ["5", 0], "latent": ["40", 2],
                                                                  "guiding_latent": ["33", 0], "latent_idx": -1, "strength": 1.0}}
        g["40"]["inputs"]["latent"] = ["21", 0]
        del g["31"]
        for node, key in (("15", "video_latent"), ("53", None), ("17", None)):
            if key:
                g[node]["inputs"][key] = ["41", 2]
            else:
                g[node]["inputs"]["positive"], g[node]["inputs"]["negative"] = ["41", 0], ["41", 1]
    if canny:
        g["22"] = {"class_type": "Canny", "inputs": {"image": ["20", 0], "low_threshold": 0.2, "high_threshold": 0.5}}
        g["40"]["inputs"]["image"] = ["22", 0]
    if mask:
        g["24"] = {"class_type": "VHS_LoadVideo", "inputs": {"video": zf.upload(IC / mask), "force_rate": 24, "custom_width": W, "custom_height": H,
                                                             "frame_load_cap": n, "skip_first_frames": 0, "select_every_nth": 1, "format": "LTXV"}}
        g["25"] = {"class_type": "ImageToMask", "inputs": {"image": ["24", 0], "channel": "red"}}
        g["40"]["inputs"]["attention_mask"] = ["25", 0]
    return g


def frame(video, index, dest):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"select=eq(n\\,{index})", "-frames:v", "1", str(dest)], check=True)
    return dest


def klein_grey(shot):
    """Model-card recipe: an image model turns the previs' first frame into the art direction."""
    src = frame(IC / SHOTS[shot]["previs"], 0, IC / f"{shot}_previs_f000.png")
    refs = (zf.upload(src), zf.upload(ROOT / "samples/cast_kael.png"), zf.upload(ROOT / "samples/set_observatory.png"))
    return zf.run(zf.klein(GREY_TO_PHOTO, KLEIN_SEED, refs=refs), f"ic/{shot}_first_grey")[0]


def klein_draft(shot):
    """The product look key, on the baseline draft's first frame instead of its last."""
    src = frame(IC / f"{shot}_base.mp4", 0, IC / f"{shot}_base_f000.png")
    refs = (zf.upload(src), zf.upload(ROOT / "samples/cast_kael.png"), zf.upload(ROOT / "samples/set_observatory.png"))
    return zf.run(zf.klein(LOOK_KEY, KLEIN_SEED, refs=refs), f"ic/{shot}_first_draft")[0]


def free_actor(shot, grow=24):
    """Guide attention mask from the SAM actor matte (sam_matte.py on the previs frames): white = follow the layout,
    black = the actor (dilated), whose look should come from the first frame instead."""
    import cv2, numpy as np
    src, dest = IC / f"{shot}_sam/matte", IC / f"{shot}_sam/free"
    dest.mkdir(exist_ok=True)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))
    for f in sorted(src.glob("*.png")):
        m = cv2.dilate((cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) > 127).astype(np.uint8) * 255, kernel)
        cv2.imwrite(str(dest / f.name), 255 - cv2.GaussianBlur(m, (31, 31), 0))
    out = IC / f"{shot}_free_actor.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "24", "-i", str(dest / "%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "12", str(out)], check=True)
    return out, 0


def stage_free(shot, grow=24):
    """Same guide attention mask, but from the 3D Stage's own actor matte (stage_render.py matte): pixel-exact for
    previs rendered by the current scene.js, no SAM needed."""
    import cv2, numpy as np
    matte, out = IC / f"{shot}_matte.webm", IC / f"{shot}_free_actor.mp4"
    subprocess.run([sys.executable, str(Path(__file__).with_name("stage_render.py")), str(IC / SHOTS[shot]["previs"]), str(matte), "matte"], check=True)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))
    cap, frames = cv2.VideoCapture(str(matte)), []
    while (f := cap.read())[0]:
        m = cv2.dilate((cv2.cvtColor(f[1], cv2.COLOR_BGR2GRAY) > 127).astype(np.uint8) * 255, kernel)
        frames.append(255 - cv2.GaussianBlur(m, (31, 31), 0))
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", "24", "-i", "-",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", str(out)], stdin=subprocess.PIPE)
    enc.communicate(b"".join(f.tobytes() for f in frames))
    return out, 0


RUNS = {
    "s03_free_actor": lambda: free_actor("s03"),
    "s03_base": lambda: zf.run(baseline("s03"), "ic/s03_base"),
    "crane_base": lambda: zf.run(baseline("crane"), "ic/crane_base"),
    "s03_first_grey": lambda: (klein_grey("s03"), 0),
    "crane_first_grey": lambda: (klein_grey("crane"), 0),
    "s03_first_draft": lambda: (klein_draft("s03"), 0),
    "s03_union_canny": lambda: zf.run(ic("s03", IC / "s03_first_grey.png", UNION, canny=True), "ic/s03_union_canny"),
    "s03_layout_grey": lambda: zf.run(ic("s03", IC / "s03_first_grey.png", LAYOUT), "ic/s03_layout_grey"),
    "s03_layout_grey_ref": lambda: zf.run(ic("s03", IC / "s03_first_grey.png", LAYOUT, first_mode="ref"), "ic/s03_layout_grey_ref"),
    "s03_layout_ref_l06": lambda: zf.run(ic("s03", IC / "s03_first_grey.png", LAYOUT, strength=0.6, first_mode="ref"), "ic/s03_layout_ref_l06"),
    "s03_layout_ref_g07": lambda: zf.run(ic("s03", IC / "s03_first_grey.png", LAYOUT, guide_strength=0.7, first_mode="ref"), "ic/s03_layout_ref_g07"),
    "s03_layout_mask_ref": lambda: zf.run(ic("s03", IC / "s03_first_grey.png", LAYOUT, mask="s03_free_actor.mp4", first_mode="ref"), "ic/s03_layout_mask_ref"),
    "crane_layout_grey_ref": lambda: zf.run(ic("crane", IC / "crane_first_grey.png", LAYOUT, first_mode="ref"), "ic/crane_layout_grey_ref"),
    "s03_layout_draft": lambda: zf.run(ic("s03", IC / "s03_first_draft.png", LAYOUT), "ic/s03_layout_draft"),
    "s03_layout_mask": lambda: zf.run(ic("s03", IC / "s03_first_grey.png", LAYOUT, mask="s03_free_actor.mp4"), "ic/s03_layout_mask"),
    "crane_layout_grey": lambda: zf.run(ic("crane", IC / "crane_first_grey.png", LAYOUT), "ic/crane_layout_grey"),
    "s03_layout_text": lambda: zf.run(ic("s03", None, LAYOUT), "ic/s03_layout_text"),
    "crane_layout_text": lambda: zf.run(ic("crane", None, LAYOUT), "ic/crane_layout_text"),
    **{f"{s}_base": (lambda s=s: zf.run(baseline(s), f"ic/{s}_base")) for s in ("s03m", "cranem")},
    **{f"{s}_layout_text": (lambda s=s: zf.run(ic(s, None, LAYOUT), f"ic/{s}_layout_text")) for s in ("s03m", "cranem")},
    **{f"{s}_first_grey": (lambda s=s: (klein_grey(s), 0)) for s in ("s03m", "cranem")},
    **{f"{s}_layout_ref": (lambda s=s: zf.run(ic(s, IC / f"{s}_first_grey.png", LAYOUT, first_mode="ref"), f"ic/{s}_layout_ref"))
       for s in ("s03m", "cranem")},
    **{f"{s}_free_actor": (lambda s=s: stage_free(s)) for s in ("s03m", "cranem")},
    **{f"{s}_layout_mask_ref": (lambda s=s: zf.run(ic(s, IC / f"{s}_first_grey.png", LAYOUT, mask=f"{s}_free_actor.mp4", first_mode="ref"),
                                                    f"ic/{s}_layout_mask_ref")) for s in ("s03m", "cranem")},
    "crane_layout_mask_ref": lambda: zf.run(ic("crane", IC / "crane_first_grey.png", LAYOUT, mask="crane_free_actor.mp4", first_mode="ref"),
                                            "ic/crane_layout_mask_ref"),
}


def metrics():
    """Camera fidelity (fidelity.py), guide copy (luma correlation with the previs) and colourfulness per clip."""
    import cv2, numpy as np
    import fidelity

    def frames(path, width=160):
        cap, out = cv2.VideoCapture(str(path)), []
        while True:
            ok, f = cap.read()
            if not ok:
                return out
            out.append(cv2.resize(f, (width, int(f.shape[0] * width / f.shape[1]))).astype(np.float32))

    def colourful(f):  # Hasler & Suesstrunk
        b, g, r = f[..., 0], f[..., 1], f[..., 2]
        rg, yb = r - g, 0.5 * (r + g) - b
        return float(np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean()))

    rows = {}
    for shot in SHOTS:
        previs = frames(IC / SHOTS[shot]["previs"])
        rows[f"{shot}_previs"] = {"colourful": round(float(np.mean([colourful(f) for f in previs])), 1)}
        for clip in sorted(c for c in IC.glob(f"{shot}_*.mp4") if "free_actor" not in c.stem):
            out = frames(clip)
            n = min(len(out), len(previs))
            luma = lambda f: cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (5, 5), 0).ravel()
            copy = [float(np.corrcoef(luma(previs[i]), luma(out[i]))[0, 1]) for i in range(0, n, 4)]
            cam = fidelity.score(IC / SHOTS[shot]["previs"], clip)
            # reach: how much of the previs' travel the shot covers (the score itself only compares path shape)
            reach = {k: round(cam[k]["shot"] / cam[k]["previs"], 2) for k in ("pan_y", "zoom")}
            rows[clip.stem] = {"camera": cam["score"], "reach": reach, "guide_copy": round(float(np.mean(copy)), 2),
                               "colourful": round(float(np.mean([colourful(f) for f in out])), 1), "frames": len(out)}
    (IC / "metrics.json").write_text(json.dumps(rows, indent=1))
    for k, v in rows.items():
        print(k, v)


def board(shot, clips, dest):
    """Evidence: a frame grid (one row per clip, 6 moments) and a labelled side-by-side video, previs first."""
    font = "C\\:/Windows/Fonts/arial.ttf"
    paths = [IC / SHOTS[shot]["previs"]] + [IC / f"{c}.mp4" for c in clips]
    labels = ["previs"] + list(clips)
    n = SHOTS[shot]["frames"]
    picks = "+".join(f"eq(n\\,{round(i * (n - 1) / 5)})" for i in range(6))
    rows = []
    for path, label in zip(paths, labels):
        row = IC / f"_row_{label}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf",
                        f"select={picks},scale=384:-2,drawtext=fontfile='{font}':text='{label}':x=8:y=8:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6,tile=6x1",
                        "-frames:v", "1", str(row)], check=True)
        rows.append(row)
    inputs = sum((["-i", str(r)] for r in rows), [])
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", f"vstack=inputs={len(rows)}", "-q:v", "3", str(dest.with_suffix(".jpg"))], check=True)
    inputs = sum((["-i", str(p)] for p in paths), [])
    scaled = "".join(f"[{i}:v]scale=640:352,setsar=1,drawtext=fontfile='{font}':text='{l}':x=8:y=8:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.6[v{i}];"
                     for i, l in enumerate(labels))
    cols = 2 if len(paths) == 4 else len(paths)
    if cols == 2:
        layout = f"{scaled}[v0][v1]hstack[t];[v2][v3]hstack[b];[t][b]vstack"
    else:
        layout = scaled + "".join(f"[v{i}]" for i in range(len(paths))) + f"hstack=inputs={len(paths)}"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", layout, "-frames:v", str(n), "-an", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "24", "-movflags", "+faststart", str(dest.with_suffix(".mp4"))], check=True)
    for r in rows:
        r.unlink()
    return dest


if __name__ == "__main__":
    for name in sys.argv[1:]:
        if name == "metrics":
            metrics(); continue
        if name.startswith("board:"):  # board:SHOT:DEST_STEM:clip1,clip2,...
            _, shot, stem, clips = name.split(":", 3)
            print(board(shot, clips.split(","), ROOT / "docs/verification/motion-lab" / stem)); continue
        try:
            path, t = RUNS[name](); zf.sheet(path) if path.suffix == ".mp4" else None
            print(name, "ok", path.name, f"{t:.0f}s", flush=True)
        except Exception as e:
            print(name, "FAIL", str(e)[:1500], flush=True)
