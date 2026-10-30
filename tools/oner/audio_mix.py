"""Sound for the oner from the LTX takes' own audio (48 kHz stereo, generated with each picture, so it is in sync).

python -X utf8 audio_mix.py <picture.mp4> <out.mp4> [music.flac]
Each take's audio sits where its picture sits; seams cross-fade over 0.3 s (the outgoing take is extended by its own
reversed tail, so nothing shifts out of sync). Two silent takes (16-32 s) get a wind bed and burner bursts lifted from
the opening takes at the times the flame shows. In the circle chain each plate's sound follows its fade on screen.
With a music track (ACE-Step 1.5, one take laid from 0 s), the score sits a few dB under the effects (its quiet opening
drone lifted), drops under the quiet hold (40-56 s), rises for the memory, and ducks 3 dB whenever the burner roars;
the burner's roar is then trimmed a little (envelope and memory) so the returning theme is heard. The mix is normalised to -17 LUFS (-16 with
music) with a -1 dBTP limiter and muxed onto the picture (video copied).
"""
MUSIC_GAIN = -4.0
MUSIC_SECTIONS = [(0, 10), (18, 4), (30, 0), (39, 0), (41, -8), (55, -8), (57, -3), (65, -3), (67, 3), (999, 3)]   # (seconds, dB)
import json, subprocess, sys
import numpy as np

SR, XF = 48000, 0.3
E = "exp2/"


def load(name, start=0.0, length=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", str(start), "-i", E + name, "-vn", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"]
    if length:
        cmd[5:5] = ["-t", str(length)]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32).reshape(-1, 2).copy()


def db(x):
    return 10 ** (x / 20)


def ramp(n, up=True):
    t = np.linspace(0, np.pi / 2, n)[:, None]
    return np.sin(t) if up else np.cos(t)          # equal-power


def extend(clip, sec):
    """Pad with the clip's own reversed tail (noise-like ambience: no audible seam, no time shift)."""
    n = int(sec * SR)
    return np.concatenate([clip, clip[::-1][:n]])


class Mix:
    def __init__(self, seconds):
        self.buf = np.zeros((int(seconds * SR) + SR, 2), np.float32)

    def put(self, clip, t0, gain_db=0.0, fade_in=XF, fade_out=XF, env=None):
        c = clip * db(gain_db)
        if env is not None:
            c = c * env[:len(c), None]
        if fade_in:
            n = min(len(c), int(fade_in * SR)); c[:n] *= ramp(n, True)
        if fade_out:
            n = min(len(c), int(fade_out * SR)); c[-n:] *= ramp(n, False)
        i = int(t0 * SR)
        self.buf[i:i + len(c)] += c[:len(self.buf) - i]


