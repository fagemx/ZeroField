# `SPEC_07` — `limb_worker` Modularization (`project_assistant/studio/`) & Agent-Driven Hybrid Model Router (Closed-Source Mainstay × Open-Weights Lab)

- **Parent Spec**: [`docs/ZEROFIELD_SPEC.md`](../ZEROFIELD_SPEC.md)
- **Prerequisite Specs**:
  - [`SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md`](./SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md) (Completed)
  - [`SPEC_06_RH_STORY_WORKBENCH_AND_MACRO_MESO_MICRO.md`](./SPEC_06_RH_STORY_WORKBENCH_AND_MACRO_MESO_MICRO.md) (Execute after `SPEC_06` finishes)
- **Target Scope**:
  1. **De-bloat `project_assistant/limb_worker.py`** (~2,882 lines) into a clean, single-responsibility `project_assistant/studio/` package while maintaining a 100% backward-compatible facade in `limb_worker.py`.
  2. **Unify Closed-Source Flagship Models & Open-Weights Models** under a single `Studio Card` + `ModelRouter` architecture (`comfy_local`, `comfy_partner`, `runninghub_cloud`, `vendor_api`).
  3. **Integrate Agent-Driven Resource Allocation (`agent_allocator.py`)**: Enable agents (`Showrunner`, `Cinematographer`, `Continuity Supervisor`) and the user to dynamically allocate tasks between **Closed-Source Models** (industrial production mainstay, complex physics/acting, tight deadlines) and **Open-Weights Models** (planning, zero-cost experimentation, structural pre-viz, B-roll, and 4K local restoration).
- **Owned / Target Files**:
  - **New Backend Package (`project_assistant/studio/`)**:
    - `project_assistant/studio/__init__.py`
    - `project_assistant/studio/context_compiler.py`
    - `project_assistant/studio/card_engine.py`
    - `project_assistant/studio/media_prep.py`
    - `project_assistant/studio/line_worlds.py`
    - `project_assistant/studio/openapi_v2_hub.py`
    - `project_assistant/studio/model_router.py`
    - `project_assistant/studio/agent_allocator.py`
  - **Refactored Facade**:
    - `project_assistant/limb_worker.py` *(shrunk to < 300 lines; re-exports all public symbols from `project_assistant.studio` for 100% test compatibility)*
  - **Cards & Frontend Integration**:
    - `workflows/cards/*.json` *(add `tier`, `driver`, and closed-source/cloud card templates)*
    - `project_docs/story_openapi.py` & `project_docs/runtime_http.py` *(wire `budgetMode` / `engineTier` preflight & escalation)*
    - `ui/src/SheetWorkspace.jsx`, `ui/src/SheetCards.jsx`, `ui/src/SheetReview.jsx`, `ui/src/StoryWorkbenchModals.jsx`
  - **Tests**:
    - `tests/test_studio_modular_and_router.py`

---

## 1. Architectural Diagnosis & Core Philosophy

### 1.1 Why `limb_worker.py` Must Be Modularized Now
`project_assistant/limb_worker.py` grew to **2,882 lines** because six distinct architectural layers were accumulated into a single script:
1. Remote worker lease loop & HTTP transport (`Head`, `process_one`, `fetch`, `acp_stdio`).
2. Self-hosted RunningHub `/openapi/v2` server-side state (`_OPENAPI_CARDS`, `_OPENAPI_TASKS`, `openapi_run_ai_app`).
3. ComfyUI LiteGraph-to-API compiler & `nodeInfoList` injector (`convert_litegraph_to_api`, `inject_node_info_into_workflow`).
4. Cross-tab studio context resolver & prompt compiler (`resolve_studio_context`, `compile_h3_context_ir`, `build_slot_plan`).
5. FFmpeg media pre/post-processing (`extract_first_frame`, `render_frame_sheet`, `trim_video_duration_bounded`, `assemble_files`).
6. `line-worlds` 2D inverse-kinematics procedural motion renderer (`render_line_worlds_structure`).

Because server modules (`project_docs/runtime_http.py` and `project_docs/story_openapi.py`) only need layers 2–5, keeping everything inside `limb_worker.py` couples the HTTP control plane to the remote worker script and makes adding multi-provider routing brittle.

