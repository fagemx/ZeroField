"""SPEC_10 §7.4 follow-up on the 4090: does a pose in the previs make the body move, where text alone did not?

The S03 plan (s03r, jointed mannequin) twice: as blocked (turn, reach the dial, hold) and with a recoil after the beacon
lights (he lets go of the dial and recoils, 0.72 -> 0.80 of the shot, planned with performance keys). Both get the
same neutral prompt, which never mentions recoiling, the same seed and the same Klein first frame, through three lanes:

  motion      the Motion pass: grey previs as the init latent, denoise 0.75 (workflows/ltx25_previs_motion.json)
  layout      Layout-To-Render IC-LoRA with the first frame as an out-of-clip reference, actor not freed
  layout_mask the same with the actor freed by the stage matte (the Layout Render lane)

Actor motion energy (perf_scale.py energy) after the recoil starts, inside each previs' own dilated actor matte.

usage: python pose_motion.py
"""
import json, subprocess, sys
from pathlib import Path

import iclora as L
import zf
from perf_scale import DOCS, energy

PROMPT = ("Inside a circular glass-dome observatory at dawn, rain streaks the curved glass above a ring of brass consoles with amber "
          "instrument lights. Kael, a man in his thirties with short dark hair, light stubble and a charcoal field jacket, stands with "
          "his back to the camera facing the glass. The camera tilts down from the dome ribs and pushes in behind his shoulder as he "
          "turns to the large brass dial and turns it; far beyond the glass a beacon light blinks on. One person only. No text.")
# S03's blocked action as performance keys (plan.js sampleActs; the same curves as the canned turnreach), then the recoil.
BLOCKED = [{"at": 0, "yaw": -1.75, "reach": 0}, {"at": 22 / 96, "reach": 0}, {"at": 39 / 96, "yaw": 0}, {"at": 44 / 96, "reach": 1.16}]
RECOIL = BLOCKED + [{"at": 0.72, "reach": 1.16, "body": "stand"}, {"at": 0.8, "reach": 0, "body": "recoil"}]


def plan_of(webm):
    head = (L.IC / webm).read_bytes()[:8192].decode("latin-1")
    return json.JSONDecoder().raw_decode(head, head.index("zf-plan:") + len("zf-plan:"))[0]


def energy_after(clip, matte, start=0.72, frames=145):
    """Energy from the recoil on: the frames before it are the same blocking in both previs."""
    import cv2
    cut = L.IC / f"_{Path(clip).stem}_tail.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf", f"select=gte(n\\,{round(start * (frames - 1))})", "-vsync", "0", str(cut)], check=True)
    mcut = L.IC / f"_{Path(matte).stem}_tail.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(matte), "-vf", f"select=gte(n\\,{round(start * (frames - 1))})", "-vsync", "0", str(mcut)], check=True)
    e = energy(cut, mcut); cut.unlink(); mcut.unlink()
    return e


def main():
    plan = plan_of("s03r_previs.webm")
    (L.IC / "s03p_plan.json").write_text(json.dumps({**plan, "acts": RECOIL}))
    (L.IC / "s03b_plan.json").write_text(json.dumps({**plan, "acts": BLOCKED}))
    render = Path(__file__).with_name("stage_render.py")
    for name in ("s03b", "s03p"):  # the blocked keys re-rendered too, so both previs come from the same keys path
        subprocess.run([sys.executable, str(render), str(L.IC / f"{name}_plan.json"), str(L.IC / f"{name}_previs.webm")], check=True)
        L.SHOTS[name] = dict(L.SHOTS["s03m"], previs=f"{name}_previs.webm", prompt=PROMPT)
        L.stage_free(name)
    first = L.IC / "s03r_first_grey.png"  # frame 0 is the same in both: the recoil comes at 4.3 s
    clips = []
    for name in ("s03b", "s03p"):
        for lane, graph in (("motion", lambda n=name: L.baseline(n)),
                            ("layout", lambda n=name: L.ic(n, first, L.LAYOUT, first_mode="ref")),
                            ("layout_mask", lambda n=name: L.ic(n, first, L.LAYOUT, mask=f"{n}_free_actor.mp4", first_mode="ref"))):
            path, t = zf.run(graph(), f"ic/{name}_{lane}")
            clips.append((name, lane)); print(f"{name}_{lane}", f"{t:.0f}s", flush=True)
    result = {f"{n}_{lane}": energy_after(L.IC / f"{n}_{lane}.mp4", L.IC / f"{n}_matte.webm") for n, lane in clips}
    print(json.dumps(result), flush=True)
    for lane in ("motion", "layout", "layout_mask"):
        L.board("s03p", [f"s03b_{lane}", f"s03p_{lane}"], DOCS / f"perf_pose_s03_{lane}")
    (DOCS / "perf_pose_s03.json").write_text(json.dumps({"prompt": PROMPT, "recoil_keys": RECOIL[len(BLOCKED):], "actor_motion_energy_after_0.72": result}, indent=1))


