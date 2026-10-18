# SPEC 03 — Flexible Reference Pack Preparation & External ComfyUI JSON Slot Binder

**Parent Index**: [`docs/ZEROFIELD_SPEC.md`](../ZEROFIELD_SPEC.md)  
**Order of Execution**: **Step 2B (Backend Reference Prep & Comfy Runner)** — Pure Python + external workflow configs. Zero file overlap with `SPEC_02` (Frontend UI); can run in parallel with `SPEC_02`.  
**Owned Files**:
- `project_assistant/limb_worker.py`
- `workflows/*.json` (external ComfyUI API JSON templates mounted by config)
- `tests/test_studio_worker.py` (new unit test file)

---

## 1. Core Architectural Principle: Separate Reference Asset Prep from External ComfyUI JSONs

1. **External ComfyUI JSONs Are Treated as Black-Box / Configurable Graphs**:
   - In real production, ComfyUI workflows are authored externally in ComfyUI and handed to ZeroField as JSON files to manage and schedule.
   - ZeroField **must not hardcode ComfyUI internal node structures**. Instead, ZeroField provides a **Universal JSON Slot Binder (`input_bindings`)** that maps prepared project reference assets into whatever `(node_id, input_name)` slots an external JSON expects.

2. **ZeroField's Core Value Is Preparing & Managing the "Flexible Reference Pack" (靈活的參考與控制素材包)**:
   - Motion transfer, character swap, and multi-shot continuity fail when a user only sends a raw text prompt. They succeed when the workflow receives **aligned reference & conditioning assets**:
     1. **`source_video` (原始驅動影片)**: The live-action driving clip (`.mp4` / `.webm`).
     2. **`first_frame` (原片第一幀圖片)**: Extracted frame 0 (or target timestamp frame) from `source_video` as a lossless PNG image asset, used as the structural/pose anchor for swapping the character in the first frame.
     3. **`motion_structure_video` (連續動作結構素材)**: A continuous motion/structure conditioning video derived from `source_video` (e.g., continuous edge/lineart contour video, depth/luminance structure video, temporal motion-diff video, or mask sequence) that guides the video model frame-by-frame.
     4. **`anchor_keyframe` (定錨／換角首幀圖)**: The keyframe where `@CAST-01`'s identity/wardrobe has been applied onto `first_frame`'s pose and composition (inspectable and replaceable by the human director before running the heavy video workflow!).
     5. **`asset_images` (`@CAST-01`, `@SET-01`, `@PROP-01` 多來源參考圖組)**: Automatically resolved from the `soul-cast` / `assets` table whenever a row mentions `@CAST-01`, `@SET-01`, etc.
     6. **`compiled_prompt` & `seed`**: Structured Cinema Studio 4.0 prompt (`Optical Rig` + `Ordered Camera Motion` + `@Asset` descriptions + `Action Prompt`) and locked seed.

