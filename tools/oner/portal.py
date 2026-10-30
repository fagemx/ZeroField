"""Circle-to-circle push-through chain: each moving plate opens inside a round thing in the plate before it.

python -X utf8 portal.py <chain.json> <out.mp4>
chain.json: {"hold": [frames per scene before its exit], "reveal": frames, "scenes": [
    {"video": "eye.mp4", "exit": [x, y, r]},
    {"video": "pool.mp4", "enter": [x, y, r], "exit": [x, y, r]}, ...
    {"video": "env.mp4", "enter": [x, y, r], "fade": 0.5, "bloom": 0.9}]}
Per scene, "hold_zoom" sets how far it pushes in while whole (default 1.12; the sun pushes 2.2x, accelerating into
it); "fade" (fraction of the reveal) fades the scene in inside the circle instead of cutting to it, and "bloom" lifts it
toward white as it appears, so the envelope rises out of the sun's light. "track": "bright" follows the brightest
round thing (the rising sun) through the plate and holds it still on screen while the scene is pushed into.
"ease_in" starts a scene's push from rest (the shot before it settled). On an entering scene, "reveal" overrides the
reveal length, "tint" (BGR gains) colours it like the circle it appears in and fades with "fade", and "highlights" keeps
the outer scene's specular glints (the cornea's reflections) over it until it has faded in, so it reads as inside the eye;
"tint_until" (fraction of the reveal) holds the tint longer, and "feather" softens the circle's edge (fraction of radius).
A scene's enter circle is fitted inside the exit circle of the scene before (the pupil becomes the pool's black water, the
moon's reflection becomes the sun, the sun becomes the glowing envelope); then the outer scene keeps zooming about its
exit circle while the inner scene grows to fill the frame, revealed through a circle that widens past it. All the
plates keep playing, so nothing is a still. The first output frame is frame 0 of the first plate (pin it to the shot
before); the last scene settles at full frame, unzoomed, so the next shot can start from its last frame.
"""
import json, subprocess, sys
import cv2
import numpy as np

W, H = 1280, 704
HOLD_ZOOM, REVEAL_ZOOM = 1.12, 4.0   # the outer scene's slow push while it is whole, and its push while it is left behind


def hermite(x, m0, m1):
    """0 -> 1 over x in [0, 1] with start slope m0 and end slope m1."""
    return (x ** 3 - 2 * x ** 2 + x) * m0 + (-2 * x ** 3 + 3 * x ** 2) + (x ** 3 - x ** 2) * m1


def smooth(a, b, x):
    u = np.clip((x - a) / (b - a), 0, 1)
    return u * u * (3 - 2 * u)


class Plate:
    """Sequential reader; holds its last frame if asked past the end."""
    def __init__(self, path):
        self.cap, self.i, self.frame = cv2.VideoCapture(path), -1, None

    def at(self, k):
        while self.i < k:
            ok, f = self.cap.read()
            if not ok:
                break
            self.frame, self.i = cv2.resize(f, (W, H)), self.i + 1
        return self.frame


def track_bright(path):
    """Per-frame centre of the largest near-white blob, smoothed by a straight-line fit (the sun rises steadily)."""
    cap, pts = cv2.VideoCapture(path), []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(f, (W, H)), cv2.COLOR_BGR2GRAY), (0, 0), 2)
        n, lab, st, ce = cv2.connectedComponentsWithStats((g > 245).astype(np.uint8))
        pts.append(ce[1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))] if n > 1 else (np.nan, np.nan))
    pts = np.array(pts, float); t = np.arange(len(pts)); ok = ~np.isnan(pts[:, 0])
    fit = [np.polyval(np.polyfit(t[ok], pts[ok, i], 1), t) for i in (0, 1)]
    return np.stack(fit, 1)


