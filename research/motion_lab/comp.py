"""Stage 3 comp on the AI plate: matte cleanup, tracked beacon flare + flash relight, rain on glass, haze, bloom, grade, lens.
usage: comp.py <comp_dir> <source_mp4_for_audio> <out_stem>"""
import subprocess, sys
from pathlib import Path
import cv2, numpy as np

root = Path(sys.argv[1]); src = sys.argv[2]; stem = sys.argv[3]
out = root / f"{stem}_frames"; out.mkdir(exist_ok=True)
plates = sorted((root / "plate").glob("*.png")); N = len(plates)
H, W = cv2.imread(str(plates[0])).shape[:2]
rng = np.random.default_rng(7)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)


def clean(m):
    m = (m > 127).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n > 1:
        m = (lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    return cv2.GaussianBlur(m.astype(np.float32), (0, 0), 2.0)


def flash(f):  # beacon: dark until 70, two pulses (frame numbers 1..N)
    def pulse(c, rise, decay):
        return np.where(f < c, np.exp(-((f - c) / rise) ** 2), np.exp(-(f - c) / decay)) if f > c - 4 * rise else 0.0
    return float(min(1.0, (pulse(72, 1.2, 6.0) + .8 * pulse(86, 1.2, 6.0)))) if f >= 66 else 0.0


# Rain-on-glass texture: falling streaks + static droplets, tall so it can scroll.
tall = np.zeros((H * 3, W), np.float32)
for _ in range(2600):
    x, y = rng.integers(0, W), rng.integers(0, H * 3); l = rng.integers(6, 40)
    cv2.line(tall, (int(x), int(y)), (int(x + rng.integers(-2, 3)), int(y + l)), float(rng.uniform(.3, 1.0)), 1, cv2.LINE_AA)
tall = cv2.GaussianBlur(tall, (0, 0), .8)
drops = np.zeros((H, W), np.float32)
for _ in range(900):
    cv2.circle(drops, (int(rng.integers(0, W)), int(rng.integers(0, H))), int(rng.integers(1, 4)), float(rng.uniform(.4, 1)), -1, cv2.LINE_AA)
drops = cv2.GaussianBlur(drops, (0, 0), 1.0)


def track_point(frames, seed_frame, sx, sy, half=14, search=70):
    """Nuke-style 2D tracker: template match from a clicked point, forward and backward, template refreshed each frame."""
    grays = [cv2.GaussianBlur(cv2.imread(str(p), cv2.IMREAD_GRAYSCALE).astype(np.float32), (0, 0), 1) for p in frames]
    pos = {seed_frame: (sx, sy)}
    for step in (1, -1):
        x, y = sx, sy; tpl = grays[seed_frame][y - half:y + half, x - half:x + half].copy()
        j = seed_frame + step
        while 0 <= j < len(grays):
            g = grays[j]; x0, y0 = max(0, x - search), max(0, y - search)
            win = g[y0:min(g.shape[0], y + search), x0:min(g.shape[1], x + search)]
            if win.shape[0] <= tpl.shape[0] or win.shape[1] <= tpl.shape[1]: pos[j] = (x, y); j += step; continue
            r = cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED); _, conf, _, (mx, my) = cv2.minMaxLoc(r)
            if conf > .35:
                x, y = x0 + mx + half, y0 + my + half
                new = g[y - half:y + half, x - half:x + half]
                if new.shape == tpl.shape: tpl = .7 * tpl + .3 * new
            pos[j] = (x, y); j += step
    return [pos[k] for k in range(len(grays))]

TRACK = track_point(plates, int(sys.argv[4]) - 1, int(sys.argv[5]), int(sys.argv[6])) if len(sys.argv) > 6 else None

