# SPEC 05 — Self-Hosted RunningHub Card Engine, Dual-Engine Alignment (`MiniMax H3` & `LTX-2.5 IC-LoRA`), Agent 8-Frame Pre-Compiler & `line-worlds` Motion Structure

**Parent Index**: [`docs/ZEROFIELD_SPEC.md`](../ZEROFIELD_SPEC.md)  
**Prerequisite Baseline**: [`docs/specs/SPEC_03_ASSET_BINDING_AND_COMFY_PLATFORM.md`](./SPEC_03_ASSET_BINDING_AND_COMFY_PLATFORM.md)  
**Reference Implementation Audited**: `C:\ai_project\ad_growth_data\custom_delivery_dashboard\art_bench` (`runninghub_app.py`, `h3.py`, `h3_prompt.py`, `slot_plan.py`, `payload.py`, `config/art_bench_cards/*.json`) & `C:\Users\synvoke\Downloads\Guardian\prototypes\line-worlds` (`art-api.mjs`)  
**Order of Execution**: **Step 4 (Self-Hosted RunningHub Card Layer + Dual-Engine Reference Prep + `line-worlds` Structure Engine)**  
**Owned Files**:
- `project_assistant/limb_worker.py`
- `workflows/cards/*.json` (declarative RunningHub-style Studio Cards for `h3-reference`, `h3-optimize`, `ltx25-openjutsu`, `ltx25-cinema`, `flux-soul-cast`)
- `workflows/minimax_h3_ref2va.json`, `workflows/ltx25_openjutsu_v2v.json`, `workflows/ltx25_cinema_shot.json`
- `workflows/README.md`
- `tests/test_studio_worker.py`
- `ui/src/FlowPanels.jsx`, `ui/src/SheetReview.jsx` (optional Card-driven parameter controls & 8-frame contact sheet preview)

---

## 1. Executive Summary: Why Build a Self-Hosted RunningHub Card Layer Inside `ZeroField`?

### 1.1 Reverse-Engineering RunningHub + `art_bench`
A raw ComfyUI API workflow (`workflow.json`) contains 100–200 internal nodes (`VAELoader`, `CLIPLoader`, `ComfyMathExpression`, `ResolutionSelector`, `BasicGuider`, `VAEDecodeAudio`, `CreateVideo`). Exposing raw node graphs directly to humans or AI agents creates five severe failure modes that RunningHub + `ad_growth_data/art_bench` solved through a layered architecture:

1. **Declarative Card Contract (`Card JSON` ➔ `nodeInfoList`)**:
   - Instead of mutating 150 raw nodes, a workflow is wrapped in a **Studio Card (`workflows/cards/*.json`)** that exposes only **6–10 typed semantic fields** (`nodeId`, `fieldName`, `fieldType`, `slot`, `min/max`, `options`, `projectDefaults`) while locking internal engineering nodes (`252.megapixels = "1.0"`, `283.value = "2.0"`, unused audio slots = `"None"`).
   - Execution compiles form/row values into a flat, engine-agnostic override array:
     ```json
     {
       "nodeInfoList": [
         {"nodeId": "27",  "fieldName": "video",        "fieldValue": "source_video.mp4"},
         {"nodeId": "51",  "fieldName": "image",        "fieldValue": "ingredients_sheet.png"},
         {"nodeId": "49",  "fieldName": "image",        "fieldValue": "cast_kael.png"},
         {"nodeId": "50",  "fieldName": "image",        "fieldValue": "None"},
         {"nodeId": "263", "fieldName": "text",         "fieldValue": "..."},
         {"nodeId": "259", "fieldName": "value",        "fieldValue": "5"},
         {"nodeId": "252", "fieldName": "aspect_ratio", "fieldValue": "16:9 (Widescreen)"}
       ]
     }
     ```
   - **Tri-Modal Execution Portability**: The exact same `Card + nodeInfoList` payload can be executed against:
     - **Local Self-Hosted ComfyUI Server API** (`http://127.0.0.1:8188`)
     - **Official Comfy SDK / Comfy Cloud API v2** (`COMFY_BASE_URL` + Bearer Token)
     - **RunningHub WebApp API / Media Bridge** (`webappId` + `/openapi/v2/media/upload/binary`)

