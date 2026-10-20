"""Stronger identity edit on the face-visible end frame of the draft."""
import sys, zf
from pathlib import Path
S = Path(sys.argv[1]); face = zf.upload(zf.OUT / "kael_face.png"); cast = zf.upload(S / "official/cast01.png")
src = zf.upload(zf.OUT / "draft_f096.png")
PROMPT = ("Replace the face and hair of the man in the first image with the face of the man in the second image: an older man in his mid thirties with "
          "a longer face, sharp jaw, short dark swept-back hair and light stubble, as in the second and third images. His jacket becomes the charcoal "
          "field jacket with an analog recorder on a shoulder strap from the third image. Keep his exact head angle, his hand on the brass dial, the "
          "camera framing, the lighting and everything else in the first image unchanged. No text.")
for seed in (5501, 5502):
    p, t = zf.run(zf.klein(PROMPT, seed, refs=(src, face, cast)), f"kaelswap_f096_{seed}")
    print(p.name, f"{t:.0f}s", flush=True)
