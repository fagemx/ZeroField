# SPEC 04 — Pre-Loaded Short Drama Showcase (`samples/`) & `run_studio.py` Launcher

**Parent Index**: [`docs/ZEROFIELD_SPEC.md`](../ZEROFIELD_SPEC.md)  
**Order of Execution**: **Step 3 (Integration & Launcher)** — Run after `SPEC_01`, `SPEC_02`, and `SPEC_03` are complete.  
**Owned Files**:
- `run_studio.py`
- `samples/` (sample images and short MP4 clips)
- `README.md` (update "Available now" vs "Next development phase" once features land)
- `tests/test_run_studio.py` (new integration/launcher test)

---

## 1. Objective & Scope

When an international judge or developer clones `ZeroField` and starts the studio, they should not be greeted by an empty spreadsheet with zero media and disconnected workers. They need:
1. **A one-command launcher (`run_studio.py`)** that starts the embedded PostgreSQL database (or connects to a configured DB), seeds the showcase project with real playable media assets (`samples/`), auto-registers built-in Comfy / FFmpeg workers (supporting both **Comfy Router / SDK** and local ComfyUI), and runs a background worker polling loop.
2. **Pre-loaded showcase media (`samples/`)** inside **The Last Signal** default production so judges can immediately experience:
   - **Macro (`Table` / `Board`)**: Shots across `Queued`, `Pending Review`, and `Approved` states.
   - **Meso (`Gallery / Storyboard Visual Chain`)**: Side-by-side `@CAST-01` reference ➔ `Keyframe` ➔ playable `Cinema Shot` video on every card, plus `Source Driving Video` ➔ `Remastered Video` ➔ `Split-Screen MP4` in `OpenJutsu Lab`.
   - **Micro (`SheetReview` + `Studio Assistant`)**: Open Shot `S02` (which has a pre-seeded director annotation asking `@Cinematographer` for a retake), step through shots with `←` / `→`, and trigger an in-place re-shoot.

---

## 2. Critical Guardrail: Do NOT Break `tests/test_zerofield_baseline.py`

In `tests/test_zerofield_baseline.py`, `test_studio_template_has_five_english_tabs_and_empty_media_cells` explicitly asserts that calling `templates.tab_specs('zerofield_studio', 'Test Film', '')` directly returns **empty media cells** and **no `"Approved"` status**:
```python
self.assertNotIn('Approved', json.dumps(clean))
self.assertNotIn('asset_url', json.dumps(clean))
```
Therefore:
- **Keep `project_docs/templates.py:tab_specs("zerofield_studio", ...)` returning empty media cells and `Queued` statuses by default!**
- Perform the showcase media & annotation seeding **inside a dedicated seeding function** `seed_showcase_media(conn, slug="the-last-signal")` called by `run_studio.py` (or `server.py` when `--seed-showcase` is passed), NOT inside raw `templates.tab_specs()`.

---

## 3. Exact Implementation Requirements

### 3.1 Generate / Bundle Compliant Showcase Media in `samples/`
Ensure `samples/` contains lightweight, 100% SFW, copyright-clean, original sci-fi noir assets (or generate them deterministically via PIL/FFmpeg if not yet rendered by ComfyUI, and replace with full FLUX / LTX-2.5 renders once ComfyUI runs):
- `samples/cast_kael.png` (`CAST-01` Kael reference portrait)
- `samples/set_observatory.png` (`SET-01` Rainy observatory reference)
- `samples/keyframe_s01.png` & `samples/shot_s01.mp4` (`S01` establishing shot, H.264 MP4 with audio & `+faststart`)
- `samples/keyframe_s02.png` & `samples/shot_s02.mp4` (`S02` recorder close-up, H.264 MP4 with audio & `+faststart`)
- `samples/openjutsu_source.mp4`, `samples/openjutsu_remastered.mp4`, `samples/openjutsu_split.mp4` (`VFX-01` OpenJutsu comparison clips)

### 3.2 Create `run_studio.py` at Repo Root
Support CLI arguments:
```powershell
python run_studio.py --port 3020 --comfy-url http://127.0.0.1:8188 [--router-url https://...] [--api-key ...] [--no-worker]
```
`run_studio.py` must:
1. **Initialize Database & Schema**:
   - Use `--embedded-db` (via `server.py` embedded PostgreSQL helper) unless `OPENBENCH_DB_URI` / `DATABASE_URL` is already set.
   - Ensure schema and default demo members (`DEMO_MEMBERS`) exist.
2. **Seed Showcase Media & Worker Registrations (`seed_showcase_media`)**:
   - Upload the files in `samples/` into `projectops.asset` via `repo.put_asset()`.
   - Populate `soul-cast` (`CAST-01` with `@CAST-01` reference image, `SET-01` with `@SET-01` reference image), `cinema-studio` (`S01` and `S02` with `Keyframe`, `Cinema Shot`, and `@CAST-01 @SET-01` references; set `S01` to `Approved`, `S02` to `Pending Review` with a row annotation from `Alex Rivera (Showrunner)`), and `openjutsu-lab` (`VFX-01` with `Source Driving Video`, `@CAST-01` prompt, `Remastered Video`, and `Split-Screen MP4`).
   - Register default workers in `projectops.agent_limb` for the showcase project (`image_gen` bound to `workflows/flux3_klein_soul_cast.json`, `video_gen` bound to `workflows/ltx25_cinema_shot.json` and `workflows/ltx25_openjutsu_v2v.json`, and `media_assemble` for `ffmpeg`), and start a background daemon thread running `limb_worker` polling when `--no-worker` is not set.
3. **Start HTTP Server**:
   - Print the studio URL (`http://127.0.0.1:3020/projects/`) and serve requests cleanly until Ctrl+C.

---

## 4. Verification & Acceptance Criteria

Run the full verification suite:
```powershell
python -m unittest discover -s tests -v
npm test --prefix ui
npm run build --prefix ui
python -m build --wheel
```
And verify `python run_studio.py --help` and `seed_showcase_media()` in `tests/test_run_studio.py`.
