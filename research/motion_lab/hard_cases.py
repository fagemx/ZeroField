"""SPEC_10 §7.9 on the 4090: the hard cases. Every performance test so far was calm and seen from behind (S03 turning
the dial); this one faces the camera at high tension. Three beats of a Kael / Mira confrontation, 6 s each:

  tears   Kael close-up, facing the camera: holding it together, his face crumples, he lifts his head in tears
  scream  Mira close-up, facing the camera: glaring, she lunges forward and screams at him
  shove   two-shot, Kael facing the camera, Mira over her shoulder: she shoves him into the console (body contact)

Each beat through the product's Layout Render recipe (Layout-To-Render on the previs with the cast freed, Union-Control
on the pose skeleton, the layout key as an out-of-clip reference; pose_skeleton.py layout_pose), three ways to push the
emotion, the same detailed timed prompt and seed:

  text    the product as it is: a layout key with no expression asked for, body + hands skeleton
  key     the layout key drawn with the beat's emotion (Klein): does the reference carry the face?
  face    the skeleton also draws the 68 face points, moved by the performance keys' expressions (skeleton.js)

plus scream_face_neutral: face points with a prompt that never mentions screaming, so only the points can make her scream.
Cast portraits are drawn first (Klein text to image); the layout keys follow the product's Layout Key wording.
A local vision model reads each take blind (what emotion, same person as the portrait?).

usage: python hard_cases.py [cast|prep|run|grade|board]...   (no argument: all of them in order)
"""
import base64, json, subprocess, sys, urllib.request
from pathlib import Path

import fidelity
import iclora as L
import zf
from perf_scale import DOCS

SEED_CAST = {"kael": 7101, "mira": 7202}
KAEL = "Kael, a man in his mid thirties with short dark hair, light stubble and a charcoal field jacket"
MIRA = "Mira, a woman in her early thirties with shoulder-length auburn hair, freckles and a dark green wool long coat"
PORTRAIT = ("Photographic head-and-shoulders portrait of {who}, facing the camera, calm neutral expression, soft window light, plain dark "
            "grey background. Live-action film still, 35mm photography, natural skin texture. One person only. No text.")
CAST = {
    "kael": PORTRAIT.format(who="Kael, a man in his mid thirties with short dark hair, light stubble, a strong jaw and tired grey-green eyes, "
                               "wearing a charcoal field jacket over a dark henley"),
    "mira": PORTRAIT.format(who="Mira, a woman in her early thirties with shoulder-length auburn hair, freckles, sharp cheekbones and dark "
                               "brown eyes, wearing a dark green wool long coat over a cream sweater"),
}
FIG = {"kael": {"build": "man", "outfit": "jacket", "hair": "short", "tone": 0}, "mira": {"build": "woman", "outfit": "longcoat", "hair": "long", "tone": 1}}
SET = ("Inside a circular glass-dome observatory at dawn, rain streaks the curved glass above a ring of brass consoles with amber "
       "instrument lights. ")
END1, END2 = " One person only. No text.", " Two people only. No text."

