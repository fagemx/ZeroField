# Canvas integration verification

Implemented the M2/M4/M5 canvas integration against `docs/EXECUTION_API.md`.

- `CanvasViews.jsx` exports the standalone sheet and flow surfaces; simulated execution and fictional provider selections were removed.
- Flow definitions load once per mounted tab and persist with optimistic revisions. Editing or polling run progress does not reset unsaved node drafts. Users can add/delete/drag nodes, connect branches and joins through ports, remove edges, configure capability and registered worker binding, source tabs, output table/cell targets and reviewed/direct write mode.
- Runs save dirty definitions before starting and use durable API runs. The UI polls workers, run history and selected run details; it displays real task states, approval waits, errors and outputs, and provides creator/admin cancel and retry controls.
- Sheet selections pass `target_tab` and `row_ids` through per-project session storage to the selected workflow. The flow offers full-graph or selected-row execution.
- Sheets poll real tasks for row progress and reload completed outputs while preserving an actively typed formula draft. Media uploads render image, video or audio previews, with image enlargement.
- Excel TSV paste uses atomic `/table-edit` with `base_revision`, including mixed ordinary/status/fill cells and appended rows. Multiple imported worksheets are selectable. Column add/delete/type controls remain available. CSV exports only the current worksheet, with current field values and proper quoting; Excel export keeps the server's workbook handoff.
- Row history uses the existing history API and includes field-backed changes. Existing document view remains available for annotations and restoration.

Verification performed:

- `cd ui; npm test`: 39 tests passed, 0 failed (includes graph branch/join/cycle handling, legacy capability migration, selection validation, task progress, quoted TSV, mixed field paste payloads, CSV quoting, imported Excel formula row offsets).
- `cd ui; npm run build`: passed; Vite generated the production bundle in `static/projects`.

Main agent is performing browser/API integration acceptance on the isolated development database. No live model inference or external provider costs were incurred by these frontend checks. Real generation requires a registered worker with a matching capability polling its claim loop; disconnected capability errors are shown on the canvas.
