"""Match a slice's opening brightness to the end of the slice before, easing the correction out (an exposure step at a
seam becomes a slow drift).

python -X utf8 lumamatch.py <A.mp4> <B.mp4> <out.mp4> [ease_frames]
B's Lab L is scaled so its frame 1 has A's last-frame mean, and the gain eases back to 1 over ease_frames.
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


def main():
    a, b, out = frames(sys.argv[1]), frames(sys.argv[2]), sys.argv[3]
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 72
    L = lambda f: cv2.cvtColor(f, cv2.COLOR_BGR2LAB)[..., 0].astype(np.float32)
    g0 = L(a[-1]).mean() / L(b[1]).mean()
    h, w = b[0].shape[:2]
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", "24",
                             "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", out], stdin=subprocess.PIPE)
    for i, f in enumerate(b):
        u = min(1.0, max(0.0, (i - 1) / n))
        g = 1 + (g0 - 1) * (1 - u * u * (3 - 2 * u)) if i >= 1 else 1.0
        if abs(g - 1) > 1e-3:
            lab = cv2.cvtColor(f, cv2.COLOR_BGR2LAB).astype(np.float32)
            lab[..., 0] = np.clip(lab[..., 0] * g, 0, 255)
            f = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)
        proc.stdin.write(f.tobytes())
    proc.stdin.close(); proc.wait()
    print(f"{out}: opening gain {g0:.3f}, eased out over {n} frames")


if __name__ == "__main__":
    main()