def partial(shot, follow):
    """The stage matte as a grey attention mask: the actor follows the previs by `follow` (0 = freed, 1 = the layout)."""
    import cv2, numpy as np
    out, kernel = L.IC / f"{shot}_follow{round(follow * 100)}.mp4", cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (49, 49))
    cap, frames = cv2.VideoCapture(str(L.IC / f"{shot}_matte.webm")), []
    while (f := cap.read())[0]:
        m = cv2.GaussianBlur(cv2.dilate((cv2.cvtColor(f[1], cv2.COLOR_BGR2GRAY) > 127).astype(np.uint8), kernel).astype(np.float32), (31, 31), 0)
        frames.append((255 * (1 - m * (1 - follow))).astype(np.uint8))
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{L.W}x{L.H}", "-r", "24", "-i", "-",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", str(out)], stdin=subprocess.PIPE)
    enc.communicate(b"".join(f.tobytes() for f in frames))
    return out.name


def follow_test(levels=(0.35, 0.6)):
    """The middle ground: the recoil previs with the actor half-freed, between s03p_layout (1) and s03p_layout_mask (0)."""
    L.SHOTS["s03p"] = dict(L.SHOTS["s03m"], previs="s03p_previs.webm", prompt=PROMPT)
    first, result = L.IC / "s03r_first_grey.png", {}
    for v in levels:
        name = f"s03p_follow{round(v * 100)}"
        path, t = zf.run(L.ic("s03p", first, L.LAYOUT, mask=partial("s03p", v), first_mode="ref"), f"ic/{name}")
        result[name] = energy_after(path, L.IC / "s03p_matte.webm"); print(name, f"{t:.0f}s", flush=True)
    print(json.dumps(result), flush=True)
    L.board("s03p", ["s03p_layout_mask"] + [f"s03p_follow{round(v * 100)}" for v in levels] + ["s03p_layout"], DOCS / "perf_pose_s03_follow")
    data = json.loads((DOCS / "perf_pose_s03.json").read_text()); data["actor_follow"] = result
    (DOCS / "perf_pose_s03.json").write_text(json.dumps(data, indent=1))


# The same shot with the action written out in detail, timed to the previs keys (the recoil runs 4.3-4.8 s), each
# segment stamped with its facing and no face details (SPEC_10 §7.4).
DETAILED = ("Inside a circular glass-dome observatory at dawn, rain streaks the curved glass above a ring of brass consoles with amber "
            "instrument lights. Kael, a man in his thirties with short dark hair, light stubble and a charcoal field jacket. The camera "
            "tilts down from the dome ribs and pushes in behind his shoulder. "
            "0.0–1.4s, seen in profile: Kael stands at the rain-streaked glass, listening, weight on his back foot. "
            "1.4–2.8s, seen from behind: he turns from the glass to the console, shoulders squaring. "
            "2.8–4.3s, seen from behind: his left hand finds the large brass dial and turns it; far beyond the glass a beacon light blinks on. "
            "4.3–4.8s, seen from behind: he jerks his hand off the dial and recoils, his head snapping back, both arms flying up in front "
            "of his chest, his upper body rocking back half a step. "
            "4.8–6.0s, seen from behind: he holds the recoil, arms raised, head thrown back toward the light, shoulders locked. "
            "One person only. No text.")


