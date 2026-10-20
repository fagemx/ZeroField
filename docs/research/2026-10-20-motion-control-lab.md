# Motion, space and compositing control on open weights (2026-10-20)

**Question.** ZeroField shots were "posed keyframe + one sentence of prompt": stiff motion, Optical Rig and Camera
Motion were only words, no lighting control, no layers. Can the local open-weights stack (FLUX 3 Klein, LTX-2.5 22B
distilled, ComfyUI 0.42.1 on one RTX 4090) be driven by **space and motion** instead of text, then have its subjects
replaced, then be finished with VFX, relighting and a real comp?

Everything below ran locally; evidence is in [`verification/motion-lab/`](../verification/motion-lab/), scripts in
[`research/motion_lab/`](../../research/motion_lab/). Shot under test: S03 "Kael reaches for the brass dial as a light
answers outside", 97 frames, 1280x704, 24 fps.

## Answer

```
3D blockout (Blender or three.js): camera path, real lens, actor blocking, lighting
  -> pass 1: LTX-2.5 V2V with the grey render as the init latent, denoise 0.75, beat-timed prompt
     = motion-correct draft (camera, blocking and hold come from 3D)
  -> pull the first/last frames from the draft, FLUX 3 Klein edits identity/wardrobe (face crop + cast references)
  -> pass 2: LTX-2.5 V2V of the draft, denoise 0.5, edited frames as first frame + last-frame guide
     = same motion, the right person, no ghosting
  -> comp: SAM mattes, 2D tracker, flare, relight, rain on glass, haze, bloom, grade, lens
```

## Motion control: what works and why

| Method | Result | Why |
| --- | --- | --- |
| Posed keyframe + one sentence (old) | stiff | the still is a pose, the prompt names no event |
| Action-start keyframe + beat sheet (no 3D) | lively, camera roughly follows the text; hand leaves the dial | text steers, nothing pins space |
| 3 independently painted keyframes (0/48/96) | hard cuts between keyframes ([sheet](../verification/motion-lab/P1_keyframes_0_48_96.jpg)) | keyframes disagree, LTX cannot interpolate them |
| First + last frame | end pins, arrives early and freezes ([sheet](../verification/motion-lab/P2_first_last.jpg)) | a single-image guide at strength 1 is reached too soon; its quality decides everything |
| Grey / depth / line-worlds video as `LTXVAddGuide` | **copies the guide** - output is the grey model ([P5](../verification/motion-lab/P5_guide_gray_s50.jpg), [P4](../verification/motion-lab/P4_guide_depth_s60.jpg), [P6](../verification/motion-lab/P6_guide_lineworlds_s60.jpg)) | the guide is pixel conditioning; the official LTX-2.5 repo ships **no** depth/pose/layout IC-LoRA |
| Depth video as the init latent | white blob ([sheet](../verification/motion-lab/R2e_depth_d75_nofirst.jpg)) | depth values read as image content |
| **Grey render as the init latent, denoise 0.75** | **camera path, blocking and the hand-on-dial hold follow the 3D scene** ([draft](../verification/motion-lab/pass1_draft_grey_v2v.mp4), [sheet](../verification/motion-lab/R2a_gray_d75_nofirst.jpg)) | the grey shading seeds structure; the model repaints the look |

Denoise is the space-control knob: 0.9 is almost text-only, 0.75 holds camera and blocking, 0.7 and below starts to keep
the grey look.

Generality on the same grey-V2V setup:

- **Crane** (floor to top-down) and **orbit** follow the path ([crane](../verification/motion-lab/crane_grey_v2v.mp4), [orbit](../verification/motion-lab/T_orbit.jpg)).
- **Lens**: an 85 mm Blender camera gives telephoto compression and shallow depth of field ([sheet](../verification/motion-lab/T_lens85.jpg)).
  Optical Rig becomes a real focal length, not words. Very tight framings make small props ambiguous (the dial became a telescope eyepiece).
- **Lighting**: an Eevee render with a warm low key and a cold rim carries direction and colour temperature into the take
  ([video](../verification/motion-lab/lit_grey_v2v.mp4)); hard cold edge light can turn into LED strips.
- three.js renders the same blockout headless (Playwright + WebGL), so the previs can live inside the ZeroField web UI.

## Replacement (identity, wardrobe, set)

- Klein **repainting a grey blockout** keeps composition only loosely (it reframes); first frames painted that way ghost
  for ~1 s against the grey-driven motion ([sheet](../verification/motion-lab/P3_v2v_gray_d75.jpg)).
- Klein **editing a photoreal draft frame** keeps composition exactly. A light instruction does not change the face; an
  explicit face replacement with a face crop + cast reference does ([board](../verification/motion-lab/identity_swap.jpg), seed 5502).
- Pass 2 (draft as init, denoise 0.5, edited first frame + last-frame guide at 0.8) keeps the draft's motion with no
  ghost and lands the edited identity ([video](../verification/motion-lab/pass2_identity.mp4)). Using the grey video
  instead of the draft also works but loses smoothness ([F1](../verification/motion-lab/F1_gray_k0_k96s80.jpg)).
