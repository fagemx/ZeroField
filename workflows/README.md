# ZeroField open-weights workflows

These are API-format graphs derived from official ComfyUI model templates and current node schemas, checked on 2026-10-18. JSON/link validation and mocked transports pass locally; GPU inference is **not verified** on this workstation. Install matching models and nodes before rendering. Output quality, memory use and identity fidelity still require an actual render review.

- [FLUX 3 Klein guide](https://docs.comfy.org/tutorials/flux/flux-3-klein), [official template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_flux3_klein_t2i.json): ComfyUI 0.41.1+; models/diffusion_models/flux3-image-klein-base-int8-convrot.safetensors; models/text_encoders/qwen3vl_4b_int8_convrot.safetensors; models/vae/flux2-vae.safetensors. Download from [BFL](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy), review its FLUX Kommunity License. Uses separate UNET/CLIP/VAE loaders and EmptyFlux2LatentImage, rather than a fictitious flux3_klein_5.6b checkpoint. Prompt upsampling is disabled.
- [LTX 2.5 guide](https://docs.comfy.org/tutorials/video/ltx/ltx-2-5), [official I2V template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_ltx2_5_i2v.json): latest compatible ComfyUI; models/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors; models/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors; models/vae/ltx-2.5-video-vae-bf16.safetensors and ltx-2.5-audio-vae-bf16.safetensors. Accept [Lightricks model access/license](https://huggingface.co/Lightricks/LTX-2.5) first. The compact graphs omit the official two-pass upscaler; LTX latents use 1280x704, 97 frames at 24 fps, with an 8-step first-pass sampler. Tune against the official template after validating on your GPU.
- OpenJutsu additionally requires [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite). Its VHS_LoadVideo caps and normalizes driving frames to the LTXV format (8n+1 frames, at most 97). The graph encodes the source video, denoises its latent at 0.72, and uses LTXVAddGuide for the selected character reference. This is source-guided video restyling; it does not implement SAM2 segmentation, depth masks, a guaranteed face swap, or a dedicated motion-transfer model. Source audio passes through unchanged. Mode/optics/movement are compiled prompt instructions; they are not separate physics controls.

Model files (take bundles list each model a graph loads with its source from this table):

| File | ComfyUI folder | Source |
| --- | --- | --- |
| flux3-image-klein-base-int8-convrot.safetensors | diffusion_models | [black-forest-labs/flux-3-image-klein-comfy](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy) |
| qwen3vl_4b_int8_convrot.safetensors | text_encoders | [black-forest-labs/flux-3-image-klein-comfy](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy) |
| flux2-vae.safetensors | vae | [black-forest-labs/flux-3-image-klein-comfy](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy) |
| ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors | diffusion_models | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) |
| gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors | text_encoders | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) |
| ltx-2.5-video-vae-bf16.safetensors | vae | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) |
| ltx-2.5-audio-vae-bf16.safetensors | vae | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) |
| ltx-2.5-22b-ic-lora-alpha-gen-0.9.safetensors | loras | [Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen) |
| ltx-2.5-22b-ic-lora-layout-to-render-1.0.safetensors | loras/ltx | [Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render) |

Bindings (adapter=comfyui):

| Workflow | prompt_node | seed_node | output_node | Inputs |
| --- | --- | --- | --- | --- |
| flux3_klein_soul_cast.json | 6 | 3 | 9 | Text only; latent size 5.width / 5.height |
| flux3_klein_reference_key.json | 6 | 3 | 9 | Up to 6 references: LoadImage 21–26 → `ReferenceMultiLatent` images.image0–5; latent size 10.width / 10.height |
| flux3_klein_edit.json | 6 | 3 | 9 | Image to edit 21 (image0) and up to 2 more references 22–23; latent size 10.width / 10.height |
| ltx25_cinema_shot.json | 6 | 3 | 12 | image_node=2, image_input=image |
| ltx25_openjutsu_v2v.json | 6 | 3 | 12 | video_node=1, video_input=video, reference_image_node=2, reference_image_input=image |
| ltx25_openjutsu_swap.json | 6 | 3 | 12 | input_bindings 20.video and 25.video = source_video, 2.image = anchor_keyframe |
| ltx25_layout_render.json | 30 (string_a) | 50 (noise_seed) | 12 | input_bindings 20.video = previs_video, 24.video = actor_matte, 2.image = anchor_keyframe |

