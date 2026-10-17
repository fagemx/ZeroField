# Execution and auth review — 2026-10-16

Reviewed baseline: `4ea8fbeafbed4814273740370ccab8e666070786` (plus current working-tree execution/auth implementation at review start). Scope: M3/M5 scheduler, workers, proposal integration and M6 authentication/member core. Read `PRODUCTIZATION_ROADMAP.md` and `EXECUTION_API.md`. UI and packaging are outside this review.

## Findings

### P1 — Approval can apply a result after cancellation has committed

Locations at review baseline: `project_assistant/service.py:257-274` (`_own_pending` / `apply_proposal`), `project_assistant/store.py:469-473,493-501`, `project_assistant/flow_runner.py:308-320,528-542`.

`_own_pending` reads a pending proposal without a row lock. Before `_write` starts, another transaction can cancel its run and dismiss the proposal. The approval transaction still uses its stale pending object, writes the table, and unconditionally changes the proposal to applied. `proposal_decided` then finds an already canceled task and does not undo the write. This violates the documented guarantee that cancellation dismisses pending outputs and only previously approved writes remain.

Reproduced with real PostgreSQL transactions and threads: pause `apply_proposal` immediately after `_own_pending` returns, commit `control(..., "cancel")` on another connection, then resume approval. Observed approval response 200, run `canceled`, proposal `applied`, and the canceled output present in the sheet. The inverse lock ordering is also unsafe: cancel locks the run then updates proposal, whereas approval updates proposal and only later locks the run; concurrent operations can deadlock. Concurrent approve/dismiss or duplicate approval share the unlocked decision problem.

Fix: resolve an associated execution run first, acquire its row lock, then lock and re-read the proposal before verifying pending status, then acquire the target tab lock. Use consistent `run -> proposal -> tab` ordering for approval/dismissal/cancel and do not write from a stale pending object. Lock ordinary proposals too, even when no run is associated.

### P1 — Worker credentials cannot download media required by downstream nodes

Locations at review baseline: `project_docs/runtime_http.py:13-30`; `project_docs/http.py:371-381,420-430`; `server.py:161-185`.

Workers receive project-relative asset URLs in predecessor outputs and rendered input tabs, but the runtime only authenticates worker POST actions. GET `/projects/api/<slug>/assets/pa_*` goes through member authentication. In token/header deployments, the worker bearer is not a member credential, so the image-to-video and media-assembly stages cannot retrieve the image/video/audio data required to execute.

Reproduced using the real `OpenBenchHandler`, `OPENBENCH_AUTH_MODE=token`, an uploaded project asset and a valid worker token scoped to that project: GET returned 401 `projects_login`. Existing execution HTTP tests replace member authentication with an always-admin stub, masking this integration failure.

Fix: support authenticated worker reads of the existing asset URL and check enabled status plus `allowed_projects` against the URL slug. Keep member reads working. Project-scoped access matches the current explicit registration contract granting project model inputs; an active-task lease is an optional narrower future policy, not necessary to repair the documented protocol. Invalid/revoked worker bearers must never fall through to the development-mode default admin. Test another project's asset and a revoked token in addition to the positive path.

### P1 — A deleted input/target can indefinitely block healthy queued work

Locations at review baseline: `project_assistant/flow_runner.py:395-419` (`claim`), especially `_snapshot` / `_inputs` outside the per-task failure handling; `project_docs/runtime_http.py:114-118` (request rollback).

An older queued run whose input or target tab is subsequently deleted causes `_snapshot` or `_inputs` to raise. The whole claim request is rolled back instead of recording that candidate as failed and continuing to later runs. The bad task retains `queued`, attempts 0, and remains first on every future poll. Because a worker can serve multiple runs/projects, the impact extends beyond the edited flow.

Reproduced: commit a run reading `shots`; delete `shots`; save and start a later valid graph with no tab inputs; poll three times with a worker eligible for both. All three claims returned 409 and both tasks remained queued with attempts 0. Separate commits matter because PostgreSQL `NOW()` is transaction-scoped and same-transaction fixtures otherwise create tied run timestamps.

Fix: treat expected input/snapshot preparation failures as failure of that candidate. Persist a useful error, advance the run, and continue scanning other tasks/runs within the same transaction. Preserve unexpected database errors as transaction failures. Add a deleted-target variant as well as deleted-input coverage.

## Validation and verdicts

Baseline validation: `python -m unittest tests.test_execution tests.test_auth -v` with `OPENBENCH_TEST_DB_URI=postgresql://postgres@127.0.0.1:55433/postgres`: **20 passed**, including PostgreSQL lease expiry/reclaim, graph fork/join, review gating, selected rows, persistence, optimistic target conflict, privacy, retry limit, creator revocation, worker project scope and auth unit checks.

The three findings above were separately reproduced against PostgreSQL. `docs/execution-review-repro.py` preserves the cases as tests asserting corrected behavior. Run it from the repository root with the same database environment variable; each test uses a unique project and cleans its data. It performs no provider calls or external inference.

**Baseline specification verdict: changes required before M3/M5 acceptance.** Persisted graph snapshots, capability routing, leases, row batching and proposal gating are present and the ordinary-path tests pass. The three failures break cancellation correctness, real multimodal handoff, and queue progress respectively. M6 auth core has token/header/dev separation and live member lookups; no ordinary-path authentication bypass was identified. This is not an assessment of the member-management UI or production reverse-proxy configuration.

**Code-quality verdict: sound decomposition, insufficient concurrency/integration coverage.** The scheduler has clear transaction boundaries and keeps worker code outside the server; snapshots and optimistic edits protect normal completion. However, proposal decisions need one consistent lock order, and errors while preparing a single task must not roll back scheduler progress for unrelated work. The existing HTTP fixture bypasses the exact member-versus-worker authentication distinction the protocol depends on. Add the real-handler and competing-transaction regressions before accepting the implementation.

## Fix re-review

The primary implementation agent fixed all three findings during the review. Inspected the current changes: `_own_pending` now acquires run then proposal locks before reading pending status, worker asset GET authenticates the enabled worker and enforces project scope and current privacy policy, and claim converts expected snapshot/input failures into a persisted task failure while continuing the queue.

Re-ran `docs/execution-review-repro.py -v`: **3 passed**. Its real-handler asset test also confirms a different project is denied (403), `mask_numbers` denies raw media (403), revoked credentials are denied (401), and an invalid worker bearer cannot fall through to the dev default admin (401). The concurrency test confirms cancel waits when approval already holds the run lock; the deleted-input test confirms a later healthy run can be claimed.

**Final scoped verdict: the three identified execution blockers are resolved.** No additional actionable authentication bypass was found in the reviewed core. This is an execution/auth code review and local protocol acceptance; it does not certify external image/video providers, browser behavior, or deployment infrastructure.
