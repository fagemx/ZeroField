# Phase 2: 4090 local render bring-up (2026-10-20)

First real renders through the product: Pipeline → local ComfyUI → proposal → director review →
table/canvas → Director Cut. The first pass used interim open-weights models already on this
workstation; the second pass runs the **official LTX-2.5 + FLUX 3 Klein** graphs.

## Official models (LTX-2.5 + FLUX 3 Klein)

Downloaded after the licenses were accepted: exactly the 7 files the shipped graphs load (49.7 GB,
no LoRAs). ComfyUI 0.42.1 at `E:\AITool\ZeroField_ComfyUI`, plus ComfyUI-VideoHelperSuite for the
OpenJutsu source loader. The studio runs the built-in worker defaults (`python run_studio.py`, no
`--worker-config`).

| Stage | Model | 4090 time | Result |
| --- | --- | --- | --- |
| Soul Cast CAST-01 / SET-01 | FLUX 3 Klein base int8, 1280×720, 50 steps | ~13 s | Approved |
| S01–S03 keyframes | FLUX 3 Klein | ~16 s | Approved (one Pipeline batch run) |
| S01–S03 cinema shots | LTX-2.5 22B distilled int8, 1280×704, 97 frames, 8 steps | ~35 s (first load +10 s) | 4.0 s each **with generated audio** |
| Director Cut | FFmpeg assemble | ~20 s | 12.1 s, 1280×720, AAC — [video](verification/phase2/director-cut-ltx25.mp4) |

8-frame grader (local qwen3.8 vision), same rubric as the interim pass:

| Shot | Interim | LTX-2.5 | Notes |
| --- | --- | --- | --- |
| S01 | 48 | **72 pass** | The dolly push-in now lands; entry beat missing — [sheet](verification/phase2/ltx25-s01-grader-72.jpg) |
| S02 | 88 | **89 pass** | Identity, set, locked-off camera hold — [sheet](verification/phase2/ltx25-s02-grader-89.jpg) |
| S03 | 64 | 35 → **58** | Takes 1–5 drifted (a second figure appeared; Kael turned to the window). The grader's notes were applied: prompt rewritten, keyframe rebuilt in profile at the dial, take 6 lands push-in, single subject, rain and beacon; the hand leaves the dial late. Kept as **Retake** — [take 1](verification/phase2/ltx25-s03-take1-grader-35.jpg), [take 6](verification/phase2/ltx25-s03-take6-grader-58.jpg) |

### Six-shot cut (S04–S06 added)

S04–S06 were added through the table UI to finish the brief's pacing ("establish the space, reveal
the signal, hold on the decision"). Director Cut: **24.3 s, six shots, AAC** —
[video](verification/phase2/director-cut-ltx25-6shot.mp4), [table](verification/phase2/cinema-table-ltx25.jpg),
[canvas](verification/phase2/story-canvas-ltx25.jpg).

| Shot | Beat | Grader | Status |
| --- | --- | --- | --- |
| S04 | Insert: reels turn, a hand at the record key | 48 — [sheet](verification/phase2/ltx25-s04-grader-48.jpg) | Retake (hand presses and withdraws) |
| S05 | Kael at the glass, the beacon pulses | 64 — [sheet](verification/phase2/ltx25-s05-grader-64.jpg) | Retake (exposure jump mid-shot) |
| S06 | Recorder raised, deciding whether to speak | **84 pass** — [sheet](verification/phase2/ltx25-s06-grader-84.jpg) | Approved |

S03 take 7 scored 58 again (the hand leaves the dial late); take 6 stays. Three passes (S01, S02, S06),
three retakes with notes in the table.

Prompt fixes found while adding shots (compiler, with tests):

- **Seed and reference framing leaked into shot prompts.** `seed 48291` was compiled as words, and
  reference-render framing typed into the Soul Cast lock ("waist-up portrait, grey backdrop", "no people")
  reached every shot. The seed is stripped from appearance text; Soul Cast renders now get framing from the
  asset kind (character portrait, environment "no people", prop), so the lock column holds appearance only.
