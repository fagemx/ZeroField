"""Round 2: grey-model V2V is the motion control. Fix the opening ghost and identity drift."""
import sys, zf
from pathlib import Path
S = Path(sys.argv[1]); A = Path("assets/push35")
gray, depth = zf.upload(A / "gray.mp4"), zf.upload(A / "depth.mp4")
paint, match = zf.upload(zf.OUT / "paint_0001_5101.png"), zf.upload(zf.OUT / "match_0001_5302.png")
cast = zf.upload(S / "official/cast01.png")
PROMPT = open("prompt_s03.txt", encoding="utf-8").read()
RUNS = {
    "R2a_gray_d75_nofirst": dict(init_video=gray, denoise=0.75),
    "R2b_gray_d75_match_s70": dict(init_video=gray, denoise=0.75, first=match, first_strength=0.7),
    "R2c_gray_d70_guide0_s50": dict(init_video=gray, denoise=0.70, guides=[(paint, 0, 0.5, False)]),
    "R2d_gray_d75_castpreroll": dict(init_video=gray, denoise=0.75, latent_guides=[(cast, -1, 1.0)]),
    "R2e_depth_d75_nofirst": dict(init_video=depth, denoise=0.75),
    "R2f_gray_d80_paint": dict(init_video=gray, denoise=0.80, first=paint),
}
for name in (sys.argv[2:] or RUNS):
    try:
        p, t = zf.run(zf.ltx(PROMPT, 61001, **RUNS[name]), name); zf.sheet(p); print(name, "ok", f"{t:.0f}s", flush=True)
    except Exception as e:
        print(name, "FAIL", str(e)[:800], flush=True)
