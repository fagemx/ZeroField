"""SPEC_10 checks on the 4090 with the Layout Render recipe (Layout-To-Render IC-LoRA, actor freed by the stage matte,
Klein first frame as an out-of-clip reference; iclora.py s03m_layout_mask_ref):

1. the jointed mannequin (scene.js P2) re-rendered from the s03m plan still reads as the same adult man;
2. the performance text's scale changes how big the performance plays: the same shot, seed and first frame with the
   shot grammar's subtle and heightened beat sheets.

Actor motion energy: mean absolute frame-to-frame change inside the dilated actor matte (0..255). The camera move is the
same in every clip, so a difference between the two scales is the actor's.

usage: python perf_scale.py SHEETS.json      (SHEETS: {"subtle": {"sheet": ...}, "heightened": {"sheet": ...}})
"""
import json, subprocess, sys
from pathlib import Path

import cv2, numpy as np

import iclora as L
import zf

SETUP = ("Inside a circular glass-dome observatory at dawn, rain streaks the curved glass above a ring of brass consoles with amber "
         "instrument lights. Kael, a man in his thirties with short dark hair, light stubble and a charcoal field jacket. The camera "
         "tilts down from the dome ribs and pushes in behind his shoulder. ")
DOCS = L.ROOT / "docs/verification/motion-lab"


def energy(clip, matte, grow=24):
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))
    a, m, prev, total = cv2.VideoCapture(str(clip)), cv2.VideoCapture(str(matte)), None, []
    while (f := a.read())[0] and (g := m.read())[0]:
        grey = cv2.cvtColor(cv2.resize(f[1], (L.W, L.H)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        mask = cv2.dilate((cv2.cvtColor(g[1], cv2.COLOR_BGR2GRAY) > 127).astype(np.uint8), kernel).astype(bool)
        if prev is not None and mask.any():
            total.append(float(np.abs(grey - prev)[mask].mean()))
        prev = grey
    return round(sum(total) / max(1, len(total)), 2)


def main(sheets, tag=""):
    """tag: a rerun of the two scales only (the jointed previs, its matte and first frame already exist), e.g. "_facing"."""
    L.SHOTS["s03r"] = dict(L.SHOTS["s03m"], previs="s03r_previs.webm")
    for k in ("subtle", "heightened"):
        L.SHOTS[f"s03r_{k}"] = dict(L.SHOTS["s03r"], prompt=SETUP + sheets[k]["sheet"].replace("\n", " ") + " One person only. No text.")
    runs = [(f"s03r_subtle{tag}", "s03r_subtle"), (f"s03r_heightened{tag}", "s03r_heightened")]
    if not tag:
        subprocess.run([sys.executable, str(Path(__file__).with_name("stage_render.py")), str(L.IC / "s03m_previs.webm"), str(L.IC / "s03r_previs.webm")], check=True)
        L.stage_free("s03r")
        L.klein_grey("s03r")
        runs.insert(0, ("s03r_layout_mask_ref", "s03r"))
    for name, shot in runs:
        path, t = zf.run(L.ic(shot, L.IC / "s03r_first_grey.png", L.LAYOUT, mask="s03r_free_actor.mp4", first_mode="ref"), f"ic/{name}")
        print(name, f"{t:.0f}s", flush=True)
    clips = (["s03m_layout_mask_ref", "s03r_layout_mask_ref"] if not tag else ["s03r_layout_mask_ref"]) + [n for n, _ in runs if n != "s03r_layout_mask_ref"]
    result = {c: energy(L.IC / f"{c}.mp4", L.IC / "s03r_matte.webm") for c in clips}
    print(json.dumps(result), flush=True)
    if not tag:
        L.board("s03r", ["s03m_layout_mask_ref", "s03r_layout_mask_ref"], DOCS / "perf_rig_jointed_s03")
    L.board("s03r", [f"s03r_subtle{tag}", f"s03r_heightened{tag}"], DOCS / f"perf_scale_s03{tag}")
    (DOCS / f"perf_scale_s03{tag}.json").write_text(json.dumps({"actor_motion_energy": result, "sheets": {k: v["sheet"] for k, v in sheets.items() if isinstance(v, dict)},
                                                               **({"facing": sheets["facing"]} if "facing" in sheets else {})}, indent=1))


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")), sys.argv[2] if len(sys.argv) > 2 else "")
