"""Smooth a one-frame jump at a chained seam: warp the start of slice B so its frame 1 lines up with slice A's last frame,
then let the correction ease out over N frames; a local pop (hair or fabric regenerated in frame 1) is softened by
dissolving from A's last frame over the first D frames.

python -X utf8 seamfix.py <A.mp4> <B.mp4> <out.mp4> [N] [D]
The similarity transform (shift, scale, slight rotation) is fitted to the dense flow from B[1] to A[-1]; frame 0 of B
(shared with A and dropped on assembly) is left as it is.
"""
import subprocess, sys
import cv2
import numpy as np


def frames(path):
    cap, out = cv2.VideoCapture(path), []
    while True:
        ok, f = cap.read()
        if not ok:
            return out
        out.append(f)


def fit(b1, a_last):
    """2x3 similarity mapping B[1] onto A[-1], at full resolution."""
    k = 640 / b1.shape[1]
    g = lambda im: cv2.cvtColor(cv2.resize(im, None, fx=k, fy=k), cv2.COLOR_BGR2GRAY)
    fl = cv2.calcOpticalFlowFarneback(g(b1), g(a_last), None, .5, 4, 25, 3, 5, 1.1, 0)
    ys, xs = np.mgrid[8:fl.shape[0] - 8:8, 8:fl.shape[1] - 8:8]
    p = np.stack([xs.ravel(), ys.ravel()], 1).astype(np.float32)
    q = p + fl[ys.ravel(), xs.ravel()]
    M, _ = cv2.estimateAffinePartial2D(p, q, method=cv2.RANSAC, ransacReprojThreshold=1.5)
    M[:, 2] /= k
    return M


def main():
    a, b, out = frames(sys.argv[1]), frames(sys.argv[2]), sys.argv[3]
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 24
    d = int(sys.argv[5]) if len(sys.argv) > 5 else 8
    M = fit(b[1], a[-1])
    h, w = b[0].shape[:2]
    print(f"{out}: B[1]->A[-1] shift ({M[0, 2]:.1f}, {M[1, 2]:.1f}) px, scale {np.hypot(M[0, 0], M[1, 0]):.4f}")
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", "24",
                             "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", out], stdin=subprocess.PIPE)
    eye = np.float32([[1, 0, 0], [0, 1, 0]])
    for i, f in enumerate(b):
        if 1 <= i <= n:
            wgt = .5 * (1 + np.cos(np.pi * (i - 1) / n))
            f = cv2.warpAffine(f, eye + wgt * (M - eye), (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT_101)
        if 1 <= i <= d:
            k = .5 * (1 + np.cos(np.pi * i / (d + 1)))
            f = (f.astype(np.float32) * (1 - k) + a[-1].astype(np.float32) * k).astype(np.uint8)
        proc.stdin.write(f.tobytes())
    proc.stdin.close(); proc.wait()


if __name__ == "__main__":
    main()
