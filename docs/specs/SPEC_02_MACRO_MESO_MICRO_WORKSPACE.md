# SPEC 02 — Macro ↔ Meso ↔ Micro Seamless Switching & Pipeline Management

**Parent Index**: [`docs/ZEROFIELD_SPEC.md`](../ZEROFIELD_SPEC.md)  
**Order of Execution**: **Step 2 (Frontend UX Core)** — Depends on `SPEC_01` (`MediaCell.jsx` inline video). Independent of `SPEC_03` (Backend Worker).  
**Owned Files**:
- `ui/src/App.jsx`
- `ui/src/SheetWorkspace.jsx`
- `ui/src/sheetViews.js`
- `ui/src/SheetCards.jsx`
- `ui/src/FlowSurface.jsx`
- `ui/src/FlowPanels.jsx`
- `ui/src/flowModel.js`
- `ui/src/sheet-workspace.css` / `ui/src/flow-workspace.css`
- `ui/tests/` (view model, switching, and workspace tests)

---

## 1. Objective & Architectural Rationale

In AI film/short-drama production, most execution work is delegated to **multi-tool agents and workers** (M8 specialist agents, ACP CLI bridges, Comfy SDK/Router workflows, external media bridges). The human director's core workflow is **management, inspection, annotation, and decision-making** across three scales:

1. **Macro (巨觀 —的全片統籌與批量交辦)**: `Table` and `Board` views + `Studio Assistant` / `Agent Board`. See all 20–50 shots at once, filter by status, batch-select rows, and assign to agents or trigger background pipeline runs **in-place**.
2. **Meso (中觀 — 帶畫面的視覺分鏡與參考素材鏈路牆)**: `Gallery / Storyboard` view inside the **same** tab (`Cinema Studio` / `OpenJutsu Lab` / `Soul Cast`). Each shot card displays its complete **Reference Pack & Output Progression** side-by-side:
   - In `Cinema Studio`: `[@CAST/@SET Reference Thumbnails] ──► [Anchor Keyframe (首幀)] ──► [Cinema Shot <video>]`
   - In `OpenJutsu Lab`: `[Source Video] + [@CAST Thumbnail] ──► [First Frame / Motion Structure / Anchor Frame] ──► [Remastered <video>]`
   with hover-to-play `<video>` previews and 1-click upload or in-place preparation/generation on each stage.
3. **Micro (微觀 — 單鏡參考素材對照審片與指揮台)**: Unified single-shot inspection drawer/modal (`SheetReview` / Row Inspector) that **coexists with the right-hand `Studio Assistant`**, supports `←` / `→` keyboard shot stepping, displays all reference & output media stages of the active shot side-by-side (including resolved `@CAST-01` / `@SET-01` reference thumbnails from `soul-cast`), offers 1-click preset chips (`Optical Rig`, `Camera Motion`, `Jutsu Mode`, `@Assets`), and dispatches single-stage reference prep or external ComfyUI JSON runs **in-place without jumping tabs**.

Meanwhile, **`FlowSurface` (`Comfy Pipeline` tab) is dedicated to Pipeline Architecture & Management** (configuring multi-table DAG steps, binding workers/agents, and viewing pipeline-level runs)—users are **never** forced to jump to `FlowSurface` just to generate or re-shoot a shot!

### Explicit Non-Goals for This Spec
- **Do NOT implement canvas mask painting (`Inpaint Brush`) or video frame extraction (`Extend`)**. Keep 100% focus on making **Macro ↔ Meso ↔ Micro** switching effortless.

---

## 2. Exact Implementation Requirements (5 Concrete Fixes)

### 2.1 Fix #1: Stop Auto-Closing Micro Review / Row Detail When `Studio Assistant` Opens (`ui/src/SheetWorkspace.jsx`)
- **Current Bug (`ui/src/SheetWorkspace.jsx` line 42)**:
  ```js
  useEffect(()=>{if(assistantOpen){setPanel(null);setPreview(null);setRequest(null);}},[assistantOpen]);
  ```
  Whenever a user opens `Studio Assistant` or `Annotations` while inspecting a shot in `SheetReview` (`preview`) or Row Details (`panel === 'row'`), their shot view is forcefully closed!
