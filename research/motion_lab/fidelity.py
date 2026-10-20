"""Camera-move fidelity: does a rendered shot move its camera the way the previs does?

Per frame step, corners tracked with pyramidal Lucas-Kanade on a downscaled frame give point pairs; a RANSAC similarity fit
(estimateAffinePartial2D) gives the image-space camera motion: pan x, pan y (fraction of frame width) and zoom
(log scale). Moving actors are outliers to the fit. The score compares the cumulative paths per component (Pearson
correlation), weighted by how far that component travels in the previs; a component the previs holds still scores by how
still the shot keeps it. Checked on the observatory shots: matched previs/shot pairs 0.65-1.0, mismatched pairs -0.66-0.32.

usage: python fidelity.py PREVIS SHOT [PREVIS SHOT ...]
"""
import sys

import cv2
import numpy as np


def motion(path, width=320):
    cap, prev, steps = cv2.VideoCapture(str(path)), None, []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(cv2.resize(frame, (width, int(frame.shape[0] * width / frame.shape[1]))), cv2.COLOR_BGR2GRAY)
        if prev is not None:
            # Track textured corners only: flat fog, sky and grey walls have no measurable flow and would vote for "no motion".
            src = cv2.goodFeaturesToTrack(prev, maxCorners=500, qualityLevel=0.005, minDistance=6)
            m = None
            if src is not None and len(src) >= 12:
                dst, ok, _ = cv2.calcOpticalFlowPyrLK(prev, gray, src, None, winSize=(21, 21), maxLevel=4)
                good = ok.ravel() == 1
                if good.sum() >= 12:
                    m, _ = cv2.estimateAffinePartial2D(src[good], dst[good], method=cv2.RANSAC, ransacReprojThreshold=1.5)
            if m is None:
                steps.append((0.0, 0.0, 0.0))
            else:
                scale = float(np.hypot(m[0, 0], m[1, 0]))
                cx, cy = gray.shape[1] / 2, gray.shape[0] / 2  # translation of the frame centre, so zoom does not read as pan
                tx = m[0, 0] * cx - m[1, 0] * cy + m[0, 2] - cx
                ty = m[1, 0] * cx + m[0, 0] * cy + m[1, 2] - cy
                steps.append((tx / width, ty / width, np.log(max(scale, 1e-6))))
        prev = gray
    return np.array(steps)


STILL = 0.03  # a component that travels less than this (frame widths / log zoom) over the shot counts as held


def score(previs, shot):
    """Compare the cumulative camera paths (shape and direction, not per-frame speed: the model keeps the move, not
    its exact easing). A component the previs holds still scores by how still the shot keeps it."""
    a, b = motion(previs), motion(shot)
    n = min(len(a), len(b))
    if n < 8:
        return {"score": 0.0}
    out, parts = {}, []
    for i, name in enumerate(("pan_x", "pan_y", "zoom")):
        x, y = np.cumsum(a[:n, i]), np.cumsum(b[:n, i])
        reach_a, reach_b = float(np.abs(x).max()), float(np.abs(y).max())
        if reach_a < STILL:
            s, weight = max(0.0, 1 - max(0.0, reach_b - STILL) / (3 * STILL)), STILL
        else:
            s = float(np.corrcoef(x, y)[0, 1]) if y.std() > 1e-9 else 0.0
            weight = reach_a
        out[name] = {"score": round(s, 2), "previs": round(float(x[-1]), 3), "shot": round(float(y[-1]), 3)}
        parts.append((s, weight))
    out["score"] = round(sum(s * w for s, w in parts) / sum(w for _, w in parts), 2)
    return out


if __name__ == "__main__":
    pairs = sys.argv[1:]
    for previs, shot in zip(pairs[::2], pairs[1::2]):
        print(previs.split("/")[-1], "->", shot.split("/")[-1], score(previs, shot))