- **Camera brands were lettered onto props.** "Shot on RED V-Raptor / 85mm Prime" made FLUX 3 Klein print
  "RED V-RAPTOR 8mm" on the recorder. Stills keep the lens look only.
- **Insert shots drew a second Kael.** An insert that references `@CAST-01` gets the full character
  description; the S04 insert references the set only and describes the sleeve
  ([keyframe](verification/phase2/klein-s04-insert-keyframe.jpg)). A director choice, not a code change.
- Director Cut links appended to Director Brief read "產出媒體"; now "Output media".
- Story canvas: `min-height: 560px` overflowed the card at 1440×900, so fitting hid the last row
  under the hint; the canvas now fits its card and fitting leaves room for the button and hint.

Fixed while running the official graphs:

- **Official LTX graphs could not save.** `SaveVideo` carried a nested `{"format": {"format": "mp4",
  "codec": {...}}}` object; ComfyUI 0.42.1 takes the flat API form (`"format": "mp4", "codec": "h264"`).
  Sampling finished and the save failed. Graph test now pins the flat form.
- **Retry replayed the rejected take.** Retry clears a task's own output, so the take counter (earlier
  outputs of the same cell) never advanced and every retry reused the same seed. Rejected takes are now
  also counted from their proposals. PostgreSQL test: reject → retry → take 1.

## Interim pass (first bring-up)

| Stage | Model | Result |
| --- | --- | --- |
| Soul Cast CAST-01 / SET-01 references | FLUX.1 dev | Approved (character portrait, observatory interior) |
| S01–S03 keyframes | FLUX.1 dev, 1280×720 | Approved after re-shoots (S02 4 takes, S03 3 takes) |
| S01–S03 cinema shots | LTX-Video 13B 0.9.7, 1024×576, 3 s | Real takes in the table; see grader scores |
| Director Cut | FFmpeg assemble | 9.1 s, 1280×720, three real shots, appended to Director Brief |
| OpenJutsu VFX-01 v2v | LTXV, core nodes only | Graph runs end to end; output ≈ source because the source is a procedural fixture. Needs a real self-shot clip. |

Timing on the 4090: keyframe ~22 s, shot ~90 s (2.3–2.6 s/step), qwen grading ~25–45 s per shot.

## 8-frame grader (local qwen3.8 27B vision)

The product's own `build_video_frame_sheet` contact sheet, graded by local qwen through the
OpenAI-compatible endpoint the grader uses.

| Shot / take | Score | Verdict |
| --- | --- | --- |
| S03 take 1 | 46 | Fail: hands smear (frame 3), reach collapses, set missing — [sheet](verification/phase2/s03-take1-grader-46.png) |
| S02 take 1 | 88 | Pass: identity, console, locked-off camera hold — [sheet](verification/phase2/s02-take1-grader-88.png) |
| S01 take 3 / S03 take 3 | 48 / 64 | Identity and set now continuous; push-in and story beats (rain, outside light) missing. Model ceiling of LTXV 0.9.7, not seed luck. Approved as interim takes, status **Retake**, notes in the table. |

## Product fixes made during the bring-up

- **Re-shoot replayed the same take.** The identity seed (`seed 48291`) was reused on every
  re-shoot, so local Comfy returned an identical result. Each earlier output for the same cell now
  advances the seed (take 1 keeps the identity seed). `flow_runner._inputs` → `take`, `context_compiler._take_seed`.
- **Keyframes drew tripods and camera bodies.** Still-image prompts carried "Camera Movement: Static
  Tripod" and "Optical Rig: RED V-Raptor"; FLUX rendered them as props. Image tasks now get
  "Cinematic film still, shot on …; no camera equipment in frame" and no camera move.
- **S03 never got its asset tags.** The seed only tagged rows that received fixture media, so the empty
  S03 compiled without @CAST-01/@SET-01 and rendered an unrelated room. Tags now live in the template.
