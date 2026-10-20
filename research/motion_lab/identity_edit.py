"""Pass 2 prep: edit draft frames (composition already right) so the man becomes Kael and the room our observatory."""
import sys, zf
from pathlib import Path
S = Path(sys.argv[1]); cast = zf.upload(S / "official/cast01.png"); setref = zf.upload(S / "official/set01.png")
PROMPT = ("Edit the first image only where needed: replace the man with the man from the second image - same face, short dark hair, light stubble, "
          "charcoal field jacket, analog recorder on a shoulder strap - keeping his exact pose, position, size, head angle and the exact camera framing. "
          "Make the console brass with warm amber instrument lights and the curved glass streaked with rain like the room in the third image. Keep the "
          "distant beacon tower on the horizon, the light, the framing and everything else unchanged. Only one person. No text.")
for f in ("f000", "f096"):
    src = zf.upload(zf.OUT / f"draft_{f}.png")
    p, t = zf.run(zf.klein(PROMPT, 5401, refs=(src, cast, setref)), f"kael_{f}")
    print(p.name, f"{t:.0f}s", flush=True)
