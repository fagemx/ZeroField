# ZeroField Studio — 4090 PC Development Handoff (`docs/HANDOFF_4090_PC.md`)

**Handoff Date**: 2026-10-18  
**Target Machine**: RTX 4090 Development PC (Local ComfyUI + GPU Inference & `SPEC_05` Implementation)  
**Main Repository**: `https://github.com/fagemx/ZeroField.git` (Branch: `main`)

---

## 1. Current Progress Summary (What Is Already Done & Verified in `main`)

`SPEC_01` through `SPEC_04` are **100% implemented, tested, built, and committed** (see [`docs/studio-verification.json`](./studio-verification.json)):

| Spec | Status | Summary of Completed Work |
| :--- | :---: | :--- |
| **[`SPEC_01`](./specs/SPEC_01_MEDIA_STREAMING_AND_VIDEO_PLAYER.md)** | ✅ Done | Zero-Blob `/meta` (`get_asset_meta`), `If-None-Match` (`304 Not Modified`), `META_CACHE`, inline `<video>` player (`MediaCell.jsx` hover-to-play & full controls, `ProposalRaceView.jsx` side-by-side video blind test). |
| **[`SPEC_02`](./specs/SPEC_02_MACRO_MESO_MICRO_WORKSPACE.md)** | ✅ Done | In-place **Macro (`Table`/`Board`) ↔ Meso (`Gallery` visual chain cards) ↔ Micro (`SheetReview` side-by-side inspector)** switching, `Studio Assistant` coexistence (never auto-closes `SheetReview`), `runInPlace` background execution, and `FlowSurface` pipeline manager. |
| **[`SPEC_03`](./specs/SPEC_03_ASSET_BINDING_AND_COMFY_PLATFORM.md)** | ✅ Done | `resolve_studio_context()`, `prepare_reference_media()` (`extract_frame`, `motion_structure` with `edge_lineart`/`luma_depth`/`frame_diff`, `side_by_side`), `bind_external_workflow()`, `ComfyPlatformClient` (`local` + `comfy_sdk`), and initial `workflows/*.json`. |
| **[`SPEC_04`](./specs/SPEC_04_SHOWCASE_SEED_AND_LAUNCHER.md)** | ✅ Done | One-command launcher `run_studio.py`, `seed_showcase_media()`, and pre-rendered CC0 showcase assets in `samples/`. |
| **[`SPEC_05`](./specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md)** | ✅ Done | Self-Hosted RunningHub `/openapi/v2` Card Engine (`workflows/cards/*.json`, `convert_litegraph_to_api`, `parse_runninghub_curl_or_payload`, `inject_node_info_into_workflow`), `H3-Context-IR`, `Ingredients Sheet`, `line-worlds`, and `.bounded.mp4` trimming. |
| **[`SPEC_06`](./specs/SPEC_06_RH_STORY_WORKBENCH_AND_MACRO_MESO_MICRO.md)** | 📋 **Next to Execute** | **Self-Hosted RH STORY AI Drama Workbench (`/aivideo/open/v1/*`) & Macro ↔ Meso ↔ Micro Integration** (see [`docs/references/runninghub-open-api-2026-10-18/`](./references/runninghub-open-api-2026-10-18/README.md)). |

---

## 2. Immediate Next Step on the 4090 PC: Implement `SPEC_05`

Read **[`docs/specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md`](./specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md)** first. It contains the complete, self-contained specification for:

1. **Self-Hosted RunningHub Card Engine (`workflows/cards/*.json` + `build_node_info` + `inject_node_info_into_workflow`)**:
   - Wraps 150-node ComfyUI workflows into 6–10 typed semantic fields (`h3-reference.json`, `h3-optimize.json`, `ltx25-openjutsu.json`, `ltx25-cinema.json`).
   - Enforces `is None` fallback (never falsy `or`), `locked_nodes` (`252.megapixels = "1.0"`, `283.value = "2.0"`, unused audio = `"None"`), `disabled_loras` (`lora_name="none"` ➔ valid `.safetensors` filename + `strength_model="0"`), and automatic unlinking of `"None"` optional media slots when injecting into local/SDK ComfyUI graphs.