2. **Safe Graph Injection (`"None"` Empty-Slot Unlinking & `disabled_loras` Zeroing)**:
   - In ComfyUI, passing `"None"` or `""` to an optional `LoadImage` / `LoadAudio` node crashes the graph with `FileNotFoundError`, and passing `lora_name = "none"` to `LoraLoader` crashes model loading.
   - Our reverse-engineered injector (`inject_node_info_into_workflow`) automatically:
     - Replaces `lora_name = "none"` with the first valid `.safetensors` option while setting `strength_model = 0.0` on the same `nodeId`.
     - Disconnects downstream input links (or removes optional `ref_images.ref_image_k` / `ref_audios.ref_audio_k` entries) whenever an optional media slot is `"None"` or empty.

3. **Smart `@Asset` Slot Planning & Forbidden-Asset Guard (`slot_plan`)**:
   - Shots often reference more `@Asset` items than a card has image slots, or include text-only props without images.
   - `slot_plan()` automatically filters out `excluded_refs` (forbidden assets for that shot), selects only assets that have actual images (`pictured`), sorts them by `(anchor_priority, appear_count, cast_order)`, fills `slot: "ref"` nodes up to `MAX_MATERIALS = 5`, and pads remaining slots with `"None"`.

4. **Agent Visual Pre-Compiler (`frame_sheet` 8-Frame Timestamped Contact Sheet + `H3-Context-IR` / `Ingredients Sheet`)**:
   - Agents cannot reliably inspect raw multi-megabyte `.mp4` files, and local `MiniMax H3` lacks MiniMax's proprietary cloud `H3-Context-IR` preprocessor.
   - ZeroField automatically extracts an **8-frame timestamped contact sheet (`motion-frames.jpg`, `1600x600`, labeled `VIDEO 1 / 0.312s ...`)** via FFmpeg, pairs it with compressed `@Asset` reference images ($\le 1600\text{px}$) and/or `line-worlds` `time_strata.png`, and compiles both:
     - **Role-Separated Agent Prompt + Fixed Project Style (`projectDefaults`)** locked by a SHA-256 **Input Fingerprint (`fingerprint`)**.
     - **Local Open-Source `H3-Context-IR` 6-Section Prompt** (for `MiniMax H3 Ref2VA`) and **Horizontal `Ingredients Reference Sheet` (`ingredients_sheet.png`) + Spatial Panel Prompt** (for `LTX-2.5 Ingredients IC-LoRA`).

5. **Post-Render Duration Bounding (`.bounded.mp4`), Two-Pass `@source` Restoration (`h3-reference` ➔ `h3-optimize`), & Paid-Task Safety**:
   - Both `MiniMax H3` (`17n + 5` frames) and `LTX-2.5` (`8n + 1` frames) pad frame counts upward inside the workflow graph (e.g. a `4.0s` request at `24fps` yields `107` frames = `4.458s`).
   - ZeroField automatically trims the returned video back to `min(requested_seconds, source_video_seconds)` using frame-accurate H.264 CRF 16 + `-movflags +faststart` (`.bounded.mp4`), filters out incidental `.zip` archive outputs (`NON_TAKE_KINDS = {"archive"}`), never auto-retries task creation, and supports 1-click `@source` chaining into Pass 2 (`h3-optimize`).

---

## 2. Complete System Architecture