def moving_mean(x, w):
    """Centred running mean over w samples (cumulative sum: linear time on a minute-long signal)."""
    c = np.concatenate([[0.0], np.cumsum(x, dtype=np.float64)])
    i = np.clip(np.arange(len(x)) + w // 2, 0, len(x)); j = np.clip(np.arange(len(x)) - w // 2, 0, len(x))
    return ((c[i] - c[j]) / np.maximum(i - j, 1)).astype(np.float32)


def envelope(points, n):
    """Piecewise-linear gain from (seconds, gain) points, sampled for n samples."""
    t = np.arange(n) / SR
    xs, ys = zip(*points)
    return np.interp(t, xs, ys).astype(np.float32)


def main():
    picture, out = sys.argv[1], sys.argv[2]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", picture],
                               capture_output=True, text=True).stdout)
    m = Mix(dur)
    # 0-56 s: one take per 8 s slice, in sync with its picture. Gains bring the burner bursts to one level (about -20 dB
    # RMS) and lift the near-silent hold (40-56 s) to a quiet, audible breeze and breath.
    takes = [("l1e.mp4", 0, 0), ("l2e.mp4", 8, 0), ("l5n.mp4", 32, -6), ("l6n.mp4", 40, 8), ("l7r.mp4", 48, 8)]
    for name, t0, g in takes:
        m.put(extend(load(name, 0, 8.0), XF), t0, g, fade_in=XF if t0 else 0.02)
    # 16-32 s (two silent takes): canyon wind under, and burner bursts where the flame burns (18-20.5 s, 26-28 s).
    wind = load("plate_sun.mp4")
    bed = np.concatenate([wind, wind[::-1]])
    m.put(bed[:int(17.0 * SR)], 15.5, -16, fade_in=1.5, fade_out=1.5)
    m.put(load("l2e.mp4", 2.0, 3.8), 18.0, 0, fade_in=0.05, fade_out=1.2)
    m.put(load("l1e.mp4", 2.5, 2.8), 26.0, 0, fade_in=0.05, fade_out=1.0)
    # The same wind, very low, under the climb so the canyon never drops to digital silence.
    m.put(bed[:int(16.0 * SR)], 0.0, -24, fade_in=2.0, fade_out=2.0)
    m.put(np.concatenate([wind, wind[::-1]])[:int(8.5 * SR)], 31.5, -26, fade_in=1.0, fade_out=2.0)
    # 56-73.25 s: the circle chain. Each plate's sound follows the picture: the eye's breath fades as the pool comes in
    # (with the drop falling just as it appears), the wind of the sunrise brightens, then the burner's roar swells in with
    # the envelope and carries straight on into the memory.
    chain = json.load(open(E + "chain_v11.json", encoding="utf-8"))
    holds, R = chain["hold"], chain["reveal"]
    Rk = [chain["scenes"][k + 1].get("reveal", R) for k in range(3)]
    start, full = [0], [0]
    for k in range(3):
        start.append(full[k] + holds[k]); full.append(start[k + 1] + Rk[k])
    T = lambda f: 56.0 + f / 24.0
    eye = extend(load("plate_eye_r.mp4", 0, 3.7), 1.2)
    m.put(eye, T(0), -8, fade_in=XF, fade_out=0, env=envelope([(0, 1), (T(start[1]) - 56, 1), (T(start[1] + 60) - 56, 0)], len(eye)))
    pool = load("plate_pool.mp4")
    m.put(pool, T(start[1]), 6, fade_in=0.4, fade_out=0,
          env=envelope([(0, 1), ((full[1] + holds[1] - start[1]) / 24, 1), (min((full[2] - start[1]) / 24, len(pool) / SR - .05), 0)], len(pool)))
    sun = load("plate_sun.mp4")
    m.put(sun, T(start[2]), -9, fade_in=0, fade_out=0,
          env=envelope([(0, 0), (Rk[1] / 24, 1), ((full[2] + holds[2] - start[2]) / 24, 1.2), ((full[3] - start[2]) / 24, 0)], len(sun)))
    env_ = load("plate_env.mp4", 0, (full[3] + holds[3] - start[3]) / 24)
    roar = -7 if len(sys.argv) > 3 else -3
    m.put(extend(env_, XF), T(start[3]), roar, fade_in=0, fade_out=XF,
          env=envelope([(0, 0), (Rk[2] * .6 / 24, .7), (Rk[2] / 24, 1)], len(env_) + int(XF * SR)))
    # 73.25-88.25 s: the memory. The tilt's own roar and creak, then the push in to her eye; the sound thins to silence
    # over the last 1.75 s as we enter her pupil.
    t11 = T(full[3] + holds[3])
    m.put(extend(load("l11a.mp4", 0, 7.0), XF), t11, roar - 2)
    l12 = load("l12d.mp4", 0, 8.0)
    m.put(l12, t11 + 7.0, roar - 2, fade_out=0, env=envelope([(0, 1), (6.25, 1), (8.0, 0)], len(l12)))
    mix = m.buf[:int(dur * SR)]
    target = -17
    if len(sys.argv) > 3:
        target = -16
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", sys.argv[3], "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                             capture_output=True, check=True).stdout
        mus = np.frombuffer(raw, np.float32).reshape(-1, 2)[:len(mix)].copy()
        mus = np.pad(mus, ((0, len(mix) - len(mus)), (0, 0)))
        g = envelope([(t, db(MUSIC_GAIN + d)) for t, d in MUSIC_SECTIONS], len(mus))
        # Duck under the effects: 0.25 s RMS of the effects, up to -3 dB as they rise from -40 to -25 dB.
        w = SR // 4
        rms = np.sqrt(moving_mean((mix ** 2).mean(1), w)) + 1e-9
        duck = db(-3 * np.clip((20 * np.log10(rms) + 40) / 15, 0, 1)).astype(np.float32)
        duck = moving_mean(duck, w)                                     # smooth the gain so it never pumps
        mix = mix + mus * (g * duck)[:, None]
    wav = E + "mix_raw.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-i", "-", wav], input=mix.tobytes(), check=True)
    # Two-pass loudness: measure, then a linear shift to -17 LUFS; a -1 dBTP limiter catches the burner peaks.
    meas = subprocess.run(["ffmpeg", "-v", "info", "-i", wav, "-af", f"loudnorm=I={target}:TP=-1:LRA=18:print_format=json", "-f", "null", "-"],
                          capture_output=True, text=True).stderr
    j = json.loads(meas[meas.rindex("{"):meas.rindex("}") + 1])
    ln = (f"loudnorm=I={target}:TP=-1:LRA=18:linear=true:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
          f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", picture, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-af", f"{ln},alimiter=limit=0.89:level=false", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-shortest", out], check=True)
    print(f"{out}: {dur:.2f}s, input {j['input_i']} LUFS / {j['input_tp']} dBTP -> {target} LUFS")


if __name__ == "__main__":
    main()
