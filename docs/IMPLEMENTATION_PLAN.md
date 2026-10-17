# OpenBench productization implementation plan

**Goal:** Deliver the M0–M7 workflows in PRODUCTIZATION_ROADMAP.md as working, tested software.
**Architecture:** Retain the existing PostgreSQL repository, transactional service layer, React canvases, block operations, revision history and human-approved proposals. Add focused file, table, worker, workflow and authentication modules around those interfaces.
**Spec:** [PRODUCTIZATION_ROADMAP.md](PRODUCTIZATION_ROADMAP.md)

**Completion:** Follow-up scope and adapter work is recorded in [ROADMAP_COMPLETION_PLAN.md](ROADMAP_COMPLETION_PLAN.md); final requirement-by-requirement evidence is in [ROADMAP_COMPLETION.md](ROADMAP_COMPLETION.md).

## Constraints and decisions

- All work stays in this repository. Preserve pre-existing edits to AGENTS.md, the Roadmap and service.py.
- User has authorized implementation of the supplied design through completion. Use local branch codex/productization; no remote publication.
- Binary source files stay server-side. Preserve untouched Office ZIP parts; document unsupported edits instead of claiming arbitrary Office round-trip fidelity.
- File reimports and proposals use optimistic concurrency and existing locks, revisions and reanchoring.
- The default privacy mode is full_access. mask_numbers applies at every model/worker boundary, including prior conversation history.
- Remote workers use expiring task leases and authenticated completion; they never execute arbitrary server shell commands.
- DAG runs persist state and release a node only after all predecessors succeed. No simulated UI timers.
- Token/header auth fails closed; dev identity switching is limited to dev mode.

## Tasks

- [x] 1. M0 file handoff: implement file_handoff.py, repository/source metadata, import/export HTTP routes; test XLSX/DOCX/CSV/MD round trips, stale imports, annotations and malformed uploads.
- [x] 2. M0/M1 assistant: table proposal tool and apply path using current row bases; project privacy setting at input, output and history boundaries; test approval, concurrency and masking.
- [x] 3. M2/M4 canvases: file drop/import/export, media upload/preview, selection and batch prompts, TSV paste, column types/add/delete, workbook tables and row history. Test pure grid transformations and build React.
- [x] 4. M3/M5 execution: SQL worker registry/tasks and flow definition/runs; API claim/renew/complete/fail and cell assets; topology, forks/joins, persistence, retries/cancellation; test with PostgreSQL and local protocol worker.
- [x] 5. M6 authentication and member roles: dev/token/header modes, management API/UI, role enforcement, login experience; test unauthorized access and role changes.
- [x] 6. M7 delivery: pyproject, Docker/Compose, CI, worker example, setup/security/API documentation and regenerated static frontend.
- [x] 7. Acceptance: Python and JS suites, build, real PostgreSQL HTTP integration, browser smoke and independent code review; update Roadmap with verified state and limitations. Docker runtime/remote CI remain unexecuted, as recorded in ACCEPTANCE.md.

## Verification commands

```powershell
python -m unittest discover -s tests -v
npm test --prefix ui
npm run build --prefix ui
python server.py --embedded-db --no-worker --port 3020
```

## Progress ledger

Initial read: repository has the three canvases and templates; file handoff, durable flow execution, privacy setting and production authentication are absent. Existing uncommitted template additions are retained. Tasks share service/http/schema interfaces, so one delegated implementation runs at a time while the primary agent works on separate modules; integration and reviews are sequential.