BEATS = {
    "tears": dict(
        cast=["kael"],
        plan={"set": "observatory", "mood": "grey", "lens": 50, "seconds": 6, "move": "static", "figure": FIG["kael"], "mark": [0, 0], "turn": 180,
              "keys": [[0, [-0.42, 1.76, -1.45], [0, 1.74, 0]], [96, [-0.3, 1.76, -1.05], [0, 1.72, 0]]],
              "acts": [{"at": 0, "yaw": 0, "face": "tense"}, {"at": 0.3, "body": "stand", "face": "tense"}, {"at": 0.5, "body": "slump", "face": "cry"},
                       {"at": 0.72, "body": "slump"}, {"at": 0.88, "body": "stand"}]},
        prompt=SET + KAEL + ". Close-up, the camera slowly pushes in on his face. "
               "0.0–1.8s, facing the camera: Kael stands with his back against the console, jaw clenched, eyes glistening, fighting to hold it "
               "together, looking at Mira just off camera. "
               "1.8–4.3s, facing the camera: his face crumples, his chin trembles, his shoulders drop and his head sinks forward as he starts to sob. "
               "4.3–6.0s, facing the camera: he lifts his head, tears streaming down his cheeks, eyes red and wet, mouth trembling, breathing in "
               "ragged sobs." + END1,
        facing="He faces the camera, looking just past it: paint his face toward us, not the back of his head.",
        emotion="He is crying: tears streaming down his cheeks, eyes red and wet, brows pulled up in the middle, mouth trembling."),
    "scream": dict(
        cast=["mira"],
        plan={"set": "observatory", "mood": "grey", "lens": 50, "seconds": 6, "move": "static", "figure": FIG["mira"], "mark": [0, -1.25], "turn": 0,
              "keys": [[0, [0.36, 1.64, 0.2], [0, 1.6, -1.25]], [96, [0.3, 1.64, 0.06], [0, 1.6, -1.25]]],
              "acts": [{"at": 0, "yaw": 0, "face": "rage"}, {"at": 0.25, "body": "stand", "face": "rage"}, {"at": 0.38, "body": "lean", "face": "scream"},
                       {"at": 0.8, "body": "lean", "face": "scream"}, {"at": 0.95, "body": "stand", "face": "rage"}]},
        prompt=SET + MIRA + ". Close-up on her face, the camera slowly pushes in. "
               "0.0–1.5s, facing the camera: Mira glares straight at Kael just past the camera, nostrils flaring, jaw tight, breathing hard with rage. "
               "1.5–2.3s, facing the camera: she lunges forward from the hips and screams at him, mouth wide open, teeth bared, brows crushed down, "
               "the cords of her neck straining. "
               "2.3–4.8s, facing the camera: she keeps screaming, leaning in, eyes blazing, her whole face shaking with fury. "
               "4.8–6.0s, facing the camera: she pulls back upright, chest heaving, still glaring, out of breath." + END1,
        neutral=SET + MIRA + ". Close-up on her face, the camera slowly pushes in. "
                "0.0–6.0s, facing the camera: Mira stands in front of Kael, just past the camera, and looks at him." + END1,
        facing="She faces the camera, looking just past it: paint her face toward us, not the back of her head.",
        emotion="She is screaming in rage: mouth wide open, teeth bared, brows crushed down, eyes blazing."),
    "shove": dict(
        cast=["kael", "mira"],
        plan={"set": "observatory", "mood": "grey", "lens": 35, "seconds": 6, "move": "static", "figure": FIG["kael"], "mark": [0, 0], "turn": 180,
              "keys": [[0, [1.95, 1.5, -1.75], [0, 1.35, -0.38]], [96, [1.8, 1.5, -1.6], [0, 1.35, -0.38]]],
              "acts": [{"at": 0, "yaw": 0, "back": 0, "face": "tense"}, {"at": 0.22, "back": 0, "body": "stand", "face": "tense"},
                       {"at": 0.32, "back": -0.38, "body": "recoil", "face": "shock"}, {"at": 0.55, "body": "stand"}],
              "cast": [{"figure": FIG["mira"], "mark": [0, -0.72], "turn": 0,
                        "acts": [{"at": 0, "yaw": 0, "back": 0, "face": "rage"}, {"at": 0.18, "back": 0, "body": "stand"},
                                 {"at": 0.28, "back": -0.2, "body": "push", "face": "scream"}, {"at": 0.45, "body": "push"},
                                 {"at": 0.62, "body": "stand", "face": "rage"}]}]},
        prompt=SET + KAEL + ", and " + MIRA + ". Medium two-shot, the camera eases in. "
               "0.0–1.1s: Mira, seen from behind over her shoulder, stands face to face with Kael, inches apart, glaring; Kael, facing the camera, "
               "stares back, jaw tight. "
               "1.1–1.9s: Mira shoves him hard in the chest with both hands, stepping into it; Kael, facing the camera, is knocked backward, his "
               "head snapping back and his arms flying up. "
               "1.9–3.3s: Kael, facing the camera, slams back against the brass console behind him and catches himself, shocked, mouth open; "
               "Mira, seen from behind, stays close with her arms still out, shouting at him. "
               "3.3–6.0s: Kael, facing the camera, stares at her in disbelief, breathing hard; Mira, seen from behind, stands over him, her "
               "shoulders heaving." + END2,
        facing=("The man faces the camera at three-quarters: paint his face toward us. The woman has her back to the camera, her face "
                "turned toward him."),
        emotion="The woman is furious, glaring at him; the man is shocked and afraid, eyes wide, mouth open."),
}
# The product's Layout Key wording (run_studio.py LAYOUT_KEY_PROMPT): composition first. No set image: a photographic set still
# as the last reference made Klein copy its framing (a small figure at the glass) whatever the blockout showed. The facing is
# written out: the render mannequin's bare egg of a face read as the back of a head.
KEY = ("Repaint the first image, a grey 3D blockout, as a photographic live-action film still. The first image fixes the composition: keep "
       "its exact camera angle, framing, horizon and set layout, and each figure's exact position, size, pose and facing; do not move the "
       "camera or change the shot size. {who} {facing} Paint the set as a glass-dome observatory at dawn: rain-streaked glass, thin dark metal "
       "ribs, brass consoles with amber instrument lights.{emotion} {end}")
