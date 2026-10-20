"""Pass 2: grey V2V with keyframes taken from the pass-1 draft and identity-edited (composition already matches the grey path)."""
import sys, zf
from pathlib import Path
A = Path("assets/push35"); O = zf.OUT
gray = zf.upload(A / "gray.mp4"); draft = zf.upload(O / "R2a_gray_d75_nofirst.mp4")
k0, k96 = zf.upload(O / "kael_f000.png"), zf.upload(O / "kaelswap_f096_5502.png")
PROMPT = open("prompt_s03.txt", encoding="utf-8").read()
RUNS = {
    "F1_gray_k0_k96s80": dict(init_video=gray, denoise=0.75, first=k0, guides=[(k96, 96, 0.8, False)]),
    "F2_gray_k0_k96s100": dict(init_video=gray, denoise=0.75, first=k0, guides=[(k96, 96, 1.0, False)]),
    "F3_draft_d50_k0_k96": dict(init_video=draft, denoise=0.50, first=k0, guides=[(k96, 96, 0.8, False)]),
    "F4_gray_k96only": dict(init_video=gray, denoise=0.75, guides=[(k96, 96, 0.8, False)]),
}
for name in (sys.argv[1:] or RUNS):
    try:
        p, t = zf.run(zf.ltx(PROMPT, 61001, **RUNS[name]), name); zf.sheet(p); print(name, "ok", f"{t:.0f}s", flush=True)
    except Exception as e:
        print(name, "FAIL", str(e)[:800], flush=True)
