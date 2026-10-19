# SPEC_08 portable handoff — USER_PAUSE_REQUESTED

## Stop and authority

**Stage:** integration engineering complete; safely paused by the user's explicit request
to change agents. **Control status: blocked / `USER_PAUSE_REQUESTED`. Overall acceptance:
false. Independent security and journey reviews have NOT STARTED.** Passing engineering
checks do not authorize a reviewer, new writer, agent, provider call, push or deployment.
Only the parent may transfer/resume control after observing terminal state and obtaining
explicit user permission. This file/report is not automatic launch authorization.

Authoritative IDs, supplied by the parent from native status/receipts:

- Mission: `bc012162-63cf-4046-857f-5bef62adc57f` (parent state waiting, USER_PAUSE_REQUESTED).
- This integration child run: `49eea8c7-f6f5-4aeb-8a53-ad7ee6070bc5`.
- Stable key: `spec08-console-final-gate`.
- Owning immutable/original workflow: `57bfb298-4986-4ca4-97dc-6eefe0e461b6`.
  Returning ready would auto-start two reviewers; this child must return **blocked**, not ready.
- Historical, terminal lineage only: `184cae2f-b1e4-4f32-8209-6b3ca52f37e6`
  (lean runtime/Router; old generic ready guard/wheel dependency); and
  `c18fc6e0-5ee3-4900-aeef-13220674d4b5` (old26-page scope revoked for lean12).
  Neither is active or should be rerun to clear historical metadata.

## Revisions and exact checkpoint

- Original base: `eaf87f19d3fa4b7959024fb1f0faaa65553ff77c`.
- Frozen product/UI: **`c3900b440e75c015ef9d6c686667ef8887daaea2`**.
- Verified integration checkpoint/current HEAD before this handoff-only successor:
  **`1738b1a6691e1dbff26772de0925bbc482674f7f`**.
- This document is committed separately to avoid a self-referencing commit hash. The final
  native blocked receipt gives the resulting full HEAD; `git rev-parse HEAD` resolves it.
- At checkpoint1738b1a, working tree and staging were empty. No unverified partial/product
  patch remains. Only this requested handoff document follows that checkpoint; no new
  product edits, tests/gates, agents or reviews were started after the pause instruction.
- Checkpoint14 paths: AGENTS, README, original approved HANDOFF/SPEC08, current usage/receipt,
  source-derived wheel verifier/test and six durable logs. Original user-approved dirty docs
  are included; existing data/helpers, historical SPEC06/07 and failed scope/packaging
  receipts are preserved. No reset, clean, stash, destructive pruning or push.

Completed component SHAs:

| Component | Full commit |
|---|---|
| Resources | `e0bf2e5036fc05e72cd907b14ec3f38686269b0d` |
| Seven tools | `d437fdc1ed8804a0515da8d8f62548c0ede89de7` |
| Runtime/grader/governance | `409ba4da4523bff34ae1aa0bd3bae67d743123b4` |
| Official Router/MCP discovery | `d7cb6031d16e53daa08959bf633e087db1548571` |
| Lean service/application | `8c3eb4a767aaca2694d48cb338147daa95e5838e` |
| Twelve-view UI | `c3900b440e75c015ef9d6c686667ef8887daaea2` |

## Scope and preserved contracts

Exactly four groups/twelve IDs:

```text
workspace = dashboard, api_keys
build = playground, skills
managed_agents = quickstart, agents, sessions, deployments, environments, memory_store
analytics = usage_cost, spend_rate_limits
```

Retain12 exact Quickstart template IDs, blank/literal natural-language draft, seven tools,
versioned skills/scoped memory, bounded isolated grader, real existing M8 sessions/manual+
cron deployments, provider/environment controls and combined truthful analytics/active
spend/rate/Judge limits. No new duplicate Files/Batches/IAM/service-account/webhook/OTel/
retention or extra cache/log/CLI/integration pages/services. Inherited storage is preserved,
not an authorization to expose excluded services. Full page/API/result mapping:
[usage](SPEC08_CONSOLE.md), [UI contract](../ui/src/agentConsole/README.md).

- Current `cp.actor` is required on every Console endpoint. Agent/provider/environment/limit
  changes require existing admin `me.can_edit`; viewers cannot execute. Admin configuration/
  cancellation does not grant another owner's private chats/sessions/gates/traces/memory.
- Computed read-only `studio:*`/`server_media`, private `_PRINCIPAL`, existing M8 admission/
  task/lease/proposal/race/winner/cancel authority remain intact. No second scheduler.
- AllocationId stays owner/episode/selection/source/policy bound; ALL assignments receive
  configuration_and_inputs preflight before dispatch. Exact source/column/current role/
  privacy/grants remain authoritative. Open-only local default/deployment ceiling and
  explicit authorized hybrid remain; tools/skills/templates/limits cannot grant privilege.