```text
┌────────────────────────────────────────────────────────────────────────────────────┐
│         REFERENCE PACK PREPARATION & EXTERNAL JSON BINDING ARCHITECTURE            │
├────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                    │
│  [Source Video (.mp4)]                                                             │
│     │                                                                              │
│     ├──► 1. Extract First Frame (`mode: "extract_frame"`)                          │
│     │       Produces `first_frame` (PNG asset in sheet cell, inspectable/editable) │
│     │                                                                              │
│     ├──► 2. Build Continuous Motion Structure (`mode: "motion_structure"`)         │
│     │       Produces `motion_structure_video` (MP4 conditioning asset in cell)     │
│     │                                                                              │
│     └──► 3. Combine with `@CAST-01 / @SET-01` (`resolve_studio_context`)           │
│             Produces `anchor_keyframe` (Swapped 1st Frame) + `Reference Pack`      │
│                                      │                                             │
│                                      ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│  │        UNIVERSAL EXTERNAL JSON SLOT BINDER (`bind_external_workflow`)        │  │
│  │  Maps Reference Pack keys (`anchor_keyframe`, `motion_structure_video`,      │  │
│  │  `first_frame`, `source_video`, `asset_images.0`, `compiled_prompt`, `seed`) │  │
│  │  into ANY external ComfyUI JSON's `(node_id, input_name)` slots!             │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Exact Implementation Requirements in `project_assistant/limb_worker.py`

### 2.1 Reference Media Preparation Modes in `ffmpeg()` (First Frame & Continuous Motion Structure)

Upgrade `ffmpeg(task, config, head)` (and helper functions) in `project_assistant/limb_worker.py` so the built-in media worker can prepare reference/conditioning assets from a row's `Source Video` without requiring manual external video editing:

1. **Mode A — `mode: "extract_frame"` (Extract First Frame / Reference Frame as PNG)**:
   - Triggered when `config.get("mode") == "extract_frame"` or `config.get("layout") == "extract_frame"`.
   - Finds the source video asset from `resolve_studio_context(task)["source_video"]` or `_media_urls(task.get("input", {}))`.
   - Uses `ffmpeg_binary(config)` to extract the frame at `timestamp_sec = float(config.get("timestamp_sec", 0.0))` (or frame 0 via `-ss {timestamp_sec} -i {src} -frames:v 1 -f image2 {out.png}`).
   - Uploads the resulting PNG via `head.upload(task, out.read_bytes(), "image/png", "first_frame.png")` and returns `{"text": asset["asset_url"], "asset_url": asset["asset_url"], "asset_id": asset["asset_id"], "reference_role": "first_frame"}`.

2. **Mode B — `mode: "motion_structure"` (Build Continuous Motion Structure Video)**:
   - Triggered when `config.get("mode") == "motion_structure"` or `config.get("layout") == "motion_structure"`.
   - Finds the source video asset from the row.
   - Generates a continuous **Motion & Structure Conditioning MP4** (`-c:v libx264 -pix_fmt yuv420p -movflags +faststart`, preserving original frame rate, duration, and audio track if present) using `structure_type = config.get("structure_type", "edge_lineart")`:
     - `"edge_lineart"` (default): applies FFmpeg filter `scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,edgedetect=low=0.08:high=0.25,format=yuv420p` to produce a clean continuous motion contour/lineart guide video.
     - `"luma_depth"`: applies `scale=...,pad=...,format=gray,eq=contrast=1.35:brightness=0.02,format=yuv420p` for a normalized structural luminance guide video.
     - `"frame_diff"`: applies `scale=...,pad=...,tblend=all_mode=difference128,format=yuv420p` for a temporal motion-trajectory guide video.
   - Uploads the resulting MP4 via `head.upload(task, out.read_bytes(), "video/mp4", "motion_structure.mp4")` and returns `{"text": asset["asset_url"], "asset_url": asset["asset_url"], "asset_id": asset["asset_id"], "reference_role": "motion_structure_video"}`.

3. **Mode C — `layout: "side_by_side"` (Split-Screen Comparison MP4)**:
   - Triggered when `config.get("layout") == "side_by_side"` or `config.get("mode") == "side_by_side"`.
   - Places two videos from the row (e.g., `Source Driving Video` and `Remastered Video`) side-by-side using `hstack` (`-c:v libx264 -pix_fmt yuv420p -movflags +faststart`).
   - **Important**: Keep the default `assemble_files()` concat behavior unchanged when `mode` / `layout` is not set, so all existing `tests/test_execution.py` tests pass!

---

### 2.2 Flexible Reference Pack Resolver: `resolve_studio_context(task: dict) -> dict`

Add `resolve_studio_context(task: dict) -> dict` in `project_assistant/limb_worker.py`:

1. **Inspect Active Row Columns by Semantic Role**:
   - Locate the active row in `task.get("input", {}).get("structured_rows", [])` (matching `task.get("row_id")` or index `0`) and its headers from `task.get("input", {}).get("tabs", [])`.
   - Identify cell values and media URLs in the active row by column header patterns (case-insensitive):
     - `source_video`: column matching `/source.*video|driving.*video|original.*video|原片/i`
     - `first_frame`: column matching `/first\s*frame|extracted\s*frame|source\s*frame|第一幀|首幀原圖/i`
     - `motion_structure_video`: column matching `/motion\s*structure|structure.*video|control.*video|pose|depth|動作結構/i`
     - `anchor_keyframe`: column matching `/anchor.*frame|swapped.*frame|keyframe|關鍵幀|首幀|定錨/i`
     - `output_video`: column matching `/cinema\s*shot|remastered.*video|output.*video|成品/i`
     - `optical_rig`: column matching `/optical|rig|camera.*lens|film\s*setup/i`
     - `camera_motion`: column matching `/camera\s*motion|movement|運鏡/i`
     - `jutsu_mode`: column matching `/jutsu\s*mode|mode/i`
     - `action_prompt`: column matching `/action.*prompt|swap\s*prompt|prompt|appearance/i`

2. **Cross-Tab `@Asset` Resolution (`soul-cast` / `assets`)**:
   - Scan all text cells in the active row for `@?\b((?:CAST|SET|LOC|PROP|CHAR|SCENE|STYLE)-\d+)\b` (case-insensitive, deduplicated in mention order).
   - Look up each ID in the `soul-cast` / `assets` table inside `task.get("input", {}).get("tabs", [])`.
   - Build:
     - `resolved_assets`: list of `{"asset_id": "CAST-01", "name": "Kael", "appearance_prompt": "...", "seed": 48291, "reference_urls": ["/projects/api/.../assets/pa_..."]}`
     - `asset_images`: flat list of all reference image URLs from `resolved_assets` in mention order
     - `asset_map`: dict keyed by `"CAST-01"`, etc.

3. **Fallbacks & Predecessor Task Outputs**:
   - Check `predecessor_tasks = task.get("input", {}).get("predecessor_tasks", [])` for any media URLs produced by upstream nodes in the same run (e.g., if an upstream node just extracted `first_frame`, `motion_structure_video`, or `anchor_keyframe`).
   - Compute:
     - `primary_image_url`: `anchor_keyframe` ➔ `first_frame` ➔ first image in `predecessor_tasks` ➔ `asset_images[0]` (if any).
     - `compiled_prompt`: deterministic concatenation of `Optical Rig` + `Camera Movement` + `Mode` + `References (@Asset prompts)` + `Action Prompt`.

4. **Return Standardized Reference Pack Dict**:
   ```python
   {
       "source_video": source_video_url,
       "source_video_url": source_video_url,          # alias
       "first_frame": first_frame_url,
       "motion_structure_video": motion_structure_url,
       "anchor_keyframe": anchor_keyframe_url,
       "primary_image_url": primary_image_url,
       "asset_images": asset_images,
       "reference_image_urls": asset_images,          # alias
       "asset_map": asset_map,
       "resolved_assets": resolved_assets,
       "compiled_prompt": compiled_prompt,
       "seed": resolved_seed,
       "optical_rig": optical_rig,
       "camera_motion": camera_motion,
       "jutsu_mode": jutsu_mode,
   }
   ```

---

### 2.3 Universal External JSON Slot Binder (`bind_external_workflow`) & `ComfyPlatformClient`

1. **`ComfyPlatformClient` (Comfy Router / SDK + Local ComfyUI)**:
   - Supports `platform: "comfy_router" | "comfy_sdk" | "local"`, `router_url` / `COMFY_ROUTER_URL`, and `COMFY_API_KEY` / Bearer auth headers in addition to local ComfyUI (`http://127.0.0.1:8188`).
   - Supports uploading both images (`image/*`) and videos (`video/mp4`, `video/webm`) via `upload_media(raw, mime, prefix)`.

