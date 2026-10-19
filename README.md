# ZeroField Studio

An open-source production workspace for planning films with a crew of AI agents. Organize a director brief, cast references, shot slates, and editable pipelines in one place.

Built for the ComfyUI [Open Source Higgsfield Challenge](https://comfy.org/open-source-higgsfield). The target is an open-weights filmmaking and V2V studio; this checkout delivers a **bilingual production workspace with inline video review and configurable Comfy workflows**.

## Available now

- English / Traditional Chinese studio navigation, crew settings, annotations, asset review, and agent controls. English is the first-run default.
- The [Story Workbench](docs/STORY_WORKBENCH.md): five navigation entries, script confirmation/breakdown, scene-grouped galleries, wardrobe variants, candidate selection, card/node overrides, split/merge, batch generation and episode film export over `/aivideo/open/v1`.
- Seven built-in Studio Cards plus authenticated, persistent ComfyUI JSON / RunningHub curl card imports.
- A `ZeroField Studio` template with five editable pages: **Director Brief**, **Soul Cast**, **Cinema Studio**, **OpenJutsu Lab**, and **Comfy Pipeline**.
- **The Last Signal** showcase, seeded by the launcher with original procedural PNG/MP4 playback fixtures, review statuses and a director annotation. Raw project templates retain empty media cells.
- Inline video controls and hover previews, cached metadata, candidate video comparison, and visual input/output chains with resolved `@Asset` references.
- Single-shot comparison, keyboard shot stepping and optical/motion/mode presets alongside Studio Assistant; selected shots and individual stages run in the current sheet.
- Standard reference packs: source video, extracted PNG frame, continuous motion guide, anchor keyframe, multiple `@Asset` images, prompt and seed.
- FFmpeg first-frame extraction, edge/luminance/frame-difference motion guides, and split-screen output with audio and faststart.
- Arbitrary external ComfyUI JSON slot binding through `input_bindings`, including dot paths and optional media; local ComfyUI or official Comfy SDK execution with separate Cinema and V2V worker routing.
- Documents, typed tables, gallery and board views, source-file import/export, revisions, and scoped editing proposals.
- The inherited M8 agent system: configurable roles and tools, persistent tasks and dispatches, decision gates, candidate comparison, batch row assignments, and the ACP stdio bridge.
- English statuses with compatibility for existing Chinese status values and legacy tool actions.

The default crew agents are Showrunner, Screenwriter, Cinematographer, and Continuity Supervisor. Candidate proposals are applied only after review. Existing authentication, permissions, stable row/column identities, and lease protections remain in place.

Use **English / 繁體中文** in the top bar to switch the interface. The same preference applies to sign-in and access-error pages and survives a reload. Switching preserves unsaved table / assistant drafts and does not translate or rewrite project titles, documents, prompts, custom agent names, or saved workflow definitions. The studio template and its example content remain English.

![Traditional Chinese interface with the existing English production content and M8 board](docs/research/screenshots/zerofield-bilingual-zh-TW.png)

Translations live in `ui/src/i18n/locales/en.json` and `zh-TW.json`. Add semantic keys to both dictionaries, including matching interpolation parameters. Use fixed IDs and `normalizeStatus()` for application logic; use `statusLabel()` only for display. Legacy Chinese status values and tool action keys remain valid. API errors retain their original `error` and policy `code`, with additive `message_key` / `message_params` for localized presentation; unknown errors retain a readable fallback.

## Generation setup and limits

The bundled [FLUX 3 Klein and LTX 2.5 workflows](workflows/README.md) use open-weights model graphs and documented node dependencies. Install the listed weights/custom nodes in your Comfy deployment before generating. The official Comfy SDK is the Comfy Developer Platform route; Comfy Router's model API cannot execute arbitrary workflow graphs, so Router-only workflow configuration produces an actionable error.

GPU generation and model quality have not been exercised in this environment. OpenJutsu currently provides source-guided V2V restyling with a reference image; SAM2 segmentation, depth conditioning and precise object replacement need separate validated workflows. The bundled [showcase media](samples/README.md) are original CC0 procedural playback fixtures, not model renders or proof of motion/object transfer. `luma_depth` is a luminance structure proxy, not learned depth estimation. The sample V2V graph exposes a motion-guide upload slot; using that guide as model conditioning requires an externally authored compatible control graph.

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

For the Comfy Developer Platform, install `.[comfy]`, set `COMFY_API_KEY`, and select `--platform comfy_sdk`. Use `--comfy-url` / `COMFY_BASE_URL` for a workflow-capable deployment; the SDK defaults to Comfy Cloud. Generation outputs are proposals for director review. The launcher uses `OPENBENCH_DB_URI` or `DATABASE_URL` when supplied, otherwise it starts the embedded development database. `OPENBENCH_PG_BIN` selects an installed PostgreSQL bin directory. Non-development authentication never seeds demo accounts or registers demo workers.

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
python -m build --wheel
```

Set `OPENBENCH_TEST_DB_URI` to a **dedicated test PostgreSQL database** to run the database integration suite. Without it those tests are skipped. FFmpeg and FFprobe enable the existing media-assembly tests. Frontend changes must be rebuilt because the server serves `static/projects/`.

SPEC_06 verification (306 backend / 108 frontend tests, build and packaged resources) is recorded in [the Story Workbench receipt](docs/story-workbench-verification.json). Earlier verification is recorded in [the bilingual baseline receipt](docs/bilingual-baseline.json). The [English baseline receipt](docs/english-baseline.json) records the earlier checkpoint.

Read [AGENTS.md](AGENTS.md), [design and development guidelines](docs/DESIGN_AND_DEV_GUIDELINES.md), and the [ZeroField specification](docs/ZEROFIELD_SPEC.md) before extending the application. The specification describes the target product; the Available now section above describes this checkout.

## Provenance and license

ZeroField is based on OpenBench. The complete M8-A–D / ACP / E1 baseline was imported from commit `a1f5d915bb2cafb8b92d9ff9c6003dc19348fdf9`; its provenance and validation are recorded in [the synchronization receipt](docs/openbench-m8-sync.json). That receipt describes the import checkpoint, before ZeroField-specific changes.

Code is distributed under the [MIT license](LICENSE). Use original or appropriately licensed material for production examples. Model weights and generated or imported media have their own applicable licenses.