### OpenJutsu subject replacement (Object Swap)

Rows whose **Jutsu Mode** is `Object Swap` run their own pipeline lane, **Swap Key → OpenJutsu Swap**; other rows keep the restyle above.

1. **Swap Key** (`flux3_klein_look_key.json`, stage `swapkey`): FLUX 3 Klein edits frame 0 of the source (`23.batch_index` = 0) with the row's first `@CAST` reference (and an optional second reference). It keeps the pose and framing and writes **Anchor Keyframe** for review.
2. **OpenJutsu Swap** (`ltx25_openjutsu_swap.json`, stage `swap`) is one LTX-2.5 graph:
   - The [Alpha-Gen IC-LoRA](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen) mattes the subject. Settings follow its model card: LoRA strength 1.0, the source video as the IC-LoRA reference at strength 1.0, an empty prompt, and the official 8-step distilled sigmas. No custom nodes are needed: ComfyUI 0.42.1 core chains `LoraLoaderModelOnly` → `GetICLoRAParameters` → `LTXVAddGuide(iclora_parameters)`.
   - The subject is regenerated from the source latent at denoise 0.85, with the approved Anchor Keyframe pinned on frame 0 (`LTXVImgToVideoInplace`). Motion comes from the source and identity from the key.
   - `GrowMask` (20 px) and an `ImageBlur` feather extend the matte past the old silhouette, since the new subject's outline differs from the old one. The decoded matte carries faint VAE noise everywhere, so `ThresholdMask` (0.02) × `MaskComposite` sets it to exactly 0 outside the subject. `ImageCompositeMasked` then places the regenerated frames inside the matte, over the source loaded at native size (node 25, same frame count as node 20). Pixels outside the matte are copied from the source unchanged, and the source audio is kept.

Install `ltx-2.5-22b-ic-lora-alpha-gen-0.9.safetensors` into `models/loras` (gated: accept the license on the model page first). Alpha-Gen accepts up to 145 frames (6 s at 24 fps), so node 20 caps the source at 145 frames. The LTX passes run at 1280x704, and the composite resizes the regenerated frames back to the source size.

### Layout Render (3D Stage previs as an IC-LoRA layout)

An optional cinema lane next to Previs Motion Pass → Look Key → Look Pass: **Layout Key → Layout Render**, queued from the 3D Stage with *Run layout render*. *Render previs* also saves the shot's **Actor Matte** (the same plan with the actor white on black).

1. **Layout Key** (`flux3_klein_look_key.json`, stage `layoutkey`): FLUX 3 Klein repaints previs frame 0 (`20.frame_load_cap` 1, `23.batch_index` 0) with the row's cast and set references under a composition-first edit instruction (`LAYOUT_KEY_PROMPT` in `run_studio.py`), and writes **Keyframe** for review.
2. **Layout Render** (`ltx25_layout_render.json`, stage `layout`): the [Layout-To-Render IC-LoRA](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render) at strength 1.0 takes the previs as its reference (`LTXVAddGuide`, frame 0, strength 1.0, on an empty latent); lower strengths copy the grey model. The approved key is an out-of-clip reference (`LTXVAddLatentGuide`, latent_idx -1) that gives the look. The actor matte is grown 24 px, blurred and inverted inside the graph (`GrowMask` / `ImageBlur` / `InvertMask`) into the guide's attention mask, so the layout binds everything except the actor; without it the mannequin is rendered literally. cfg 1, euler_ancestral on the 8 distilled sigmas, `LTXVCropGuides` before decode. It writes **Cinema Shot** for review.