```text
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│            ZEROFIELD SELF-HOSTED RUNNINGHUB CARD & DUAL-ENGINE PIPELINE                    │
├────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                            │
│  [Production Sheet Row / Shot Inspector (`cinema-studio` or `openjutsu-lab`)]              │
│   • Mentions: `@CAST-01`, `@PROP-01`, `@SET-01` (and optional `excluded_refs: !-@CAST-02`) │
│   • Media Cells: `Source Video`, `First Frame`, `Motion Structure`, `Anchor Keyframe`      │
│   • Controls: `Card ID`, `Duration (1..15s)`, `Aspect Ratio`, `Rig`, `Camera Motion`       │
│                                           │                                                │
│                                           ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ LAYER 1: PRE-EXECUTION REFERENCE & STRUCTURE PREPARATION (`prepare_reference_media`) │  │
│  │  • `snap_dimensions(w, h, grid_size=32)` & `snap_frame_count(n, "8n+1" | "17n+5")`   │  │
│  │  • `mode="extract_frame"`     ➔ `first_frame.png` (32px-aligned Opening Still)       │  │
│  │  • `mode="ingredients_sheet"` ➔ `ingredients_sheet.png` (horizontal @Asset composite)│  │
│  │  • `mode="motion_structure"`  ➔                                                      │  │
│  │      - Path A (Source Video): `ref05_edge` / `ref05_depth` (0.5x de-textured MP4)    │  │
│  │      - Path B (`line-worlds` 2-Link IK + Knobs `stride/turn/reach/flare/zoom`):      │  │
│  │        `layout_silhouette.mp4` | `sparse_tracks.mp4` | `time_strata.png` (Onion-Skin)│  │
│  │  • `mode="frame_sheet"`       ➔ `motion_frames.jpg` (8-frame timestamped sheet)      │  │
│  └────────────────────────────────────────┬─────────────────────────────────────────────┘  │
│                                           ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ LAYER 2: AGENT VISUAL PRE-COMPILER & SLOT PLANNER (`resolve_studio_context`)         │  │
│  │  • `slot_plan()`: Allocates pictured @Assets to Card `slot="ref"` nodes (max 5 + 1), │  │
│  │    enforces `excluded_refs`, sets missing/text-only slots to `"None"`                │  │
│  │  • `compile_h3_context_ir()`: Builds 6-section MiniMax H3 prompt with `<Subject N>`, │  │
│  │    `<Picture N>`, `<Video 1>`, `<Audio 1>`, `retention_analysis`, `<d>[English]...</d>`│
│  │  • `ltx_ingredients_prompt`: Appends `[Left panel: ...] [Center: ...] [Right: ...]`  │  │
│  │  • `compute_request_fingerprint()`: SHA-256 lock over `(video, refs, sec, ratio)`    │  │
│  └────────────────────────────────────────┬─────────────────────────────────────────────┘  │
│                                           ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ LAYER 3: RUNNINGHUB-STYLE CARD COMPILER (`build_node_info` + `inject_node_info`)     │  │
│  │  • Compiles `nodeInfoList: [{nodeId, fieldName, fieldValue}]` from Card contract     │  │
│  │  • Enforces `locked_nodes` (`252.megapixels=1.0`, `283.value=2.0`, unused audio)     │  │
│  │  • Applies `disabled_loras` (`lora_name="none"` ➔ valid filename + `strength=0`)     │  │
│  │  • Unlinks `"None"` optional media slots when injecting into local/SDK `workflow.json`│  │
│  └──────────────────┬─────────────────────────────┬──────────────────────────┬──────────┘  │
│                     ▼                             ▼                          ▼             │
│        [Local ComfyUI Server API]      [Official Comfy SDK v2]    [RunningHub / Bridge]    │
│          (`127.0.0.1:8188`)              (`COMFY_BASE_URL`)         (`webappId` runner)    │
│                     └─────────────────────────────┼──────────────────────────┘             │
│                                                   ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ LAYER 4: POST-PROCESSOR & 2-STAGE `@source` HANDOFF (`bound_output_video_duration`)  │  │
│  │  • Filters out `NON_TAKE_KINDS = {"archive"}` (`.zip` side-outputs)                  │  │
│  │  • Trims `17n+5` / `8n+1` tail overrun back to `min(requested_sec, source_sec)`      │  │
│  │    as `.bounded.mp4` (H.264 CRF 16 + `-movflags +faststart`, audio preserved)        │  │
│  │  • Supports `@source` 1-click handoff from Pass 1 (`h3-reference`) ➔ Pass 2          │  │
│  │    (`h3-optimize` 4K restoration & de-flicker)                                       │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Declarative Studio Card Specification (`workflows/cards/*.json`)

### 3.1 Card JSON Contract
Create `workflows/cards/` with 4 built-in cards that work out-of-the-box with both local/SDK ComfyUI (`workflow`) and RunningHub/Bridge (`webappId`):

1. **`workflows/cards/h3-reference.json` (`MiniMax H3 Ref2VA` — Pass 1 Reference Video Generation)**:
   ```json
   {
     "card_id": "h3-reference",
     "label": "① H3 Reference Video Generation",
     "sublabel": "Source Video · Multi-Ref Character & Scene (MiniMax H3 Ref2VA)",
     "group_label": "Video",
     "icon": "▷",
     "output_mode": "video",
     "engine_key": "comfy-webapp/1",
     "engine_config": {
       "workflow": "workflows/minimax_h3_ref2va.json",
       "webappId": "2103540145878601730",
       "instance": "default",
       "frame_rule": "17n+5",
       "grid_size": 32,
       "timeout": 3600,
       "locked_nodes": {
         "252.megapixels": "1.0",
         "283.value": "2.0",
         "48.audio": "None",
         "14.audio": "None",
         "15.audio": "None"
       }
     },
     "nodes": [
       {"nodeId": "27",  "fieldName": "video",        "fieldType": "VIDEO",  "label": "Source Reference Video",   "required": true,  "slot": "driving_video", "defaultValue": "None"},
       {"nodeId": "51",  "fieldName": "image",        "fieldType": "IMAGE",  "label": "Character & Scene Sheet",  "required": true,  "slot": "ref",           "defaultValue": "None"},
       {"nodeId": "49",  "fieldName": "image",        "fieldType": "IMAGE",  "label": "Supplementary Ref 1",      "required": false, "slot": "ref",           "defaultValue": "None"},
       {"nodeId": "50",  "fieldName": "image",        "fieldType": "IMAGE",  "label": "Supplementary Ref 2",      "required": false, "slot": "ref",           "defaultValue": "None"},
       {"nodeId": "43",  "fieldName": "image",        "fieldType": "IMAGE",  "label": "Supplementary Ref 3",      "required": false, "slot": "ref",           "defaultValue": "None"},
       {"nodeId": "19",  "fieldName": "image",        "fieldType": "IMAGE",  "label": "Supplementary Ref 4",      "required": false, "slot": "ref",           "defaultValue": "None"},
       {"nodeId": "23",  "fieldName": "image",        "fieldType": "IMAGE",  "label": "Supplementary Ref 5",      "required": false, "slot": "ref",           "defaultValue": "None"},
       {"nodeId": "48",  "fieldName": "audio",        "fieldType": "AUDIO",  "label": "Unused Audio 1",           "required": false, "hidden": true,          "defaultValue": "None"},
       {"nodeId": "14",  "fieldName": "audio",        "fieldType": "AUDIO",  "label": "Unused Audio 2",           "required": false, "hidden": true,          "defaultValue": "None"},
       {"nodeId": "15",  "fieldName": "audio",        "fieldType": "AUDIO",  "label": "Unused Audio 3",           "required": false, "hidden": true,          "defaultValue": "None"},
       {"nodeId": "263", "fieldName": "text",         "fieldType": "STRING", "label": "Generation Instruction",   "required": true,  "slot": "prompt",        "defaultValue": "Use the character identity and scene environment from the reference images, and transfer the physical motion, timing, and camera trajectory from Reference Video 1.", "projectDefaults": {"default": "Cinematic 35mm film photography, natural skin texture, coherent directional lighting, clean silhouette separation, zero temporal flicker."}},
       {"nodeId": "259", "fieldName": "value",        "fieldType": "FLOAT",  "label": "Duration (Seconds)",       "required": true,  "slot": "duration",      "defaultValue": "5", "min": 1, "max": 15, "step": 0.001},
       {"nodeId": "252", "fieldName": "aspect_ratio", "fieldType": "LIST",   "label": "Aspect Ratio",             "required": true,  "slot": "aspect_ratio",  "defaultValue": "16:9 (Widescreen)", "options": ["1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", "3:4 (Portrait Standard)", "4:3 (Standard)", "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)"]}
     ]
   }
   ```

2. **`workflows/cards/h3-optimize.json` (`MiniMax H3` — Pass 2 4K/2K Restoration & Temporal Stabilization)**:
   - Accepts `27.video` (`@source` or uploaded Pass 1 take) + single composite image `51.image` (`@source` or primary reference).
   - Forces supplementary image slots `49, 50, 43, 19, 23` to `hidden: true` and `"None"`.
   - Automatically locks `259.value` (duration) and `252.aspect_ratio` (`aspect_for(media, options)`) to match the Pass 1 video, and applies the verified restoration prompt (`4K video restoration and upscale, strictly preserve original composition, subject identity, facial features, expression, pose, lighting and scene...`).

3. **`workflows/cards/ltx25-openjutsu.json` (`LTX-2.5 IC-LoRA` — OpenJutsu Motion & Structure Transfer)**:
   - Maps `1.video` (`slot: "driving_video"`), `2.image` (`slot: "ref"` — `anchor_keyframe` / `ingredients_sheet`), `4.video` (`slot: "structure_video"` — `motion_structure_video`), `6.text` (`slot: "prompt"` — `ltx_ingredients_prompt`), `3.seed` (`slot: "seed"`), with `frame_rule: "8n+1"` and `grid_size: 32`.

4. **`workflows/cards/ltx25-cinema.json` (`LTX-2.5` — Storyboard Keyframe / Layout to Cinema Shot)**:
   - Maps `2.image` (`slot: "ref"` — `anchor_keyframe` or `ingredients_sheet`), optional `4.video` (`slot: "structure_video"` — `line-worlds` `layout_silhouette.mp4` or `sparse_tracks.mp4`), `6.text` (`slot: "prompt"`), `3.seed` (`slot: "seed"`), with `frame_rule: "8n+1"` and `grid_size: 32`.

---

## 4. Detailed Backend Implementation Specifications (`project_assistant/limb_worker.py`)

### 4.1 Card Loader, Validation & `nodeInfoList` Compiler

1. **`load_studio_card(card_id_or_path: str) -> dict` & `validate_studio_card(card: dict) -> dict`**:
   - Resolves `card_id_or_path` from `workflows/cards/{card_id}.json` or direct path.
   - Validates:
     - `fieldType in {"IMAGE", "AUDIO", "VIDEO", "STRING", "LIST", "INT", "FLOAT"}`
     - `LIST` nodes define non-empty `options` (and matching `optionLabels` length if present)
     - `INT` / `FLOAT` default values fall within `[min, max]` when specified
     - `slot in {None, "ref", "prompt", "driving_video", "structure_video", "duration", "aspect_ratio", "seed"}`
     - `output_mode in {"video", "image", "audio"}`

2. **`aspect_for(media: dict, options: list[str]) -> str`**:
   - Computes `ratio = float(media["width"]) / float(media["height"])`.
   - Parses `"W:H"` prefix from each option (e.g., `"16:9 (Widescreen)"` ➔ `16.0 / 9.0`) and returns `min(options, key=lambda opt: abs(math.log(ratio / (w / h))))`.

3. **`slot_plan(assets: list[dict], slot_count: int, *, limit: int = 5, excluded_ids: set[str] | None = None) -> list[dict | None]`**:
   - Filters `assets` (`resolved_assets` from `resolve_studio_context`):
     - Excludes any asset whose `asset_id` is in `excluded_ids` (`!-@CAST-02` or `Excluded Assets` column).
     - Keeps only assets that actually have at least one image URL (`bool(asset.get("reference_urls"))` and `not asset.get("offstage", False)`). Text-only props (`descriptive`) do **not** consume an image slot!
   - Sorts pictured assets by `(-int(asset.get("appear_count", 1)), int(asset.get("cast_order", 1_000_000)), original_index)`.
   - Takes up to `min(limit, slot_count)` assets and pads the remainder of `slot_count` with `None`.

4. **`build_node_info(card: dict, form_values: dict) -> list[dict]`**:
   - Implements the exact `art_bench/payload.py` contract:
     - For each node in `card["nodes"]`, key is `f"{node['nodeId']}.{node['fieldName']}"`.
     - `value = form_values.get(key); if value is None: value = node.get("defaultValue", "")` (strictly `is None`, never falsy `or`).
     - **`disabled_loras` rule**: If `node["fieldName"] == "lora_name"` and `str(value).lower() == "none"`, substitute the first non-`"none"` option from `node.get("options", ())` into `lora_name` and force `strength_model = "0"` on the same `nodeId`.
     - Appends any `locked_nodes` from `card.get("engine_config", {}).get("locked_nodes", {})` (overriding any external attempt to modify locked nodes).
     - Returns `[{"nodeId": str(nodeId), "fieldName": str(fieldName), "fieldValue": str(value), "description": None}, ...]`.

5. **`inject_node_info_into_workflow(workflow: dict, node_info_list: list[dict], card: dict, task: dict, head, client) -> dict`**:
   - Bridges the RunningHub `nodeInfoList` contract directly into any ComfyUI API `workflow.json`:
     - Maps each `{"nodeId", "fieldName", "fieldValue"}` to `workflow[nodeId]["inputs"][fieldName]`:
       - **When `fieldType in ("IMAGE", "VIDEO", "AUDIO")` and `fieldValue in ("", "None", None)`**:
         - If `nodeId` is a loader node (`LoadImage`, `VHS_LoadVideo`, `LoadAudio`), disconnects any downstream node inputs referencing `[nodeId, ...]` (e.g., removing `ref_images.ref_image_k` or `ref_audios.ref_audio_k` on `MiniMaxH3ReferenceToVideo`) and removes the unused loader node from the submitted graph so ComfyUI never fails on `"None"`.
       - **When `fieldType in ("IMAGE", "VIDEO", "AUDIO")` and `fieldValue` is a project asset URL (`/projects/api/.../assets/pa_...`)**:
         - Downloads bytes via `head.asset(task, fieldValue)`, uploads via `client.upload_media(raw, mime)`, and writes the returned filename into `workflow[nodeId]["inputs"][fieldName]`.
       - **When `fieldType in ("INT", "FLOAT", "STRING", "LIST")`**:
         - Coerces `fieldValue` to match the target input's native type in `workflow.json` (`int`, `float`, `bool`, or `str`).

---

### 4.2 Agent 8-Frame Contact Sheet (`frame_sheet`), Dual-Engine Prompt Compiler & Fingerprint Lock

1. **`build_video_frame_sheet(video_path: Path, duration: float, folder: Path, config: dict) -> tuple[Path, list[float]]`**:
   - Extracts 8 evenly spaced frames across `duration` using `ffmpeg_binary(config)`:
     ```python
     fps_expr = f"fps={8.0 / max(duration, 0.1):.9f},scale=400:280:force_original_aspect_ratio=decrease,pad=400:280:(ow-iw)/2:(oh-ih)/2:white"
     ```
   - Tiles the 8 frames into a `4x2` grid (`1600x600`, `motion-frames.jpg` / `motion-frames.png`) using FFmpeg `tile=4x2:margin=4:padding=4:color=white` (zero PIL dependency required; works with pure FFmpeg!), and calculates the 8 sample timestamps `[round((i + 0.5) * duration / 8.0, 3) for i in range(8)]`.
   - Also exposes `mode="frame_sheet"` in `prepare_reference_media(task, config, head, mode="frame_sheet")` so a workflow step or agent pre-pass can upload `motion_frames.png` (`reference_role="frame_sheet"`) directly to the project sheet!

2. **Role-Separated Agent Instruction & Fingerprint (`compute_request_fingerprint` & `compile_h3_agent_instruction_prompt`)**:
   - **`compute_request_fingerprint(project_slug: str, row_id: str, card_id: str, values: dict) -> str`**:
     - Hashes `[project_slug, row_id, card_id, {k: str(values.get(k, "None")) for k in sorted_media_and_timing_keys}]` with SHA-256.
   - **Role-Separated Prompt Contract**:
     - Enforces the battle-tested `art_bench/h3_prompt.py` rule:
       - **Image Assets (`圖片素材1..N` / `<Picture 1..N>`)** define character identity, face, wardrobe, props, art style, scene geometry, and lighting.
       - **Reference Video (`參考影片1` / `<Video 1>`)** defines ONLY motion timing, movement sequence, displacement direction, center-of-gravity shift, and camera movement — **never** inheriting source video blur, compression artifacts, or the original actor's identity.
   - **Local Open-Source `H3-Context-IR` 6-Section Prompt (`compile_h3_context_ir(ctx)`)**:
     - Automatically generates the 6 sections required by `MiniMax-H3` (`subject_definitions:`, `summary:`, `retention_analysis:`, `detailed_description:`, `overall_soundscape:`, `non_diegetic_music:`) with `<Subject N>`, `<Picture N>`, `<Video 1>`, `<Audio 1>`, and `<d>[English] ... </d>` dialogue tags.
   - **LTX-2.5 `Ingredients Reference Sheet` (`mode="ingredients_sheet"` + `ltx_ingredients_prompt`)**:
     - Horizontally stitches all pictured `@Asset` references into a single `32px`-aligned `ingredients_sheet.png` and appends spatial panel tags (`Reference Sheet Layout: [Left panel: ...] [Center panel: ...] [Right panel: ...]`).

---

### 4.3 Multi-Density Motion Structure & `line-worlds` Procedural Renderer (`prepare_reference_media`)

Supports both **Source-Video De-Textured Extraction (`ref0.5`)** and **`line-worlds` Procedural / Re-Rigged Structure Generation**:

1. **Spatial (`32px`) & Temporal (`8n+1` / `17n+5`) Spec Aligner**:
   - `snap_dimensions(width, height, grid_size=32)` rounds dimensions to exact multiples of `32px`.
   - `snap_frame_count(frames, frame_rule)` supports `"none"` (default passthrough), `"8n+1"` (LTX-2.5), and `"17n+5"` (MiniMax H3: `max(5, frames) + (5 - (max(5, frames) % 17)) % 17`).

2. **Path A — Source Video De-Textured `ref0.5` Modes (`ref05_edge`, `ref05_depth`)**:
   - Downsamples source video to `0.5x` resolution first + applies Gaussian smoothing (`gblur`) before extracting edges or luminance depth, washing out source actor clothing creases and facial pores before scaling back to the `32px`-snapped output size.

3. **Path B — `line-worlds` Articulated 2-Link IK & Trajectory Renderer (`layout_silhouette`, `sparse_tracks`, `time_strata`)**:
   - Ported from `line-worlds/art-api.mjs` into pure Python + FFmpeg (`render_lineworlds_media`), requiring **zero third-party pip packages**:
     - **With `Source Video` (Extract & Re-Rig)**: Samples coarse motion centroid trajectory `(cx[t], cy[t], scale[t])` from the source video, discards source pixels, and drives the articulated 2-link IK figure with target `@CAST` proportions (`flare` coat width, `stride`, `turn`, `reach`, `camera_zoom`).
     - **Without `Source Video` (Direct Storyboard Rehearsal)**: Synthesizes `t ∈ [0..1]` motion across `8n+1` or `17n+5` frames directly from the shot's `camera_motion`, `action_prompt`, and control knobs.
   - Produces 3 outputs:
     - `structure_type="layout_silhouette"` (`video/mp4`): 3-layer depth planes (`far` arch/horizon, `mid` stair/perspective floor, `near` flat-shaded IK silhouette + hand/gaze anchors) for **LTX-2.5 `Layout-To-Render IC-LoRA`**.
     - `structure_type="sparse_tracks"` (`video/mp4`): Dark background with decaying motion-trail ribbons and color-coded tracking beacons (`head`, `right_hand`, `left_hand`, `pelvis`, `camera`) for **LTX-2.5 `Motion Track IC-LoRA`**.
     - `mode="time_strata"` or `structure_type="time_strata"` (`image/png`, `reference_role="time_strata"`): Single-frame **Chronophotography / Onion-Skin Motion Sheet** (`t = 0.0, 0.25, 0.5, 0.75, 1.0` phase ghosts + trajectory arrows) for instant 0.1s human review in the table or `<Picture N>` storyboard conditioning in `MiniMax H3`!

---

### 4.4 Post-Render `.bounded.mp4` Trimmer, `@source` 2-Pass Chaining & Paid-Task Safety

1. **`bound_output_video_duration(raw_video_bytes: bytes, max_duration_sec: float, config: dict) -> bytes`**:
   - Probes the generated video via `_probe_video`.
   - If `rendered["duration"] <= max_duration_sec + (0.5 / rendered["fps"])`, returns `raw_video_bytes` untouched.
   - If `rendered["duration"] > max_duration_sec + (0.5 / rendered["fps"])` (caused by `17n+5` or `8n+1` upward frame padding in ComfyUI):
     - Computes `target_frames = max(1, int(math.floor(max_duration_sec * rendered["fps"] + 1e-6)))`.
     - Runs FFmpeg to write `.bounded.mp4` (`-frames:v {target_frames} -c:v libx264 -crf 16 -preset veryfast -pix_fmt yuv420p -c:a aac -movflags +faststart`), verifies the bounded output with `_probe_video`, and returns the bounded MP4 bytes!
   - Triggered automatically in `comfyui()` whenever `config.get("bound_to_source_duration", True)` and `max_duration_sec` (from `config.get("duration_sec")` and/or `source_video` duration) is known.

2. **Two-Pass `@source` Resolution (`resolve_pass2_source`)**:
   - When a task or card specifies `card_id == "h3-optimize"` or binds `@source`:
     - Automatically resolves `@source` video from the row's Pass 1 output (`output_video` / `Remastered Video` / `Cinema Shot` or predecessor video output) and `@source` image from `ingredients_sheet` / `anchor_keyframe` / `asset_images[0]`, locking duration and aspect ratio (`aspect_for`) to the Pass 1 video.

3. **Archive Filtering & Error Normalization**:
   - In `comfyui()`, ignores `.zip` / `.tar` / `.7z` side-outputs unless no media output exists (`NON_TAKE_KINDS = {".zip", ".tar", ".gz", ".7z"}`).
   - Normalizes ComfyUI / SDK / RunningHub `OutOfMemoryError` / `VRAM OOM` and `queue limit` errors into clear, actionable `WorkerError` messages.

---

## 5. Verification & Acceptance Criteria (`tests/test_studio_worker.py`)

Run and verify:
```powershell
python -m unittest discover -s tests -v
npm test --prefix ui
npm run build --prefix ui
```

In `tests/test_studio_worker.py`, verify all 7 acceptance suites:
1. **Declarative Studio Cards & `build_node_info` / `inject_node_info_into_workflow`**:
   - Validates all `workflows/cards/*.json` (`h3-reference`, `h3-optimize`, `ltx25-openjutsu`, `ltx25-cinema`).
   - Verifies `is None` vs `""` handling, `locked_nodes` enforcement (`252.megapixels = "1.0"`, `283.value = "2.0"`), `disabled_loras` (`lora_name="none"` ➔ valid `.safetensors` + `strength_model="0"`), and automatic unlinking of `"None"` optional image/audio nodes in `workflows/minimax_h3_ref2va.json`.
2. **Smart `@Asset` Slot Planner (`slot_plan`) & Forbidden Asset Guard (`excluded_refs`)**:
   - Verifies pictured assets rank ahead of text-only props, text-only props leave `"None"` in image slots without failing, and `excluded_refs` (`!-@CAST-02`) are strictly excluded.
3. **8-Frame Timestamped Contact Sheet (`mode="frame_sheet"`) & Fingerprint Lock (`compute_request_fingerprint`)**:
   - Verifies `mode="frame_sheet"` generates a valid `1600x600` 8-frame contact sheet from a test MP4 video and returns the 8 sample timestamps.
   - Verifies `compute_request_fingerprint` changes whenever reference images, driving video, duration, or aspect ratio change.
4. **Dual-Engine Multi-Asset & Context Compiler (`compile_h3_context_ir` & `mode="ingredients_sheet"`)**:
   - Verifies `h3_context_ir_prompt` contains all 6 mandatory sections (`subject_definitions:`, `summary:`, `retention_analysis:`, `detailed_description:`, `overall_soundscape:`, `non_diegetic_music:`) with `<Subject N>`, `<Picture N>`, `<Video 1>`, and `<d>[English] ... </d>`.
   - Verifies `mode="ingredients_sheet"` horizontally stitches multiple `@Asset` PNGs into a `32px`-aligned composite PNG (`reference_role="ingredients_sheet"`) and builds `ltx_ingredients_prompt`.
5. **Spec Aligner (`32px` Grid & `8n+1` / `17n+5` Frame Formulas)**:
   - Verifies `snap_dimensions` (`32px` multiple) and `snap_frame_count` (`8n+1` for LTX-2.5 and `17n+5` for MiniMax H3).
6. **Multi-Density Motion Structure (`ref05_edge`, `ref05_depth`) & `line-worlds` Procedural Renderer (`layout_silhouette`, `sparse_tracks`, `time_strata`)**:
   - Verifies `ref05_edge` and `ref05_depth` downsampled structure videos.
   - Verifies `line-worlds` `layout_silhouette` and `sparse_tracks` MP4 generation (both with a source video via Extract & Re-Rig and without a source video via Storyboard Rehearsal) plus `time_strata` single-frame Onion-Skin PNG generation.
7. **Post-Render `.bounded.mp4` Frame Trimming & Pass 2 `@source` Optimization (`h3-optimize`)**:
   - Verifies that an over-length `17n+5` padded video (e.g., `2.5s` returned for a `1.5s` source/request) is trimmed to `1.5s` (`36` frames @ 24fps) with `+faststart` and preserved audio track, and that `@source` binds Pass 1 output into `h3-optimize`.
