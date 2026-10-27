# Story Workbench (SPEC_06)

> **Current SPEC16 workspace:** The studio now has three spaces (**Story & World**, **Shot Stage**, **Timeline**) behind one breadcrumb menu, Ctrl K, the crew dock and one Film overlay; the writing workspace is the script view of Story & World (its outline in the left rail, the manuscript in the middle, its panels in the right column). [Writing workspace usage](WRITING_WORKSPACE.md) covers persistent private sources/drafts, plot structure, immutable creative versions, selected-shot impact, narrative notes, literal search/replace and private Office/print handoff. [Original SPEC16 verification](spec16-verification.json) is preserved separately from the [three-space integration receipt](spec16-integration-verification.json) and [V12 dispositions](SPEC16A_REVIEW.md). The SPEC06 five-entry workflow and receipts below are preserved historical contracts, not the current top-level navigation.

> SPEC_13 extends Start Creating with offline idea/novel adaptation, multi-beat storyboard coverage, generated 3D Stage plans and episode-scoped missing asset generation. See [current upstream workflow and API additions](SPEC13_UPSTREAM_PIPELINE.md). The one-initial-shot description below records the original SPEC_06 baseline.

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

## Studio revision (SPEC_18)

What changed in the three spaces after studying RunningHub STORY's panels. No step bar, no hard gates, no new data model; each screen still has one primary button.

- **Pictures generate in the background.** In Cast & sets, *Generate* returns at once. The card shows *Generating* with a Cancel, several cards can run together, and nothing else on the page waits. A failure keeps its reason and a Retry; a cancel reads *Canceled*, not failed. Tasks in flight are remembered for the tab (`sessionStorage` key `zf.gen:<episode>`), so a reload picks them up and refreshes only the cards that finished. One task per card: a card in flight cannot be sent again.
- **Scene filter.** The wall can show only what one scene uses (the scene in focus, one you picked, or *Unscened* for assets no shot places in a scene). It stacks with the type and Needs-an-image filters and is remembered with the view.
- **Space menu shortcuts.** Under each space the menu lists what it needs (script changed, *n* missing images, *n* to review, *n* shots missing references) as menu items of their own. One opens the wall or the shot list already filtered. The menu still appears only when opened.
- **Shot detail.** A previs → first frame → video ladder (a paused first frame, never autoplay; a shot without previs says so and offers *Plan previs*), an *On set* block listing the `@codes` of the prompt with picture, look menu, remove and add (a code missing its picture offers *Add reference*; a code the cast sheet does not list is flagged, never dropped), and the prompt itself drawn with `@code` tags. A binding edit rewrites only the code concerned, through the sheet's own cell commit (so undo, locks and conflicts behave). It never uses `PUT /shots/{id}/assets`, which moves every code to the end of the sentence. A code that also sits in another cell (director notes, say) is shown as *Also in: …*.
- **Build dialog.** The primary button on Story & World opens a dialog: how to split, aspect ratio, style (with sample images), a target length and the shots each way of splitting would give, and *Import shot table*. The dialog only opens once the server holds what you wrote (the writing workspace saves first); confirming sends `PUT settings` → `POST asset-extractions` → `POST storyboards` and no `PUT script`, because the workspace owns the script; cancelling sends nothing. The estimate only counts: existing shots are kept, only missing beats are added, and the seconds are planned seconds, not the film's length.
- **Cast & sets editor.** Nothing opens by itself; picking a card opens it in a large pane on the right (about three fifths of the width, the wall shrinking to a compact picker; × gives the wall the whole view back). The pane reads top to bottom, the way RunningHub's character editor does, and it works on the look you picked (or on the card itself when none is):
  - the picture, with every picture of that look beside it. Click one to preview it, then *Make it the main picture* to switch; the main one is what shots use. A character is not one picture: the card and each look keep their own set.
  - the looks as a strip of pictures with a **+** tile at the end. A new look starts from the card's own description; rename and delete appear once a look is picked, and deleting lists the shots that use it.
  - the description, the biggest box in the pane, edited where it stands. Unsaved text is marked and can be reverted; *+ Attributes* composes tags into the box as a draft and never overwrites text silently. Each look keeps its own draft.
  - the generation choices on one row: workflow, ratio and resolution as the card allows, the style, the time earlier runs of that workflow took with how many runs it rests on (or *Time unknown*; a Router card shows a quote labelled as no price lock), and the button at the right end. When the description changed the button reads *Save & generate* and saves first, so a picture is always made from the text you see.
  - voice, status, notes, and the shots and scenes that use the card fold into *More*, whose summary line shows the voice, status and shot count.
