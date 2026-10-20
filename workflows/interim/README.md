# Interim local workflows (4090 bring-up)

Stand-ins for the official LTX-2.5 / FLUX 3 Klein graphs, using model files already on this
workstation. They prove the full ZeroField path (Pipeline → local ComfyUI → proposal → review)
before the gated models are downloaded. Same node bindings as the official graphs
(prompt 6, seed 3, image 2, output 9/12); swap the config back to the built-in defaults once
the official models are installed.

| Stage | Graph | Model | 4090 time |
| --- | --- | --- | --- |
| Keyframe / Soul Cast | `flux1_dev_keyframe.json` | FLUX.1 dev (bf16 weights, fp8 compute), 1280×720, 24 steps | ~22 s |
| Cinema Shot (I2V) | `ltxv097_cinema_shot.json` | LTX-Video 13B 0.9.7 dev, 1024×576, 73 frames @24 fps, 30 steps | ~90 s |
| OpenJutsu (V2V) | `ltxv097_openjutsu_v2v.json` | Same LTXV, core `LoadVideo` (no custom nodes), denoise 0.72 + anchor guide | — |

FLUX.1 dev is open weights under a non-commercial license; LTXV 0.9.7 under the LTXV Open
Weights license. Both run locally (`comfy_local`, `open_weights_only` policy passes).

## Run

1. ComfyUI 0.42.1 portable at `E:\AITool\ZeroField_ComfyUI\ComfyUI_windows_portable`
   (`extra_model_paths.yaml` reads models from the existing `E:\AITool\ComfyUI_windows_portable`).
   Start it with `run_nvidia_gpu.bat` (port 8188).
2. `python run_studio.py --worker-config workflows/interim/workers.local.json`
   (or the `zerofield-studio-render` entry in `.claude/launch.json`).

## Official models (gated, ~50 GB)

Accept the licenses on Hugging Face first (sign in, open each page, agree), then log in with
`huggingface-cli login`. Files land in the ComfyUI `models/` sub-folders the official graphs expect.

```powershell
$M = "E:\AITool\ZeroField_ComfyUI\ComfyUI_windows_portable\ComfyUI\models"
huggingface-cli download Lightricks/LTX-2.5 diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors vae/ltx-2.5-video-vae-bf16.safetensors vae/ltx-2.5-audio-vae-bf16.safetensors --local-dir $M
huggingface-cli download black-forest-labs/flux-3-image-klein-comfy diffusion_models/flux3-image-klein-base-int8-convrot.safetensors text_encoders/qwen3vl_4b_int8_convrot.safetensors vae/flux2-vae.safetensors --local-dir $M
```

LTX-2.5: 21.5 + 15.4 + 1.5 + 0.4 GB. FLUX 3 Klein: 5.8 + 4.9 + 0.3 GB. The official OpenJutsu
graph also needs ComfyUI-VideoHelperSuite in `custom_nodes`.