- **Required Fix**:
  - Change line 42 so opening `assistantOpen` **does NOT close `preview` or `panel === 'row'`**:
    ```js
    useEffect(()=>{if(assistantOpen){setRequest(null);if(panel==='columns')setPanel(null);}},[assistantOpen]);
    ```
  - Ensure CSS in `ui/src/sheet-workspace.css` allows `SheetReview` (`preview`) and `.sheet-side-panel` to remain visible within `.doc-host` when `.pa-on` (the right-hand `AssistantSide` dock) is open.

---

### 2.2 Fix #2: In-Place Pipeline Execution (`runInPlace`) — Eliminate the 6-Step Tab Jump (`ui/src/SheetWorkspace.jsx`)
- **Current Bug**:
  - Clicking `Run Pipeline` on selected rows (line 225) or `Review regeneration pipeline` in `SheetReview` (line 270) calls `toFlow()`, which writes to `sessionStorage` and sets `window.location.hash = workflow`. This kicks the user out of `Cinema Studio` / `OpenJutsu Lab` into `Comfy Pipeline`, forcing 6 manual clicks across tabs just to run or re-shoot a cell!
- **Required Fix in `ui/src/SheetWorkspace.jsx`**:
  1. **Add `runInPlace(rowIds, options = {})` inside `SheetSurface`**:
     - Determine `flowKey = workflow || flows[0]?.key`. If no flow tab exists, report an error.
     - Fetch `const flowData = await api.get(`/projects/api/${slug}/tabs/${flowKey}/flow`);`
     - Determine the execution payload:
       - **Single-cell / single-step regeneration** (when `options.singleStep` or called from a specific media column in `SheetReview` / `MediaCell`):
         - Find the matching node in `flowData.definition.nodes` via `redrawStart(flowData.definition, { target_tab: tab.key, row_ids: rowIds, capability: options.capability, col_index: options.col_index })` or fallback to a node targeting `tab.key` with matching `capability`.
         - If a matching `node` is found and `rowIds.length === 1`:
           - Build `preflightBody = { execution_mode: "single_step", node_id: node.id, input_mode: "current_sources", sample_row_id: rowIds[0], definition_revision: flowData.revision }`.
       - **Batch / multi-row execution** (when called from the batch bar or card/row action without a single-step node):
         - Build `preflightBody = { target_tab: tab.key, row_ids: rowIds, definition_revision: flowData.revision, ...(matchedNodeId ? { start_node_id: matchedNodeId } : {}) }`.
     - Call `const preflight = await api.post(`/projects/api/${slug}/tabs/${flowKey}/flow/preflight`, preflightBody);`
     - If `preflight.ready`:
       - Immediately call `await api.post(`/projects/api/${slug}/tabs/${flowKey}/flow/runs`, { ...preflightBody, source_revisions: preflight.source_revisions });`
       - Show toast via `onToast?.("Queued for execution — results will appear automatically.")`. (Note: `SheetWorkspace.jsx` line 77 already polls `/projects/api/${slug}/tasks?target_tab=${tab.key}` every 5s and reloads the tab when tasks complete!)
     - If `!preflight.ready`:
       - Extract the first error message from `preflight.errors?.[0]?.message || "Pipeline preflight requires attention"` and surface it via `fail(new Error(msg), () => toFlow(rowIds, options))` so the user can still click retry/configure in `FlowSurface` if a worker is offline.
  2. **Wire `runInPlace` to Macro, Meso, and Micro triggers**:
     - In the batch bar (`selected.size > 0`): primary button runs `runInPlace([...selected])` in-place, while keeping a secondary quiet button `"Configure in Pipeline ↗"` (`toFlow([...selected])`) for users who specifically want to open `FlowSurface`.
     - In `SheetReview` (line 270):
       - Fix the hardcoded `capability: "image_gen"` bug! Compute `const cap = (types[preview.c] === 'video' || preview.kind === 'video') ? 'video_gen' : 'image_gen';`
       - Make the primary regeneration button call `runInPlace([previewRow.rid], { singleStep: true, capability: cap, col_index: preview.c })` in-place, and keep `"Open in Pipeline ↗"` (`toFlow([previewRow.rid], { capability: cap, col_index: preview.c })`) as a secondary action.
     - In empty media cells in the `Table` grid (around line 246): when `['image', 'video', 'audio'].includes(types[c]) && !media && writable`, render a compact inline `<button className="cell-upload-btn" onClick={() => pickUpload(r, c)}>+ Upload</button>` so users can upload directly without opening the side drawer.