### 1.2 Real-World Production Economics: Closed-Source Mainstay × Open-Weights Lab
In real AI drama and commercial video production, creators do **not** dogmatically use only open-weights or only closed-source models—they **allocate resources based on complexity, time pressure, and budget**:

| Dimension | Closed-Source Flagship Models<br>*(Seedance 2.0 / Dreamina, Kling 2.0, Veo 3, Hailuo Cloud, Flux Pro, Claude / GPT / Gemini)* | Open-Weights Local Models<br>*(LTX-2.5, FLUX Klein/Dev, Local MiniMax H3 / Wan, Local VLM via Ollama/vLLM)* |
| :--- | :--- | :--- |
| **Primary Role** | **Industrial Production Mainstay (工業生產主力)** | **Planning, Pre-viz, B-Roll & Structural Control (規劃實驗、預演與結構精控)** |
| **When to Use** | • Complex multi-character acting, micro-expressions, hand/prop physics<br>• Hero shots where 1-shot quality saves hours of human compositing<br>• Tight deadlines requiring 10–30 concurrent cloud renders | • Early script/storyboard experimentation & blocking validation (no time pressure)<br>• Cost-sensitive batch runs & atmospheric B-roll / static dialogue shots<br>• Deep multi-control pipelines (`IC-LoRA`, `line-worlds` 2D IK, `.bounded.mp4` 4K restoration) |
| **Cost vs. Time** | Higher API credit cost, **lowest human iteration time & highest concurrency** | **Zero marginal API cost** (local RTX 4090 electricity only), serial local queue or multi-step workflow |

