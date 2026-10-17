# M0 / M1 backend review

Reviewed and revalidated 2026-10-16 against `docs/PRODUCTIZATION_ROADMAP.md` and `docs/file-handoff-report.md`. Scope: file handoff, repository/service/schema/HTTP integration, table proposals, and assistant privacy boundaries. Engine, later authentication, and UI work are outside this review.

## Final scoped verdict after corrections

**Specification verdict: passes the six reviewed acceptance issues.** All six original findings below are resolved in the current implementation and targeted verification. The broader M0/M1 completion claim still carries the documented Office structural-edit and formula-recalculation limits. This is not a full UI, authentication, engine, or whole-repository acceptance verdict.

**Quality verdict: passes this targeted follow-up review.** No unresolved blocker remains among these six findings. The earlier findings are retained below as historical evidence, not outstanding issues.

| Original finding | Follow-up evidence | Result |
| --- | --- | --- |
| 1. Numeric masking leaks | `mask_text` handles signed values and currency prefixes; whole and inline formulas use `mask_formula`, whose numeric operands over 100 are masked. Fresh regression covers the exact negative, currency, year-like formula constant and Markdown inline formula cases. | Resolved |
| 2. Deleted-row resurrection | Missing `put_row` targets with non-null `base` now produce `gone`; proposal regression returns 409 without invoking persistence. Explicit null-base new rows still work. | Resolved |
| 3. Partial application after lock change | `_run_ops(..., atomic=True)` returns an unchanged document before persistence on any conflict; the proposal caller checks the result before field writes. Fresh two-row lock-change test confirms no `save_tab_doc` call. `lock_unit` also acquires the shared tab row lock. | Resolved |
| 4. Concurrent manual field overwrite | `set_field` acquires the same `get_tab_for_update` lock as proposal application. A real PostgreSQL concurrent writer waited on that lock; a proposal based on the old field state then returned 409 without overwriting the manual update. | Resolved |
| 5. Synthetic DOCX paragraph text loss | DOCX top-level tables are now represented and cell text patches are supported. `_docx_patch` rejects changed nodes beyond the imported source mapping. Fresh table-only DOCX test verifies both safe cell export and refusal of changed unmapped trailing text. | Resolved |
| 6. Large-sheet row IDs clipped | Sheet reads now put `table_id` and `row_id` on each row, bound output before the global clip, and expose `offset`/`limit` in the tool schema. Fresh first-page and later-page regression verifies IDs and continuation instructions. Document tabs can explicitly use `offset` for table pagination. | Resolved |

Fresh commands executed during follow-up:

- `python -m unittest discover -s tests -p test_file_handoff.py -v`: **14 passed**, exit 0.
- `python -m unittest discover -s tests -p test_table_proposals.py -v`: **8 passed**, exit 0.
- PostgreSQL probe against the supplied local test server: created only unique project `review-4213e4363db34b`, with one sheet and one initially absent fill-field value. Connection A held the tab row lock; connection B called the real `service.set_field`. An independent connection observed connection B in PostgreSQL `wait_event_type='Lock'`, and its call had not finished. Connection A successfully applied and committed the field proposal; connection B then completed and committed its manual value. Final field value was `manual-after`, proving the manual write occurred after the proposal rather than being overwritten inside it. Reapplying the old prepared target returned **409**. The probe deleted its unique project and cascading data in `finally` and closed all connections.

Only this report was edited by the follow-up reviewer. No production source, tests, or shared demo data were modified. This follow-up adds live PostgreSQL evidence to the earlier mock-based review.

## Original review findings — historical, resolved above

Original specification and quality verdicts were **changes required**. All four formats, private source storage, versioned reimport, reanchoring, export endpoints, project privacy configuration, and cross-tab proposals were present, but the original implementation had the reproducible failures below. Original Office structural editing was explicitly refused rather than supported; this remains a documented limit of the broader file handoff goal.

### Original actionable findings

### 1. P1 — Masked projects still send common monetary forms to the model

Location: `project_assistant/privacy.py:14` and `:19-20`, using `project_assistant/masking.py:16` / `:39-73`.

Every model boundary now calls `guard_input` / `mask_text`, but that free-text matcher deliberately exempts digits adjacent to a minus sign or ASCII letters. This leaks ordinary negative amounts and currency-prefix notation. Formula constants also need formula-aware handling rather than only the free-text ID heuristic. This applies to user input, historical text, imported text, tool results, and `read_page` content.

Executed:

```python
from project_assistant.privacy import sanitize
for value in ['Loss -128500 dollars', 'Budget USD128500', '=B2-128500']:
    print(sanitize(value, 'mask_numbers'))
```

The negative/currency amounts remain present. A separate probe returned `=▢+2000` for `=1000+2000`, retaining a monetary constant under the year exception. Year/identifier exemptions should be context aware; at minimum currency prefixes, signed values, and formula numeric operands must not bypass the boundary.

### 2. P1 — An edit proposal resurrects a row deleted after proposal creation

Location: `project_assistant/table_edits.py:102-104`, delegating to `project_docs/blocks.py:189-209`.

The preflight treats `put_row` for a missing row as an insertion even when its `base` contains an existing row. Deleting a row after proposal generation therefore does not yield a stale conflict. Acceptance restores the old row, including untouched old cells, at the end of the table. A proposal containing multiple row edits can silently restore content another collaborator deliberately removed.

Executed with an imported CSV `Shot,Prompt\nS01,old\nS02,keep\n`: prepare an edit to S01's second cell, remove S01 from a copy of the current document, then call `blocks.apply_ops` with the prepared ops. Actual: `applied=1`, `conflicts=[]`, rows become `[header, S02, S01(new)]`.