---

### 2.3 Fix #3: Upgrade **Meso (中觀)** — Visual Shot Chain Cards in `Gallery` & `Board` (`ui/src/sheetViews.js` & `ui/src/SheetCards.jsx`)
- **Current Bug**:
  - `ui/src/sheetViews.js` lines 12 and 27–30 only look for `types[index] === 'image'`. In `OpenJutsu Lab` (which only has `video` columns) or `Cinema Studio` (`Cinema Shot` column), `video` columns cannot be selected as card covers, and cards only show a single thumbnail rather than the shot's visual progression!
- **Required Fix in `ui/src/sheetViews.js`**:
  1. In `viewColumns(parsed)`:
     ```js
     coverColumns: columns.filter(({index}) => ['image', 'video'].includes(types[index]) || parsed.rows.some(row => ['image', 'video'].includes(mediaOf(row.cells[index]?.value, types[index])?.kind))),
     ```
  2. In `sheetViewModel(parsed, visibleRows, preferences = {}, assetLookup = {})`:
     - When computing `cover` for each row:
       ```js
       const coverType = types[coverColumn] || 'image';
       const media = coverColumn < 0 ? null : mediaOf(row.cells[coverColumn]?.value, coverType);
       const cover = ['image', 'video'].includes(media?.kind) ? { ...media, column: coverColumn, value: row.cells[coverColumn].value } : null;
       ```
     - Also build `mediaChain` on each card item:
       - Collect all columns `c` where `['image', 'video'].includes(types[c])` or `['image', 'video'].includes(mediaOf(row.cells[c]?.value, types[c])?.kind)`:
         ```js
         const mediaChain = parsed.headers.flatMap((label, c) => {
           const m = mediaOf(row.cells[c]?.value, types[c]);
           if (!['image', 'video'].includes(types[c]) && !['image', 'video'].includes(m?.kind)) return [];
           return [{ column: c, label, type: m?.kind || types[c] || 'image', value: row.cells[c]?.value || '', media: m }];
         });
         ```
       - Extract any `@Asset` IDs mentioned in the row's text cells (`row.cells.map(c => String(c?.value || '')).join(' ').match(/@?\b(?:CAST|SET|LOC|PROP|STYLE)-\d+\b/gi) || []`) into `assetRefs` (deduplicated uppercase IDs like `["CAST-01", "SET-01"]`).
