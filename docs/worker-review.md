# Worker adapter independent review — 2026-10-16

Reviewed `project_assistant/limb_worker.py`, `tests/test_limb_worker.py`, and `examples/worker.example.json` against the worker portion of `ROADMAP_COMPLETION_PLAN.md` Task 2. Read the project handoff, roadmap, acceptance, deployment, and current head lease/input implementation. This review did not modify implementation or tests, call paid providers, or use production services.

## Scoped re-review verdict

**Final verdict: no outstanding findings from this scoped worker review.** The updated worker suite passed **10/10** freshly, with zero skipped. The original sheet-media merge failure is fixed: rows establish stable ordering and predecessor outputs augment their corresponding row. The latest video candidate takes precedence. Uploads now reject a known lost lease, ComfyUI/bridge polling checks lease state, and FFmpeg uses a killable subprocess. Provider HTTP 408/429/5xx and transport timeouts are classified as retryable. These changes address the original direct reproductions below.

The intermediate **P2** renewal/retry issue is also closed: `process_one` now preserves transient classification from heartbeat errors. Re-ran the exact claimed 3-second lease / renewal HTTP 503 / cooperative polling reproduction; the final failure payload now contains `retryable=True`.

The new explicit FFmpeg output limit uses the probed video-stream duration (container duration fallback) for video clips and configured duration for stills. Independently rendered two 0.5-second MP4s into one final MP4: actual mux duration was **1.021333 seconds**, with an audio stream. This covers the reported AAC padding / shortest growth case.

Independently ran the real pipeline test using the dedicated PostgreSQL instance supplied by the coordinating agent:

```powershell
$env:OPENBENCH_TEST_DB_URI = 'postgresql://postgres@127.0.0.1:55433/postgres'
python -m unittest discover -s tests -p test_production_pipeline.py -v
```

Result: **1/1 passed**, zero skipped, all six tasks delivered. This exercised real Head HTTP and PostgreSQL, isolated LLM/ComfyUI/bridge HTTP fixtures, authorized media downloads/uploads, dynamic row expansion, and actual FFmpeg assembly with the final movie written to the output document. External paid models remain unverified.

Cancellation is cooperative: a currently blocking HTTP call and FFprobe may run until their configured timeout; remote provider jobs are not actively canceled. This should remain an explicit limitation rather than an immediate cancellation guarantee.

## Findings

The following describes the original review and reproduction evidence; use the scoped verdict above for current status.

### [P1] Merge sheet media with predecessor media by stable row ID

Location: `project_assistant/limb_worker.py:300–308`.

Any predecessor creates a `groups` entry, even when its output contains no media. This disables both fallbacks to `input.rows` and the rest of the input. Consequently an assembly node after a text-only review gate cannot assemble existing sheet videos. An audio-generation predecessor plus sheet videos also produces no visual clips; a video-generation predecessor plus existing sheet narration silently produces a movie without that narration.

Reproduced directly with `ffmpeg()` and an instrumented Head:

```python
url = '/projects/api/test/assets/pa_' + 'a' * 32
task = {'input': {
    'predecessor_tasks': [{'node_id': 'review', 'row_id': None,
                           'output': {'text': 'approved'}}],
    'rows': [{'row_id': 'r1', 'cells': [url]}],
}}
worker.ffmpeg(task, {}, head)
```

Observed `WorkerError: Assembly requires at least one video or image asset`; `head.asset` was never called. With row `r1` containing a video and an audio asset and only the video in predecessor output, captured `assemble_files` input was `[('video/mp4', False)]` and only the video URL was read. With only the audio predecessor, captured clips were empty. The head already supplies stable row IDs and sorted row data, so merge corresponding row assets with predecessor outputs and define precedence explicitly.

### [P2] Stop local work when renewal establishes that the lease was lost

Location: `project_assistant/limb_worker.py:341–357` and adapter polling/subprocess paths.

A failed renewal appends an error and exits the heartbeat, but running adapters cannot observe this state. The adapter continues generation, polling, FFmpeg rendering, downloading, and uploading until it returns; only afterward does `process_one` check `errors`. A canceled or reassigned task can keep a worker occupied for the full provider timeout and overlap the replacement attempt. The server rejects stale completion/upload, which protects persisted results but does not stop the obsolete work.

Reproduced with a 3-second claimed lease and an adapter that waits for a failed renewal before calling upload. `renew` raised `WorkerError('HTTP 409')`; the exact event order was `claim`, `renew`, `upload after known lease loss`, `fail`. Pass a lease-loss/cancellation signal into adapters, check it before provider polls/downloads/uploads, and terminate a running local process when the signal is set. An unavailable renewal endpoint and an authoritative 409 should be distinguished.

### [P2] Classify transient failures before making them permanently fail the task

Location: `project_assistant/limb_worker.py:360–363`.

Every adapter failure is reported with `retryable=False`, including provider HTTP 503/429 and connection timeouts. The head's `fail()` only requeues a task below its `max_attempts` when `retryable` is true, so a momentary provider outage permanently fails an otherwise retryable flow and blocks downstream work until manual intervention.

Reproduced with an adapter raising `WorkerError('HTTP 503 from configured endpoint')`. The captured fail payload was `{'task_id': 't', 'lease_token': 'lease', 'error': 'HTTP 503 from configured endpoint', 'retryable': False}`. Preserve structured HTTP status/error categories and mark transient transport/provider errors retryable; keep configuration, invalid output, and lost lease failures terminal as appropriate.

## Verification and boundaries

- Fresh baseline: `python -m unittest tests.test_limb_worker -v` passed all 7 tests, including the real FFmpeg test; zero skipped.
- Additional real FFmpeg check used a 160×90, 12 fps, one-second MP4 with 440 Hz embedded audio. With no paired narration, output retained one second of video and an audio stream; mux duration was 1.020996 seconds. Paired 0.3-second and 2-second narration also retained one second of video and an audio stream. No duration regression was reproduced in these cases.
- A paired narration track explicitly replaces the input video's embedded audio (`-map 1:a:0`); mixing original audio and voice is not implemented. This is a behavior to document or choose deliberately, rather than a separate finding without a defined mixing requirement.
- The redirect handler blocks redirects rather than forwarding bearer credentials. Head asset reads require an exact same-project asset path. Bridge output media is restricted to the configured origin and provider output is fetched using only the provider credential. No credential-forwarding bypass was found in these reviewed paths.
- The LLM adapter sends JSON text; it does not resolve image references into vision message parts. ComfyUI input-image binding and HTTP bridge byte forwarding exist, but current baseline tests do not exercise those media-input paths, lost renewal, retries, or source/predecessor merging.
- No actual ComfyUI/model service or remote bridge deployment was exercised. HTTP provider behavior was tested through the repository's isolated fixture, and synthetic review probes used instrumented Heads without changing source files.