2. **Smart `@Asset` Slot Planner (`slot_plan`) & Agent 8-Frame Timestamped Contact Sheet (`mode="frame_sheet"`)**:
   - `slot_plan()` assigns pictured `@Asset` items by `(anchor_priority, appear_count, cast_order)` into `slot="ref"` nodes (up to 5 + 1 slots), leaves text-only props as `"None"`, and blocks `excluded_refs`.
   - `mode="frame_sheet"` extracts 8 evenly spaced frames into a `1600x600` timestamped contact sheet (`motion_frames.png`, `VIDEO 1 / 0.312s ...`) for the agent pre-compiler, locked by a SHA-256 input `fingerprint`.
3. **Dual-Engine Alignment (`32px` Grid + `8n+1` / `17n+5` Frame Formulas + `H3-Context-IR` + `Ingredients Sheet`)**:
   - Local open-source **`H3-Context-IR` 6-section structured prompt compiler** (`compile_h3_context_ir`) for `MiniMax H3 Ref2VA`.
   - **`mode="ingredients_sheet"`** horizontal multi-asset stitcher + spatial prompt (`[Left panel: ...] [Center: ...] [Right: ...]`) for `LTX-2.5 Ingredients IC-LoRA`.
4. **Multi-Density Motion Structure (`ref05_edge`, `ref05_depth`) & `line-worlds` Procedural Rig/Trajectory Renderer (`layout_silhouette`, `sparse_tracks`, `time_strata`)**:
   - Works both **with** a source video (Extract & Re-Rig) and **without** a source video (Storyboard Rehearsal) using 2-link IK (`solve_ik`) and 4 honest control knobs (`stride`, `turn`, `reach`, `flare`, plus `camera_zoom`).
5. **Post-Render `.bounded.mp4` Frame Trimmer & Two-Pass `@source` Chaining (`h3-reference` ➔ `h3-optimize`)**:
   - Automatically trims `17n+5` / `8n+1` upward frame padding back to `min(requested_sec, source_sec)` using H.264 CRF 16 + `-movflags +faststart`, and supports `@source` 1-click handoff into Pass 2 restoration.

---

## 3. Referenced Repositories & External Links (For the 4090 PC)

> **Note**: [`docs/specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md`](./specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md) is written to be **100% self-contained**, so you can implement `SPEC_05` directly inside `ZeroField` even without cloning the sibling repositories below. However, if you or the coding agent want to inspect the original reference implementations on the 4090 PC, here are the exact repositories, git remotes, commits, and file paths:

### 3.1 Internal Sibling Repositories (GitHub `fagemx/*`)

| Repo Name | GitHub Remote URL | Reference Commit | Original Local Path (Source PC) | Key Files to Reference |
| :--- | :--- | :---: | :--- | :--- |
| **`ZeroField`** *(This Repo)* | `https://github.com/fagemx/ZeroField.git` | `main` (HEAD) | `C:\ai_project\ZeroField` | • `AGENTS.md`<br>• `docs/ZEROFIELD_SPEC.md`<br>• `docs/specs/SPEC_05_DUAL_ENGINE_ALIGNMENT_AND_LINEWORLDS.md`<br>• `project_assistant/limb_worker.py` |
| **`ad_growth_data`** *(RunningHub + ArtBench H3 Reference)* | `https://github.com/fagemx/ad_growth_data.git` | `e8714778` (`main`) | `C:\ai_project\ad_growth_data` | • `custom_delivery_dashboard/art_bench/engines/runninghub_app.py` (RunningHub WebApp runner, `nodeInfoList`, paid-task safety, OOM parsing)<br>• `custom_delivery_dashboard/art_bench/engines/query_receipt.mjs`<br>• `custom_delivery_dashboard/art_bench/payload.py` (`build_node_info`, `is None` fallback, `disabled_loras` zeroing)<br>• `custom_delivery_dashboard/art_bench/slot_plan.py` (`slot_plan` pictured-first ranking)<br>• `custom_delivery_dashboard/art_bench/h3.py` (`prepare_fields`, `aspect_for`, `@source` 2-pass restoration, `1..15s` validation)<br>• `custom_delivery_dashboard/art_bench/h3_prompt.py` (`frame_sheet` 8-frame timestamped `1600x600` sheet, `fingerprint` SHA-256 lock)<br>• `custom_delivery_dashboard/config/art_bench_cards/h3-reference.json`, `h3-optimize.json`, `multiref-video.json`, `image-to-video-g.json`<br>• `docs/ARTBENCH_H3_WORKFLOW.md` (`.bounded.mp4` trimming for `17n+5` overrun)<br>• `docs/superpowers/specs/2026-09-03-art-generation-bench-design.md` |
| **`guardian`** *(`line-worlds` Rigged Motifs & IK Reference)* | `https://github.com/fagemx/guardian.git` | `52c1db3` (`main`) | `C:\Users\synvoke\Downloads\Guardian\prototypes\line-worlds` | • `prototypes/line-worlds/art-api.mjs` (`solveIK` 2-link IK, `rig.figure`, `rig.face`, `rig.hand`, `rig.arch`, `rig.stair`, `curve`/`taper`/`ribbon`, `near/mid/far` depth layers)<br>• `prototypes/line-worlds/examples.mjs` (`time-strata` chronophotography onion-skin diagram, `stage-blocking`, `ik-figure`)<br>• `prototypes/line-worlds/concept-desk.mjs` & `core.mjs` (4-stage Extract ➔ Motifs & Anchors ➔ Fuse ➔ Render with `controls` knobs) |

