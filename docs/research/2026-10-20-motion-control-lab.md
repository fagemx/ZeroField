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
| Grey / depth / line-worlds video as `LTXVAddGuide` | **copies the guide** - output is the grey model ([P5](../verification/motion-lab/P5_guide_gray_s50.jpg), [P4](../verification/motion-lab/P4_guide_depth_s60.jpg), [P6](../verification/motion-lab/P6_guide_lineworlds_s60.jpg)) | a plain guide is pixel conditioning. These runs loaded no IC-LoRA; Lightricks publishes them in separate HF repos (see [Layout-To-Render IC-LoRA](#layout-to-render-ic-lora-2026-10-21)) |
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
- **3D Stage** view of the slate (three.js, lazy-loaded), next to Table / Canvas / Gallery / Board: every shot in one
  set. The shot list (keyframe thumbnails, previs state) sits beside a viewport with three cameras: **Lens** (through
  the shot's planned camera), **Overhead** (a floor plan with every shot's camera path, glyph and label; shots on the
  same path share one label) and **Free camera** (orbit, then set the shot's start/end key). *Play shot* loops one shot,
  *Play scene* cuts through the following shots in slate order; ↑/↓ switch shots. A shot starts from its slate text
  (Camera Motion, the Optical Rig lens, the action). *Render previs* writes 97 frames into the shot's Previs cell and
  stores the plan inside the WebM (Segment Title), so the project keeps it; unrendered edits stay in the browser.
  *Block in 3D* in the shot bench opens the stage on that shot ([workbench](../verification/motion-lab/stage_workbench.jpg),
  [overhead plan](../verification/motion-lab/stage_overhead.jpg); the earlier per-shot dialog:
  [editor](../verification/motion-lab/previs_editor.jpg), [night light](../verification/motion-lab/previs_editor_night.jpg)).
- **Stage → AI in one place**: *Run motion pass* on the stage queues the Previs Motion Pass for that shot (a node
  predicate picks it among the steps that write Cinema Shot) and the take waits for review. A short *How it works* list
  sits above the controls. Presets are framed for 35 mm; another lens dollies each key along its line of sight to hold
  the shot size, stopping on the open floor inside the console ring. *Facing* turns the actor to the room (camera side).
- **Shot length**: the stage offers 4, 6 or 8 s (97, 145 or 193 frames, LTX's 8n+1); camera keys and the actor's timing
  run on a 0..96 beat clock, so a longer shot plays the same blocking slower. The previs graphs load up to 193 frames and
  encode/decode the video in 64-frame chunks (`VAEEncodeTiled` / `VAEDecodeTiled`): a 145-frame clip with a one-piece
  decode spilled out of VRAM and stalled for minutes, chunked it takes 54 s; 193 frames take 72-86 s on the 4090.
- **Five shots re-run at 6 s, previs → motion → look key → look pass**, each step applied before the next because a
  single-step proposal pins the page revision (proposals made before another write to the slate fail on apply)
  ([30 s side by side: previs | final shot](../verification/motion-lab/stage_demo.mp4),
  [S06 bench: Previs, Keyframe and Cinema Shot agree](../verification/motion-lab/stage_bench_s06_matched.jpg)).
  S02, S05, S06 matched first time; S03 flipped to a front view on one seed (its text says the glass is "behind him")
  and matched on a retake; S01 was re-blocked as a pull-out with Kael walking toward camera, which is what "as Kael
  enters" asks for.
- **Earlier 4 s run through the stage**:
  camera path, framing and timing carried over in all four (S01 push-in walk-in, S02 locked-off 85 mm, S05 track,
  S06 push-in 85 mm). Facing did not at first: a bare grey head reads as a face from behind, and LTX turned the actor
  to camera in S01, S02 and S06. Hair over the back of the head and forward shoes fixed S02 and the end of S01; S06
  ("raises the recorder to his mouth") still turned, because the action text wants his face, and matched once the
  stage set *Facing: room* ([previs | before | after](../verification/motion-lab/stage_facing_cues.jpg)). Rule of thumb:
  the motion pass follows the previs for camera and blocking, and the text when the two disagree on who faces the lens.
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
the key.

## Product consequences

1. Shot bench gets a **3D previs** (three.js, already proven headless): blocking, camera path, lens, key/rim lights.
   Camera Motion and Optical Rig become authored data that renders to the grey init video.
2. The cinema stage becomes **two-pass** (draft from the grey init, identity edit on draft frames, pass 2 from the draft).
3. A **comp stage** with click-to-track, mattes and look layers after pass 2.
4. line-worlds as a plain LTX guide is copied, not followed; its value is the blocking data, rendered as a grey blockout
   instead. With an IC-LoRA the blockout can be a reference rather than the init latent (next section).

## Layout-To-Render IC-LoRA (2026-10-21)

**Question.** Does LTX-2.5's [Layout-To-Render IC-LoRA](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render)
remove the denoise-0.75 trade-off (keep the blocking vs lose the grey look)? Script:
[`iclora.py`](../../research/motion_lab/iclora.py). Same seed, 145 frames at 1280x704, S03 push-in and a crane, both
rendered headless by the product's own `scene.js` ([`stage_render.py`](../../research/motion_lab/stage_render.py)).

Graph (ComfyUI 0.42.1 core, no custom nodes): `LoraLoaderModelOnly` (LoRA 1.0) → `GetICLoRAParameters` →
`LTXVAddGuide(previs, frame 0, strength 1.0, iclora_parameters[, attention_mask])` on an empty latent, the FLUX 3 Klein
first frame as an out-of-clip reference (`LTXVAddLatentGuide`, latent_idx -1, as the official graph's frame_idx -1),
cfg 1, euler_ancestral on the 8 distilled sigmas, `LTXVCropGuides` before decode. The first frame is Klein editing
previs frame 0 with the cast and set references.

| Run | Result |
| --- | --- |
| IC-LoRA, no first frame (text only) | **copies the grey model** ([failure modes](../verification/motion-lab/iclora_failure_modes.jpg), bottom row): the look must come from a first frame |
| IC-LoRA 0.6, or guide strength 0.7 | copies the grey model too: both strengths must be 1.0 |
| IC-LoRA + Klein first frame, box-torso actor | set, rain-streaked glass, console ring and camera follow; the **actor is rendered literally** (box torso → brass box) |
| same, human-proportion mannequin | no box, but the mannequin still reads as a doll or a child |
| **same + attention mask freeing the actor** | **adult man, real jacket**, set and camera from the layout ([S03](../verification/motion-lab/iclora_s03.jpg), [crane](../verification/motion-lab/iclora_crane.jpg), videos [S03](../verification/motion-lab/iclora_s03.mp4) / [crane](../verification/motion-lab/iclora_crane.mp4)) |

Camera, from `fidelity.py`: the score saturates for every run (0.95-1.0), so the table compares **travel**, the shot's
cumulative tilt and zoom as a fraction of the previs':

| Shot | Grey-init V2V 0.75 | IC + first frame | IC + first frame + actor mask |
| --- | --- | --- | --- |
| S03 push-in: tilt / zoom | 0.75 / 0.66 | 1.11 / 0.65 | 1.09 / 0.63 |
| Crane: tilt / zoom | 1.01 / 0.69 | 1.13 / 0.99 | 1.13 / 0.94 |
| Colourfulness (previs 24-27) | 26-29 | 31-39 | 31-38 |

- **Camera**: equal on the push-in, clearly better on the crane (the grey-init pass undershoots big moves by about a third).
- **Set**: the IC pass keeps the blockout's glass dome and console ring and takes its art direction from the first frame;
  the grey-init pass invents its own room on the crane (a brown wall with a window).
- **Actor**: needs the attention mask. The 3D Stage gives it for free: the same plan rendered with the actor white on
  black is pixel-exact (dilated 24 px, blurred, inverted; white = follow the layout). A SAM matte of the previs works too.
  Inside the mask the model decides the action: the crane hand lands on the dial, the S03 hand does not.
- **Cost on the 4090**: grey-init 55 s; Klein first frame 55 s + IC pass 116-133 s, about what the current three-step
  lane (motion → look key → look pass) takes.
- LTX-2.3 Union-Control (canny) also runs on LTX-2.5 and humanises the box actor without a mask, but keeps square shoulders.

**Product consequence.** The 3D Stage actor is now a human-proportion mannequin (adult head, tapered torso, capsule limbs);
the grey-init pass is unchanged by it ([S03 base row](../verification/motion-lab/iclora_s03.jpg)). The recipe is wired as
an optional cinema lane, **Layout Key → Layout Render** (`flux3_klein_look_key.json` on previs frame 0, then
`ltx25_layout_render.json`; [workflow notes](../../workflows/README.md#layout-render-3d-stage-previs-as-an-ic-lora-layout)).
*Render previs* now renders the same plan a second time with the actor white on black into a new **Actor Matte** column
(appended after Previs); the graph does the 24 px grow, blur and invert, and *Run layout render* on the stage queues the
lane, whose key waits for review before the render runs. S03 end to end in the app on the 4090
([board](../verification/motion-lab/app_layout_lane_s03.jpg), [previs | render](../verification/motion-lab/app_layout_lane_s03.mp4)):
Klein 54 s, IC pass 167 s; an adult man in a charcoal jacket inside the glass dome and console ring, his hand on the
brass dial; camera score 0.97, tilt / zoom travel 1.10 / 0.72 (lab: 1.09 / 0.63). He ends in profile where the previs
shows his back (inside the mask the model decides the pose). One prompt change on the way: with the app's photographic
Soul Cast portrait as image 2, the lab's `GREY_TO_PHOTO` (and a generic "same face" edit) made Klein copy the portrait's
close-up; a composition-first instruction ("do not move the camera or enlarge the figure") kept the blockout's small
figure on two seeds.
