# One-take tools (Updraft, 88 s)

These scripts made [`samples/updraft/updraft_oner.mp4`](../../samples/updraft/updraft_oner.mp4), an 88-second
single take: up a red canyon before dawn, over the rim into the first sun, a quiet hold on the pilot's face, a push
into her eye, through her pupil into a night rock pool, from the moon's reflection into the rising sun, from the sun
into the glowing balloon, and down to the child she was on her first flight. Every frame and every sound comes
from open-weights models in a local ComfyUI: LTX-2.5 22B distilled (video and sound, Layout-to-Render IC-LoRA),
FLUX 3 Klein (keyframes and edits) and ACE-Step 1.5 turbo (score).

The product side of the method is the chained Layout Render (`project_assistant/studio/layout_guides.py`): add
**Chain In Frame**, **Mid Key** and **End Key** image columns to a Cinema Studio row and its Layout Render pins the
previous slice's last frame and guides the slice toward the keys. These scripts are the same steps run directly
against ComfyUI, plus the compositing and sound work that sits outside a single shot.

## Pipeline

| Step | Script | What it does |
|---|---|---|
| Previs | `canyon_blockout.py` | Blender 4.3, headless. One continuous camera, balloon and cast blockout for the whole take; `lit` and `matte` (red = actor) passes; cut into 193-frame (8 s) slices that share their boundary frames. `blender -b --python canyon_blockout.py -- <out> lit <first> <last>` |
| Keys | `klein_trial.py` | FLUX 3 Klein reference edits: the previs frame fixes the composition, cast and set sheets fix the look. Three seeds per key; keep the one whose framing matches the previs. |
| Identity | `crop_edit.py`, `face_edit.py` | Crop a small or large face, repaint it against an approved face at 4x or 2x, paste it back feathered. |
| Slices | `layout_trial.py` | The product's `ltx25_layout_render.json` with `--pin <previous last frame>`, `--mid <frame>:<image>` (repeatable), `--end <key>` and `--grow <matte px>`. |
| Plates | `ltx_trial.py` | LTX-2.5 image-to-video from a key with a locked-off camera: the moving plates for the circle transitions. |
| Circles | `portal.py` | Circle-to-circle push-through: each plate opens inside a round thing in the plate before it (pupil to pool water, moon's reflection to sun, sun to the glowing envelope), size-matched, faded in, tinted and tracked. Settings: `updraft_chain.json`. |
| Seams | `assemble.sh`, `seam_check.py`, `facehold.py`, `lumamatch.py`, `seamfix.py` | Join slices (dropping each shared first frame), measure every seam (pixel difference, motion, sharpness), cancel a subject shrinking in frame with a face-locked push-in, ease out a brightness step at a seam. |
| Sound | `audio_mix.py`, `music_trial.py` | Each LTX take carries its own synced 48 kHz audio; `audio_mix.py` lays the takes where their pictures are, cross-fades seams, fills silent stretches with the takes' own wind and burner bursts, makes each plate's sound follow its fade on screen, and with a third argument lays the ACE-Step score under the effects (section levels, ducking under the burner), -16 LUFS. `music_trial.py` runs ACE-Step 1.5 through ComfyUI's core nodes with the official template settings. |

`audio_mix.py` and `updraft_chain.json` name the Updraft takes and plates; they are the worked example of the method.

## What we learned (and the tools encode)

- **Keep faces in the profile of the approved keys.** A face turned frontal is painted as a different person, and a
  Klein edit cannot change a frontal face's identity. Move head turns to where the camera is already tight.
- **Guides from small edits.** A Klein edit that only opens the eyes or adds a smile keeps the face; use it as a mid
  guide. Guides must match the framing LTX actually produces (start from the previous slice's last frame, unzoomed);
  an upscaled guide gives soft, fast-zooming output.
- **Never cover a seam with a dissolve.** Fix the cause: pin, a guide at frame 24 holding the previous framing, then
  `facehold.py` and `lumamatch.py` for what remains.
- **Moving plates, not still zooms.** A zoomed still as previs gives a still-looking shot; composite real LTX plates.
- **Every take has sound.** Mix from the takes' own audio before adding anything.

## Requirements

ComfyUI 0.42.x at `COMFY_BASE_URL` (default `http://127.0.0.1:8188`) with LTX-2.5 22B distilled and its
Layout-to-Render IC-LoRA, FLUX 3 Klein and, for the score, the ACE-Step 1.5 split files
(`acestep_v1.5_turbo`, `qwen_0.6b_ace15`, `qwen_1.7b_ace15`, `ace_1.5_vae`); Python with `numpy` and
`opencv-python`; FFmpeg; Blender 4.3 for the previs. Run the scripts from this folder with `python -X utf8`.