- **Start from a story.** The hub's New Production dialog opens on *From a story* (the template form is the other tab): an idea, a novel chapter or a screenplay in one big box (or a .txt or .md file), a ratio and a style, and *Create and start* makes a studio production and opens Story & World with the text already in the writing workspace: an idea or a novel opens as the private source of that name, a screenplay uses the working script only if it is empty. Existing source/manuscript content is never overwritten: occupied resources receive the new text in a private draft instead. The text stays in this tab's sessionStorage until an actor-bound server acknowledgement and resource reload succeed; mutation checkpoints retain the same retry identity after a lost response. Failures offer retry and original-text download. A private source/draft is visible only to its author; this save reaches the server before any build and is not production confirmation. Receipt retries are limited to 24 hours and the same authentication credential, not a guarantee across sign-out/sign-in.
- **Crew suggestions** follow where you are and what you hold (scene, card or shot).

API additions: `GET /assets/{id}/generation-options`, `POST /episodes/{id}/storyboard-estimates`; `PATCH /assets/{id}` also takes `voice`, `status`, `notes`; `GET /catalog/apps?usageScope=` now filters; styles carry `sampleImage` (static SVG swatches under `/projects/assets/style-samples/`, abstract and without people). See [SPEC_18](specs/SPEC_18_RUNNINGHUB_INFORMED_STUDIO_REVISION.md) and the [verification receipt](spec18-verification.json).

## Execution limits and safeguards

Install the card's model weights and custom nodes before generation. The existing Comfy client supports local ComfyUI and official Comfy SDK execution. Script refinement (`POST /episodes/{id}/script-refinements`) still answers 409 `DRAMA_STAGE_PRECONDITION` unless both `OPENBENCH_MODEL` and `OPENBENCH_API_BASE` are set in the server's environment, so the local Ollama default alone does not enable this one call (`project_docs/story_openapi.py`). Once enabled it runs as a governed model call on the Showrunner's settings (`provider_from_env()` plus `ProviderAdmission`): usage tier, host allow list, price ceiling and the ledger apply, and a local endpoint is unbilled. The crew's adaptation and breakdown candidates in the script view (SPEC_20 R23) use the provider defaults and do not need those two variables, and they only propose. Building a storyboard (offline breakdown) does not call a model.

Media jobs run outside document transactions. A delayed output is retained as a candidate but does not replace a row edited since submission. Cancellation prevents late writeback and stops waiting; it cannot guarantee that a remote Comfy/provider job has stopped consuming resources. Interrupted jobs are marked failed on the next query after a server restart and require an explicit retry, never an automatic paid resubmission.

Native Story generation selects a successful take only when its row is unchanged. The existing M8 proposal/review path is retained separately. H3 Optimize dispatch is implemented, but actual 4K quality depends on the configured graph and weights.

Restart `python run_studio.py` to load the new backend and migration. The compiled frontend is already rebuilt under `static/projects/`.

## Verification

See [the SPEC_06 receipt](story-workbench-verification.json). Tests cover real HTTP/PostgreSQL synchronization, baseline locks, variants, candidate selection, stale-output protection, split/merge, authenticated durable card imports, webhook signatures/retry bounds, multi-episode isolation and real FFmpeg concatenation. GPU/provider calls and public webhook networking are isolated in tests, not presented as live-render validation.