def text_test(follow=0.35):
    """Pose and text together: which carries the recoil, and does the text rescue the freed or the Motion pass actor."""
    first, runs = L.IC / "s03r_first_grey.png", []
    for name in ("s03b", "s03p"):
        L.SHOTS[f"{name}_text"] = dict(L.SHOTS["s03m"], previs=f"{name}_previs.webm", prompt=DETAILED)
    runs.append(("s03b_text_layout_mask", lambda: L.ic("s03b_text", first, L.LAYOUT, mask="s03b_free_actor.mp4", first_mode="ref"), "s03b"))
    runs.append(("s03p_text_layout_mask", lambda: L.ic("s03p_text", first, L.LAYOUT, mask="s03p_free_actor.mp4", first_mode="ref"), "s03p"))
    runs.append(("s03p_text_motion", lambda: L.baseline("s03p_text"), "s03p"))
    runs.append((f"s03p_text_follow{round(follow * 100)}", lambda: L.ic("s03p_text", first, L.LAYOUT, mask=partial("s03p", follow), first_mode="ref"), "s03p"))
    result = {}
    for name, graph, previs in runs:
        path, t = zf.run(graph(), f"ic/{name}")
        result[name] = energy_after(path, L.IC / f"{previs}_matte.webm"); print(name, f"{t:.0f}s", flush=True)
    print(json.dumps(result), flush=True)
    L.board("s03p_text", [n for n, _, _ in runs], DOCS / "perf_pose_s03_text")
    data = json.loads((DOCS / "perf_pose_s03.json").read_text()); data["detailed_prompt"] = DETAILED; data["pose_and_text"] = result
    (DOCS / "perf_pose_s03.json").write_text(json.dumps(data, indent=1))


def newrig_test(levels=(0.35, 0.6)):
    """The anatomical render mannequin (figure.js: closed torso, tapering limbs, fingered hands) on the same recoil plan
    and detailed text: does the 60% follow still turn arms into tubes and hands into fists, and is the actor an adult?"""
    subprocess.run([sys.executable, str(Path(__file__).with_name("stage_render.py")), str(L.IC / "s03p_plan.json"), str(L.IC / "s03n_previs.webm")], check=True)
    L.SHOTS["s03n"] = dict(L.SHOTS["s03m"], previs="s03n_previs.webm", prompt=DETAILED)
    L.stage_free("s03n"); L.klein_grey("s03n")
    first, result, runs = L.IC / "s03n_first_grey.png", {}, ["s03n_text_layout_mask"] + [f"s03n_text_follow{round(v * 100)}" for v in levels]
    path, t = zf.run(L.ic("s03n", first, L.LAYOUT, mask="s03n_free_actor.mp4", first_mode="ref"), "ic/s03n_text_layout_mask"); print(runs[0], f"{t:.0f}s", flush=True)
    for v, name in zip(levels, runs[1:]):
        path, t = zf.run(L.ic("s03n", first, L.LAYOUT, mask=partial("s03n", v), first_mode="ref"), f"ic/{name}"); print(name, f"{t:.0f}s", flush=True)
    result = {n: energy_after(L.IC / f"{n}.mp4", L.IC / "s03n_matte.webm") for n in runs}
    print(json.dumps(result), flush=True)
    L.board("s03n", runs, DOCS / "perf_pose_s03_newrig")
    data = json.loads((DOCS / "perf_pose_s03.json").read_text()); data["anatomical_mannequin"] = result
    (DOCS / "perf_pose_s03.json").write_text(json.dumps(data, indent=1))


def product_test():
    """workflows/ltx25_layout_render.json as the product binds it (previs, actor matte, layout key, prompt), now with the
    actor following at 0.35 in-graph: it should match the lab's s03n_text_follow35."""
    g = json.loads((L.ROOT / "workflows/ltx25_layout_render.json").read_text(encoding="utf-8"))
    g["30"]["inputs"]["string_a"] = DETAILED
    g["20"]["inputs"]["video"] = zf.upload(L.IC / "s03n_previs.webm")
    g["24"]["inputs"]["video"] = zf.upload(L.IC / "s03n_matte.webm")
    g["2"]["inputs"]["image"] = zf.upload(L.IC / "s03n_first_grey.png")
    path, t = zf.run(g, "ic/s03n_product"); print("s03n_product", f"{t:.0f}s", flush=True)
    result = {n: energy_after(L.IC / f"{n}.mp4", L.IC / "s03n_matte.webm") for n in ("s03n_text_follow35", "s03n_product")}
    print(json.dumps(result), flush=True)
    L.SHOTS["s03n"] = dict(L.SHOTS["s03m"], previs="s03n_previs.webm")
    L.board("s03n", ["s03n_text_follow35", "s03n_product"], DOCS / "perf_pose_s03_product")
    data = json.loads((DOCS / "perf_pose_s03.json").read_text()); data["product_graph_follow35"] = result
    (DOCS / "perf_pose_s03.json").write_text(json.dumps(data, indent=1))


if __name__ == "__main__":
    {"follow": follow_test, "text": text_test, "newrig": newrig_test, "product": product_test}.get(sys.argv[1] if sys.argv[1:] else "", main)()
