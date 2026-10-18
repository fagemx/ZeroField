# ZeroField open-weights workflows

These are API-format graphs derived from official ComfyUI model templates and current node schemas, checked on 2026-10-18. JSON/link validation and mocked transports pass locally; GPU inference is **not verified** on this workstation. Install matching models and nodes before rendering. Output quality, memory use and identity fidelity still require an actual render review.

- [FLUX 3 Klein guide](https://docs.comfy.org/tutorials/flux/flux-3-klein), [official template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_flux3_klein_t2i.json): ComfyUI 0.41.1+; models/diffusion_models/flux3-image-klein-base-int8-convrot.safetensors; models/text_encoders/qwen3vl_4b_int8_convrot.safetensors; models/vae/flux2-vae.safetensors. Download from [BFL](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy), review its FLUX Kommunity License. Uses separate UNET/CLIP/VAE loaders and EmptyFlux2LatentImage, rather than a fictitious flux3_klein_5.6b checkpoint. Prompt upsampling is disabled.
- [LTX 2.5 guide](https://docs.comfy.org/tutorials/video/ltx/ltx-2-5), [official I2V template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_ltx2_5_i2v.json): latest compatible ComfyUI; models/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors; models/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors; models/vae/ltx-2.5-video-vae-bf16.safetensors and ltx-2.5-audio-vae-bf16.safetensors. Accept [Lightricks model access/license](https://huggingface.co/Lightricks/LTX-2.5) first. The compact graphs omit the official two-pass upscaler; LTX latents use 1280x704, 97 frames at 24 fps, with an 8-step first-pass sampler. Tune against the official template after validating on your GPU.
- OpenJutsu additionally requires [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite). Its VHS_LoadVideo caps and normalizes driving frames to the LTXV format (8n+1 frames, at most 97). The graph encodes the source video, denoises its latent at 0.72, and uses LTXVAddGuide for the selected character reference. This is source-guided video restyling; it does not implement SAM2 segmentation, depth masks, a guaranteed face swap, or a dedicated motion-transfer model. Source audio passes through unchanged. Mode/optics/movement are compiled prompt instructions; they are not separate physics controls.

Bindings (adapter=comfyui):

| Workflow | prompt_node | seed_node | output_node | Inputs |
| --- | --- | --- | --- | --- |
| flux3_klein_soul_cast.json | 6 | 3 | 9 | Text only |
| ltx25_cinema_shot.json | 6 | 3 | 12 | image_node=2, image_input=image |
| ltx25_openjutsu_v2v.json | 6 | 3 | 12 | video_node=1, video_input=video, reference_image_node=2, reference_image_input=image |

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
