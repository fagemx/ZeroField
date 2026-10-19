# Story Workbench (SPEC_06)

> SPEC_07 extends this baseline with explicit production policy, graphless routing, allocation preflight and M8-reviewed media chains. Use the [current routing/allocation guide](SPEC07_STUDIO_ROUTING.md) and [separate verification receipt](spec07-verification.json); the historical SPEC_06 receipt is unchanged.

The production header now exposes **Start Creating**, **My Projects**, **Asset Vault**, **Toolbox**, and **Open API**. English is the default; Traditional Chinese is selectable without changing saved IDs, prompts or card inputs.

## Daily workflow

1. Open a ZeroField production and choose **Start Creating**. Paste or upload a UTF-8 `.txt` / `.md` script, choose its aspect ratio and style, then confirm and build.
2. Offline breakdown recognizes numbered `Scene 01:` / `INT.` / `EXT.` sections, explicit `@CAST-01`, `@SET-01`, `@PROP-01` tags and `Character: Name` / uppercase speaker cues. It is a deterministic structured parser, not an unconfigured AI service. Each scene receives an initial shot; add or split shots for more detailed coverage.
3. Changes go into the existing **Director Brief**, **Soul Cast** and **Cinema Studio** pages. Existing productions keep their reviewed media and rows. API-created productions start with the same five-page schema but no demo rows.
4. Script changes invalidate the confirmed baseline. Confirm/extract again before building or rebuilding scene shots. The banner also detects edits made directly in the document editor.
5. In Gallery, scene sections collapse independently. Asset Vault creates/edits/deletes wardrobe variants. Click a card's asset chip to cycle its variants. Both `@CAST-01:night` and `@CAST-01#night` resolve; an unpictured variant inherits the base thumbnail, not its appearance prompt.
6. Select shot checkboxes, choose an AI-App, and generate in place. Selected shots can also be merged. In single-shot review, choose historical takes, split the shot, start H3 Optimize using the selected source video, or override exposed `nodeId.fieldName` inputs before re-shooting.
7. **Export Episode Film** normalizes and concatenates selected videos in natural shot-index order, preserves/adds audio, and produces a faststart MP4. The finished film appears inline. No NLE/timeline editor was added.

Example structured script:

```text
Scene 01: Observatory Arrival
@CAST-01:night enters beside @SET-01, holding @PROP-01.

Scene 02: The Signal
@CAST-01 turns the recorder toward the open dome.
```

## API and persistence

- Story base: `/aivideo/open/v1`. Use **Open API** for live curl/Python examples and a read-only capabilities check.
- Success: `{code: 0, msg: "success", errorMessages: null, data}`. Errors use non-200 HTTP status, a `DRAMA_*` code, `message`, and `requestId`.
- Reuse the application's configured crew Bearer tokens in token mode. Browser sessions retain same-origin/CSRF checks. Viewer accounts cannot mutate productions. Development authentication remains loopback-only; the API does not introduce a separate master credential.
- POST idempotency keys are persisted for 24 hours and scoped by actor, credential and endpoint. Lists accept cursor pagination and limits of 1–100. Large integer counters and file sizes are strings.
- Scripts, asset rows, variants and shot cells remain in collaborative tabs. Migration `162_story_workbench.sql` stores API metadata, task snapshots, candidate references, imports and upload bytes. File metadata queries do not retrieve upload blobs.
- Imported cards require a signed-in writable crew member and workflow JSON, not a server filesystem path. They persist in PostgreSQL and are restored at server startup. Built-in card IDs cannot be replaced. Never paste credentials in imported curl snippets; only the workflow/node contract is retained.
- Card IDs/webappIds and RH aliases resolve through the configured catalog. Since SPEC_07, the Seedance alias can select a graphless provider only under explicit effective hybrid permission and configured adapter; it otherwise resolves to local H3 before submission. Cloud cards are explicit choices. Provider credentials and Comfy deployment settings remain server configuration.
- Webhooks require public HTTPS/443 destinations, pin the validated IP, reject redirects/private addresses, and sign exact request bytes using `X-RH-Signature`. Secrets are masked after creation. Failed deliveries retry after 60/300/1800/7200/43200 seconds, then become `DEAD`; pending deliveries resume on startup.

## Execution limits and safeguards

Install the card's model weights and custom nodes before generation. The existing Comfy client supports local ComfyUI and official Comfy SDK execution. Script refinement requires explicit `OPENBENCH_MODEL` and `OPENBENCH_API_BASE` configuration and uses an OpenAI-compatible endpoint; offline breakdown does not call a model.

Media jobs run outside document transactions. A delayed output is retained as a candidate but does not replace a row edited since submission. Cancellation prevents late writeback and stops waiting; it cannot guarantee that a remote Comfy/provider job has stopped consuming resources. Interrupted jobs are marked failed on the next query after a server restart and require an explicit retry, never an automatic paid resubmission.

Native Story generation selects a successful take only when its row is unchanged. The existing M8 proposal/review path is retained separately. H3 Optimize dispatch is implemented, but actual 4K quality depends on the configured graph and weights.

Restart `python run_studio.py` to load the new backend and migration. The compiled frontend is already rebuilt under `static/projects/`.

## Verification

See [the SPEC_06 receipt](story-workbench-verification.json). Tests cover real HTTP/PostgreSQL synchronization, baseline locks, variants, candidate selection, stale-output protection, split/merge, authenticated durable card imports, webhook signatures/retry bounds, multi-episode isolation and real FFmpeg concatenation. GPU/provider calls and public webhook networking are isolated in tests, not presented as live-render validation.