- **Required Fix in `ui/src/SheetCards.jsx`**:
  - Pass `onUpload` (calling `pickUpload(index, col)`) and `onRunStep` (calling `runInPlace([row.rid], { singleStep: true, capability: ..., col_index: col })`) from `SheetWorkspace.jsx` to `<SheetCards />`.
  - When rendering each card in `Gallery` (`mode === 'gallery'`) or `Board` (`mode === 'kanban'`):
    - If `item.mediaChain?.length > 1` (such as `Cinema Studio` with `Keyframe` ➔ `Cinema Shot`, or `OpenJutsu Lab` with `Source Driving Video` ➔ `Remastered Video` ➔ `Split-Screen MP4`), render a **Meso Visual Chain Strip (`.sheet-card-chain`)** at the top of the card showing each stage side-by-side with `→` connectors:
      - Populated stages render `<MediaCell compact value={stage.value} type={stage.type} label={`${title} · ${stage.label}`} onLightbox={media => onPreview({ ...media, r: index, c: stage.column })} />` with a small stage caption (`stage.label`).
      - Empty stages render a compact placeholder showing `stage.label` with quick `Upload` / `✦ Run` buttons when `writable`.
    - If `item.mediaChain?.length <= 1`, render the single `cover` with `type={cover?.kind || types[model.coverColumn] || "image"}` (never hardcode `type="image"`!).
    - If `item.assetRefs?.length > 0`, render compact `@Asset` reference pills (`.card-asset-Chips`, e.g., `@CAST-01`, `@SET-01`) in the card body so the director immediately sees which assets are bound to that shot.

---

### 2.4 Fix #4: Upgrade **Micro (微觀)** — Unified Side-by-Side Shot Review, Preset Chips & Row Annotation Jump (`ui/src/App.jsx` & `ui/src/SheetWorkspace.jsx`)
1. **Fix Row Annotation Jump (`ui/src/App.jsx` line 302 & `ui/src/SheetWorkspace.jsx` line 44)**:
   - In `ui/src/App.jsx:pick(a)`:
     - When `a.kind === "row"` and `a.anchor?.rid`:
       - After ensuring `tabKey` is navigated to `a.tab_key`, check if the target tab has `surface_type === "sheet"`. If so, call:
         `setSheetFocus({ tabKey: a.tab_key, tableId: a.anchor.table_id, rowId: a.anchor.rid, colIndex: 0, openRow: true, nonce: Date.now() });`
   - In `ui/src/SheetWorkspace.jsx` (`useEffect` handling `focusRow` around line 44):
     - Locate `target = focusRow.tableId ? tables.find(t => t.tableId === focusRow.tableId) : tables.find(t => t.rows.some(r => r.rid === focusRow.rowId)) || tables[0]`.
     - If `focusRow.openRow` is true, automatically open the row inspection panel (`setRowOpen(focusRow.rowId); setPanel('row');`) so clicking a row annotation in `Annotations` opens the shot's discussion and details immediately!
2. **Keyboard `←` / `→` Shot Stepping in `SheetReview` (`ui/src/SheetWorkspace.jsx`)**:
   - Add a `useEffect` when `preview` is open: listening for `keydown` (`ArrowLeft` ➔ `stepPreview(-1)`, `ArrowRight` ➔ `stepPreview(1)`) whenever ` !e.target.closest('input,textarea,select,[contenteditable=true]')`.
3. **Side-by-Side Shot Chain inside `SheetReview` (`ui/src/SheetWorkspace.jsx` line 269)**:
   - When `preview` (`SheetReview`) is open for `previewRow`:
     - Compute all media columns of `previewRow` (`rowMediaCols = parsed.headers.map((h, idx) => ({ idx, label: h, type: types[idx], value: previewRow.cells[idx]?.value || '', media: mediaOf(previewRow.cells[idx]?.value, types[idx]) })).filter(item => ['image', 'video'].includes(item.type) || ['image', 'video'].includes(item.media?.kind))`).
     - When `rowMediaCols.length > 1` (e.g., `Keyframe` + `Cinema Shot`, or `Source Driving Video` + `Remastered Video`), render a **Side-by-Side Media Stage Comparison Bar (`.review-stage-grid`)** inside `.sheet-review-image` so the director sees both the input (`Keyframe` / `Source Video`) and output (`Cinema Shot` / `Remastered Video`) side-by-side, and can click any stage to focus it (`setPreview({ ...(stage.media || {}), r: preview.r, c: stage.idx, label: stage.label, value: stage.value })`), upload to it (`pickUpload(preview.r, stage.idx)`), or run it in-place (`runInPlace([previewRow.rid], { singleStep: true, capability: stage.type === 'video' ? 'video_gen' : 'image_gen', col_index: stage.idx })`)!
