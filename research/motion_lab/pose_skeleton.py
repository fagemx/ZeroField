"""SPEC_10 §7.6 follow-up on the 4090: carry the mannequin's acting as a pose skeleton instead of its shape.

The Layout Render ties pose to shape: followed at 0.6 the pose comes through and so does the mannequin's shape; at 0.35
the actor is a person but only the head carries the recoil. An OpenPose skeleton has joints and no body, so nothing of
the mannequin's shape can leak. The skeleton is exact: stage_render.py pose projects the mannequin's own joints, no
pose estimation. It goes in through LTX-2.3 Union-Control (canny + depth + pose; it runs on LTX-2.5, see the
2026-10-20 lab), drawn the DWPose way (body, hands, black background) by the product's ui/src/previs/skeleton.js, the
pass Render previs writes (the first 4090 runs drew it in Python, one frame late; see SPEC_10 §7.8).

The S03 recoil plan (pose_motion.py s03p) re-rendered with the current render mannequin (no shoulder ball) as s03q,
the same Klein first frame (s03n_first_grey) and seed, and one detailed prompt (the right hand turns the dial: the
reaching arm is figure.js shoulderL, at -x, his right). Four runs:

  follow35       the product recipe: Layout-To-Render, actor following the previs at 0.35
  layout_pose    Layout-To-Render with the actor freed, plus Union-Control on the skeleton (two IC-LoRAs, two guides)
  pose           Union-Control on the skeleton only: no layout guide, so the set and camera come from the first frame
  follow60       the product recipe at 0.6 with the ball-less mannequin: does the shape still leak?

The same four with the neutral prompt of pose_motion.py (the dial turn, no recoil) as s03q_neutral_*: the detailed
prompt drives the recoil on its own, so only without it does a run show what the skeleton carries.

usage: python pose_skeleton.py [prep|neutral]  (prep renders previs, matte, skeleton and the overlay check only)
"""
import json, subprocess, sys
from pathlib import Path

import cv2
import numpy as np

import fidelity
import iclora as L
import zf
from perf_scale import DOCS
from pose_motion import PROMPT as NEUTRAL, energy_after, partial

SHOT, FIRST = "s03q", L.IC / "s03n_first_grey.png"
PROMPT = ("Inside a circular glass-dome observatory at dawn, rain streaks the curved glass above a ring of brass consoles with amber "
          "instrument lights. Kael, a man in his thirties with short dark hair, light stubble and a charcoal field jacket. The camera "
          "tilts down from the dome ribs and pushes in behind his shoulder. "
          "0.0–1.4s, seen in profile: Kael stands at the rain-streaked glass, listening, weight on his back foot. "
          "1.4–2.8s, seen from behind: he turns from the glass to the console, shoulders squaring. "
          "2.8–4.3s, seen from behind: his right hand finds the large brass dial and turns it; far beyond the glass a beacon light blinks on. "
          "4.3–4.8s, seen from behind: he jerks his hand off the dial and recoils, his head snapping back, both arms flying up in front "
          "of his chest, his upper body rocking back half a step. "
          "4.8–6.0s, seen from behind: he holds the recoil, arms raised, head thrown back toward the light, shoulders locked. "
          "One person only. No text.")

def skeleton():
    """Keypoints from the plan, the skeleton video, and a check that the body keypoints land on the actor's matte."""
    render, plan, kp_path, webm = Path(__file__).with_name("stage_render.py"), L.IC / "s03p_plan.json", L.IC / f"{SHOT}_keypoints.json", L.IC / f"{SHOT}_skeleton.webm"
    subprocess.run([sys.executable, str(render), str(plan), str(kp_path), "pose"], check=True)
    subprocess.run([sys.executable, str(render), str(plan), str(webm), "skeleton"], check=True)
    frames, out = json.loads(kp_path.read_text(encoding="utf-8")), L.IC / f"{SHOT}_skeleton.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(webm), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", str(out)], check=True)
    # Self-check: projected body joints sit on the rendered actor (matte dilated 12 px for joints at the silhouette edge).
    cap, hits, total, kernel = cv2.VideoCapture(str(L.IC / f"{SHOT}_matte.webm")), 0, 0, np.ones((25, 25), np.uint8)
    for people in frames:
        m = cv2.dilate((cv2.cvtColor(cap.read()[1], cv2.COLOR_BGR2GRAY) > 127).astype(np.uint8), kernel)
        for x, y, v in people[0]["body"][:14]:  # nose..ankles; the face points can sit just off the head mesh
            if v and 0 <= int(x) < L.W and 0 <= int(y) < L.H:
                total += 1; hits += int(m[int(y), int(x)])
    assert total and hits / total > 0.95, f"skeleton off the actor: {hits}/{total}"
    print(f"skeleton on actor: {hits}/{total}", flush=True)
    # Overlay for the eye: skeleton over the previs at six moments.
    picks = "+".join(f"eq(n\\,{round(i * 144 / 5)})" for i in range(6))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(L.IC / f"{SHOT}_previs.webm"), "-i", str(out), "-filter_complex",
                    f"[0:v][1:v]blend=all_mode=lighten,select={picks},scale=384:-2,tile=6x1", "-frames:v", "1", str(L.IC / f"_{SHOT}_overlay.png")], check=True)
    return out