2. **`bind_external_workflow(workflow: dict, ctx: dict, config: dict, task: dict, head, client) -> dict`**:
   - Works with **any external ComfyUI API JSON** without assuming fixed internal node types!
   - Reads `input_bindings = config.get("input_bindings", {})` (and automatically normalizes legacy keys `prompt_node`, `seed_node`, `image_node`, `reference_image_node`, `video_node`, `structure_video_node`, `first_frame_node`, `param_bindings` into bindings):
     - Each entry in `input_bindings` can be written in either direction so both human configs and UI configs work effortlessly:
       - **Format 1 (Source Key ➔ Target Slot)**:
         ```json
         "input_bindings": {
           "anchor_keyframe":        { "node": "2",  "input": "image", "upload": "image" },
           "first_frame":            { "node": "14", "input": "image", "upload": "image" },
           "motion_structure_video": { "node": "4",  "input": "video", "upload": "video" },
           "source_video":           { "node": "1",  "input": "video", "upload": "video" },
           "asset_images.0":         { "node": "15", "input": "image", "upload": "image" },
           "compiled_prompt":        { "node": "6",  "input": "text" },
           "seed":                   { "node": "3",  "input": "seed" }
         }
         ```
       - **Format 2 (Node.Input Path ➔ Source Key or Literal)**:
         ```json
         "param_bindings": {
           "6.text": "compiled_prompt",
           "3.seed": "seed",
           "10.frame_rate": 24
         }
         ```
     - **Dot-Path Resolution on `ctx`**:
       - `"asset_images.0"` resolves to `ctx["asset_images"][0]`.
       - `"asset_map.CAST-01.url"` resolves to `ctx["asset_map"]["CAST-01"]["url"]`.
     - **Automatic Media Upload**:
       - Whenever a bound value is an asset URL (`/projects/api/.../assets/pa_...`) or `upload` is `"image"` / `"video"` / `"auto"`, `bind_external_workflow` downloads `(raw, mime)` via `head.asset(task, url)`, validates MIME against `upload` if specified, calls `uploaded_name = client.upload_media(raw, mime)`, and assigns `workflow[str(node_id)]["inputs"][input_name] = uploaded_name`.
       - If `optional: true` is set on a binding and the source asset is not present in the row, skip cleanly without raising an error.

