"""Crop - edit - paste: repaint a small region of a key at 4x with Klein, then paste it back feathered.

python -X utf8 crop_edit.py <key.png> <cx> <cy> <size> <seed> <out.png> <ref.png> [prompt.txt]
The square crop (size px, centred on cx, cy) is upscaled to 4x, edited with the reference, scaled back and pasted
with an elliptical feather, so the person is painted at a scale where the model can judge proportions.
"""
import json, os, sys
import cv2
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import klein_trial as kt

PROMPT = ("Edit the first image, a close view of a hot-air balloon basket hanging in the air. Keep the basket, the cables, "
          "the burner frame, the background and the light exactly as they are. Inside the basket stands one woman, the woman "
          "of the second image: short black hair, a faded saffron-orange flight jacket over a heather-grey hoodie. Real "
          "proportions: the wicker basket is 1.5 metres wide and comes up to her chest, so only her chest, shoulders and head "
          "show above the rim; her head is small, about a sixth of the basket's width; both gloved hands rest on the rim; she "
          "looks ahead. One person only. No text.")


def main():
    key, cx, cy, size, seed, out, ref = sys.argv[1], *map(int, sys.argv[2:6]), sys.argv[6], sys.argv[7]
    prompt = open(sys.argv[8], encoding="utf-8").read() if len(sys.argv) > 8 else PROMPT
    img = cv2.imread(key)
    x0, y0 = max(0, cx - size // 2), max(0, cy - size // 2)
    x1, y1 = min(img.shape[1], x0 + size), min(img.shape[0], y0 + size)
    crop = img[y0:y1, x0:x1]
    up = cv2.resize(crop, ((x1 - x0) * 4, (y1 - y0) * 4), interpolation=cv2.INTER_LANCZOS4)
    tmp = os.path.splitext(out)[0]
    cv2.imwrite(tmp + "_crop4x.png", up)
    job = {"name": os.path.basename(tmp) + "_edit4x", "kind": "ref", "prompt": prompt, "seed": seed,
           "width": up.shape[1] // 16 * 16, "height": up.shape[0] // 16 * 16, "refs": [tmp + "_crop4x.png", ref]}
    path, secs = kt.run(job, os.path.dirname(out) or ".")
    edited = cv2.resize(cv2.imread(path), (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    mask = np.zeros((y1 - y0, x1 - x0), np.float32)
    cv2.ellipse(mask, ((x1 - x0) // 2, (y1 - y0) // 2), (int((x1 - x0) * .36), int((y1 - y0) * .42)), 0, 0, 360, 1, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), (x1 - x0) * .06)[..., None]
    img[y0:y1, x0:x1] = (edited * mask + crop * (1 - mask)).astype(np.uint8)
    cv2.imwrite(out, img)
    print(f"{out}: edit {secs:.0f}s")


if __name__ == "__main__":
    main()