- A cast reference as a pre-roll latent guide (before frame 0) does not disturb motion but did not visibly carry identity.
- **Set identity** follows the blockout geometry more than any edit: the crane blockout's ring console produced a ring
  console; thin mullions produced ordinary windows. Rebuilding the room in the keyframes moves pass 2 only at denoise
  0.7 ([sheet](../verification/motion-lab/G2_draft_d70_room.jpg)). Model the dome ribs and console arc in the blockout.

## Compositing on the AI plate

[`comp.py`](../../research/motion_lab/comp.py) on the pass-2 plate ([before/after](../verification/motion-lab/comp_before_after.mp4),
[frames](../verification/motion-lab/comp_before_after_frames.jpg)):

- **Mattes**: SAM ViT-H per frame (local weights, no download), first box from the blockout actor matte, then box +
  head point from the previous mask, picking the candidate with the best temporal IoU. Without those constraints the box
  grows to the frame and the matte inverts or drops the head.
- **Tracking**: template-match tracker seeded by one click on the beacon lamp, forward and backward. An automatic
  "brightest warm spot" heuristic locked onto a window reflection.
- **Beacon flash**: timed pulses with glow + anamorphic streak at the tracked point, a cool light sweep from that
  direction, brass glints, and a directional cool rim on the actor's edge facing the beacon (an even outline looked cut out).
- **Atmosphere and lens**: rain on glass (scrolling streaks + droplets refracting the background inside the window
  region), horizon haze, highlight bloom, teal/amber split grade, chromatic aberration, vignette, grain; source audio kept.

## Set identity, solved in the blockout

Rebuilding the blockout from the SET-01 reference (meridian dome ribs meeting overhead, a continuous console ring
hugging the glass, the opening camera tilted up at the dome) makes the motion pass produce the glass-dome observatory
([pass 1](../verification/motion-lab/observatory_pass1.jpg), [pass 2](../verification/motion-lab/observatory_pass2.jpg),
script [`blockout_observatory.py`](../../research/motion_lab/blockout_observatory.py)). The comp on that plate
([before/after](../verification/motion-lab/observatory_comp_before_after.jpg), [video](../verification/motion-lab/observatory_comp.mp4))
is now S03's cinema shot in the showcase.

## In the product (same day)

- **Previs column** on the cinema slate (appended last, so existing column indexes and pipelines keep working); the
  showcase upgrade adds it once and gives S03 the Blender blockout (`samples/previs_s03_blockout.mp4`).
- **3D previs editor** in the shot bench (three.js, lazy-loaded): set, actor action, camera move, lens, light,
  free framing with start/end keys, scrub, and *Render previs*, which records 97 frames and writes the Previs cell
  through the normal upload path ([editor](../verification/motion-lab/previs_editor.jpg),
  [night light](../verification/motion-lab/previs_editor_night.jpg), [bench](../verification/motion-lab/shot_bench_previs.jpg)).
- **Pipeline lane** *Previs Motion Pass → Look Key → Look Pass* with three graphs
  (`ltx25_previs_motion.json`, `flux3_klein_look_key.json`, `ltx25_previs_look.json`); frames are picked inside the
  graphs (`ImageFromBatch`), Soul Cast references bind to the Klein edit. A rearranged pipeline gets the lane appended
  once instead of being replaced. Ran end to end in the app on S03 ([motion pass](../verification/motion-lab/app_lane_motion_pass.jpg)).
- Fixed on the way: an optional media binding with no asset left its `LoadImage` pointing at a placeholder file; the
  empty loader is now removed.
- **Frame-exact previs**: *Render previs* encodes with WebCodecs (VP9) into a small WebM writer (`ui/src/previs/webm.js`),
  so the clip is exactly 97 frames at 24 fps (MediaRecorder gave ~95 at ~21). The blockout casts soft shadows from a
  studio key like the Blender workbench one ([earlier flat version](../verification/motion-lab/previs_blender_vs_threejs.jpg)).
- **Style lock in the motion pass**: distilled LTX-2.5 runs at cfg 1, so the negative prompt has no effect, and a grey
  blockout pulled the draft toward CG cartoon. `ltx25_previs_motion.json` appends a fixed live-action sentence after the
  shot prompt (`StringConcatenate`, node 30). Same S03 previs, before and after: [cartoon → photographic](../verification/motion-lab/motion_pass_style_lock.jpg).

Known gaps: **identity**. The Klein look key keeps the draft's person when the head is small or turned away. On S03 the
push-in ends on his back, and a swap on the mid-shot profile (frame 48) either changed nothing or produced a different
man ([draft, two seeds, CAST-01](../verification/motion-lab/look_key_identity_limit.jpg)); a stronger swap instruction
and a camera end key beside him did not help (LTX still turns him to the console). The look pass is photographic and
follows the blocking, but it is not Kael. Next candidates: an identity LoRA for the cast, or framing where the face fills
the key. The editor plan is remembered per browser; the rendered previs is what the project stores.

## Product consequences

1. Shot bench gets a **3D previs** (three.js, already proven headless): blocking, camera path, lens, key/rim lights.
   Camera Motion and Optical Rig become authored data that renders to the grey init video.
2. The cinema stage becomes **two-pass** (draft from the grey init, identity edit on draft frames, pass 2 from the draft).
3. A **comp stage** with click-to-track, mattes and look layers after pass 2.
4. line-worlds as an LTX guide is not usable on LTX-2.5 (no IC-LoRA); its value is the blocking data, rendered as a grey
   blockout instead.