WHO = {
    "kael": "Paint the figure as the man of the second image (face, short dark hair, stubble, charcoal field jacket) at the figure's size.",
    "mira": "Paint the figure as the woman of the second image (face, auburn hair, freckles, dark green wool long coat) at the figure's size.",
    "kael+mira": ("Paint the figure facing the camera as the man of the second image (face, short dark hair, stubble, charcoal field jacket) "
                  "and the figure with its back to the camera as the woman of the third image (auburn hair, dark green wool long coat), "
                  "each at the figure's size."),
}
GRAB = {"tears": (0.15, 0.6, 0.9), "scream": (0.15, 0.5, 0.7), "shove": (0.12, 0.35, 0.6)}  # moments graded and boarded: before / in / after the peak
METHODS = ("text", "key", "face")


def shot(beat):
    return f"hc_{beat}"


def cast():
    for who, prompt in CAST.items():
        path, t = zf.run(zf.klein(prompt, SEED_CAST[who], width=1024, height=1024), f"ic/cast_{who}")
        print(path.name, f"{t:.0f}s", flush=True)


def prep():
    render = Path(__file__).with_name("stage_render.py")
    for beat, b in BEATS.items():
        s = shot(beat); plan = L.IC / f"{s}_plan.json"
        plan.write_text(json.dumps(b["plan"]), encoding="utf-8")
        subprocess.run([sys.executable, str(render), str(plan), str(L.IC / f"{s}_previs.webm")], check=True)
        L.SHOTS[s] = dict(previs=f"{s}_previs.webm", frames=145, prompt=b["prompt"])
        L.stage_free(s)
        for mode in ("skeleton", "skeletonface"):
            webm = L.IC / f"{s}_{mode}.webm"
            subprocess.run([sys.executable, str(render), str(plan), str(webm), mode], check=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(webm), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", str(L.IC / f"{s}_{mode}.mp4")], check=True)
        # Layout keys: the previs' first frame through Klein, without and with the beat's emotion.
        src = L.frame(L.IC / f"{s}_previs.webm", 0, L.IC / f"{s}_previs_f000.png")
        refs = (zf.upload(src), *(zf.upload(L.IC / f"cast_{c}.png") for c in b["cast"]))
        who, end = WHO["+".join(b["cast"])], END2 if len(b["cast"]) > 1 else END1.strip()
        for tag, emotion in (("key", ""), ("keyemo", " " + b["emotion"])):
            path, t = zf.run(zf.klein(KEY.format(who=who, facing=b["facing"], emotion=emotion, end=end.strip()), L.KLEIN_SEED, refs=refs), f"ic/{s}_{tag}")
            print(path.name, f"{t:.0f}s", flush=True)


def layout_pose(s, first, guide):
    """pose_skeleton.py layout_pose for any shot: Layout-To-Render on the previs (cast freed) + Union-Control on a skeleton."""
    g = L.ic(s, first, L.LAYOUT, mask=f"{s}_free_actor.mp4", first_mode="ref")
    g["62"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["60", 0], "lora_name": L.UNION, "strength_model": 1.0}}
    g["63"] = {"class_type": "GetICLoRAParameters", "inputs": {"iclora_model": ["62", 0]}}
    g["26"] = dict(g["20"], inputs=dict(g["20"]["inputs"], video=zf.upload(guide)))
    g["42"] = {"class_type": "LTXVAddGuide", "inputs": {"positive": ["41", 0], "negative": ["41", 1], "vae": ["5", 0], "latent": ["41", 2], "image": ["26", 0],
                                                        "frame_idx": 0, "strength": 1.0, "iclora_parameters": ["63", 0]}}
    g["15"]["inputs"]["video_latent"] = ["42", 2]
    g["53"]["inputs"].update(model=["62", 0], positive=["42", 0], negative=["42", 1])
    g["17"]["inputs"].update(positive=["42", 0], negative=["42", 1])
    return g


def runs():
    out = {}
    for beat, b in BEATS.items():
        s = shot(beat)
        out[f"{s}_text"] = (s, b["prompt"], "key", "skeleton")
        out[f"{s}_key"] = (s, b["prompt"], "keyemo", "skeleton")
        out[f"{s}_face"] = (s, b["prompt"], "key", "skeletonface")
    out[f"{shot('scream')}_face_neutral"] = (shot("scream"), BEATS["scream"]["neutral"], "key", "skeletonface")
    return out


