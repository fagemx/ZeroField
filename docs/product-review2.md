# Product completion review 2 — 2026-10-16

Read-only review of the current sheet/media/flow UI, executable templates, project creation, Office export recalculation flags, asset metadata route, and packaging. Implementation and tests were not modified; no server or database was changed. Main agent owns live UI, end-to-end, and full-suite verification. Findings below are against the snapshot reviewed and may be resolved by subsequent parallel work.

## Scoped re-review

**Final scoped verdict: all findings from this review are resolved.** Rechecked the final two fixes: annotation-panel `pick` now returns before navigation when flow flush fails; CSV transformation preserves the `LOG10` function name and complete quoted/unquoted sheet-qualified ranges while shifting local references. Fresh `node --test ui/tests/sheet.test.mjs` passed **7/7**, including those regression cases. No implementation changes were made by this reviewer. Browser smoke, archive rebuild, and the full-suite verdict remain the main agent's verification responsibility.

The original native XLSX formula-coordinate/numeric-type reproduction is fixed. Fresh verification: `python -m unittest discover -s tests -p test_file_handoff.py -v` passed **15/15**; `node --test ui/tests/sheet.test.mjs` passed **7/7**. Native ordinary references shift by the header row, numeric columns export as numbers, and imported XLSX addresses remain unchanged. Source worksheet/status-column selectors are present, source-tab changes clear obsolete selection, and the manifest now includes JSON examples. Manifest source configuration was inspected; the main agent owns rebuilding/inspecting release archives and browser smoke.

Two narrower follow-ups were found in the first re-review and are now resolved (historical details):

1. **[P2] Frontend CSV formula rewriting changes non-cell tokens and part of external ranges.** `ui/src/sheetModel.js:78` applies a cell-reference regex to complete unquoted formula fragments. Direct Node execution produces `=LOG11(A2)` from `=LOG10(A1)` and `=SUM(Sheet2!A1:B4)` from `=SUM(Sheet2!A1:B3)`. This silently rewrites a function identifier and the second half of a sheet-qualified range. The backend token-based path avoids those particular mutations. Preserve complete function/name/nonlocal-range tokens or delegate CSV formula translation to the server's export path.
2. **[P2] Annotation-panel navigation still ignores a failed flush.** Flow now registers a save-aware `controlRef`, normal `navigate`/hash changes respect `false`, and switching to document mode saves. But `App.jsx:301` (`pick`) awaits `flush()` and proceeds regardless of its return value. With a dirty graph and a failed save (e.g. definition revision conflict), clicking an annotation on another tab still unmounts the flow and loses the draft. Apply the same false-return guard there.

## Original findings (retained as review history)

### [P1] Preserve native sheet formula coordinates and numeric types during export

Locations: `project_docs/file_handoff.py:438–439`, `ui/src/sheetModel.js:76`, and the marketing template in `project_docs/templates.py`.

Native sheet formulas use data-row-relative addresses: the first marketing row displays `=D1/C1` as 1.55. Clean XLSX export appends the header and leaves that formula unchanged. An in-memory reproduction using `templates.tab_specs`, `markdown_to_doc`, `export_file`, and `openpyxl.load_workbook` produced:

```text
C1 = 花費; D1 = 營收
C2 = '12000' (string); D2 = '18600' (string); E2 = =D1/C1
C3 = '8500' (string); D3 = '11900' (string); E3 = =D2/C2
```

Thus the first exported ROAS references headers and the next row computes the previous row. The frontend CSV export has the same added-header/raw-formula combination. Declared number columns also export as text in clean XLSX, so Excel SUM over those cells ignores them. Translate native formula coordinates into workbook coordinates and emit actual numbers for declared numeric columns, preserving intentional textual identifiers. Imported XLSX already uses worksheet coordinates and must not receive another offset. Setting recalculation flags does not correct wrong references or cell types.

### [P2] Guard internal navigation while a workflow has unsaved changes

Locations: `ui/src/FlowSurface.jsx:73–76`; `ui/src/App.jsx:200–231`, `534–545`.

The dirty graph installs only a `beforeunload` guard. App tab navigation uses pushState/hash state and flushes `surfaceControl`, which is connected only to the document surface. Reproduction path: change a prompt, drag a node, or add a connection; click another project tab; return to the flow. The keyed flow component has unmounted and reloads the stored definition, discarding the changes without a save/discard choice. Expose a flow flush/navigation guard to App or retain the draft across tab switches. The normal browser reload warning does not protect in-app navigation.

### [P2] Expose the source worksheet and status column in workflow configuration

Location: `ui/src/FlowSurface.jsx:149`.

The “來源表格” control selects only a tab; there is no control for the available `row_source.table_id`. A full rows run on a multi-worksheet imported XLSX consequently expands rows from all worksheets, including reference or summary sheets. The “只處理狀態” input also never supplies `status_col`, so the head's documented fallback matches any cell with that text. A completed row whose note says `未開始` can therefore be included as an unstarted row. Read the selected source tab's tables, offer a worksheet/table selector, and resolve a specific status column for status filtering. Explicit sheet-row selections are a workaround but do not fix full-flow authoring.

### [P2] Include the production worker configuration example in the source distribution

Location: `MANIFEST.in:6`.

The manifest includes only `examples/*.py`; the new `examples/worker.example.json` is excluded. `docs/WORKERS.md:7–10` directs users to launch the production worker with that exact file, so the documented command fails from an extracted sdist. Include JSON examples and verify the new example is present in the rebuilt source archive. This finding concerns the source distribution, not a requirement to ship editable examples inside the installed wheel.

## Confirmed integrations and scope

- New project creation persists executable graphs via `flow_runner.save_definition`; the drama project also creates its `deliverables` output doc.
- Template graph scopes are explicit: drama split once, image/video per row, final assembly once after aggregation; marketing writes a doc proposal and art writes row outputs.
- Sheet comments use the existing row-annotation endpoint and reload project annotations; lock badges consume the shared lock representation.
- Bare project asset URLs can query the metadata endpoint and choose media rendering. Video/audio metadata events supply duration and resolution.
- Modified imported XLSX files set automatic/full recalculation flags while unchanged source bytes remain preserved.
- No new blocker was identified in the asset metadata endpoint or Docker/package layout within this review. Docker execution and provider behavior were not exercised here; separate reviewers own DAG/head and worker runtime correctness.