- Story canvas minimap removed (it covered the output column). Flaky ACP pid-file race fixed in its test.

## Continuity grades in the product

The hand grading above now runs from shot review (`project_assistant/take_grader.py`). Each take in
**Candidate Takes** has **Grade**; **Auto-grade new takes** (off by default, per production) grades every
video a worker delivers to a Cinema Studio / OpenJutsu Lab row while its proposal waits for review.
The Continuity Supervisor's configured vision model (`qa_critic`, OpenAI-compatible endpoint) gets the
same rubric and brief as the hand runs, plus one ask: a rewritten shot prompt when the take fails.

- **GPU hand-off.** A grade waits until ComfyUI's queue is empty (it never interrupts a render; in-process
  renders and grades share one lock, so later renders queue behind a grade), then `POST /free`, grades, and
  unloads the model (`keep_alive: 0` on a local Ollama-style endpoint). The ComfyUI URL is the Local 4090
  environment's `comfy_url`.
- **Stored with the take.** Score, pass/retake, issues, notes, the contact sheet asset, model, seconds and the
  hand-off record live in `story_record` (`take_grade`), keyed by row and take asset; `GET/POST
  /aivideo/open/v1/shots/{id}/grades`, `GET/PUT /aivideo/open/v1/projects/{id}/grading`.
- **Retake proposals wait.** A failing grade with a rewritten prompt stages a normal table proposal (prompt +
  `Retake` status, `@asset` tags kept) in Studio Assistant; nothing changes until the director applies it.

Real run on the 4090 (2026-10-21): an LTX-2.5 render was queued in ComfyUI, then **Grade** was pressed on the
selected S03 take (6 s 3D Stage take). The grade showed *Waiting for the GPU* until the render finished
([screenshot](verification/take-grading/s03-waiting-for-gpu.jpg)); `/free` dropped VRAM from 22.2 GB to
2.7 GB, qwen3.8 27B loaded (21.3 GB in use), scored **58 / retake** (blocking: Kael faces the camera for frames
1–4 and turns to the console at frame 5; no rain streaks; no anamorphic signature), and unloaded back to
2.2 GB. Grade, notes and the pending retake proposal #259 in English and Traditional Chinese:
[graded](verification/take-grading/s03-graded-58.jpg), [zh-TW](verification/take-grading/s03-graded-58-zh-TW.jpg),
[sheet](verification/take-grading/s03-grader-58-sheet.jpg),
[proposal](verification/take-grading/s03-retake-proposal-pending.jpg). That run recorded 145 s including the
wait for the render; the stored seconds now count model load and grading only. Grader notes are model text
in English in both interface languages.

## Open decision for the owner

**Single-step proposals pin the whole source page.** Approving any change on that page bumps its
revision, so other pending single-step proposals on it fail (reproduced again with three keyframes:
only the first landed). This is the SPEC_08 contract, pinned by
`test_source_changed_while_executing_or_waiting_for_approval_cannot_write`, which edits a *different*
row and expects failure. It is not silent in the UI: `App.jsx` shows "Could not apply" with the error;
only direct API callers see HTTP 200 with `status: failed`. Production avoids it by running Pipeline
batches (workflow runs rebase per cell). Options: scope the pin to the sample row, or keep it.

## Next

1. Shoot a 3–4 s phone clip of a person for OpenJutsu VFX-01, then run it through LTX-2.5 V2V.
2. Retakes: S03/S04 hand holds (LTX-2.5 tends to withdraw the hand late in a 4 s take), S05 exposure jump.
3. ~~Wire the grader agent into the review flow~~ and 4. ~~GPU sharing~~: done, see
   [Continuity grades in the product](#continuity-grades-in-the-product). The Agent Console's
   `studio_inspect_frames` tool still serves episode-bound Story shots only.
5. Story canvas lays six shots out in one tall column, so fit-to-view shrinks the cards; wrap long shot
   lists if the canvas is shown with more than six shots.
