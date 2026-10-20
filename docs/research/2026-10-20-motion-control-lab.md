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

## Product consequences

1. Shot bench gets a **3D previs** (three.js, already proven headless): blocking, camera path, lens, key/rim lights.
   Camera Motion and Optical Rig become authored data that renders to the grey init video.
2. The cinema stage becomes **two-pass** (draft from the grey init, identity edit on draft frames, pass 2 from the draft).
3. A **comp stage** with click-to-track, mattes and look layers after pass 2.
4. line-worlds as an LTX guide is not usable on LTX-2.5 (no IC-LoRA); its value is the blocking data, rendered as a grey
   blockout instead.