Install `ltx-2.5-22b-ic-lora-layout-to-render-1.0.safetensors` into `models/loras/ltx/`. On the RTX 4090 a 6 s shot takes about 55 s (key) + 2-3 min (render). Findings: [motion-control lab](../docs/research/2026-10-20-motion-control-lab.md#layout-to-render-ic-lora-2026-10-21).

**Chained Layout Render (long takes).** A long take is rendered as 8 s slices (193 frames) that share their boundary frames. Three optional image columns on the row turn the stage into a chained slice ([`layout_guides.py`](../project_assistant/studio/layout_guides.py)); a row without them binds exactly as above.

| Column | Graph | Use |
|---|---|---|
| **Chain In Frame** | `LoadImage` → `ImageScale` → `LTXVImgToVideoInplace` (strength 1.0) on the empty latent before the previs guide | The previous slice's last frame becomes frame 0: no seam. |
| **Mid Key** | `LTXVAddGuide` at the middle of the previs (a multiple of 8), strength 0.8 | A still the slice must pass through, e.g. a small Klein edit of an approved frame (eyes open, a smile) that keeps a face while the camera moves. |
| **End Key** | `LTXVAddGuide` at frame -1, strength 0.9 | The planned last frame; the next slice starts from it. |

The guides chain after the pose-skeleton guide and feed the sampler, `LTXVCropGuides` and the audio/video concat. An End Key must match the framing the next slice's previs starts with, or the next slice pulls back to the previs. The 88 s [Updraft one-take](../samples/updraft/updraft_oner.mp4) was made this way; the scripts that ran it directly against ComfyUI, with the compositing and sound around it, are in [`tools/oner/`](../tools/oner/README.md).

Image bindings accept the active shot, its predecessors, and mentioned @Asset rows only. Include soul-cast in the flow node input_tabs to resolve @CAST-01 references. The compiler supports the actual input.rows payload and the older documented structured_rows alias. param_bindings maps node_id.input_name to a context key or literal; empty context values leave the workflow default intact.

For local ComfyUI use platform=local and base_url=http://127.0.0.1:8188. For the Developer Platform install pip install 'openbench[comfy]', use platform=comfy_sdk, set COMFY_API_KEY, and set base_url or COMFY_BASE_URL to a serverless deployment or a self-hosted [comfy-api-proxy](https://github.com/Comfy-Org/comfy-api-proxy); Comfy Cloud is the default SDK target. The [official SDK](https://github.com/Comfy-Org/comfy-python-sdk) uses workflow API v2 assets/jobs, with origin-scoped bearer credentials and bounded output streaming. Credentials stay in api_key_env/environment, never in a workflow. Cloud/deployments must have these same model files and custom nodes installed.

Comfy Router is a model API at /v2/models, and does not accept workflow /prompt requests. platform=comfy_router and router_url are rejected with an explicit setup error; choose comfy_sdk for these graphs. No Partner Nodes or paid closed-model endpoints are embedded.


## Flexible reference preparation and external slot binding

The media worker accepts mode (or layout) extract_frame with timestamp_sec (default0), and motion_structure with structure_type edge_lineart (default), luma_depth, or frame_diff. It uses the active row's source video, uploads a PNG first_frame or H.264 MP4 motion_structure_video, and returns text, asset_url, asset_id, content_type and reference_role. Width/height default to source dimensions; optional even dimensions resize and pad the guide. FFprobe checks frame count, average FPS, duration and audio presence after motion preparation. Audio is retained through AAC encoding. Frame-diff prep prepends a cloned source frame before computing differences, then restores source cadence to keep the initial frame and full duration. luma_depth is a luminance proxy, not estimated scene depth; edge and frame-diff guides also remain ordinary inspectable video assets. Heavy workflows must explicitly implement the intended conditioning.

Reference packs expose source_video (alias source_video_url), first_frame, motion_structure_video, anchor_keyframe, output_video, asset_images (alias reference_image_urls), asset_map, resolved_assets, compiled_prompt and seed. asset_map.CAST-01.url addresses the first reference for that asset. Matching same-row predecessors tagged reference_role override stale media of that role. Anchor keyframe then first frame then predecessor images then cast references determine primary_image_url. Default Comfy video_gen outputs carry output_video; set reference_role=anchor_keyframe on an externally configured anchor image worker.

Use an external API-format JSON for real first-frame character editing or specialized edge/depth/pose conditioning. The supplied FLUX soul-cast graph is text-to-image; binding a first frame into an unused loader would not turn it into an image editor. The sample V2V graph exposes source node1, anchor node2, motion node4, prompt node6, seed node3 and output node12. Node4 is intentionally an external control slot, unconnected to the compact sample's output path: connect it to a model-compatible conditioner in your own graph. The shipped sample makes no motion-structure control claim.

The binder does not inspect class_type or impose these example node IDs. Both forms below work with arbitrary external graphs; explicit input_bindings override legacy slots and param_bindings:

~~~json
{
  "input_bindings": {
    "anchor_keyframe": {"node": "photo-loader", "input": "image", "upload": "image"},
    "first_frame": {"node": "frame-loader", "input": "image", "upload": "image", "optional": true},
    "motion_structure_video": {"node": "control-loader", "input": "video", "upload": "video"},
    "source_video": {"node": "source-loader", "input": "video", "upload": "video"},
    "asset_images.0": {"node": "reference-loader", "input": "image", "upload": "image"},
    "prompt-encoder.text": "compiled_prompt",
    "sampler.seed": "seed",
    "sampler.cfg": {"literal": 1}
  },
  "output_node": "save-output"
}
~~~

Dot paths traverse maps and list indexes. Exact project asset URLs upload automatically; upload=image/video enforces MIME, and upload=auto accepts either supported visual kind. Missing required inputs fail before submission; optional bindings retain graph defaults. Downloads/uploads deduplicate within one binding call. Legacy prompt_node, seed_node, image_node, reference_image_node, video_node, first_frame_node, structure_video_node and their corresponding *_input names remain available. param_bindings retains optional empty-context behavior. Credentials and endpoint configuration still use the local/SDK configuration described above.

## Self-Hosted RunningHub Studio Cards, Dual-Engine Alignment & `line-worlds` Structure (`SPEC_05`)

Declarative Studio Cards (`workflows/cards/*.json`) wrap complex ComfyUI workflows into 6–10 typed semantic fields (`nodeId`, `fieldName`, `fieldType`, `slot`, `locked_nodes`, `projectDefaults`) that compile to a flat `nodeInfoList` payload and execute directly on local ComfyUI (`platform="local"`) or Comfy SDK v2 (`platform="comfy_sdk"`). Any ComfyUI / RunningHub `.json` workflow (including LiteGraph UI format with `SetNode`/`GetNode` virtual wires such as `短视频复刻-v3.json`) is automatically converted to flat ComfyUI API format via `convert_litegraph_to_api()` and can be reverse-engineered into a self-hosted Studio Card via `extract_studio_card_from_workflow()` (or `card="auto"`):

- `workflows/cards/h3-reference.json`, `workflows/cards/h3-optimize.json`, & `workflows/cards/h3-short-video-v3.json` (`workflows/minimax_h3_ref2va.json`, `workflows/minimax_h3_short_video_v3.json`): Pass 1 multi-reference video generation (`17n+5` frame alignment, `32px` grid, `compile_h3_context_ir()` 6-section prompt, `slot_plan()` pictured-first @Asset ranking with `excluded_refs` guard, `disabled_loras` strength zeroing, automatic `"None"` media slot and `LayerUtility` passthrough cascade unlinking) and Pass 2 `@source` 4K restoration.
- `workflows/cards/ltx25-openjutsu.json` & `workflows/cards/ltx25-cinema.json`: LTX-2.5 (`8n+1` frame alignment, `32px` grid) with `mode="ingredients_sheet"` horizontal multi-asset reference stitcher and spatial panel prompt (`ltx_ingredients_prompt`).
- `workflows/cards/flux-soul-cast.json` & `workflows/cards/local-smoke.json` (`workflows/local_smoke_sdxl_lightning.json`): Character/scene reference generation and 4-step zero-custom-node SDXL Lightning smoke testing on local GPUs.
- Multi-density motion structure & `line-worlds` procedural 2-link IK renderer (`prepare_reference_media`):
  - `mode="frame_sheet"`: 8-frame timestamped `1600x600` contact sheet (`VIDEO 1 / 0.312s ...`) locked by `compute_request_fingerprint()`.
  - `structure_type="ref05_edge"` / `"ref05_depth"`: Half-resolution Gaussian-smoothed de-textured motion structure videos.
  - `structure_type="layout_silhouette"` / `"sparse_tracks"` & `mode="time_strata"`: Articulated 2-link IK (`solve_ik`) + control knobs (`stride`, `turn`, `reach`, `flare`, `camera_zoom`, `phases`) supporting both Extract & Re-Rig (with source video) and Storyboard Rehearsal (without source video).
- Post-render `.bounded.mp4` trimming (`bound_output_video_duration`): Trims `17n+5` / `8n+1` upward frame padding back to `min(requested_sec, source_sec)` with H.264 CRF 16, `-movflags +faststart`, and preserved audio.

## Reference keyframes, Klein edits and compiled prompts (`SPEC_21`)

Two FLUX 3 Klein graphs carry reference images into the picture, built like `flux3_klein_look_key.json` (same UNET/CLIP/VAE loaders, `ModelSamplingFlux`, `ReferenceMultiLatent` with resize at 1 MP, `EmptyFlux2LatentImage`, KSampler 50 steps at cfg 4, `VAEDecode`, `SaveImage`) but without the source-video frame:

- `workflows/flux3_klein_reference_key.json`, card `flux-reference-key` (webappId `2105000000000000005`): text plus up to six references. `LoadImage` nodes 21–26 feed `images.image0`–`images.image5` and are the card's six `slot: "ref"` inputs. It is the shot keyframe card: its prompt numbers the pictures ("the person in image 1 and image 2 is …"), so the references go in the order the prompt names them.
- `workflows/flux3_klein_edit.json`, card `flux-klein-edit` (webappId `2105000000000000006`): node 21 (`image0`) is the picture being edited and is required; nodes 22–23 are up to two more references. The prompt follows the "Edit image 1. CHANGE: … PRESERVE EXACTLY: …" form. Used for state variants and reverse angles.

Story panels and shot keyframes choose these cards by id. In the generic asset generation bar they are listed only in their `usage_scopes` (reference key: `FREE_CREATION_T2I`, `FREE_CREATION_I2I`; edit: `SCENE_PROP_EDIT`, `FREE_CREATION_I2I`), so Character and Scene & prop assets keep `flux-soul-cast` as the first image card to fall back to.

Both cards expose the latent size as `10.width` / `10.height` (INT, 256–2048). `engine_config.mirror_inputs` (`{"7.width": "10.width", "7.height": "10.height"}`) copies the size into `ModelSamplingFlux` after injection, so the sampler shift always reads the latent size. `flux-soul-cast` exposes its latent size as `5.width` / `5.height` (defaults 1280×720, as before).

Empty reference inputs are unlinked by the same `"None"` media-slot rule as the other cards (`_unlink_node_and_dependents`). For `ReferenceMultiLatent` the remaining `images.imageN` inputs are then renumbered from `image0` in their original order, so the node never has a gap or a dangling input. With no reference left the node is bypassed (the sampler takes the text conditioning directly) and the graph is plain text-to-image: zero references never fail. Six 1 MP references multiply the sampler's sequence length; time and memory on the RTX 4090 are not measured yet (GPU acceptance G1).

`engine_config.prompt_compile` names the compiled text a card's prompt input takes: `reference_image` → `image_reference_prompt` (`flux-reference-key`), `edit` → `edit_prompt` (`flux-klein-edit`), `asset_panel` → `asset_panel_prompt` (`flux-soul-cast`), `video_skeleton` → `video_skeleton_prompt` (`ltx25-cinema`). When that text is missing or blank, the prompt is filled by the earlier rules (H3 context IR, LTX ingredients prompt, compiled prompt, card default). A job's config may name a different `prompt_compile`; explicit card values still win. Cards that compile an image prompt (`reference_image`, `asset_panel`, `edit`) fill their reference inputs from the context's `reference_plan` (`[{url, assetCode, role, panel}]`) in plan order, one entry per input and `"None"` after the last entry; without a plan they use `slot_plan` as before. The video skeleton card keeps the first frame in its one reference input.