for i, p in enumerate(plates):
    f = i + 1
    img = cv2.imread(str(p)).astype(np.float32) / 255.0
    a = clean(cv2.imread(str(root / "matte" / p.name), cv2.IMREAD_GRAYSCALE))[..., None]
    bg = 1.0 - a
    lum = img @ np.array([.114, .587, .299], np.float32)

    bx, by = TRACK[i]
    k = flash(f)

    # 2. Rain on glass in the background: refraction offsets from streak gradients + bright droplets.
    streak = tall[(H * 2 - (f * 9) % (H * 2)):][:H]
    streak = np.vstack([streak, tall[:H - streak.shape[0]]]) if streak.shape[0] < H else streak
    glass = cv2.GaussianBlur(streak * .7 + drops, (0, 0), 1.2)
    gx, gy = cv2.Sobel(glass, cv2.CV_32F, 1, 0), cv2.Sobel(glass, cv2.CV_32F, 0, 1)
    sky = np.clip((lum - .25) * 2.0, 0, 1) * np.clip((H * .62 - yy) / (H * .25), 0, 1)
    wgt = (bg[..., 0] * sky)
    refr = cv2.remap(img, xx + gx * 11 * wgt, yy + gy * 11 * wgt, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    img = refr + (glass * .2 * wgt)[..., None] * np.array([1.0, .98, .95], np.float32)

    # 3. Atmospheric haze toward the horizon (background only), cool.
    haze = np.clip((H * .7 - yy) / H, 0, 1)[..., None] * .10 * bg
    img = img * (1 - haze) + haze * np.array([.80, .72, .66], np.float32)

    # 4. Beacon flash: glow + anamorphic streak (screen), and the room brightens slightly with the pulse.
    d2 = (xx - bx) ** 2 + (yy - by) ** 2
    glow = (np.exp(-d2 / (2 * 5 ** 2)) * 1.0 + np.exp(-d2 / (2 * 22 ** 2)) * .45 + np.exp(-d2 / (2 * 90 ** 2)) * .18)
    streak_h = np.exp(-((yy - by) ** 2) / (2 * 2.5 ** 2)) * np.exp(-np.abs(xx - bx) / 420.0) * .55
    col = np.array([1.0, .93, .85], np.float32)  # BGR: cool white (RGB .85,.93,1.0)
    light = (glow + streak_h)[..., None] * col * k
    img = 1 - (1 - img) * (1 - np.clip(light, 0, 1))
    sweep = np.exp(-d2 / (2 * 520.0 ** 2))[..., None] * k
    img = img + sweep * .16 * np.array([1.0, .9, .78], np.float32) * (bg + .35 * a)
    brass = np.clip((img[..., 2] - img[..., 0]) * 3, 0, 1) * np.clip((lum - .45) * 3, 0, 1) * (yy > H * .35)
    img = img + (cv2.GaussianBlur(brass, (0, 0), 1.5) * k * .45)[..., None] * np.array([1.0, .95, .9], np.float32)

    # 5. Relight: cool rim on the actor's edge facing the beacon, plus a faint fill on the face side.
    if k > 0.01 and a.max() > .5:
        ab = cv2.GaussianBlur(a[..., 0], (0, 0), 6)
        nx, ny = -cv2.Sobel(ab, cv2.CV_32F, 1, 0, ksize=5), -cv2.Sobel(ab, cv2.CV_32F, 0, 1, ksize=5)
        mag = np.sqrt(nx ** 2 + ny ** 2) + 1e-6
        ys, xs = np.nonzero(a[..., 0] > .5); cx, cy = xs.mean(), ys.mean()
        dx, dy = bx - cx, by - cy; dn = np.hypot(dx, dy) + 1e-6
        facing = np.clip((nx * dx + ny * dy) / (mag * dn), 0, 1) ** 2.5
        edge = np.clip(a[..., 0] - cv2.erode(a[..., 0], np.ones((7, 7), np.uint8)), 0, 1)
        side = np.clip(((xx - cx) * dx + (yy - cy) * dy) / (dn * 220.0), 0, 1)  # brighter on the beacon side
        rim = cv2.GaussianBlur(edge * facing * side, (0, 0), 2.5)[..., None] * k * 1.4
        img = img + rim * np.array([1.0, .88, .72], np.float32)  # BGR: cool rim (RGB .72,.88,1.0)
        img = img + (a * .06 * k) * np.array([1.0, .95, .85], np.float32)

    # 6. Bloom on highlights (amber lamps, the flash).
    hi = np.clip(img - .78, 0, None)
    img = img + cv2.GaussianBlur(hi, (0, 0), 18) * .9 + cv2.GaussianBlur(hi, (0, 0), 4) * .5

    # 7. Grade: teal shadows / warm highlights, gentle S-curve, background slightly desaturated.
    l = (img @ np.array([.114, .587, .299], np.float32))[..., None]
    sh, hl = np.clip(1 - l * 2, 0, 1), np.clip(l * 2 - 1, 0, 1)
    img = img * (1 + sh * np.array([.06, .02, -.05], np.float32) + hl * np.array([-.05, .0, .06], np.float32))
    img = img * (1 - .12 * bg) + l * .12 * bg
    img = np.clip(img, 0, 1); img = img + .12 * (img - img ** 2) * (img - .5) * 4  # S-curve
    img = np.clip(img, 0, 1)

    # 8. Lens: chromatic aberration, vignette, grain.
    def scale_ch(c, s):
        return cv2.remap(c, (xx - W / 2) * s + W / 2, (yy - H / 2) * s + H / 2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    img = np.dstack([scale_ch(img[..., 0], 1.0016), img[..., 1], scale_ch(img[..., 2], .9984)])
    vig = 1 - .28 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) ** 1.2
    img = img * vig[..., None]
    grain = cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), .7) * .022
    img = np.clip(img + grain[..., None] * (1 - np.abs(img - .5)), 0, 1)
    cv2.imwrite(str(out / p.name), (img * 255).astype(np.uint8))
    if f % 24 == 0: print(f, (bx, by), round(k, 2), flush=True)

subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "24", "-i", str(out / "%04d.png"), "-i", src, "-map", "0:v", "-map", "1:a?",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "15", "-c:a", "aac", "-shortest", str(root / f"{stem}.mp4")], check=True)
print("ok", root / f"{stem}.mp4")
