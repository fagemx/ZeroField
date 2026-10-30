"""Repaint a large face in a frame as a reference person: square crop -> 1024 px -> Klein edit with several references ->
scaled back and pasted with a feathered ellipse.

python -X utf8 face_edit.py <frame.png> <cx> <cy> <size> <seed> <out.png> <prompt.txt> <ref.png> [ref.png ...]
For faces too big for crop_edit's 4x (a close-up): the crop is edited at about 2x, where the face can still be repainted.
"""
import os, sys
import cv2
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import klein_trial as kt


def main():
    src, cx, cy, size, seed, out, prompt_file, refs = sys.argv[1], *map(int, sys.argv[2:6]), sys.argv[6], sys.argv[7], sys.argv[8:]
    img = cv2.imread(src)
    x0, y0 = max(0, cx - size // 2), max(0, cy - size // 2)
    x1, y1 = min(img.shape[1], x0 + size), min(img.shape[0], y0 + size)
    crop = img[y0:y1, x0:x1]
    tmp = os.path.splitext(out)[0]
    cv2.imwrite(tmp + "_crop.png", cv2.resize(crop, (1024, 1024), interpolation=cv2.INTER_LANCZOS4))
    job = {"name": os.path.basename(tmp) + "_edit", "kind": "ref", "prompt": open(prompt_file, encoding="utf-8").read(),
           "seed": seed, "width": 1024, "height": 1024, "refs": [tmp + "_crop.png", *refs]}
    path, secs = kt.run(job, os.path.dirname(out) or ".")
    edited = cv2.resize(cv2.imread(path), (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    mask = np.zeros((y1 - y0, x1 - x0), np.float32)
    cv2.ellipse(mask, ((x1 - x0) // 2, (y1 - y0) // 2), (int((x1 - x0) * .4), int((y1 - y0) * .46)), 0, 0, 360, 1, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), (x1 - x0) * .06)[..., None]
    img[y0:y1, x0:x1] = (edited * mask + crop * (1 - mask)).astype(np.uint8)
    cv2.imwrite(out, img)
    print(f"{out}: edit {secs:.0f}s")


if __name__ == "__main__":
    main()