### 3.2 Official ComfyUI & Open-Weights Model Repositories (For 4090 Local ComfyUI Testing)

1. **ComfyUI Official Workflow Templates (`Comfy-Org/workflow_templates`)**:
   - Repo: `https://github.com/Comfy-Org/workflow_templates`
   - MiniMax H3 Reference-to-Video (`Ref2VA`): `templates/video_minimax_h3_r2v.json` (uses `MiniMaxH3ReferenceToVideo`, `17n+5` frame expression `max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17`, `VAEDecode` + `VAEDecodeAudio` + `CreateVideo`)
   - MiniMax H3 Fun ControlNet Union 2.0: `templates/video_minimax_h3_fun_controlnet_union.json` (uses `MiniMaxH3FunControlNetApply` + `ModelPatchLoader`)
   - MiniMax H3 Multi-Frame Timeline Guide: `templates/video_minimax_h3_multiframe_reference.json` (uses `MiniMaxH3AddGuide`)

2. **MiniMax H3 Quantized Weights for RTX 4090 (`Comfy-Org/MiniMax-H3` & `MiniMaxAI/MiniMax-H3`)**:
   - ComfyUI Packaged Quantized Weights (fits 24GB RTX 4090 with offloading): `https://huggingface.co/Comfy-Org/MiniMax-H3`
     - `diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors` (19.53 GB)
     - `text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` (14.61 GB)
     - `vae/minimax_h3_video_vae_int8_convrot.safetensors` (2.62 GB) & `vae/minimax_h3_audio_vae_fp32.safetensors` (577 MB)
     - `model_patches/minimax_h3_fun_controlnet_union_2.0_pruned_int8_convrot.safetensors`
     - `loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`
   - Official `H3-Context-IR` 6-Section Prompt Specification: `https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md`

3. **LTX-2.5 Open-Weights & IC-LoRA Family (`Lightricks/LTX-2.5` & `Lightricks/ComfyUI-LTXVideo`)**:
   - Workflows: `https://github.com/Lightricks/ComfyUI-LTXVideo/tree/master/example_workflows/2.5`
   - Base Model: `https://huggingface.co/Lightricks/LTX-2.5`
   - IC-LoRAs:
     - `https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Ingredients` (Multi-asset horizontal Reference Sheet conditioning)
     - `https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render` (Flat silhouette / layout blocking ➔ photoreal video)
     - `https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen` & `Union Control (ref0.5)` / `Motion Track`

---

## 4. Quick-Start Commands on the 4090 PC

```powershell
# 1. Clone or pull latest main on the 4090 PC
git clone https://github.com/fagemx/ZeroField.git
cd ZeroField
git pull origin main

# 2. (Optional) Clone sibling reference repos if you want to inspect original files
git clone https://github.com/fagemx/ad_growth_data.git ..\ad_growth_data
git clone https://github.com/fagemx/guardian.git ..\guardian

# 3. Install Python & UI dependencies
pip install -e ".[dev,comfy]"
npm install --prefix ui
npm run build --prefix ui

# 4. Run unit tests & launch ZeroField Studio
python -m unittest tests.test_studio_worker tests.test_media_streaming tests.test_run_studio tests.test_zerofield_baseline -v
npm test --prefix ui
python run_studio.py
```

### Prompt for the Next Coding Agent (`SPEC_06`)
When you open the next coding agent session, simply tell it:
> **"Read `AGENTS.md`, `docs/HANDOFF_4090_PC.md`, and `docs/specs/SPEC_06_RH_STORY_WORKBENCH_AND_MACRO_MESO_MICRO.md`, then implement `SPEC_06` and verify all backend and frontend unit tests."**