- Official Router uses native **POST `/estimate`**, NOT `/price`. Quotes, even exact, are
  NOT price locks. Default `hard` refuses unlocked charges. Only explicit versioned current-
  admin project `comfy_router_budget_mode=estimate_soft` plus risk consent permits estimated
  reservations. Task/body/quote cannot grant it. Actual provider overages remain accounted
  fully; estimates/reported price are not invoices or guaranteed billing caps.
- Fresh quotes bind actual native input/model/source/allocation/credential, expire120s and
  are process-local. Restart/source/credential changes require explicit new preview/quote/
  review, never ambiguous paid retry/refund. Future references need reviewed persistence.
- Judge is strict10 project-wide admitted generation stages. BatchN reservesN atomically;
  replay once; operation11 denied before outbound. Read/quote/preview/chat/grader/prep/cache
  without generation does not debit. Toggling never resets; uncertainty remains counted.
- Versioned project default provider affects only built-in profiles with raw config exactly
  `{}`; explicit configs/history/global defaults stay unchanged. Frozen/current binding
  checks block stale default/key rotation and A->B->A continuations/publication. Effort
  reaches compat reasoning_effort or Responses reasoning.effort only when explicitly
  configured; legacy medium SQL default does not opt in. Unsupported effort fails, no retry/
  parameter stripping/model fallback. Per-outbound current env/credential checks remain.
- Allowlisted ENV REFERENCES only, no plaintext secrets/error echoes/signed URLs in SQL/logs/
  examples. Frozen/current tool/memory/advisor/grader ceilings and cancellation/deadlines
  remain. Application controls are NOT an OS sandbox, hardware-cost or remote-stop guarantee.
- MCP is documented discovery-only; no tools/call generation, arbitrary CLI or nested agents.

## Actual RAN / READ / NOT RUN

[Durable verification JSON](spec08-verification.json) contains hashes, versions, actual
commands and source->consumed->visible chains. Core raw results are IN THIS REPO, not only
TEMP: [`docs/verification/spec08/`](verification/spec08/).

### RAN before the pause (no new gate after pause)

Dedicated environment: `OPENBENCH_TEST_DB_URI=postgresql://postgres@127.0.0.1:55447/postgres`,
`PYTHONPATH=C:/ai_project/ZeroField;C:/ai_project/ZeroField/tests`.

| Actual command | Result / durable log |
|---|---|
| `C:/Python313/python.exe -m unittest discover -s tests -p test_*.py` | exit0;506 tests in517.684s (outer519.092s); zero failures/skips; [backend.log](verification/spec08/backend.log) |
| `cmd /c npm test --prefix ui` | exit0;119 passed,0 failed/skipped/canceled;484.5982ms; [frontend.log](verification/spec08/frontend.log) |
| `cmd /c npm run build --prefix ui` | exit0;340 modules,4.01s (outer5.009s); existing >1200kB warning retained; [build.log](verification/spec08/build.log) |
| `python -m unittest discover -s tests -p test_wheel_resources.py -v` |1 passed,0 skips; missing/corrupt schema/asset negative checks; [packaging-tests.log](verification/spec08/packaging-tests.log) |
| `python -m py_compile scripts/verify_wheel.py tests/test_wheel_resources.py`; working/cached `git diff --check` | passed before checkpoint |

Full source gate covers legacy SPEC07 private principal/expanded grants/live revoke/local
SDK/facade/allocation/frame-sheet/review/race/lease/cancel plus new Console/grader/ledger/
rate/currency/Judge/Router hard-soft/native HTTP fixtures. Real local HTTP/PG/FFmpeg; no
assertion weakening/skips. Actual inference/protocol responses are deterministic fixtures.

### Packaging: mandatory gate RESOLVED, historical failures preserved

Owned TEMP root: `C:/Users/fagem/AppData/Local/Temp/spec08-final-integration` (`T` below).
Same Python313 throughout; no tool/runtime/global install or executor switch.

```text
git -c core.autocrlf=false archive c3900b440e75c015ef9d6c686667ef8887daaea2
# extract binary tar to T/canonical/frozen-source (no inherited build directory)
C:/Python313/python.exe -m pip wheel --no-deps --no-build-isolation --no-index T/canonical/frozen-source --wheel-dir T/canonical/wheels
python scripts/verify_wheel.py T/canonical/wheels/openbench-0.2.0-py3-none-any.whl --source T/canonical/frozen-source
C:/Python313/python.exe -m pip install --no-deps --no-index --target T/canonical/installed T/canonical/wheels/openbench-0.2.0-py3-none-any.whl
python scripts/verify_wheel.py --installed-root T/canonical/installed --source T/canonical/frozen-source
```

All exit0. [Wheel log](verification/spec08/wheel.log), [actual outside-checkout installed
verification](verification/spec08/installed-wheel.log). Final wheel SHA256:
`f341e3dc798dd20282ae828eb2ae12e60ca5f9240afc66726c0c2afe67584411`.
151 exact resource hashes (12 migrations/all instructions/modules/samples/UI,17 parsed
cards,7 native schema/form compilations,14 installed module imports) equal RAW HEAD blobs,
wheel and installed target. Aggregate resource identity:
`ffabdaf205ac752448e1ddacd7f353c4ed92f0f8c30b8ae195ca146dc985b376`.
The required build's three asset/index bytes match raw product HEAD exactly; no product
change invalidates the prior browser evidence. Individual asset hashes are in the receipt.

