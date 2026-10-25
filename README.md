# ZeroField Studio

An open-source production workspace for planning films with a crew of AI agents. Organize a director brief, cast references, shot slates, and editable pipelines in one place.

Built for the ComfyUI [Open Source Higgsfield Challenge](https://comfy.org/open-source-higgsfield). The target is an open-weights filmmaking and V2V studio; this checkout delivers a **bilingual production workspace with inline video review and configurable Comfy workflows**.

## Available now

- English / Traditional Chinese studio navigation, crew settings, annotations, asset review, and agent controls. English is the first-run default.
- The [Story Workbench](docs/STORY_WORKBENCH.md): five navigation entries, script confirmation/breakdown, scene-grouped galleries, wardrobe variants, candidate selection, card/node overrides, split/merge, batch generation and episode film export over `/aivideo/open/v1`.
- Three creative spaces on productions that have a cinema slate, behind one breadcrumb menu (Ctrl 1 / 2 / 3) with a scene · shot focus that travels between them and floating panels you can hide: **Story & World** (the script, which shot each beat became, and which shots an edit would leave out of step), **Shot Stage** (crew proposals reviewed on their shot, a draggable 3D plan with a beat track and easing curve), and **Timeline** (frame-accurate per-shot trims with ripple or roll, a cut preview, and a film export that honors the trims). Built on a small control kit (parameter rows, range sliders, timecode fields, curve editor). Gaps are listed in [SPEC_15 §6](docs/specs/SPEC_15_UNIFIED_CREATIVE_WORKSPACE_UI_DESIGN.md): no write-back from shots to script lines, no audio tracks or J/L cuts, no razor, and the Timeline's "runs long" hints are a local rule, not an agent.
- SPEC_18 refinements inside those spaces: on the Cast & sets wall pictures generate in the background (several at once, each with cancel and retry, picked up again after a reload) and the card you pick opens in a large editor (the picture, its looks, a generation bar that shows the time earlier runs took or "time unknown", appearance as text or tags, voice, status and notes edited in place); the primary button opens a build/update dialog with per-mode shot estimates; Shot Stage detail shows the previs → first frame → video ladder and each shot's cast, whose look menus rewrite only the `@code` in the prompt. A production can also start from a story: the New Production dialog takes an idea, a novel chapter or a screenplay in one box, with a ratio and a style, and opens Story & World with it in the draft. Not built: character three-views, voice audio, and a generation line on shot detail ([SPEC_18 §11](docs/specs/SPEC_18_RUNNINGHUB_INFORMED_STUDIO_REVISION.md)).
- Seventeen built-in Studio Cards (ten existing plus seven official native Router models) and authenticated persistent ComfyUI JSON / RunningHub curl imports. [Router protocol and limits](docs/COMFY_ROUTER.md) are separate from workflow-graph execution.
- The [lean Agent Console](docs/SPEC08_CONSOLE.md): exactly twelve functional pages, twelve templates/blank/literal drafts, seven governed Studio/advisor tools, versioned skills/scoped memory, isolated outcome grader, existing M8 sessions and manual/cron deployments, provider/environment references and combined truthful analytics/active limits. Independent review is pending; fixture engineering proof is not semantic-quality or billing acceptance.
- [SPEC_07 routing and allocation](docs/SPEC07_STUDIO_ROUTING.md): default open-weights policy lock, explicitly authorized hybrid graphless providers, source-bound batch allocation, real structural preparation and reviewed M8 media races/two-stage handoffs. Resource estimates are uncalibrated, not savings or quality promises.
- A `ZeroField Studio` template with five editable pages: **Director Brief**, **Soul Cast**, **Cinema Studio**, **OpenJutsu Lab**, and **Comfy Pipeline**.
- **The Last Signal** showcase, seeded by the launcher with original procedural PNG/MP4 playback fixtures, review statuses and a director annotation. Raw project templates retain empty media cells.
- Inline video controls and hover previews, cached metadata, candidate video comparison, and visual input/output chains with resolved `@Asset` references.
- Single-shot comparison, keyboard shot stepping and optical/motion/mode presets alongside Studio Assistant; selected shots and individual stages run in the current sheet.
- Standard reference packs: source video, extracted PNG frame, continuous motion guide, anchor keyframe, multiple `@Asset` images, prompt and seed.
- FFmpeg first-frame extraction, edge/luminance/frame-difference motion guides, and split-screen output with audio and faststart.
- OpenJutsu **Object Swap** rows: a FLUX 3 Klein swap key, then one LTX-2.5 graph that runs the Alpha-Gen IC-LoRA matte, regenerates the subject and composites it over the source ([workflow](workflows/README.md#openjutsu-subject-replacement-object-swap)).
- Cinema **Layout Render** from the 3D Stage: the previs and its actor matte drive the LTX-2.5 Layout-To-Render IC-LoRA after a reviewed FLUX 3 Klein key of frame 0, keeping the blocked set and camera ([workflow](workflows/README.md#layout-render-3d-stage-previs-as-an-ic-lora-layout), [S03 in the app](docs/verification/motion-lab/app_layout_lane_s03.jpg)).
- **Camera fidelity** in shot review: every video take in a row with a Previs is scored in the background against it (Lucas-Kanade + RANSAC camera path), with tilt / pan / zoom travel as a fraction of the previs move; needs `.[fidelity]` (OpenCV, NumPy) ([S03](docs/verification/camera-fidelity/s03_shot_review.png)).
- **Continuity grades** in shot review: the Continuity Supervisor's vision model grades a take's 8-frame contact sheet (score, issues, notes), optionally for every take as it lands. Grading waits for running ComfyUI renders, frees ComfyUI's models, then unloads the vision model (`keep_alive: 0`); grades are information only: a failing grade carries a rewritten prompt, and **Retake with this prompt** writes it into the shot and re-renders in one click ([verification](docs/PHASE2_PROGRESS.md#continuity-grades-in-the-product)).
- Arbitrary external ComfyUI JSON slot binding through `input_bindings`, including dot paths and optional media; local ComfyUI or official Comfy SDK execution with separate Cinema and V2V worker routing.
- Documents, typed tables, gallery and board views, source-file import/export, revisions, and scoped editing proposals.
- The inherited M8 agent system: configurable roles and tools, persistent tasks and dispatches, decision gates, candidate comparison, batch row assignments, and the ACP stdio bridge.
- English statuses with compatibility for existing Chinese status values and legacy tool actions.

The default crew agents are Showrunner, Screenwriter, Cinematographer, and Continuity Supervisor. Candidate proposals are applied only after review. Existing authentication, permissions, stable row/column identities, and lease protections remain in place.

Use **English / 繁體中文** in the top bar to switch the interface. The same preference applies to sign-in and access-error pages and survives a reload. Switching preserves unsaved table / assistant drafts and does not translate or rewrite project titles, documents, prompts, custom agent names, or saved workflow definitions. The studio template and its example content remain English.

![Traditional Chinese interface with the existing English production content and M8 board](docs/research/screenshots/zerofield-bilingual-zh-TW.png)

Translations live in `ui/src/i18n/locales/en.json` and `zh-TW.json`. Add semantic keys to both dictionaries, including matching interpolation parameters. Use fixed IDs and `normalizeStatus()` for application logic; use `statusLabel()` only for display. Legacy Chinese status values and tool action keys remain valid. API errors retain their original `error` and policy `code`, with additive `message_key` / `message_params` for localized presentation; unknown errors retain a readable fallback.

## Generation setup and limits

The bundled [FLUX 3 Klein and LTX 2.5 workflows](workflows/README.md) use open-weights model graphs and documented node dependencies. Install the listed weights/custom nodes in your Comfy deployment before generating. The official Comfy SDK remains the workflow-capable Developer Platform route. The separate official native Router model driver cannot execute arbitrary workflow graphs. It uses **POST `/estimate`**, not `/price`; even exact estimates are not price locks. Hard is the default and refuses unlocked charges. Only explicit versioned current-admin estimate-soft consent permits estimate-risk admission; overages remain visible, and provider reports are not invoices. Open-only stays local by default; hosted Router also needs explicitly authorized hybrid, current environment/credential grants and a fresh exact-input-bound quote.

Model quality has not been benchmarked. OpenJutsu provides source-guided V2V restyling with a reference image. Rows whose **Jutsu Mode** is `Object Swap` use an LTX-native subject replacement instead: the Alpha-Gen IC-LoRA mattes the subject, LTX-2.5 regenerates it from the FLUX 3 Klein edited first frame, and the result is composited inside the grown, feathered matte over the untouched source pixels, keeping the source audio. [Two RTX 4090 renders](docs/verification/openjutsu-swap/README.md) ran it, one through a lab driver and one through the Comfy SDK and comfy-api-proxy. Limits: Alpha-Gen mattes the whole foreground, so a shot with several people cannot pick one; clips are capped at 145 frames; higher denoise follows the new identity more closely but follows the source motion less (at 0.85 a held prop can disappear); the background inside the matte is regenerated too and drifts from the source at higher denoise (seams show at 0.9). The Clean-Plate IC-LoRA and depth conditioning are not wired. The bundled [showcase media](samples/README.md) are original CC0 procedural playback fixtures, not model renders or proof of motion/object transfer. `luma_depth` is a luminance structure proxy, not learned depth estimation. The sample V2V graph exposes a motion-guide upload slot; using that guide as model conditioning requires an externally authored compatible control graph.

## Run locally

Requirements: Python 3.11+, Node.js 22+ for frontend development, and PostgreSQL. The optional `embedded` extra supplies local PostgreSQL support; an installed PostgreSQL distribution can also be selected with `OPENBENCH_PG_BIN`.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[embedded]"
npm ci --prefix ui
npm run build --prefix ui
python run_studio.py --port 3020 --no-worker
```

Open [http://127.0.0.1:3020/projects/](http://127.0.0.1:3020/projects/). The launcher seeds the default development showcase and crew, registers separate workers, and fills only empty showcase media cells once. Subsequent launches preserve edits and custom pipeline definitions. Existing productions are preserved. Development mode binds to the local machine and includes a crew identity switcher.

For local generation, install the models/nodes listed in [workflow setup](workflows/README.md), then run:

```powershell
python run_studio.py --port 3020 --comfy-url http://127.0.0.1:8188
```

For the Comfy Developer Platform, install `.[comfy]` (the official `comfy-sdk` and `comfy-api-proxy`) and select `--platform comfy_sdk`. On your own GPU, run `comfy-api-proxy` next to ComfyUI: it serves the SDK's v2 API on `http://127.0.0.1:8189` in front of ComfyUI on `8188`, and that is the default endpoint when no `COMFY_API_KEY` is set. With a key the SDK targets Comfy Cloud; `--comfy-url` / `COMFY_BASE_URL` selects any other deployment.

```powershell
python -m pip install -e ".[comfy]"
comfy-api-proxy
python run_studio.py --port 3020 --platform comfy_sdk
```

Generation outputs are proposals for director review. The launcher uses `OPENBENCH_DB_URI` or `DATABASE_URL` when supplied, otherwise it starts the embedded development database. `OPENBENCH_PG_BIN` selects an installed PostgreSQL bin directory. Non-development authentication never seeds demo accounts or registers demo workers.

`--no-worker` lets you explore the workspace without starting model calls. To use agents, configure an appropriate model and restart without that flag. Existing `OPENBENCH_*` environment variables and CLI entry points are retained for compatibility. Configure a local open-weights, OpenAI-compatible endpoint with `OPENBENCH_PROVIDER=openai_compat`, `OPENBENCH_API_BASE`, and `OPENBENCH_MODEL`; see [worker setup](docs/WORKERS.md) for the supported settings and ACP configuration. For contest workflows, use open-weights models and open-source nodes.

## External workflows and reference preparation

The seeded OpenJutsu slate includes independently replaceable **Source Driving Video**, **First Frame**, **Motion Structure**, **Anchor Keyframe**, **Remastered Video** and **Split-Screen MP4** cells. The preparation stages use the original source video. Each result is reviewed before downstream generation proceeds.

Use a trusted JSON file with `--worker-config path/to/studio-workers.json` to override stage adapters (`image`, `cinema`, `v2v`, `extract`, `structure`, `split`, `assemble`) or provide an `anchor` image-edit adapter. Workflow paths resolve relative to that file. For example, an externally authored image-edit graph can bind its own pose/reference slots:

```json
{
  "anchor": {
    "image_gen": {
      "adapter": "comfyui",
      "platform": "local",
      "base_url": "http://127.0.0.1:8188",
      "workflow": "./my-image-edit-api.json",
      "output_node": "save",
      "input_bindings": {
        "first_frame": {"node": "pose", "input": "image", "upload": "image"},
        "asset_images.0": {"node": "identity", "input": "image", "upload": "image"},
        "compiled_prompt": {"node": "prompt", "input": "text"},
        "seed": {"node": "sampler", "input": "seed"}
      }
    }
  }
}
```

Node names in this example belong to the external graph and must match its actual API JSON. ZeroField uploads and binds slots; the graph defines how references condition the model. The text-only cast generator is not used as a substitute for an image-edit anchor workflow. If you customize the saved pipeline, add/bind the matching stage through Pipeline Settings.

## Develop and verify

```powershell
python -m unittest discover -s tests -v
npm test --prefix ui
npm run build --prefix ui
python -m pip wheel --no-deps --no-build-isolation --no-index . --wheel-dir "$env:TEMP/zerofield-wheels"
```

Set `OPENBENCH_TEST_DB_URI` to a **dedicated test PostgreSQL database** to run the database integration suite. Without it those tests are skipped. FFmpeg and FFprobe enable the existing media-assembly tests. Frontend changes must be rebuilt because the server serves `static/projects/`.

Current SPEC_08 frozen gates, installed-wheel identities and unchanged-candidate browser evidence are recorded in [the Console receipt](docs/spec08-verification.json). [Console usage](docs/SPEC08_CONSOLE.md) explains real versus deterministic preview, owner/admin authority, quote restart/expiry, strict project Judge10, and no paid replay/refund or OS-sandbox guarantee. Independent security/journey reviews are pending. No live provider/model/billing/GPU acceptance is claimed.

SPEC_07 integration verification is recorded in [its own receipt](docs/spec07-verification.json); synthetic inference is explicitly distinguished from live provider/model execution. The previous SPEC_06 verification (306 backend / 108 frontend tests, build and packaged resources) is recorded in [the Story Workbench receipt](docs/story-workbench-verification.json). Earlier verification is recorded in [the bilingual baseline receipt](docs/bilingual-baseline.json). The [English baseline receipt](docs/english-baseline.json) records the earlier checkpoint.

Read [AGENTS.md](AGENTS.md), [design and development guidelines](docs/DESIGN_AND_DEV_GUIDELINES.md), and the [ZeroField specification](docs/ZEROFIELD_SPEC.md) before extending the application. The specification describes the target product; the Available now section above describes this checkout.

## Provenance and license

ZeroField is based on OpenBench. The complete M8-A–D / ACP / E1 baseline was imported from commit `a1f5d915bb2cafb8b92d9ff9c6003dc19348fdf9`; its provenance and validation are recorded in [the synchronization receipt](docs/openbench-m8-sync.json). That receipt describes the import checkpoint, before ZeroField-specific changes.

Code is distributed under the [MIT license](LICENSE). Use original or appropriately licensed material for production examples. Model weights and generated or imported media have their own applicable licenses.