Require an existing target when a proposal op has a non-null base. Reserve missing-row insertion for explicit new rows with null base. Add a delete-after-prepare regression test through `table_edits.apply`.

### 3. P1 — A lock acquired between preflight and save allows partial proposal application

Location: `project_assistant/table_edits.py:102` and `:109-112`.

The preflight calls `blocks.apply_ops` with one lock snapshot. `_run_ops` independently reads locks again and supports partial application, but the caller ignores its conflicts and always reports success. `lock_unit` does not acquire the tab row lock, so another member can obtain a unit lock while the proposal holds `get_tab_for_update`.

Executed a deterministic test with two row edits and `repo.tab_locks` returning `{}` on preflight, then `{second_row_id: 'other'}` inside `_run_ops`. Used the real `_run_ops`, mocking repository persistence only. Actual: HTTP-style status 200, `applied=1`, `save_tab_doc` called once, first row changed and second row unchanged. Field edits would still all be written afterward.

Apply a single preflight result atomically or give `_run_ops` an explicit all-or-nothing mode that checks conflicts before saving. Merely checking `result.conflicts` after `_run_ops` returns is too late because `apply_proposal` records failures and returns status 200, so its transaction is committed.

### 4. P1 — Field optimistic checks do not serialize against manual field writes

Location: `project_assistant/table_edits.py:105-111`; interacting with `project_docs/service.py:set_field` and `project_docs/repository.py:set_field_value`.

The proposal holds a tab row lock but checks `field_values` using an ordinary SELECT. The manual `set_field` path reads its tab without `FOR UPDATE`. A collaborator can therefore commit a field change after the proposal's base check and before its call to `set_field_value`; the latter locks/reads the new field value but unconditionally overwrites it, without comparing the base again.

Confirmed from lock/read/write ordering; no live PostgreSQL race test was run. Timeline: proposal reads base A; manual field endpoint writes/commits B without needing the held tab lock; proposal writes C and returns success. This loses B despite the claimed stale-field protection. Serialize all tab field writes on the same tab lock or lock and compare each field at the actual write boundary, including the absent-field insertion case.

### 5. P1 — Editing the synthetic paragraph of a table-only DOCX silently loses text on export

Location: `project_docs/file_handoff.py:204` and `:338`.

DOCX intake maps only actual top-level paragraphs. `validate_doc` supplies an editable empty paragraph when the source has none, but `paragraph_indices` remains empty. `_docx_patch` uses `zip(old, new, paragraph_indices)` and silently ignores unmatched canvas nodes. The structure check passes because the synthetic paragraph was already in the saved baseline.

Executed:

```python
import io
from docx import Document
from project_docs import file_handoff as f
doc = Document()
doc.add_table(rows=1, cols=1).cell(0, 0).text = 'Table'
buf = io.BytesIO()
doc.save(buf)
raw = buf.getvalue()
parsed = f.import_file('table.docx', raw, slug='demo')
assert parsed.metadata['paragraph_indices'] == []
parsed.doc['content'][0]['content'] = [{'type': 'text', 'text': 'new canvas text'}]
output = f.export_file(parsed.doc, 'docx', source_blob=raw, source_meta=parsed.metadata)
assert Document(io.BytesIO(output)).paragraphs == []
```

The export succeeds and the new text disappears. Either persist a mapping for the synthetic paragraph and insert it safely or refuse edited unmapped text with `HandoffError`, consistently with the XLSX policy.

### 6. P2 — Long tables lose every row ID at the model output limit

Location: `project_assistant/tools.py:146-151` and `:536`.

`read_page` first renders the entire document, then appends a second rendering with editable table/row IDs. `call` clips the result to 7,000 characters. For normal storyboard prompts, the first rendering consumes the entire budget, and none of the IDs required by `propose_table_edit` reach the model. There is no row pagination/range parameter to retrieve them; `section` cannot divide a single large table.

Executed with 30 CSV rows, each containing `'long prompt ' * 40`: `_clip(read_page(...))` returned 7,020 characters including the truncation notice, with no `table_id=` and no first data row ID.

Render each row once with its ID and provide bounded table/row pagination or a lookup tool so rows later in the sheet remain reachable.

## Preservation and limit observations

- The original-format no-change shortcut returns exact original bytes. Changed XLSX output keeps other ZIP parts and existing style IDs; changed DOCX output preserves run properties and unrelated parts. Existing tests substantiate these narrow guarantees.
- XLSX structural changes, merged non-anchor edits, and shared/array formula edits are intentionally rejected. DOCX tables and non-paragraph structures remain in the source but are not represented/editable on canvas. These limits should remain explicit in product completion claims.
- Formula caches are not invalidated and `calcPr` is preserved. A workbook with manual calculation / `fullCalcOnLoad=False` and cached B2=2400 for `=A2*2` still exports cached B2=2400 after changing A2 from 1200 to 2400. This was reproduced with `openpyxl(data_only=True)`. The implementation report explicitly assigns calculation to spreadsheet applications, so this is recorded as a known limitation rather than a separate confirmed automatic-calculation defect. Consider explicitly forcing recalculation or warning when export retains manual calculation.
- Upload bytes, ZIP expansion/entry counts, XML entity denial, cell/row/column counts, UTF-8 intake, private source metadata, and locked revision checks are implemented. No additional proven destructive XLSX defect was found within this review.

## Verification

- `python -m unittest discover -s tests -p test_file_handoff.py -v`: 13 passed.
- `python -m unittest discover -s tests -p test_table_proposals.py -v`: 4 passed.
- Additional small in-memory probes reproduced findings 1, 2, 3, 5, and 6 as described above. Finding 4 is based on the database lock ordering in the actual code.
- No source files changed by this review. No full PostgreSQL or browser integration result is claimed. Primary agent was sent these findings while review was ongoing and is implementing corrections separately.
