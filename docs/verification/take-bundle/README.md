# Take bundles: one real S03 bundle from the app

Date: 2026-10-21. Source: the ZeroField showcase database (`zerofield-showcase`), read through the product endpoint
`GET /projects/api/zerofield-showcase/assets/pa_0822dc0f8a28a28cfa3e198c618e92c3/bundle` with a member token
(an unauthenticated request returns 401). [`s03-take/`](s03-take/) is that ZIP, unpacked and unchanged.

The take is the current **S03 · Cinema Shot** in Cinema Studio: the LTX-2.5 Layout-To-Render take queued from the 3D Stage
on 2026-10-21 at 09:02 (pipeline task `1c2d50b7…`, node `layout`, worker *ZeroField Studio / layout*). Its status in the
slate is **Retake**.

## Bundle manifest

| File | Bytes | SHA-256 |
| --- | --- | --- |
| [`output.mp4`](s03-take/output.mp4) | 3,384,635 | `0822dc0f8a28a28cfa3e198c618e92c398b2f385b56a30cc172e4e0118186953` |
| [`workflow.json`](s03-take/workflow.json) | 9,634 | `e50fce4beffac20c3b3f292b53888013b82bd35e64b38437df0d67b20af14302` |
| [`take.json`](s03-take/take.json) | 4,684 | `f146e4046b7e376c7fba748133d2be9a3e7dc845e15aeae3341f918f4d5fffb7` |
| [`README.md`](s03-take/README.md) | 3,354 | `86502fed90dae22485472b5f31b80511e6df0b44e58c484dc4e439383095cf87` |
| [`checksums.sha256`](s03-take/checksums.sha256) | 309 | lists the four files above |

`sha256sum -c checksums.sha256` passes in `s03-take/`. The asset ID is the first 32 hex digits of the output's SHA-256,
so the file is the one stored in the app.

What `take.json` records for this take:

| Field | Value |
| --- | --- |
| Provenance | `embedded_in_output`: the 37-node API graph ComfyUI's `SaveVideo` wrote into the MP4 `prompt` tag. `ffprobe -show_entries format_tags=prompt` returns a graph identical to `workflow.json`. |
| Seed | 48315 (`RandomNoise.noise_seed`, node 50) |
| Prompt | node 30 `string_a` (optical rig, camera move, CAST-01/SET-01 references, the S03 action) + `string_b` (live-action look lock); node 7 negative |
| Models | LTX-2.5 22B distilled int8, Gemma 4 12B int8 text encoder, LTX-2.5 video and audio VAEs ([Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5)), Layout-To-Render IC-LoRA 1.0 in `loras/ltx` ([model page](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render)). Sources come from the new Model files table in [`workflows/README.md`](../../../workflows/README.md). |
| Inputs | node 20 `VHS_LoadVideo` (previs), node 24 `VHS_LoadVideo` (actor matte), node 2 `LoadImage` (layout key), listed by their ComfyUI upload names |
| Timing | queued 09:02:01, delivered 09:06:08 (+08:00) |

### Limits of this bundle

This take was rendered before submit-time recording existed, so the bundle says so: input hashes, platform, ComfyUI version
and render timing are `null`, and the input files are not in the ZIP. As a manual cross-check (not part of the bundle), the
three upload names are still in the local ComfyUI `input/` folder. Their SHA-256 values match the S03 row's own assets:

| Graph input | ComfyUI upload | Matches |
| --- | --- | --- |
| 20.video | `source_video-7b8c0f8b…webm` | `pa_d6bd03d29e9bbfd12a6767a9c3d378dc` (S03 **Previs**, 6,013,709 bytes) |
| 24.video | `source_video-5d70f0cb…webm` | `pa_14a6f73da9a5af1128e60c6d8972161a` (S03 **Actor Matte**, 1,402,721 bytes) |
| 2.image | `input-b1a20457…png` | `pa_0c9a25b5c69e7940cc4ce1ddcd461ce5` (S03 **Keyframe**, 1,268,733 bytes) |

## New takes

From this change, the comfyui adapter stores the following with every take it delivers (`limb_task.output.provenance`):
the API graph after all bindings, the ComfyUI prompt/job ID, platform (`local` or `comfy_sdk`) and endpoint origin, the
ComfyUI version from `/system_stats` when the endpoint serves it, the comfy-sdk version, submit and finish times, and the
SHA-256, MIME type and size of every uploaded input. Their bundles have `provenance: recorded_at_submit` and include the
input files under `inputs/`, named as the graph references them. `tests/test_take_bundle.py` covers this through the real
worker protocol, PostgreSQL and a ComfyUI HTTP fixture. No GPU render has run through the new code yet, so no
`recorded_at_submit` bundle from real hardware is included here.

## Project export

`GET /projects/api/zerofield-showcase/takes/export` (sheet menu **⋯ → Export approved takes**) returned a 9.1 MB ZIP in
0.5 s: 8 generated takes from Approved rows (CAST-01 and SET-01 references; S01, S02 and S06 keyframes and cinema shots),
each in its own folder with the same files as above, plus [`approved-takes-manifest.json`](approved-takes-manifest.json).
Uploaded sources such as previs clips have no generation record and are left out.

## Secrets

Bundles are built in one place (`project_docs/take_bundle.py`). It redacts credential-like keys (`api_key*`, `token`,
`secret`, `password`, `authorization`, …), known key formats, and the values of `*KEY*`/`*TOKEN*`/`*SECRET*`/`*PASSWORD*`
environment variables. If any file, media included, still contains such a value, the download is refused with 409.
`tests/test_take_bundle.py` plants `COMFY_API_KEY` in the environment, in an `api_key_comfy_org` graph input and in a prompt,
and asserts that neither ZIP contains it, the member token or the worker token.
