"""Digital push-in that cancels a subject shrinking in frame (the face must only grow during a push in).

python -X utf8 facehold.py <in.mp4> <out.mp4> <first> <last>
Face boxes come from OpenCV's profile/frontal cascades every 4 frames; between first and last the face's size is
pulled up to a curve rising evenly (in log) from its size at first to its size at last, by zooming about the face.
"""
import subprocess, sys
import cv2
import numpy as np


def faces(frames):
    pr = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
    pts = []
    for i in range(0, len(frames), 4):
        g = cv2.equalizeHist(cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY))
        best = None
        for img, flip in ((g, False), (cv2.flip(g, 1), True)):
            for (x, y, w, h) in pr.detectMultiScale(img, 1.05, 4, minSize=(120, 120)):
                x = g.shape[1] - x - w if flip else x
                if best is None or w > best[2]:
                    best = (x + w / 2, y + h / 2, w)
        if best:
            pts.append((i, *best))
    pts = np.array(pts, float)
    t = np.arange(len(frames))
    cx, cy, w = (np.interp(t, pts[:, 0], pts[:, k]) for k in (1, 2, 3))
    k = np.ones(9) / 9  # the cascade jitters; a short moving average
    return [np.convolve(np.pad(v, 4, mode="edge"), k, mode="valid") for v in (cx, cy, w)]


def main():
    src, out, first, last = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    cap, frames = cv2.VideoCapture(src), []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cx, cy, w = faces(frames)
    t = np.arange(len(frames))
    target = np.exp(np.interp(t, [first, last], [np.log(w[first]), np.log(w[last])]))
    c = np.where((t > first) & (t < last), np.maximum(1.0, target / w), 1.0)
    c = np.convolve(np.pad(c, 6, mode="edge"), np.ones(13) / 13, mode="valid")
    print(f"{out}: max push-in x{c.max():.3f} at frame {int(c.argmax())}")
    h, wd = frames[0].shape[:2]
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{wd}x{h}", "-r", "24",
                             "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", out], stdin=subprocess.PIPE)
    for i, f in enumerate(frames):
        if c[i] > 1.0005:
            M = np.float32([[c[i], 0, cx[i] * (1 - c[i])], [0, c[i], cy[i] * (1 - c[i])]])
            f = cv2.warpAffine(f, M, (wd, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT_101)
        proc.stdin.write(f.tobytes())
    proc.stdin.close(); proc.wait()


if __name__ == "__main__":
    main()