Router's old `python -m build` failed missing build.__main__/build+wheel; this historical
receipt remains unchanged. Integration's FIRST pip wheel already succeeded, without any
installation. Audit then found Windows git archive auto-CRLF export (not a product defect);
final fresh command-local core.autocrlf=false export verifies all151 raw HEAD bytes. Keep
both attempts, do not weaken normalization or change global config. Earlier verification
checkpoints correctly failed: raw export/checkout mismatch; -I hid existing user-site
openpyxl (fixed to -E -P, retains installed dependencies but ignores checkout paths); and a
packaging fixture omitted required native LTX fields (final check compiles all7 card forms).
No source gate failed. Pip26.0.1/setuptools79.0.0; build/wheel distributions absent; no new
build-only packages were needed. Existing dependency versions are recorded in the receipt.

### READ, not newly RAN

UI owner's exact unchanged-product browser script/log and11 screenshots were inspected:
4 actual browser journeys,73.851s,0 failures/skips/pageerrors. Production draft/shot restore,
all4/12 pages and12 templates/blank/literal drafts, CAS conflict, real mounted35mm/shotgen,
always_ask no-write barrier + owner confirmation, actual Story mutation, isolated fixture
score95/trace/ledger, skill/memory history/source consolidation, refs/default/env forms,
manual/cron progress, viewer denial, fresh native quote->frozen allocation->tenth generated
video and operation11 denied before submit. Browser response interception is ONLY expired
quote metadata; no quote cache/counter injection. Read evidence source/path/hashes are in
the receipt; screenshots remain under `T`'s sibling `spec08-ui-evidence`. Abort reads emit
existing ConnectionAbortedError/duplicate error-write log noise; not silently called clean.
Component reports/scope/pricing decisions are historical READ evidence, not integration reruns.

### NOT RUN / genuine remaining work

**Independent security and journey reviews have not started.** They are pending, not passed,
and now explicitly unauthorized until the user permits a new owner/stage. No integration
browser rerun (unchanged-candidate READ reuse was allowed). No real semantic/model/visual
quality, entitlement, calibrated GPU/hardware cost, real credentialed catalog/pricing/MCP/
inference, invoice settlement or remote termination observation. No real coding/ACP CLI,
nested agents, GPU/model download, private production data, push/PR/release/deploy. Legacy
ACP tests use deterministic protocol subprocess fixtures, not external coding agents.

## Cleanup, temporary resources and writer release

Only owned PG16.4 cluster used:
`C:/Users/fagem/AppData/Local/Temp/zerofield-spec07-integration-scs2u4wk/data`, port55447,
`C:/Users/fagem/tools/pg16/pgsql/bin/pg_ctl.exe`. Before stop SQL returned port55447 and
**0 other client backends**. `pg_ctl -D <data> -m fast -w -t12 stop` exit0; final status3,
postmaster.pid absent, rechecked after pause. DEVNULL stdin, real binary `T/pg-control.log`
separate from `T/pg-server.log`, outer18s; no startup PIPE/capture_output/text, no initdb/
createdb, no other PG11810/real DB touched. Status/cleanup evidence is portable in the receipt.

Owned full-gate driver PID5080 exited and is absent (Windows process query error87);
`gates.done` present. Test HTTP/text/Router/MCP/FFmpeg/fixture-ACP subprocesses ended under
passing teardown; no persistent product server was launched. Integration started NO browser
process (prior UI evidence was READ). No mutating subprocess remains. Temp wheel/source/
installed target/logs are preserved for audit, not active services or product dependencies.

Writer is released after this handoff-only commit/final blocked report; parent retains the
control plane and collects terminal native descendants. No external agent launch is claimed
as transfer. Final native report confirms resulting full HEAD and empty staging/working tree.

## Next owner: first actions, only after explicit permission

1. Read this file, AGENTS, current usage/receipt and the exact source contracts. Inspect
   `git rev-parse HEAD`, `git status --short`, `git diff --cached` and owned service status.
   Do not assume temp paths exist; core results and hashes are committed above.
2. Parent must first observe this child and original workflow terminal states. User then
   explicitly chooses/permits the next owner. Do not restart old workflows, auto-launch the
   pending reviewers, switch model/control plane, rerun a full gate or resume coding yourself.
3. When authorized, independent read-only security and journey review is the remaining
   engineering review stage. Any substantive source defect returns to its owner, not a
   wholesale integration rewrite. Product changes invalidate relevant source/assets evidence.
4. Live semantic/model/billing effects remain separate, unobserved and unauthorized. Keep
   hard/soft risk, strict Judge10, privacy/current bindings and no paid replay guarantees honest.
