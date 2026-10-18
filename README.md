# ZeroField Studio

An open-source production workspace for planning films with a crew of AI agents. Organize a director brief, cast references, shot slates, and editable pipelines in one place.

Built for the ComfyUI [Open Source Higgsfield Challenge](https://comfy.org/open-source-higgsfield). The target is an open-weights filmmaking and V2V studio; this checkout currently delivers the **English production-planning baseline**.

## Available now

- English studio navigation, crew settings, annotations, asset review, and agent controls.
- A `ZeroField Studio` template with five editable pages: **Director Brief**, **Soul Cast**, **Cinema Studio**, **OpenJutsu Lab**, and **Comfy Pipeline**.
- An original planning example, **The Last Signal**, with empty media cells and Queued production tasks.
- Documents, typed tables, gallery and board views, source-file import/export, revisions, and scoped editing proposals.
- The inherited M8 agent system: configurable roles and tools, persistent tasks and dispatches, decision gates, candidate comparison, batch row assignments, and the ACP stdio bridge.
- English statuses with compatibility for existing Chinese status values and legacy tool actions.

The default crew agents are Showrunner, Screenwriter, Cinematographer, and Continuity Supervisor. Candidate proposals are applied only after review. Existing authentication, permissions, stable row/column identities, and lease protections remain in place.

![English planning workspace and M8 agent board](docs/research/screenshots/zerofield-english-m8.png)

## Next development phase

The following ZeroField features are planned and are **not included as completed capabilities**:

- Inline video players, video-take comparison, and the video-specific upload/playback performance work.
- Optical and camera-motion pickers connected to generation parameters.
- Validated FLUX / LTX image, cinema, and V2V workflow JSON files.
- OpenJutsu source-video transfer and split-screen video output.
- A `run_studio.py` launcher and actual generated sample renders.

The editable pipeline describes those production stages; it does not install or configure their workers. The existing generic ComfyUI and FFmpeg adapters are inherited infrastructure. The `workflows/` and `samples/` directories currently contain documentation, not validated generation workflows or finished media.

## Run locally

Requirements: Python 3.11+, Node.js 22+ for frontend development, and PostgreSQL. The optional `embedded` extra supplies local PostgreSQL support; an installed PostgreSQL distribution can also be selected with `OPENBENCH_PG_BIN`.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[embedded]"
npm ci --prefix ui
npm run build --prefix ui
python server.py --embedded-db --port 3020 --no-worker
```

Open [http://127.0.0.1:3020/projects/](http://127.0.0.1:3020/projects/). A fresh development database receives the English planning example and demo crew accounts. Existing productions are preserved. Development mode binds to the local machine and includes a crew identity switcher.

`--no-worker` lets you explore the workspace without starting model calls. To use agents, configure an appropriate model and restart without that flag. Existing `OPENBENCH_*` environment variables and CLI entry points are retained for compatibility. Configure a local open-weights, OpenAI-compatible endpoint with `OPENBENCH_PROVIDER=openai_compat`, `OPENBENCH_API_BASE`, and `OPENBENCH_MODEL`; see [worker setup](docs/WORKERS.md) for the supported settings and ACP configuration. For contest workflows, use open-weights models and open-source nodes.

## Develop and verify

```powershell
python -m unittest discover -s tests -v
npm test --prefix ui
npm run build --prefix ui
python -m build --wheel
```

Set `OPENBENCH_TEST_DB_URI` to a **dedicated test PostgreSQL database** to run the database integration suite. Without it those tests are skipped. FFmpeg and FFprobe enable the existing media-assembly tests. Frontend changes must be rebuilt because the server serves `static/projects/`.

Current baseline verification is recorded in [the English baseline receipt](docs/english-baseline.json).

Current baseline verification is recorded in [the English baseline receipt](docs/english-baseline.json).

Read [AGENTS.md](AGENTS.md), [design and development guidelines](docs/DESIGN_AND_DEV_GUIDELINES.md), and the [ZeroField specification](docs/ZEROFIELD_SPEC.md) before extending the application. The specification describes the target product; the Available now section above describes this checkout.

## Provenance and license

ZeroField is based on OpenBench. The complete M8-A–D / ACP / E1 baseline was imported from commit `a1f5d915bb2cafb8b92d9ff9c6003dc19348fdf9`; its provenance and validation are recorded in [the synchronization receipt](docs/openbench-m8-sync.json). That receipt describes the import checkpoint, before ZeroField-specific changes.

Code is distributed under the [MIT license](LICENSE). Use original or appropriately licensed material for production examples. Model weights and generated or imported media have their own applicable licenses.
