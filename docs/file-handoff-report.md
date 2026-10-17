# M0 file handoff and M1 project setting implementation report

Implemented in the shared workspace without commits. Existing service.py project-template edits were retained.

## Public HTTP contracts

- `POST /projects/api/<slug>/tabs/import`: raw request body, `X-File-Name` header (URL-encoded UTF-8 supported). The extension determines the parser; the client MIME is not trusted. Creates a tab by default. Returns `{tab, tabs, changes}`.
- `POST /projects/api/<slug>/tabs/import?tab_key=<key>&base_revision=<n>`: replaces a live tab. The current tab is locked with PostgreSQL `FOR UPDATE`, and `base_revision` is mandatory. Missing/invalid revision returns 400; stale revision returns 409 with current revision. Another member's active unit lock returns 409. Reimports create a revision even when only the binary file formatting changed.
- `GET /projects/api/<slug>/tabs/<key>/export?format=xlsx|docx|csv|md`: attachment download with private/no-store caching. Leading dots in format are accepted. Omitting format uses the source format, then xlsx for sheets / md for documents.
- `POST /projects/api/<slug>/meta`: accepts `privacy_mode: full_access | mask_numbers`. Only admin can set the property. The create-project API also validates and supports this setting; only admin can create in mask_numbers mode. Existing projects migrate to full_access.

The HTTP owner should retain the normal authentication, write-origin checking and transaction handling when integrating further routes. New import/export routes are already registered. `_raw_body` additionally rejects negative lengths and incomplete request bodies.

## Python interfaces

`project_docs.file_handoff`:

- `import_file(filename, data, *, slug) -> ImportedFile`: fields `doc`, `surface_type`, `filename`, `mime`, `metadata`.
- `export_file(doc, fmt, *, source_blob=None, source_meta=None) -> bytes`.
- `reconcile_ids(old_doc, new_doc) -> doc`: stable unique text/full-row matches, then first-column row keys, then matching positions. Preserves matched block/row ownership and timestamps. Ambiguous duplicate rows cannot be guaranteed semantic identity.
- `HandoffError`: bounded parser and safe-export validation error, returned as 400 by service.

`project_docs.service`:

- `import_tab_file(conn, me, slug, filename, data, *, tab_key=None, base_revision=None) -> (status, payload)`.
- `export_tab_file(conn, me, slug, key, fmt='') -> (status, payload)`. Success payload has binary `data`, `content_type`, `filename`; HTTP streams this directly and never JSON-serializes bytes.

`project_docs.repository`:

- `get_tab_source(conn, slug, key)` returns private `{filename,mime,blob,metadata}`.
- `set_tab_source(conn, slug, key, *, filename,mime,blob,metadata,surface_type)`.
- `save_tab_doc(..., force_revision=False)` additionally supports a separate import revision.
- `update_project_meta(..., privacy_mode=_UNSET)` validates allowed modes. List/get project return `privacy_mode`.

Public tab objects expose only `source_filename` and `source_mime`. The binary source, server baseline and source coordinate map stay private. Existing source metadata is intentionally not part of model-visible tab documents.

## Schema and UI metadata

`149_project_docs_schema.sql` adds `project.privacy_mode`, and `tab.source_filename`, `source_mime`, `source_blob`, `source_meta`, `linked_path` using idempotent ALTER statements. This migration is already included in `repository.SCHEMA_FILES`; no separate unregistered migration was introduced.

All workbook worksheets become separate table nodes in one sheet tab. Tables carry both `worksheet_name` and `sheet_name` aliases. `validate_doc` preserves these and `column_types` arrays containing text/number/formula/image/video/audio/status. Header row is source row 1; document tables retain all source rows, so source coordinates never shift merely because UI hides a header.

Private `source_meta` stores the validated source baseline and ordered workbook worksheet names/XML paths, or DOCX top-level paragraph child indices. Reimport reconciliation replaces the stored baseline with the newly aligned document, so the new binary remains the next export's base. Reimport records `doc_changes`, a revision, an audit event and calls existing `reanchor_tab` in the same transaction.

Identity now consumes the clean `directory_registered` flag requested by the primary agent. Role labels include writer/art_lead/member/viewer.

## Preservation guarantees and explicit limits

- Export without any document change in its original format returns the exact original bytes for XLSX, DOCX, CSV and MD.
- XLSX value edits use openpyxl for reading/coordinate validation and patch only affected worksheet XML in the original ZIP. Every untouched ZIP entry retains its uncompressed bytes and original ZipInfo metadata. Numeric values remain numbers, formulas remain formulas, existing cell style IDs remain. Other sheets, styles, charts and unknown ZIP parts are retained.
- Office structural changes (row/column addition, deletion, reordering or top-level document structure changes) are refused for source-preserving export, with an explanatory 400 instead of destructive rewriting. XLSX text edited outside worksheet tables is refused. Use a new tab or another supported export format for a clean conversion. CSV export requires exactly one table and refuses multi-sheet loss.
- Editing a shared/array/data-table formula or the non-anchor cell of a merged range is refused. No formula engine runs on the server; spreadsheet applications are responsible for recalculation.
- DOCX currently displays top-level body paragraphs. Existing tables, headers, footers, drawings, fields and attachments stay in the original ZIP but are not editable canvas representations. Text edits redistribute text across existing text runs and retain run properties; unchanged runs/other paragraphs and all other ZIP entries are preserved. Edited paragraphs containing fields, drawings, tabs, breaks or symbols are refused. Canvas inline typography changes are not translated into Office formatting: the original Office formatting is retained.
- MD/CSV edited exports are clean textual conversions. Original text bytes/line endings are preserved only when unchanged. Clean DOCX/XLSX export from an unsourced tab is supported and does not promise original-file fidelity.
- Import does not open local filesystem paths or follow uploaded links. `linked_path` is reserved schema metadata, not used as an arbitrary server file read facility.
- 8 MB upload, 64 MB total archive expansion, 16 MB per ZIP entry, 2,000 ZIP entries, bounded compression ratio, 20,000 workbook cells, 10,000 rows/paragraphs and 100 columns. Text must be UTF-8 (optional BOM). Duplicate/path-traversal ZIP entries, encryption, XML entities/DOCTYPEs and malformed files are rejected.

## Verification

`python -m unittest discover -s tests -p test_file_handoff.py -v`: **13 tests passed**.

Covered original bytes and multi-sheet visibility; XLSX value/styles/formula/untouched-part preservation; merged cells, table structure and unmapped text rejection; DOCX run and other-part retention; DOCX field refusal; CSV and Markdown round trips/conversion; row IDs after insertion plus changes; malformed inputs/compression bombs; stale and missing revisions; edit locks; reimport revision/source baseline/reanchor service behavior; privacy authorization and invalid-value checks.

`python -m compileall -q project_docs`: passed.

The primary agent owns final cross-milestone PostgreSQL and HTTP integration testing. This subtask used narrow repository mocks for transactional service behavior; no PostgreSQL integration result is claimed here. Runtime dependencies used: openpyxl 3.1.5, python-docx 1.2.0 (lxml transitive dependency).
