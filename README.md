# ZeroField Studio

> **No paywalls. No closed APIs. Just pure open-weights cinema & V2V illusion.**  
> Built for the **ComfyUI Open Source Higgsfield Challenge** (2026).

**ZeroField** is an open-source, multi-shot filmmaking and video-to-video (V2V) remastering studio built on the **Comfy Developer Platform**. It combines the best of **Cinema Studio** (optical camera/lens simulation, consistent *Soul Cast* characters, multi-shot storyboard assembly) and **Genjutsu / OpenJutsu** (batch motion transfer, object/product swap, and side-by-side viral comparison grids) into a unified **`Script + Storyboard Sheet + ComfyUI DAG Flow`** workspace—powered **100% by Open-Weights Models (`LTX-2.5` & `FLUX 3 Image Klein`)**.

---

## Why ZeroField?

Most creative AI wrappers lock you into a single-shot prompt box behind a subscription paywall. Real filmmakers and VFX creators work in **multi-shot slates, asset lookbooks, and node pipelines**:

1. **Cinema Studio Rebuilt (Multi-Shot Optical Directing)**
   - **Director's Optical Compiler**: Select real cinema camera bodies (`ARRI Alexa 65`, `RED V-Raptor`, `16mm Bolex`), anamorphic/prime lenses (`24mm`, `35mm Anamorphic`, `85mm f/1.4`), and camera motion rigs (`Dolly Push-In`, `Handheld Urgency`, `Crane Rise`, `Orbit 180°`).
   - **Soul Cast Asset Lock**: Lock character turnarounds, seeds, and reference frames generated with **`FLUX 3 Image Klein (5.6B)`** across every shot in your storyboard sheet.
   - **Native Audio + Video with `LTX-2.5`**: Generate synchronized motion and sound across multiple takes, compare Takes A/B/C side-by-side, and assemble the final short film in one click via built-in **FFmpeg**.
2. **OpenJutsu Lab (Batch V2V Motion Transfer & Object Swap)**
   - Drop in any real-world driving video and batch-run **Motion Transfer** (keep camera & human motion, swap character/world) or **Object/Product Swap** across multiple rows simultaneously using **`LTX-2.5` V2V**.
   - **One-Click Viral Split-Screen Export**: Automatically stitch the original driving video alongside your `LTX-2.5` remastered outputs (`hstack` comparison MP4) ready to share on X/TikTok.
3. **100% Open Weights & Comfy Developer Platform Native**
   - Zero reliance on closed-source partner nodes. Works seamlessly with local ComfyUI (`http://127.0.0.1:8188`) or Comfy Cloud / Router APIs.

---

## Architecture

```
+-----------------------------------------------------------------------------------+
|                              ZeroField Studio UI (React)                          |
|  [Director's Brief (Doc)]  [Soul Cast & Cinema Slate (Sheet)]  [Comfy DAG (Flow)] |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                      ZeroField Head & Orchestrator (Python)                       |
|  - Optical Preset Compiler (Camera / Lens / Motion -> Prompt & Node Params)       |
|  - Multi-Take Revision Manager & Proposal Review                                  |
+-------------------+-------------------------------------------+-------------------+
                    |                                           |
                    v                                           v
+---------------------------------------+   +---------------------------------------+
|     ComfyUI Worker (`limb_worker`)    |   |     FFmpeg Assembler (`limb_worker`)  |
|  - FLUX 3 Image Klein (Soul Cast/I2I) |   |  - Multi-Shot Film Concatenation      |
|  - LTX-2.5 Cinema I2V (Shot + Audio)  |   |  - Viral Split-Screen Comparison Grid |
|  - LTX-2.5 OpenJutsu V2V (Motion/Swap)|   +---------------------------------------+
+---------------------------------------+
```

---

## Quick Start (Local Setup)

### Prerequisites
- Python 3.11+
- PostgreSQL (or embedded local database via `--embedded-db`)
- FFmpeg (`ffmpeg` and `ffprobe` on `PATH`)
- ComfyUI running locally (`http://127.0.0.1:8188`) or via Comfy Developer Platform with open-weights **`LTX-2.5`** and **`FLUX 3 Image Klein`** workflows located in [`workflows/`](./workflows/).

### 1. Install & Launch ZeroField Studio
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
python server.py --embedded-db --port 3020
```
Open **[http://127.0.0.1:3020/projects/](http://127.0.0.1:3020/projects/)** in your browser. ZeroField comes pre-loaded with the **ZeroField Cinema & OpenJutsu Showcase** project and sample outputs so you can explore the multi-shot slate and video comparisons immediately.

### 2. Connect Your ComfyUI Worker
Configure your local ComfyUI endpoint in `examples/worker.example.json` and start the worker loop:
```powershell
$env:OPENBENCH_LIMB_TOKEN = '<your-worker-token>'
openbench-worker --config examples/worker.example.json
```

---

## Included Open-Weights ComfyUI Workflows

All workflows in [`workflows/`](./workflows/) use **100% open-weights models** (eligible for **Open Weights Only** & **LTX VFX Bonus**):
- `workflows/flux3_klein_soul_cast.json` — Character turnaround & optical keyframe generation using **FLUX 3 Image Klein (5.6B)**.
- `workflows/ltx25_cinema_shot.json` — Image-to-Video cinematic camera motion & audio synthesis powered by **LTX-2.5**.
- `workflows/ltx25_openjutsu_v2v.json` — Video-to-Video motion transfer & masked object swap powered by **LTX-2.5**.

---

## License

Released under the [MIT License](./LICENSE).
