# Crew evaluation set (SPEC_20 R42)

Hard cases for the three planning jobs of the crew, with reference answers and a scorer. Rerun it whenever the crew's
model, prompts or output formats change. Everything here is original (Kael, Mira, Odile, Tomas, Ines and their sets), SFW,
and about faces turned to the lens, high tension and visible emotion, never easy back or profile views.

It lives in `research/` next to `motion_lab/` (the 4090 hard-case lab): it is evaluation material, not application code,
and is not packaged. The runner is `scripts/crew_eval.py`; its tests are `tests/test_crew_eval.py`. No network and no
model calls happen in any of it. The real model runs happen later, on the GPU, through `--job` or `--canned`.

```
research/crew_eval/
  cases/beats.json  cases/blocking.json  cases/continuity.json     8 cases each
  runs/<label>/<case id>.json        outputs of one run (written by --save, replayed by --canned)
  reports/<label>.json               scored reports (written by --report)
```

## Run it

```powershell
python -X utf8 scripts/crew_eval.py --check-cases          # the case files are well formed
python -X utf8 scripts/crew_eval.py --reference            # the reference answers must score 100% (exit 1 otherwise)
python -X utf8 scripts/crew_eval.py --job my_adapter:run_job --label "qwen3.8:27b prompts v2" `
    --save research/crew_eval/runs/q27-v2 --report research/crew_eval/reports/q27-v2.json