### 1.3 Contest Compliance Guard (`OPENBENCH_PRODUCTION_POLICY`)
To satisfy both **ComfyUI Open Source Higgsfield Challenge** rules (Best Overall + Open Weights Only + LTX $2,000 Bonus) and daily industrial production:
- ZeroField introduces a project/deployment policy setting: `production_policy` (`"open_weights_only"` vs `"hybrid_studio"`):
  - **`"open_weights_only"` (Default out-of-the-box for Contest Judges)**:
    - Locks active media generation cards to `tier == "open_weights"` (`LTX-2.5` + `FLUX`).
    - Displays an emerald **`100% Open-Weights Verified`** badge in the top bar.
  - **`"hybrid_studio"` (Creator's Daily Production Mode)**:
    - Unlocks closed-source commercial engines (`vendor_api`, `comfy_partner`, `runninghub_cloud`) alongside local open-weights (`comfy_local`), and activates the **Agent Resource Allocator**.

---

## 2. Part 1 — De-bloating `limb_worker.py` into `project_assistant/studio/`

```text
project_assistant/
├── limb_worker.py                  # [< 300 lines] Worker lease loop, HTTP transport & backward-compat re-exports
└── studio/                         # [NEW] Modular Studio & Multimodal Execution Package
    ├── __init__.py                 # Exports public studio API
    ├── context_compiler.py         # @CAST/@SET:variant resolution, slot_plan, H3-Context-IR, 32px & 8n+1/17n+5 alignment
    ├── card_engine.py              # Studio Card schema, cURL parser, LiteGraph->API converter, nodeInfoList injector
    ├── media_prep.py               # FFmpeg extract_frame, 8-frame sheet, ingredients_sheet, .bounded.mp4 trim, concat
    ├── line_worlds.py              # 2-Link IK procedural rig & layout_silhouette / sparse_tracks / time_strata renderer
    ├── openapi_v2_hub.py           # Self-hosted /openapi/v2 card registry, binary media store & task dispatcher
    ├── model_router.py             # [NEW] Unified driver router (comfy_local, comfy_partner, runninghub_cloud, vendor_api)
    └── agent_allocator.py          # [NEW] Complexity triage, budget_mode routing, Retake escalation & Closed×Open chaining
```

### 2.1 Exact Symbol Migration Map

| Target Module | Migrated Functions & Classes (from `limb_worker.py`) | Responsibility |
| :--- | :--- | :--- |
| **`studio/context_compiler.py`** | `snap_dimensions_32`, `snap_frame_count`, `select_motion_structure_mode`, `compute_request_fingerprint`, `build_slot_plan`, `compile_h3_context_ir`, `resolve_studio_context`, `parse_asset_tokens_with_variants` | Pure studio context resolution, asset/wardrobe variant binding (`@CAST-01:night`), slot ranking, and structured prompt compilation. Zero network or FFmpeg side effects. |
| **`studio/card_engine.py`** | `CARD_FIELD_TYPES`, `CARD_SLOTS`, `CARD_OUTPUT_MODES`, `CARDS_DIR`, `validate_studio_card`, `load_studio_card`, `build_node_info`, `inject_node_info_into_workflow`, `parse_runninghub_curl_or_payload`, `extract_studio_card_from_workflow`, `convert_litegraph_to_api`, `bind_external_workflow`, `ComfyPlatformClient` | RunningHub / ComfyUI workflow card loading, LiteGraph conversion, `nodeInfoList` injection, cascade unlinking (`"None"`), and Comfy execution client. |
| **`studio/media_prep.py`** | `ffmpeg_binary`, `ffprobe_binary`, `_probe_video`, `extract_first_frame`, `render_motion_structure_video`, `render_frame_sheet`, `render_ingredients_sheet`, `trim_video_duration_bounded`, `assemble_files`, `assemble_side_by_side`, `ffmpeg` | All FFmpeg / Pillow local image & video preparation, contact sheets, duration trimming (`.bounded.mp4`), and episode assembly. |
| **`studio/line_worlds.py`** | `_compute_rig_pose`, `_draw_pose_on_canvas`, `render_line_worlds_structure` | Procedural 2D inverse-kinematics (`line-worlds`) motion structure generator (`layout_silhouette`, `sparse_tracks`, `time_strata`). |
| **`studio/openapi_v2_hub.py`** | `_parse_multipart_file`, `openapi_upload_binary`, `openapi_get_media`, `openapi_register_card`, `openapi_list_cards`, `openapi_run_ai_app`, `openapi_query_task`, `_resolve_openapi_card_and_workflow` | Self-hosted `/openapi/v2/*` endpoint handlers used by `project_docs/runtime_http.py` and `project_docs/story_openapi.py`. |
| **`studio/model_router.py`** | `execute_story_card`, `ModelRouter`, `probe_local_comfy_status`, `execute_vendor_card`, `execute_runninghub_cloud_card` | Unified card execution router: dispatches `vendor_api` / `runninghub_cloud` **without requiring a ComfyUI workflow file or running ComfyUI**, and dispatches `comfy_local` / `comfy_partner` via `ComfyPlatformClient`. |
| **`limb_worker.py`** *(Slimmed)* | `WorkerError`, `TransientWorkerError`, `fetch`, `json_fetch`, `configured_token`, `Head`, `llm`, `acp_stdio`, `speech`, `bridge`, `comfyui`, `ADAPTERS`, `process_one`, `main` + **`from project_assistant.studio import *`** | Remote worker daemon and 100% backward-compatible import surface for existing unit tests (`tests/test_studio_worker.py`, `tests/test_story_openapi.py`). |

> **⚠️ Non-Negotiable Compatibility Rule**:
> Every existing function imported from `project_assistant.limb_worker` in `tests/test_studio_worker.py`, `project_docs/runtime_http.py`, or `project_docs/story_openapi.py` MUST remain importable from `project_assistant.limb_worker` via re-exports in `limb_worker.py` and `project_assistant/studio/__init__.py`.

---

## 3. Part 2 — Unified Closed-Source & Open-Weights Model Router (`studio/model_router.py`)

### 3.1 One `Studio Card` Contract, Four Execution Drivers (Zero ComfyUI Dependency for Closed-Source!)
> **⚠️ Crucial Architectural Principle — Closed-Source Models DO NOT Require ComfyUI to Run!**
> Calling a model a "Studio Card" only means it shares the same **UI parameter schema** (`ref` images, `prompt`, `driving_video`, `duration`, `aspect_ratio`, `seed`) and shares Python/FFmpeg pre/post-processing (`@CAST-01:night` lookup, `extract_first_frame`, `.bounded.mp4` duration trim).
> - **When running Closed-Source (`vendor_api`, `cli_bridge`, `runninghub_cloud`), local ComfyUI (`127.0.0.1:8188`) DOES NOT need to be installed or running!** Python (`studio/model_router.py`) calls the commercial REST API or CLI directly. You can run the entire studio on a lightweight laptop with ComfyUI completely closed.
> - **Local ComfyUI is ONLY needed when `driver == "comfy_local"` (local Open-Weights on RTX 4090) or `driver == "comfy_partner"` (when you explicitly want to run a ComfyUI node graph).**

Regardless of whether a shot is rendered by a local open-weights ComfyUI workflow or a direct closed-source commercial API (without ComfyUI), the upstream preparation (`resolve_studio_context`, `@CAST-01:night` variants, `extract_first_frame`, `render_frame_sheet`) and downstream normalization (`trim_video_duration_bounded` with `-movflags +faststart`) are **100% shared in pure Python + FFmpeg**.

Each Studio Card in `workflows/cards/*.json` defines `engine_config.driver`, `engine_config.requires_comfyui`, and `engine_config.tier`:

```json
{
  "card_id": "seedance-20-pro",
  "version": "1.0",
  "label": "Seedance 2.0 Pro (Closed-Source Hero I2V/Ref2V)",
  "engine": "vendor_api",
  "output_mode": "video",
  "engine_config": {
    "driver": "vendor_api",
    "provider": "seedance",
    "tier": "closed_hero",
    "webappId": "2108000000000000001",
    "base_url_env": "SEEDANCE_API_URL",
    "api_key_env": "SEEDANCE_API_KEY",
    "model": "seedance-2.0-pro",
    "cost_weight": 5,
    "concurrency_limit": 10,
    "fallback_open_card_id": "h3-short-video-v3"
  },
  "nodes": [
    { "nodeId": "ref_1", "nodeTitle": "Primary Character / First Frame", "fieldName": "image_url", "fieldType": "IMAGE", "slot": "ref", "slotOrder": 1, "defaultValue": "None" },
    { "nodeId": "ref_2", "nodeTitle": "Secondary Character / Set Reference", "fieldName": "ref_image_2", "fieldType": "IMAGE", "slot": "ref", "slotOrder": 2, "defaultValue": "None" },
    { "nodeId": "motion_ref", "nodeTitle": "Driving Motion Video", "fieldName": "driving_video_url", "fieldType": "VIDEO", "slot": "driving_video", "defaultValue": "None" },
    { "nodeId": "prompt", "nodeTitle": "Director Shot Prompt", "fieldName": "prompt", "fieldType": "STRING", "slot": "prompt", "defaultValue": "" },
    { "nodeId": "duration", "nodeTitle": "Duration (Seconds)", "fieldName": "duration", "fieldType": "INT", "slot": "duration", "defaultValue": "5" },
    { "nodeId": "aspect_ratio", "nodeTitle": "Aspect Ratio", "fieldName": "aspect_ratio", "fieldType": "LIST", "slot": "aspect_ratio", "defaultValue": "16:9" }
  ]
}
```

### 3.2 Supported Drivers in `ModelRouter`

| Driver (`engine_config.driver`) | Needs Local ComfyUI? | Tier (`engine_config.tier`) | Supported Engines / Providers | How `ModelRouter.execute_card()` Runs It |
| :--- | :---: | :--- | :--- | :--- |
| **`vendor_api`** *(Direct Closed API / CLI)* | **❌ NO**<br>*(Pure Python HTTP / CLI)* | `"closed_hero"` | Direct Commercial REST APIs & CLIs:<br>• **`seedance`** (Seedance 2.0 / Dreamina API or `dreamina-cli`)<br>• **`kling`** (Kling v2 Master API)<br>• **`veo`** (Google Veo 3 / Gemini Video API)<br>• **`hailuo_cloud`** (MiniMax Hailuo Commercial API)<br>• **`flux_pro_api`** / **`openai_compat_media`** | **Zero ComfyUI required.** Python directly reads `@CAST` images & first-frame PNG from PostgreSQL/disk, sends HTTPS JSON/multipart (or invokes CLI) to the closed-source provider, downloads the MP4, and runs FFmpeg `.bounded.mp4` trimming. |
| **`runninghub_cloud`** *(Cloud GPU Pool)* | **❌ NO**<br>*(Pure Python HTTP)* | `"cloud_burst"` | RunningHub Cloud (`https://www.runninghub.cn/openapi/v2` or `.ai`) | **Zero local ComfyUI required.** Uploads media via remote `/openapi/v2/media/upload/binary` and dispatches `{webappId, nodeInfoList}` to RunningHub's cloud GPUs; polls `/openapi/v2/query` and downloads the result for local `.bounded.mp4` trimming. |
| **`comfy_local`** *(Local Open-Weights)* | **✅ YES**<br>*(Local RTX 4090)* | `"open_weights"` | Local RTX 4090 ComfyUI (`LTX-2.5`, `FLUX Klein`, `MiniMax H3 Local`) | Compiles LiteGraph/API JSON, injects `nodeInfoList`, unlinks `"None"` slots, submits to local `ComfyPlatformClient` (`127.0.0.1:8188` or Comfy Router). |
| **`comfy_partner`** *(Optional Comfy Partner Graph)* | **✅ YES**<br>*(ComfyUI + API Key)* | `"closed_hybrid"` | ComfyUI Official Partner Nodes (`Kling`, `Veo`, `Flux Pro` nodes inside a Comfy graph) | Only used when you *choose* to wire a closed-source node inside a complex ComfyUI graph. |

#### Decoupling `story_openapi.py:generation()` & `execute_story_card()` from ComfyUI (`34d2991` Hook)
In `34d2991`, `project_docs/story_openapi.py:generation()` (line 561) calls `_, workflow = worker._resolve_openapi_card_and_workflow(card["card_id"])` and `execute_story_card(task, card, values, head)` (line 1715 of `limb_worker.py`) unconditionally writes `workflow.json` and calls `comfyui(task, config, head)`.
- **Required Update in `SPEC_07`**:
  1. In `_resolve_openapi_card_and_workflow(webapp_id)`: when `card.get("engine_config", {}).get("driver") in ("vendor_api", "runninghub_cloud")` and no local `"workflow"` file is configured, return `(card, None)` instead of raising `WorkerError("Card ... has no workflow configured")`.
  2. In `execute_story_card(task, card, values, head)` (moved to `studio/model_router.py` and re-exported in `limb_worker.py`):
     - Inspect `driver = card.get("engine_config", {}).get("driver") or ("comfy_local" if card.get("engine") == "comfyui" else "vendor_api")`.
     - If `driver == "vendor_api"`: call `execute_vendor_card(task, card, values, head)` (resolves `@CAST` / `@SET` / `first_frame` via `resolve_studio_context()`, builds `nodeInfoList`, calls the direct REST/CLI provider without ComfyUI, bounds duration with `bound_output_video_duration()`, and uploads via `head.upload()`).
     - If `driver == "runninghub_cloud"`: call `execute_runninghub_cloud_card(task, card, values, head)` (uploads media slots to remote `/openapi/v2/media/upload/binary`, dispatches `{webappId, nodeInfoList}` to remote RunningHub Cloud, polls `/openapi/v2/query`, downloads output, bounds duration, and uploads via `head.upload()`).
     - If `driver in ("comfy_local", "comfy_partner")`: run the existing `comfyui(task, config, head)` path.
  3. Update `story_openapi.py:ALIASES` so `"SEEDANCE_2_FAST_MULTIMODAL_VIDEO"` maps to `"seedance-20-pro"` (with automatic fallback to `"h3-reference"` when `production_policy == "open_weights_only"` or when no external Seedance endpoint is configured).

#### Automatic ComfyUI Offline Detection (`probe_local_comfy_status()`)
- `ModelRouter` includes a fast non-blocking health check (`GET http://127.0.0.1:8188/system_stats` with 0.5s timeout):
  - When **Local ComfyUI is Offline** (e.g., you are working on a laptop or haven't launched ComfyUI), all **`vendor_api`** and **`runninghub_cloud`** closed-source cards work at 100% capacity, and `agent_allocator.py` automatically routes shots to `vendor_api` / `runninghub_cloud` without failing on `127.0.0.1:8188`!

### 3.3 Built-in Card Catalog (`workflows/cards/`)
In addition to the 7 existing open-weights cards (`h3-short-video-v3`, `h3-reference`, `h3-optimize`, `ltx25-openjutsu`, `ltx25-cinema`, `flux-soul-cast`, `local-smoke`), add 3 closed-source / cloud hero cards:
1. `workflows/cards/seedance-20-pro.json` (`webappId`: `"2108000000000000001"`, `driver`: `"vendor_api"`, `provider`: `"seedance"`, `tier`: `"closed_hero"`, `fallback_open_card_id`: `"h3-short-video-v3"`)
2. `workflows/cards/kling-v2-master.json` (`webappId`: `"2108000000000000002"`, `driver`: `"vendor_api"`, `provider`: `"kling"`, `tier`: `"closed_hero"`, `fallback_open_card_id`: `"ltx25-cinema"`)
3. `workflows/cards/rh-cloud-h3-burst.json` (`webappId`: `"2109942725885075459"`, `driver`: `"runninghub_cloud"`, `tier`: `"cloud_burst"`, `fallback_open_card_id`: `"h3-short-video-v3"`)

---

## 4. Part 3 — Agent-Driven Resource Allocation (`studio/agent_allocator.py`)

This module encodes the creator's exact workflow: **use Open-Weights when experimenting, planning, or optimizing for cost without time pressure; deploy Closed-Source Models as the industrial mainstay for high-complexity shots, retakes, or tight deadlines.**

### 4.1 Shot Complexity Triage (`evaluate_shot_complexity(row_or_shot)`)
Given a shot row (from `cinema-studio`, `openjutsu-lab`, or `/aivideo/open/v1` `Shot`), `evaluate_shot_complexity()` computes a deterministic complexity profile:

```python
{
  "complexity_score": 78,          # 0..100
  "complexity_tier": "hero",       # "b_roll" (0..34) | "standard" (35..64) | "hero" (65..100)
  "reasons": [
    "multi_character_interaction (@CAST-01, @CAST-02)",
    "complex_motion_keywords (fight, grab, micro-expression)",
    "dynamic_camera_rig (Orbit 360 / Crane Up)"
  ],
  "recommended_open_card": "h3-short-video-v3",
  "recommended_closed_card": "seedance-20-pro"
}
```

**Scoring Heuristics**:
- **Cast Count**: 0 characters (`@SET` only) = `+10` (`b_roll`); 1 character = `+30`; $\ge 2$ characters interacting = `+55`.
- **Action / Physics Keywords**: High-difficulty tokens (`fight`, `clash`, `embrace`, `hand`, `finger`, `water`, `explosion`, `dance`, `crying`, `micro-expression`, `打鬥`, `特寫`, `擁抱`, `手部`) = `+25`.
- **Camera / Optical Motion**: Static / Slow Push = `+5`; Handheld / Whip Pan / Orbit / Steadicam tracking = `+15`.
- **Retake History**: Each prior `Retake` or rejected candidate video on this shot adds `+20` (automatically pushing stubborn shots into `"hero"` tier!).

### 4.2 Three Resource Allocation Modes (`budget_mode`)

`select_card_for_shot(shot, *, budget_mode="hybrid_balanced", production_policy="hybrid_studio", time_pressure="normal")`:

| `budget_mode` | Label | Routing Behavior |
| :--- | :--- | :--- |
| **`"lab_economical"`** | **Lab / Cost-Sensitive (`省錢實驗與預演模式`)** | • **100% Open-Weights Local**: Routes all shots (`b_roll`, `standard`, `hero`) to local open-weights cards (`ltx25-cinema`, `h3-short-video-v3`, `ltx25-openjutsu`).<br>• Automatically enables `line-worlds` (`layout_silhouette` / `sparse_tracks`) for complex shots so open-weights models get extra structural guidance at $0 API cost. |
| **`"hybrid_balanced"`** | **Hybrid Smart (`閉源主力 × 開源輔助智慧分配`)** *(Default in Hybrid Mode)* | • **`b_roll` (Score < 35)**: Routes to local Open-Weights (`ltx25-cinema` / `flux-soul-cast`) to save 40–60% of API credits.<br>• **`standard` (Score 35–64)**: Routes to local Open-Weights (`h3-short-video-v3` / `h3-reference`) during planning/drafting, or Closed-Source if `time_pressure == "high"`.<br>• **`hero` (Score $\ge 65$) or `retake_count >= 1`**: Automatically routes to **Closed-Source Hero** (`seedance-20-pro` / `kling-v2-master`) for 1-shot industrial quality. |
| **`"deadline_rush"`** | **Deadline Rush (`截稿衝刺雲端高併發`)** | • Routes `hero` and `standard` shots directly to Closed-Source APIs (`seedance-20-pro`, `kling-v2-master`) and `runninghub_cloud` (`rh-cloud-h3-burst`) in parallel while dispatching only the first 1–2 `b_roll` shots to the local RTX 4090 queue. |

> **Contest Policy Override**: Whenever `production_policy == "open_weights_only"`, `select_card_for_shot()` strictly returns `recommended_open_card` (`tier == "open_weights"`) regardless of `budget_mode`.

### 4.3 Automatic Retake Escalation & Closed × Open Chaining
1. ** Escalation on Retake (`escalate_shot_on_retake(shot_id)`)**:
   - When a shot is marked `"Retake"` (or fails QA review) after running on an `"open_weights"` card, the allocator generates a structured recommendation (and 1-click UI action):
     - **Option A — Escalate to Closed-Source Hero (`seedance-20-pro` / `kling-v2-master`)**: Let the closed-source model solve the complex acting/physics in one pass.
     - **Option B — Multi-Step Open-Weights Structural Lock**: Keep it on Open-Weights, but auto-insert a `line-worlds` motion structure pass (`sparse_tracks` / `layout_silhouette`) + `frame_sheet` before re-running `h3-reference` or `ltx25-openjutsu`.
     - **Option C — Blind A/B Race (`ProposalRaceView`)**: Dispatch 1 Open-Weights worker and 1 Closed-Source worker in parallel so the director can compare both takes side-by-side.
2. **Closed × Open Two-Stage Chaining (`chain_mode`)**:
   - **`"open_previz_to_closed_hero"`**: Run fast local `line-worlds` + `LTX-2.5` draft during script iteration; once the director marks the shot composition Approved, 1-click re-render the final take on `seedance-20-pro` using the approved keyframe/blocking.
   - **`"closed_hero_to_open_4k_optimize"`**: Generate the raw acting video on `seedance-20-pro` or `kling-v2-master`, then automatically pipe its output as `@source` into local `h3-optimize` (`workflows/cards/h3-optimize.json`) on the RTX 4090 for zero-cost 4K upscaling and character consistency lock!

### 4.4 Agent Brain Tiering (`agent_registry.py` Integration)
Add a helper `recommend_agent_provider_tier(agent_key, budget_mode)` so the 4 M8 specialist agents also follow resource allocation:
- **`coordinator` (Showrunner)** & **`sheet_ops` (Cinematographer)**: Default to flagship closed reasoning models (`claude`, `gpt-5` / `codex_cli`, `gemini-2.5-pro`) for story structure, `H3-Context-IR` compilation, and shot triage.
- **`qa_critic` (Continuity Supervisor)**: Uses Vision LLM on the 8-frame timestamped `frame_sheet` (`1600x600`) to diagnose whether a shot failed due to prompt drift (fixable on open-weights) or physics/hand breakdown (escalate to closed-source).
- **`doc_writer` (Screenwriter)**: Uses flagship LLM during initial script breakdown, and can switch to economical/local `openai_compat` models for bulk formatting or translation passes.

---

## 5. Part 4 — API & UI Integration (On Top of `SPEC_06`)

### 5.1 New / Extended Endpoints in `project_docs/story_openapi.py`
1. **`POST /aivideo/open/v1/projects/{projectId}/episodes/{episodeId}/shots:plan-allocation`**
   - Input: `{ "budgetMode": "lab_economical" | "hybrid_balanced" | "deadline_rush", "productionPolicy": "open_weights_only" | "hybrid_studio", "timePressure": "low" | "normal" | "high" }`
   - Output (`{ code: 0, msg: "success", data: ... }`):
     - Per-shot allocation table (`shotId`, `complexityTier`, `complexityScore`, `assignedCardId`, `driver`, `tier`, `reasons`).
     - Summary metrics: `openWeightsShotCount`, `closedHeroShotCount`, `cloudBurstShotCount`, `estimatedLocalGpuSeconds`, `estimatedCloudCredits`.
2. **`POST /aivideo/open/v1/projects/{projectId}/episodes/{episodeId}/shots/{shotId}:escalate`**
   - Input: `{ "strategy": "closed_hero" | "open_structural_lock" | "ab_race" | "closed_to_open_4k" }`
   - Automatically updates the shot's `appCode` / pipeline chaining and enqueues the new candidate take.

### 5.2 UI Touchpoints Across Macro ↔ Meso ↔ Micro
1. **Top Bar & Macro Toolbar (`SheetWorkspace.jsx` & `StoryWorkbenchModals.jsx`)**:
   - **Resource Mode Selector Pill**:
     - `🟢 Lab (Open-Weights $0)` | `🟡 Hybrid Smart (Closed Hero + Open B-Roll)` | `🔴 Deadline Rush (Cloud Burst)`
   - **Contest Policy Lock Toggle**:
     - `🔒 Open-Weights Only (Contest Mode)` vs `⚡ Hybrid Studio (Pro Mode)`
   - **Allocation Preflight Preview**: Before running batch shot generation, displays how many shots will run on Local RTX 4090 (`open_weights`) vs Closed-Source Hero APIs (`closed_hero`).
2. **Meso Storyboard Cards (`SheetCards.jsx`)**:
   - Displays a compact badge on each shot card showing its complexity & assigned engine tier:
     - e.g., `HERO · Seedance 2.0` (amber badge) vs `B-ROLL · LTX-2.5 Local` (cyan badge) vs `STRUCT · H3 Local` (emerald badge).
3. **Micro Shot Review (`SheetReview.jsx`)**:
   - When a shot's status is `Retake` or `Pending Review`, displays the **Smart Escalation Bar**:
     - `[⬆ Escalate to Closed Hero (Seedance / Kling)]`
     - `[🦴 Add Open-Weights Structure Lock (line-worlds + Multi-Step)]`
     - `[✨ Send Take to Local 4K Optimize (@source ➔ h3-optimize)]`

---

## 6. Verification & Unit Tests (`tests/test_studio_modular_and_router.py`)

Create `tests/test_studio_modular_and_router.py` covering:
1. **`test_limb_worker_backward_compat_exports`**:
   - Verifies that `project_assistant/limb_worker.py` is under 350 lines and that all symbols previously tested in `tests/test_studio_worker.py` (`load_studio_card`, `resolve_studio_context`, `compile_h3_context_ir`, `render_line_worlds_structure`, `openapi_run_ai_app`, etc.) remain importable from both `project_assistant.limb_worker` and `project_assistant.studio`.
2. **`test_shot_complexity_triage`**:
   - Verifies that an atmospheric empty set shot (`@SET-01`) scores as `"b_roll"`, a single-character dialogue shot scores as `"standard"`, and a multi-character fight/emotional close-up (`@CAST-01 @CAST-02`) or a shot with `retake_count >= 1` scores as `"hero"`.
3. **`test_budget_mode_and_contest_policy_routing`**:
   - Verifies `"lab_economical"` routes 100% of shots to `"open_weights"`.
   - Verifies `"hybrid_balanced"` routes `"b_roll"` to `"open_weights"` and `"hero"` to `"closed_hero"`.
   - Verifies `production_policy="open_weights_only"` strictly overrides any closed card back to `"open_weights"` (`LTX-2.5` / `FLUX` / `H3 Local`).
4. **`test_retake_escalation_and_closed_to_open_4k_handoff`**:
   - Verifies escalating a failed open-weights shot switches it to `seedance-20-pro` (or `open_structural_lock`), and verifies chaining a closed-source output into `h3-optimize` via `@source`.
5. **Full Regression Suite**:
   ```powershell
   python -m unittest tests.test_studio_worker tests.test_studio_modular_and_router -v
   npm test --prefix ui
   npm run build --prefix ui
   ```
