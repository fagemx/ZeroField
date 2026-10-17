# Scoped DAG independent review — 2026-10-16

Read-only review of Task 1 (`flow_runner.py`, `table_edits.py`, execution schema and tests); no implementation changes. Used the existing isolated PostgreSQL at `127.0.0.1:55433`, unique test projects, and fixture cleanup. Read AGENTS, original roadmap, completion plan/report, acceptance/deployment and execution API docs.

## Findings

### Final targeted verdict

**All three reported findings are resolved.** The final fix persists `execution.selection_tabs`, restricts selected aggregate source/target tab rows consistently across `rows`, `tables`, and rendered `text`, and preserves complete reference tabs. Independently repeated the exact previously failing `start_node_id='assemble', row_ids=['b_shot2'], target_tab='shots'` case without an aggregate `row_source`: all three representations contain only shot2. Also ran `test_flow_scopes.ScopedFlowTests.test_selected_aggregate_restart_filters_source_tab_but_keeps_references` against PostgreSQL: **1 passed, 0 skipped**. Reference content remained intact, including a reference table with the same row IDs.

Together with the preceding 15-test re-review (including actual HTTP uploads and FFmpeg assembly), this closes this review's findings. No remaining blocker was found within these three targeted corrections; this is not a claim to have re-reviewed unrelated changes or external model services.

### Intermediate targeted re-review (superseded by final verdict)

**Verdict: #1 and #3 resolved; #2 partially resolved, with selected aggregate tab inputs still inconsistent.** Re-ran `python -m unittest test_flow_scopes test_production_pipeline -v` against the same PostgreSQL: **15 passed, 0 skipped**. This includes real HTTP worker claim/upload/complete, approved scope regressions, dynamic two-shot expansion, actual FFmpeg assembly, and ffprobe verification of the final movie.

- **#1 resolved:** the fresh schema and idempotent existing-workspace constraint migration now allow every MIME type returned by `media.validate`. Independently repeated MP4 and WAV database writes successfully; the production-pipeline test persisted and fetched the actual MP4 through HTTP.
- **#2 partial:** explicitly supplied aggregate `row_source` is now frozen and filtered in both structured rows and rendered source-tab data; the new empty/status regression passes. The original selected-row case without aggregate `row_source` still reproduces: `image(rows, source=shots/b_table) -> assemble(aggregate, input_tabs=['shots'])`, start with `start_node_id='assemble', row_ids=['b_shot2'], target_tab='shots'`; `input.rows` contains only `b_shot2`, but `input.tabs[0].tables[0].rows` and `text` still contain both shots. Selection must also filter the relevant source/target tab in this supported path, preserving unrelated reference tabs.
- **#3 resolved:** document delivery now constructs a safe ProseMirror link mark. Reviewed delivery persists the exact mark, and direct movie delivery passes the production test.

Original findings and their reproduction evidence follow for traceability; the verdict above supersedes their original unresolved status.

1. **[P1] Video/audio assets cannot be persisted by the shipped schema.** `db/149_project_docs_schema.sql:123` allows only four image MIME types; `repository.ensure_schema()` contains no migration widening this constraint. A real `repo.put_asset(conn, slug, data=b'fixture', content_type='video/mp4', actor_id=actor)` on a fresh test project throws `psycopg.errors.CheckViolation: asset_content_type_check`. The bytes do not affect this SQL MIME constraint. Consequently a successfully generated MP4 cannot reach its sheet/document target, and the complete script-to-film path is blocked. Add an idempotent migration for the formats accepted by `project_docs/media.py`, and exercise actual MP4 and audio upload through HTTP into PostgreSQL (not only a mocked head or PNG fixture).

2. **[P2] Starting at an aggregate bypasses row-source status filters.** `project_assistant/flow_runner.py:431` evaluates `_source_rows()` only for `scope='rows'`; `_inputs()` filters aggregates only against previously frozen IDs (`:597`). Reproduction using `ScopedFlowTests`: save `image(rows, row_source=shots/b_table) -> assemble(aggregate, input_tabs=['shots'])`, then start with `start_node_id='assemble', row_source={'tab_key':'shots','table_id':'b_table','status':'absent'}`. Claiming `assemble` returns `input.rows=['b_shot1','b_shot2']`, although neither row matches. This affects the documented restart-at-aggregate use case. Freeze/filter an aggregate's explicitly supplied source even when no row stage executes. Also make the effective selection consistent in source-tab `text` and `tables`: a selected aggregate run (`row_ids=['b_shot2'], target_tab='shots'`) currently has only shot2 in `rows` but both shots in `tabs`; an empty selected set still leaves all table media available to fallback consumers.

3. **[P2] Document media delivery is plain text, not a usable link.** `project_assistant/flow_runner.py:711-725` builds `[產出媒體](asset_url)` and puts it in an unmarked ProseMirror text node. Reproduced through actual `complete()` with `write_mode='direct'`, a valid stored image asset, and `target={'kind':'doc','tab_key':'report'}`: task succeeds, but the saved paragraph contains only `{'type':'text','text':'[產出媒體](/projects/api/.../assets/pa_...)'}` with no link mark. The document editor consumes structured JSON, not Markdown. Deliver a text node with the existing safe `link` mark (or an appropriate supported media block), and assert the persisted mark after direct and reviewed delivery.

## Checks that passed and limits

`OPENBENCH_TEST_DB_URI=postgresql://postgres@127.0.0.1:55433/postgres PYTHONPATH=tests python -m unittest test_flow_scopes test_table_proposals -v`: **20 passed, 0 skipped**. These cover dynamic expansion after approval, stage barriers, ordered join, empty row stages, retry/cancel/reconnect, doc revision conflicts, and disjoint/same-cell proposal behavior.

No additional demonstrable corruption, permission bypass or concurrency defect was found in the new cell-merge logic during this review. Existing run-lock/unique-task machinery and immutable graph separation remain intact. This is not a complete review of legacy execution or external providers. Initially all three findings blocked acceptance; subsequent targeted checks verified the corrections, including actual video upload and assembly and the final selected-aggregate input fix.