python -X utf8 scripts/crew_eval.py --canned research/crew_eval/runs/q27-v2 --report research/crew_eval/reports/q27-v2b.json
```

`--type beats`, `--case blocking-03` (an id prefix) select part of the set; `--fail-under 80` turns the total into an exit code.

## When the model or the prompts change

1. Run the self-check (`--reference`) so you know the harness itself is sound.
2. Write or reuse an adapter: a function `run_job(case_id, job_type, case_input)` that runs the real crew job on
   `case_input` (the whole job, including its one retry) and returns the job's JSON output, as a dict or as text. A job that
   falls back to its rule path should return the fallback's output so the set measures what the user would get. The runner
   hands the job a copy of the input only, never the expectations or the reference.
3. Run with `--job ... --save runs/<label> --report reports/<label>.json --label "<model, prompt version>"`. GPU runs need
   the user's go-ahead for a free GPU; use a database copy if the adapter writes anything.
4. Compare `totals.percent` and each type's `hard_pass` with the previous report, then read the failed hard checks
   (`types.<type>.results[].hard[]`) and the soft criteria that lost marks. Keep the `runs/` directory: `--canned` rescoring
   after a scorer or case fix needs no model.

## Scoring

Every output goes through the hard checks first. **One failed hard check scores the case 0**: that output would fail the
job's validation and fall back to rules (SPEC_20 decision 12). A case that passes scores its soft criteria, a weighted
fraction between 0 and 1. A type's `percent` is the mean case score; `hard_pass` counts the cases that pass every hard check.
Soft marks only mean something once the hard checks pass (a one-beat sheet that copies the shot text still earns some).

| Job | Hard checks (all must pass) | Soft criteria (graded, per case) |
|---|---|---|
| beats | `schema`; `starts_at_zero`; `contiguous`; `ends_at_duration`; `beat_length` (at least 0.5 s); `beat_count` (per case); `tags_kept` (every `@` tag of the shot text, variants like `@CAST-02:coat` and take references like `@S23.end` whole); `no_unknown_tags`; `no_camera_brands`; `lens_in_lenses` (any `NN mm` is one of `LENSES`) | regex checks on the sheet: face toward the lens, no back or profile views, the emotion arc in order, event timing, camera move read from the camera text, quoted dialogue word for word, one-person or two-people constraint, no text, no leaked seed or field labels |
| blocking | `schema`; `shot_id` and `base_revision` echoed; `op_schema`; `camera_lens` in `LENSES`; `camera_move` in `MOVES`; `camera_keys` (a move has two different keys); `retime_valid`; `camera_single`; `cast_known`; `cast_placed` (each cast member once); `targets_known` (only this stage's targets, `mark`, cast codes, `camera`/`room` for facing); `required_ops` | per cast member: facing, `relativeTo`, offset ranges; the distance between two members; camera size, angle, lens, move; a `retime` of a named beat into a range |
| continuity | `schema`; `critical_found` (every error marked critical is reported on the right shots and subject); `no_invented` (every finding is a planted error or tolerated; flagging a change the shot text justifies counts as invented) | per planted error: found (0.6), right severity (0.2), the detail names the evidence (0.2); the overall `score` falls in the case's band |

The vocabulary is the stage's own: `LENSES`, `MOVES`, `DURATIONS`, `SETS` and `FACINGS` are read from
`ui/src/previs/plan.js` when the script loads, and `tests/test_crew_eval.py` cross-checks them against
`project_docs/story_previs.py`.

## Job shapes

**beats** (SPEC_20 4.4). Input: `shot` {id, seconds (4/6/8/10), text with `@` tags, optional optical_rig and camera_motion},
`cast`/`props` [{code, name, look}], `set`, `previous_shot`/`next_shot` (or null). Output:
`{"setup", "beats": [{"from", "to", "camera", "action"}], "sound", "constraints": []}`.

**blocking** (SPEC_20 4.6). Input: `shot`, `cast`, `set` {code, name, stage (`observatory`/`parallax`/`empty`), targets},
`base_revision`, and `beats` when the instruction retimes one. Output:
`{"shotId", "baseRevision", "ops": [place | camera | retime]}` with `place {cast, relativeTo, offset [x, z], facing}`,
`camera {size, angle, lens, move, from?, to?}`, `retime {beat, at}`. Stage coordinates are station-local metres: `+z` toward the
glass and the console, `-z` toward the camera side, `x` the actor's right. Facing the lens is `"camera"` (or `"room"`, the stage's
camera side).

**continuity** (the seam check of SPEC_19 R17). Input: `bible` [{code, name, look}] and `shots` [{id, take, seconds, transition,
text, cast, set, first_frame, last_frame}] where the frames are the captions a vision pass writes. Output:
`{"score": 0..100, "findings": [{"kind", "shots", "subject", "severity", "detail"}]}` with kind one of position, wardrobe, prop,
lighting, gaze, screen_direction, hair_makeup, set_dressing, body_state, weather and severity `minor` or `major`. A finding
matches a planted error on kind, subject (a set code and `"scene"` stand for each other) and at least the error's shots.

## Adding or changing a case

A case is `{id, title, difficulty, input, expect, reference}`. `difficulty` must say `face: "front"`, `tension: "high"`, the
emotion and the traps. The reference must score 100%, so run `--check-cases` and `--reference` (and the tests) after every edit.
In JSON write a regex word boundary as `\\b`: a single `\b` is a backspace and `--check-cases` rejects it.

## Assumptions to confirm when the real jobs land

- The input shapes above are this set's; the later crew-job adapter maps its own job inputs onto them.
- 4.6 is a P1 draft: `size` (wide, full, medium, close, extreme_close) and `angle` (low, eye, high, overhead) are this set's
  vocabulary, `retime.beat` counts from 1 (`RETIME_BEAT_BASE`) and `retime.at` is where that beat now starts, as a fraction of the
  shot. Change the constants at the top of `scripts/crew_eval.py` if the solver decides otherwise.
- "Camera within LENSES/MOVES" is checked on the blocking `camera` op and, for beats, on every lens named in the text; a beat's
  `camera` is free text, so its move is only scored softly.
- Soft criteria are lexical. Spot-check a real run by eye, and add synonyms to a case's patterns when a good answer loses marks
  unfairly.
- Continuity is exercised on frame captions, not on pixels. A vision run needs the real frames and its own cases.
