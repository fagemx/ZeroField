"""Per-frame person matte with SAM ViT-H: frame 1 box from the grey-model actor matte, then the previous mask's box."""
import os, sys, numpy as np, torch
from pathlib import Path
from PIL import Image
from segment_anything import sam_model_registry, SamPredictor
root = Path(sys.argv[1]); seed_matte = Path(sys.argv[2])
sam = sam_model_registry["vit_h"](checkpoint=r"E:/AITool/ComfyUI_windows_portable/ComfyUI/models/sams/sam_vit_h_4b8939.pth").to(os.environ.get("SAM_DEVICE", "cuda"))  # cpu while LTX holds the GPU
pred = SamPredictor(sam)
q = np.array(Image.open(seed_matte).convert("RGBA")).astype(int); m0 = (q[:, :, 3] > 128) & (q[:, :, 0] > 128) & (q[:, :, 1] < 64) & (q[:, :, 2] < 64)
ys, xs = np.nonzero(m0); box = np.array([xs.min(), ys.min(), xs.max(), ys.max()], float)
frames = sorted((root / "plate").glob("*.png"))
prev = None
import cv2
for i, f in enumerate(frames):
    img = np.array(Image.open(f).convert("RGB")); H, W = img.shape[:2]
    pred.set_image(img)
    if prev is None:
        pad = np.array([-.12, -.08, .12, .08]) * np.array([box[2] - box[0], box[3] - box[1]] * 2)
        b = np.clip(box + pad, 0, [W - 1, H - 1, W - 1, H - 1])
        masks, scores, _ = pred.predict(box=b, multimask_output=True)
        m = masks[int(np.argmax(scores))]
    else:
        ys, xs = np.nonzero(prev)
        bw, bh = xs.max() - xs.min(), ys.max() - ys.min()
        b = np.clip([xs.min() - .06 * bw, ys.min() - .06 * bh, xs.max() + .06 * bw, ys.max() + .06 * bh], 0, [W - 1, H - 1, W - 1, H - 1])
        top = ys < ys.min() + .08 * bh
        pts = np.array([[xs.mean(), ys.mean()], [xs[top].mean(), ys[top].mean() + .03 * bh], [20, 20], [W - 20, 20]])
        lab = np.array([1, 1, 0, 0])
        masks, scores, _ = pred.predict(point_coords=pts, point_labels=lab, box=b, multimask_output=True)
        area = prev.sum()
        ok = [k for k, mk in enumerate(masks) if .6 * area < mk.sum() < 1.7 * area]
        ious = {k: np.logical_and(masks[k], prev).sum() / max(1, np.logical_or(masks[k], prev).sum()) for k in (ok or range(len(masks)))}
        m = masks[max(ious, key=ious.get)]
    prev = m
    Image.fromarray((m * 255).astype(np.uint8)).save(root / "matte" / f.name)
    if i % 16 == 0: print(i, int(m.sum()), flush=True)
print("done")