def warp(img, s, c, p):
    """Scale img by s about its point c, placing that point at screen point p."""
    M = np.float32([[s, 0, p[0] - s * c[0]], [0, s, p[1] - s * c[1]]])
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def main():
    spec, out = json.load(open(sys.argv[1], encoding="utf-8")), sys.argv[2]
    scenes, holds, R = spec["scenes"], spec["hold"], spec["reveal"]
    plates = [Plate(s["video"]) for s in scenes]
    tracks = [track_bright(s["video"]) if s.get("track") == "bright" else None for s in scenes]
    # Timeline: scene k is whole from full[k]; its exit reveal runs from full[k] + hold[k] for R frames; scene k+1 starts
    # playing (its frame 0) when that reveal starts.
    full, start = [0], [0]
    Rk = [scenes[k + 1].get("reveal", R) for k in range(len(scenes) - 1)]
    for k in range(len(scenes) - 1):
        start.append(full[k] + holds[k]); full.append(start[k + 1] + Rk[k])
    total = full[-1] + holds[-1]
    v_hold = [np.log(s.get("hold_zoom", HOLD_ZOOM)) / max(1, h) for s, h in zip(scenes, holds)]   # log-zoom per frame while whole
    if "exit" not in scenes[-1]:
        v_hold[-1] = 0.0   # the last scene settles unzoomed, framed as the shot that follows it starts
    yy, xx = np.mgrid[0:H, 0:W]
    diag = np.hypot(W, H) / 2
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", "24",
                             "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", out], stdin=subprocess.PIPE)
    for T in range(total + 1):
        k = max(i for i in range(len(scenes)) if full[i] <= T)   # the scene that is whole (or being left) now
        ex = scenes[k].get("exit")
        f_out = plates[k].at(T - start[k])
        hold_x = min(1.0, (T - full[k]) / max(1, holds[k]))
        g = hold_x * hold_x * (2 - hold_x) if scenes[k].get("ease_in") else hold_x   # from rest, ending at the hold speed
        s_h = np.exp(v_hold[k] * holds[k] * g)
        # The point pushed into: the exit circle, or the tracked sun, held where it was when the scene became whole.
        tr = tracks[k]
        c = ex[:2] if ex else [W / 2, H / 2]
        anchor = c
        if tr is not None:
            c, anchor = tr[min(T - start[k], len(tr) - 1)], tr[min(full[k] - start[k], len(tr) - 1)]
        if ex is None or T < full[k] + holds[k] or k + 1 >= len(scenes):
            frame = warp(f_out, s_h, c, anchor)
        else:
            R = Rk[k]
            x = (T - full[k] - holds[k]) / R
            nxt = scenes[k + 1]
            r_out = ex[2]
            cx, cy = anchor
            ix, iy, r_in = nxt["enter"]
            lz = np.log(REVEAL_ZOOM)
            s = s_h * np.exp(lz * hermite(x, v_hold[k] * R / lz, 3.0))      # outer keeps pushing, faster and faster
            a = warp(f_out, s, c, anchor)
            e0 = r_out * s_h / r_in                                        # inner circle fits the outer circle exactly
            le = -np.log(e0)
            h = hermite(x, v_hold[k] * R / le, v_hold[k + 1] * R / le)
            e = e0 * np.exp(le * h)
            px, py = cx + (ix - cx) * h, cy + (iy - cy) * h
            b = warp(plates[k + 1].at(T - start[k + 1]), e, (ix, iy), (px, py)).astype(np.float32)
            fade = nxt.get("fade", 0)
            come = smooth(0, fade, x) if fade else 1.0                       # how far the inner scene has faded in
            b += (255 - b) * nxt.get("bloom", 0) * (1 - smooth(0, 1.3 * fade, x) if fade else 0)
            if "tint" in nxt:
                b *= 1 + (np.float32(nxt["tint"]) - 1) * (1 - smooth(0, nxt.get("tint_until", 1.5 * fade), x))
            if nxt.get("highlights"):
                b += np.clip(a.astype(np.float32) - 160, 0, None) * 1.6 * (1 - smooth(0, 2 * fade, x))
            b = np.clip(b, 0, 255)
            # Reveal: a circle from the outer circle's edge out past the frame, never wider than the inner plate reaches;
            # the corners outside it cross-fade in at the very end.
            reach = e * min(ix, W - ix, iy, H - iy)
            rad = min(e * r_in * (diag / r_in) ** smooth(0, 1, x), max(reach, e * r_in))
            d = np.hypot(xx - px, yy - py)
            m = np.clip((rad - d) / (nxt.get("feather", 0.08) * rad + 2), 0, 1)
            edge = np.minimum.reduce([xx - (px - e * ix), px + e * (W - ix) - xx, yy - (py - e * iy), py + e * (H - iy) - yy])
            inside = np.clip(edge / (80 * (1 - smooth(.9, 1, x)) + 1e-3), 0, 1)   # soft-edged, hard only once it is the frame
            m = np.maximum(m * come, inside * smooth(.85, 1, x))[..., None]
            frame = (b * m + a * (1 - m)).astype(np.uint8)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close(); proc.wait()
    print(f"{out}: {total + 1} frames; scenes whole from {full}, reveals start {start[1:]}")


if __name__ == "__main__":
    main()
