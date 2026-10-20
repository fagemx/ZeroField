# Phase 2: 4090 local render bring-up (2026-10-20)

First real renders through the product: Pipeline → local ComfyUI → proposal → director review →
table/canvas → Director Cut. Interim open-weights models already on this workstation stand in for
the gated LTX-2.5 / FLUX 3 Klein files (see [`workflows/interim/README.md`](../workflows/interim/README.md)).

## What ran

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

## Open issue for the owner

**Approving one single-step re-shoot silently fails the others on the same page.** Single-step
proposals pin the source page revision; approving any change on that page bumps it, so the next
approval returns HTTP 200 with proposal status `failed` and the cell is not updated. Seen on S01
take 2. Workflow-run proposals are unaffected (per-cell rebase). Options: scope the single-step check
to the source row, or keep it and surface the failure in the review room. Not changed here because
it is a SPEC_08 governance decision.

## Next

1. Accept the Hugging Face licenses and download LTX-2.5 + FLUX 3 Klein (commands in the interim README).
2. Shoot a 3–4 s phone clip of a person for OpenJutsu VFX-01 (the procedural source cannot show V2V).
3. Wire the grader agent into the review flow (today `studio_inspect_frames` serves Story shots, not sheet rows).
4. GPU sharing: set `OLLAMA_KEEP_ALIVE` short (e.g. 30s) so qwen releases VRAM for ComfyUI between turns.