def prep():
    subprocess.run([sys.executable, str(Path(__file__).with_name("stage_render.py")), str(L.IC / "s03p_plan.json"), str(L.IC / f"{SHOT}_previs.webm")], check=True)
    L.SHOTS[SHOT] = dict(L.SHOTS["s03m"], previs=f"{SHOT}_previs.webm", prompt=PROMPT)
    L.stage_free(SHOT)
    return skeleton()


def layout_pose(guide):
    """Layout-To-Render on the previs (actor freed) and Union-Control on the skeleton: both LoRAs on the model, one
    guide each, each with its own IC-LoRA parameters (Union-Control's reference is at half resolution)."""
    g = L.ic(SHOT, FIRST, L.LAYOUT, mask=f"{SHOT}_free_actor.mp4", first_mode="ref")
    g["62"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["60", 0], "lora_name": L.UNION, "strength_model": 1.0}}
    g["63"] = {"class_type": "GetICLoRAParameters", "inputs": {"iclora_model": ["62", 0]}}
    g["26"] = dict(g["20"], inputs=dict(g["20"]["inputs"], video=zf.upload(guide)))
    g["42"] = {"class_type": "LTXVAddGuide", "inputs": {"positive": ["41", 0], "negative": ["41", 1], "vae": ["5", 0], "latent": ["41", 2], "image": ["26", 0],
                                                        "frame_idx": 0, "strength": 1.0, "iclora_parameters": ["63", 0]}}
    g["15"]["inputs"]["video_latent"] = ["42", 2]
    g["53"]["inputs"].update(model=["62", 0], positive=["42", 0], negative=["42", 1])
    g["17"]["inputs"].update(positive=["42", 0], negative=["42", 1])
    return g


def run(prompt=PROMPT, tag=""):
    L.SHOTS[SHOT] = dict(L.SHOTS["s03m"], previs=f"{SHOT}_previs.webm", prompt=prompt)
    guide, n = L.IC / f"{SHOT}_skeleton.mp4", SHOT + tag
    runs = {
        f"{n}_follow35": lambda: L.ic(SHOT, FIRST, L.LAYOUT, mask=partial(SHOT, 0.35), first_mode="ref"),
        f"{n}_layout_pose": lambda: layout_pose(guide),
        f"{n}_pose": lambda: L.ic(SHOT, FIRST, L.UNION, guide=guide.name, first_mode="ref"),
        f"{n}_follow60": lambda: L.ic(SHOT, FIRST, L.LAYOUT, mask=partial(SHOT, 0.6), first_mode="ref"),
    }
    result = {}
    for name, graph in runs.items():
        try:
            path, t = zf.run(graph(), f"ic/{name}")
        except Exception as e:  # one lane failing (two IC-LoRAs may not stack) must not lose the others
            print(name, "FAIL", str(e)[:1500], flush=True); continue
        cam = fidelity.score(L.IC / f"{SHOT}_previs.webm", path)
        result[name] = {"seconds": round(t), "actor_motion_after_0.72": energy_after(path, L.IC / f"{SHOT}_matte.webm"), "camera": cam["score"]}
        print(name, json.dumps(result[name]), flush=True)
    done = [n for n in runs if n in result]
    L.board(SHOT, [f"{SHOT}_skeleton"] + [x for x in (f"{n}_follow35", f"{n}_layout_pose") if x in done], DOCS / f"perf_pose_s03_skeleton{tag}")
    L.board(SHOT, [x for x in (f"{n}_follow35", f"{n}_pose", f"{n}_follow60") if x in done], DOCS / f"perf_pose_s03_skeleton{tag}_b")
    data = json.loads((DOCS / "perf_pose_s03.json").read_text()); data["pose_skeleton" + tag] = {"prompt": prompt, "runs": result}
    (DOCS / "perf_pose_s03.json").write_text(json.dumps(data, indent=1))


if __name__ == "__main__":
    arg = sys.argv[1] if sys.argv[1:] else ""
    prep() if arg == "prep" else run(NEUTRAL, "_neutral") if arg == "neutral" else (prep(), run())
