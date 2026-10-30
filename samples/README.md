# Updraft: the ZeroField showcase production

`updraft/production.json` is the single source of the showcase: the director brief, the episode look, twelve assets (two characters, four locations, four props and two prop states) with their locked descriptions, voice and acting profiles, location maps, light logic and shape locks, and a ten-shot, about forty-second slate. The launcher (`run_studio.py`) and the `zerofield_studio` project template both read it, and `docs/examples/UPDRAFT_BIBLE.md` is a readable copy.

Updraft is original: a trainee pilot's burner dies over a red canyon at sunrise and her instructor will not take the controls. No third-party footage, likenesses, characters or text are used.

## Media

Every picture and clip in `updraft/media/` was generated on 2026-10-29 through ZeroField itself, on one RTX 4090 with open-weights models only (FLUX 3 Klein for the asset panels and first frames, LTX-2.5 22B distilled for video with sound, local ComfyUI). `updraft/updraft_film.mp4` is the episode film the studio exported from the ten adopted takes (40 s, 1280×720, generated sound, no music).

`updraft/updraft_oner.mp4` is a single 88-second take made on 2026-10-29/30 with the same models plus ACE-Step 1.5 turbo for the score (1280×704, 24 fps, -16 LUFS): up the canyon before dawn, over the rim into the first sun, a quiet hold on Noa's face, a push into her eye, and through a chain of circles (pupil, rock pool, moon, sun, the glowing envelope) to the child she was on her first flight. It is nine chained Layout Render slices from one Blender previs camera, each starting on the previous slice's last frame and guided to planned Klein keys, plus a 17 s circle transition composited from four LTX image-to-video plates; the sound is the takes' own LTX audio with the score under it. How it was made: [`tools/oner/`](../tools/oner/README.md) and [chained Layout Render](../workflows/README.md#layout-render-3d-stage-previs-as-an-ic-lora-layout).

What is there, and how it was made:

- **Character sheets** (`cast-01_sheet.jpg`, `cast-02_sheet.jpg`): a 3/4 face close-up generated once (four candidates, one chosen), a full-body front rendered with the face as its only reference and then cropped below the chin by the server (`server-crop`: the model never sees a small face it could copy into wide shots), a full-body back rendered from the face, and the three composed side by side by the server (`server-compose`).
- **Locations** (`set-0N_plate.jpg`): a 3/4 plate per place, empty of people, with its location map and single light logic kept as text locks.
- **Props** (`prop-0N_product.jpg`): product shots on neutral grey with a shape lock; the burner's two states (`prop-03_lit`, `prop-03_dead`) are edits of the burner's own picture, so only the flame changes.
- **Shots** (`s01_key.jpg` … `s10_take.mp4`): each first frame was rendered with the reference plan of its shot (the faces, bodies, place and props it names, up to six pictures) and each take animated by LTX-2.5 from that frame with the compiled video skeleton.
- Files with a short suffix (`cast-01_face_5d770f.jpg`, `s04_take_eaf80b.mp4`) are the candidates the production chose between; the seed lists them beside the chosen one. Candidate takes are re-encoded at a lower bitrate to keep the repository small.

`updraft/manifest.json` records each file's card, seed and the exact prompt the card received (recompiled from the frozen task input):

```json
{"items": [{"tab": "soul-cast", "code": "CAST-01", "column": "Reference Image", "panel": "face",
            "file": "noa_face.png", "card": "flux-soul-cast", "seed": 21001, "prompt": "..."}]}
```

`tab` is `soul-cast` or `cinema-studio`, `code` the row (`CAST-01`, `S01`), `column` the sheet header, `panel` the asset panel (`face`, `front`, `plate`, ...) or `null`, `file` a file in `updraft/`, and `card`, `seed` and `prompt` the generation record. Without a manifest the seed writes the content and the asset records only. With one, it fills only empty cells, once, and never overwrites a take, prompt or edit a person made.

## Other files here

`cast_kael.png`, `set_observatory.png` and `shot_s01.mp4` are small procedural placeholders left over from the earlier fixtures. The backend upload tests and the motion-lab scripts under `research/motion_lab/` still read them; they are not model renders and are not part of Updraft.

## License

The Updraft content, and the media generated for it, are dedicated to the public domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Code elsewhere in the repository follows the repository license.