4. **Quick Preset Chips for Optical Rig, Camera Motion, Jutsu Mode & `@Assets` (`ui/src/SheetWorkspace.jsx`)**:
   - Define studio presets (either in `ui/src/SheetWorkspace.jsx` or imported from a small module `ui/src/studioPresets.js`):
     - **Optical Rig / Camera**: `["ARRI Alexa 65 / 35mm Anamorphic f/1.4", "RED V-Raptor / 85mm Prime f/1.8", "35mm Film / Vintage Anamorphic", "16mm Bolex Vintage Film", "DV Camcorder / Clean Sharp"]`
     - **Camera Motion**: `["Slow Dolly Push-In", "Tracking Shot", "Static Tripod", "Handheld Urgency", "Crane Rise High-Angle", "Drone Orbit 180°", "Rack Focus", "Whip Pan", "POV"]`
     - **Jutsu Mode**: `["Motion Transfer", "Object Swap"]`
   - When `editing` is active on a matching column (by header regex `/optical|rig|lens|camera(?!\s*motion)/i`, `/motion|movement/i`, `/jutsu|mode/i`, or `/prompt|cast|reference/i` for `@CAST-01` / `@SET-01` chips), render clickable `.preset-chip` buttons inside `.sheet-edit-strip` (and in the row inspector) that set or append the preset into `text`.

---

### 2.5 Fix #5: Enhance `FlowSurface` (`Comfy Pipeline`) as Pipeline Architecture Manager (`ui/src/FlowSurface.jsx`, `ui/src/FlowPanels.jsx`, `ui/src/flowModel.js`)
Keep `FlowSurface` clean and dedicated to pipeline management:
1. **Executor Badge & Output Media Thumbnail on `WorkStep` (`ui/src/flowModel.js` & `ui/src/FlowSurface.jsx`)**:
   - In `flowToCanvas(definition, selectedIds = [], tabs = [], tasks = [], agents = [], workers = [])`:
     - Compute `executorLabel` for each node:
       - If `node.agent_key`: find agent in `agents` or display `🤖 ${node.agent_key}`.
       - Else if `node.limb_id`: find worker in `workers` or display `🔌 Worker`.
       - Else display capability badge (`🎨 Image`, `🎬 Video`, `🎞️ Media`, `🤖 LLM`).
     - Find the latest succeeded task for `node.id` in `tasks` that has `output?.asset_url` and attach `latestMediaUrl = task.output.asset_url` to `node.data`.
   - In `WorkStep` (`ui/src/FlowSurface.jsx`):
     - Render `<small className="flow-executor-badge">{data.executorLabel}</small>`.
     - When `data.latestMediaUrl` is present, render `<div className="flow-node-media"><MediaCell compact value={data.latestMediaUrl} label={data.title} /></div>` inside the node card.
2. **Inline `<MediaCell>` in `FlowPanels.jsx` (`TaskResult`)**:
   - In `TaskResult` (`ui/src/FlowPanels.jsx` around line 93), when `task.output?.asset_url` matches the asset pattern, render `<MediaCell compact value={task.output.asset_url} label={task.id} />` alongside the download link.

---

## 3. Verification & Acceptance Criteria

Run and verify:
```powershell
npm test --prefix ui
npm run build --prefix ui
python -m unittest discover -s tests -v
```
1. **Unit Tests (`ui/tests/`)**:
   - Verify `sheetViews.js` includes `video` columns in `coverColumns` and populates `mediaChain` and `assetRefs` on cards.
   - Verify `flowToCanvas()` attaches `executorLabel` and `latestMediaUrl` when tasks have `output.asset_url`.
   - Verify `SheetWorkspace` does not clear `preview` or `panel === 'row'` when `assistantOpen` is true.
2. **Build Verification**:
   - Run `npm run build --prefix ui` and ensure zero build warnings/errors and updated `static/projects/` assets.
