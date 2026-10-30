"""Measure the join between two chained clips: colour, sharpness and motion just before and after the seam.

python -X utf8 seam_check.py <a.mp4> <b.mp4> [out.png]
B's first frame is expected to repeat A's last frame, so the joined film drops B's frame 0.
Prints per-frame mean Lab, Laplacian sharpness and Farneback flow (median dx, dy, magnitude over textured pixels) for the 12 frames on each
side, and writes a strip: A[-3], A[-1], B[1], B[3] with a flow-speed plot.
"""
import sys
import cv2
import numpy as np


def frames(path):
    cap, out = cv2.VideoCapture(path), []
    while (f := cap.read())[0]:
        out.append(f[1])
    return out


def stats(seq):
    rows = []
    grey = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in seq]
    for i, f in enumerate(seq):
        lab = cv2.cvtColor(f, cv2.COLOR_BGR2LAB).reshape(-1, 3).mean(0)
        sharp = cv2.Laplacian(grey[i], cv2.CV_64F).var()
        if i:
            flow = cv2.calcOpticalFlowFarneback(cv2.resize(grey[i - 1], (640, 352)), cv2.resize(grey[i], (640, 352)),
                                                None, 0.5, 4, 21, 3, 5, 1.1, 0)
            # Only textured pixels: flat sky has no measurable motion and would pull the median to zero.
            small = cv2.resize(grey[i], (640, 352))
            texture = np.hypot(cv2.Sobel(small, cv2.CV_32F, 1, 0), cv2.Sobel(small, cv2.CV_32F, 0, 1)) > 40
            fx, fy = flow[..., 0][texture], flow[..., 1][texture]
            dx, dy = np.median(fx) * 2, np.median(fy) * 2
            mag = np.median(np.hypot(fx, fy)) * 2
        else:
            dx = dy = mag = float("nan")
        rows.append((lab, sharp, dx, dy, mag))
    return rows


def main():
    a, b = frames(sys.argv[1]), frames(sys.argv[2])
    out = sys.argv[3] if len(sys.argv) > 3 else None
    first_diff = np.abs(a[-1].astype(int) - b[0].astype(int)).mean()
    print(f"A {len(a)} frames, B {len(b)} frames; |A[-1] - B[0]| mean pixel diff {first_diff:.2f}")
    joined = a[-13:] + b[1:13]
    rows = stats(joined)
    for i, (lab, sharp, dx, dy, mag) in enumerate(rows):
        tag = f"A[{i - 13}]" if i < 13 else f"B[{i - 12}]"
        mark = "  <- seam" if i == 13 else ""
        print(f"{tag:>6}  L {lab[0]:6.1f} a {lab[1]:6.1f} b {lab[2]:6.1f}  sharp {sharp:7.1f}  flow dx {dx:6.2f} dy {dy:6.2f} |{mag:5.2f}|{mark}")
    if out:
        pick = [a[-3], a[-1], b[1], b[3]]
        strip = np.hstack([cv2.resize(f, (480, 264)) for f in pick])
        plot = np.full((180, strip.shape[1], 3), 24, np.uint8)
        mags = [r[4] for r in rows[1:]]
        top = max(max(mags), 1e-3)
        pts = [(int(20 + i * (strip.shape[1] - 40) / (len(mags) - 1)), int(170 - 150 * m / top)) for i, m in enumerate(mags)]
        cv2.line(plot, (pts[12][0], 0), (pts[12][0], 180), (80, 80, 200), 1)
        cv2.polylines(plot, [np.array(pts)], False, (120, 220, 255), 2)
        cv2.putText(plot, f"flow speed per frame (max {top:.2f}px); red line = seam", (20, 22), cv2.FONT_HERSHEY_SIMPLEX, .6, (220, 220, 220), 1)
        for x, label in ((0, "A[-3]"), (480, "A[-1]"), (960, "B[1]"), (1440, "B[3]")):
            cv2.putText(strip, label, (x + 10, 28), cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 2)
        cv2.imwrite(out, np.vstack([strip, plot]))


if __name__ == "__main__":
    main()