---

### 2.4 Default External Workflow Templates (`workflows/*.json`)

Provide 3 external ComfyUI API JSON templates in `workflows/` that demonstrate slot binding (`workflows/flux3_klein_soul_cast.json`, `workflows/ltx25_cinema_shot.json`, `workflows/ltx25_openjutsu_v2v.json`), where `ltx25_openjutsu_v2v.json` exposes clean input slots for:
- Node `"1"` (`source_video`)
- Node `"2"` (`anchor_keyframe` / `reference_image`)
- Node `"4"` (`motion_structure_video`)
- Node `"6"` (`compiled_prompt`)
- Node `"3"` (`seed`)
- Node `"12"` (`output_node`)

---

## 3. Verification & Acceptance Criteria

Run and verify:
```powershell
python -m unittest discover -s tests -v
```
In `tests/test_studio_worker.py`, test and verify:
1. **`ffmpeg()` Reference Prep Modes**:
   - `mode="extract_frame"` extracts a valid PNG (`image/png`) from a test MP4 video and uploads it.
   - `mode="motion_structure"` (`structure_type="edge_lineart"` and `"luma_depth"`) generates a valid H.264 MP4 (`video/mp4`) with `+faststart` from a test MP4 video.
   - `layout="side_by_side"` generates a valid split-screen MP4.
2. **`resolve_studio_context()` Reference Pack Assembly**:
   - Extracts `source_video`, `first_frame`, `motion_structure_video`, `anchor_keyframe`, and resolves `@CAST-01` / `@SET-01` from `soul-cast` into `asset_images` and `asset_map`.
3. **`bind_external_workflow()` & `comfyui()` Universal Slot Binding**:
   - Maps `anchor_keyframe`, `motion_structure_video`, `source_video`, `asset_images.0`, `compiled_prompt`, and `seed` into arbitrary `(node_id, input_name)` slots of an external JSON workflow and uploads media via `ComfyPlatformClient`.
   - Supports legacy `image_node`, `reference_image_node`, `video_node`, and `param_bindings` seamlessly.

---

## 4. Next-Stage Extension (`SPEC_05`)

For the **Dual-Engine Alignment Reference Prep (`MiniMax H3 Ref2VA + H3-Context-IR` & `LTX-2.5 IC-LoRA + Ingredients Sheet`) + `line-worlds` Procedural Motion Structure (`layout_silhouette`, `sparse_tracks`, `time_strata`)** upgrade on top of this baseline, see **[`docs/specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md`](./SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md)**.

