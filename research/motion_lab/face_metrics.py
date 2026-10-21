"""Expression curves for takes: ComfyUI's own MediaPipe face landmarker (comfy_extras/nodes_mediapipe.py, BlazeFace ->
FaceMesh v2 -> ARKit-52 blendshapes, models/detection/mediapipe_face_fp32.safetensors from Comfy-Org/mediapipe) run
on every other frame (VARIANT=full for two-shots), outside a graph because FACE_LANDMARKS cannot be saved through the API. The largest face per
frame is the subject; a frame with no face is null.

Run with ComfyUI's embedded python, which has torch and the node code:
  E:/AITool/ZeroField_ComfyUI/ComfyUI_windows_portable/python_embeded/python.exe face_metrics.py OUT.json CLIP.mp4 [...]
"""
import json, os, sys
from pathlib import Path

COMFY = Path("E:/AITool/ZeroField_ComfyUI/ComfyUI_windows_portable/ComfyUI")
sys.path.insert(0, str(COMFY)); os.chdir(COMFY)
import av  # noqa: E402
import torch  # noqa: E402
import comfy.utils  # noqa: E402
from comfy_extras.nodes_mediapipe import FaceLandmarkerModel  # noqa: E402

# The expression channels, each the mean of its left / right ARKit blendshapes.
CHANNELS = {"jawOpen": ["jawOpen"], "browInnerUp": ["browInnerUp"], "browDown": ["browDownLeft", "browDownRight"],
            "eyeSquint": ["eyeSquintLeft", "eyeSquintRight"], "eyeBlink": ["eyeBlinkLeft", "eyeBlinkRight"],
            "eyeWide": ["eyeWideLeft", "eyeWideRight"], "mouthFrown": ["mouthFrownLeft", "mouthFrownRight"],
            "mouthStretch": ["mouthStretchLeft", "mouthStretchRight"], "noseSneer": ["noseSneerLeft", "noseSneerRight"]}


def curves(model, clip, step=2, variant="short"):
    frames = [f.to_ndarray(format="rgb24") for f in av.open(str(clip)).decode(video=0)][::step]
    out = []
    for i in range(0, len(frames), 16):
        for faces in model.detect_batch(frames[i:i + 16], num_faces=2, score_thresh=0.5, variant=variant):
            if not faces:
                out.append(None); continue
            f = max(faces, key=lambda x: (x["bbox_xyxy"][2] - x["bbox_xyxy"][0]) * (x["bbox_xyxy"][3] - x["bbox_xyxy"][1]))
            b = f["blendshapes"]
            out.append({k: round(sum(float(b[n]) for n in names) / len(names), 3) for k, names in CHANNELS.items()})
    return {"step": step, "frames": len(frames) * step, "curves": out}


if __name__ == "__main__":
    model = FaceLandmarkerModel(comfy.utils.load_torch_file(str(COMFY / "models/detection/mediapipe_face_fp32.safetensors"), safe_load=True))
    with torch.inference_mode():  # as ComfyUI runs nodes
        # VARIANT=full for faces farther than ~2 m (two-shots), short for close-ups
        result = {Path(c).stem: curves(model, c, variant=os.environ.get("VARIANT", "short")) for c in sys.argv[2:]}
    Path(sys.argv[1]).write_text(json.dumps(result), encoding="utf-8")
    print("ok", len(result))