def run(only=None):
    data_path = DOCS / "perf_hard_cases.json"
    data = json.loads(data_path.read_text()) if data_path.exists() else {}
    for name, (s, prompt, key, skel) in runs().items():
        if only and name not in only:
            continue
        L.SHOTS[s] = dict(previs=f"{s}_previs.webm", frames=145, prompt=prompt)
        try:
            path, t = zf.run(layout_pose(s, L.IC / f"{s}_{key}.png", L.IC / f"{s}_{skel}.mp4"), f"ic/{name}")
        except Exception as e:
            print(name, "FAIL", str(e)[:1500], flush=True); continue
        data.setdefault("runs", {})[name] = {"seconds": round(t), "camera": fidelity.score(L.IC / f"{s}_previs.webm", path)["score"]}
        print(name, json.dumps(data["runs"][name]), flush=True)
        data_path.write_text(json.dumps(data, indent=1))


def stills(clip, beat, dest):
    """The graded moments of a take side by side (640 px each)."""
    picks = "+".join(f"eq(n\\,{round(u * 144)})" for u in GRAB[beat])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf", f"select={picks},scale=640:-2,tile={len(GRAB[beat])}x1", "-frames:v", "1", str(dest)], check=True)
    return dest


def ask(prompt, images):
    body = {"model": "qwen3.8:27b-16k", "stream": False, "think": False, "options": {"temperature": 0},
            "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(Path(i).read_bytes()).decode() for i in images]}]}
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))["message"]["content"].strip()


READ = ("These are three frames from one film shot, left to right in time. For each frame, in one short phrase, say what emotion the "
        "person facing the camera shows on their face (if no face is visible, say so). Then rate from 0 to 10 how clearly a viewer can read "
        "that emotion in the strongest frame. Answer as JSON: {\"frames\": [\"...\", \"...\", \"...\"], \"clarity\": n}.")
SAME = ("The first image is a reference portrait. The second image is a frame from a film. Is the {who} facing the camera in the second "
        "image the same person as the reference? Judge the face shape, hair and features, not the expression or lighting. Answer as JSON: "
        "{{\"same\": true or false, \"confidence\": 0-100, \"why\": \"...\"}}.")
CONTACT = ("These are three frames from one film shot, left to right in time: a woman shoves a man. Rate from 0 to 10 how physically "
           "believable the contact is (hands on the body, the push and the reaction, no limbs merging or passing through bodies), and name any "
           "artefact. Answer as JSON: {\"believable\": n, \"artefacts\": \"...\"}.")


def grade():
    data_path = DOCS / "perf_hard_cases.json"; data = json.loads(data_path.read_text())
    zf.free()  # the vision model needs the GPU LTX holds
    for name, (s, _, _, _) in runs().items():
        clip = L.IC / f"{name}.mp4"
        if not clip.exists():
            continue
        beat = s.removeprefix("hc_")
        strip = stills(clip, beat, L.IC / f"_{name}_strip.png")
        g = {"read": ask(READ, [strip])}
        peak = L.frame(clip, round(GRAB[beat][2] * 144), L.IC / f"_{name}_peak.png")
        face_owner = "mira" if beat == "scream" else "kael"
        g["same"] = ask(SAME.format(who="woman" if face_owner == "mira" else "man"), [L.IC / f"cast_{face_owner}.png", peak])
        if beat == "shove":
            g["contact"] = ask(CONTACT, [strip])
        data["runs"][name]["grade"] = g
        print(name, json.dumps(g), flush=True)
        data_path.write_text(json.dumps(data, indent=1))
    body = {"model": "qwen3.8:27b-16k", "keep_alive": 0}
    urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/generate", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}))


def board():
    for beat in BEATS:
        s = shot(beat); L.SHOTS[s] = dict(previs=f"{s}_previs.webm", frames=145)
        clips = [f"{s}_skeletonface"] + [f"{s}_{m}" for m in METHODS] + ([f"{s}_face_neutral"] if beat == "scream" else [])
        L.board(s, [c for c in clips if (L.IC / f"{c}.mp4").exists()], DOCS / f"perf_hard_{beat}")
        # The graded moments, one row per method, for a close look at faces.
        rows = [stills(L.IC / f"{c}.mp4", beat, L.IC / f"_{c}_strip.png") for c in clips[1:] if (L.IC / f"{c}.mp4").exists()]
        font = "C\\:/Windows/Fonts/arial.ttf"
        inputs = sum((["-i", str(r)] for r in rows), [])
        labels = "".join(f"[{i}:v]drawtext=fontfile='{font}':text='{c.removeprefix(s + '_')}':x=8:y=8:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6[r{i}];"
                         for i, c in enumerate(clips[1:len(rows) + 1]))
        subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", labels + "".join(f"[r{i}]" for i in range(len(rows))) + f"vstack=inputs={len(rows)}",
                        "-q:v", "3", str(DOCS / f"perf_hard_{beat}_faces.jpg")], check=True)


if __name__ == "__main__":
    steps = {"cast": cast, "prep": prep, "run": run, "grade": grade, "board": board}
    for step in sys.argv[1:] or list(steps):
        steps[step]()
