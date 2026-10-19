# SPEC_08 independent security and journey review

**Reviewed candidate:** `c3900b440e75c015ef9d6c686667ef8887daaea2` (diff from original base
`eaf87f19d3fa4b7959024fb1f0faaa65553ff77c`).
**Corrected product:** `bbcb51537d1dd6441bb6b6f18ace9549013f5103`.
**Authority:** the user explicitly handed the paused integration to this owner ("請接手完成",
2026-10-19). Two read-only reviewers (security; journey) ran in parallel, then this owner verified
each finding in code before fixing it. Nothing was pushed or deployed.

## Verdict

**OK with notes.** No blocker. One major journey defect and five minor defects were fixed, with
regression checks. The security review confirmed no contract bypass. One policy question remains
open for the user (memory write authority below). Live provider/semantic/billing effects remain
unobserved, as before.

## Findings and dispositions

| # | Severity | Finding | Disposition |
|---|---|---|---|
| J1 | Major | After creating a skill/provider/environment/memory store/entry/deployment, the saved resource stayed in the shared `:new` sessionStorage draft. The next "New resource" form showed it at `version:1`, so creating another resource gave 409, or the form silently saved a new version of the old key. | **Fixed.** `ConsoleManagedViews.jsx` resets the `:new` draft and opens the created key. Root cause in `shared.jsx useDraft`: it persisted inside a lazy state updater that never ran if the form unmounted first. It now persists plain values synchronously. Browser regression: "New resource" after save shows an empty, enabled Skill ID. |
| J2 | Minor | Ctrl+K returned `agent_key` for deployment rows, because deployment rows also carry it. Every deployment opened the agent key, with duplicate React keys. | **Fixed.** Page-specific key in `model.js resourceSearch`. Unit regression for two deployments of one agent. |
| J3 | Minor | Spend & rate limits had no "Load current saved version" after a 409, so stale `version` repeated the conflict. | **Fixed.** Confirm-then-replace button, shown when the draft version differs from the current version. |
| J4 | Minor | Quickstart "Start from a blank agent" sent the typed requirements. | **Fixed.** Blank sends `requirements: ''`. |
| J5 | Major (found while verifying J1) | `signals()` attached a pending action's abort signal to every request, including the next page's `useLoad`. Navigating during Save/Trigger/Cancel aborted the new page's load, showing "Could not load current data" with no retry. | **Fixed.** Only signal-less action calls follow the action; managed loads keep their own signal. Covered by the browser deployment journey (cancel, then open deployments). |
| J6 | Major (found while verifying J1) | A deep-linked resource form rendered the default "new" form before the list loaded. Early edits went to the `:new` draft and were then silently replaced by the saved item. The original browser test passed only because the J1 stale draft masked this. | **Fixed.** `ResourceEditor` renders a named resource's form only once it has loaded. Browser regression: cron edits now persist as deployment v2. |
| S1 | Minor (hardening) | `runtime_http` now accepts dotted webapp IDs. `load_studio_card` tried `Path(id).is_file()` relative to the working directory, so `.env` or `package.json` were read and parsed as cards (no content echoed). | **Fixed at the shared loader.** String IDs resolve only inside `CARDS_DIR`; only `Path` objects load files. Red/green regression in `test_studio_worker.py`. |
| S2 | Policy question | Any non-viewer editor can create, overwrite or archive entries in project/episode-scoped memory stores. These entries are injected (labelled as untrusted data) into every user's mounted prompts. Creating non-user stores is admin-only. The contract does not state who may write project memory. | **Open: user decision.** Option: require admin for entry writes when `scope_kind != 'user'`. |
| S3 | Note | The Router quote cache key does not include the allocation/source snapshot, and a quote is not consumed by dispatch. | No financial bypass: each dispatch reserves and admits separately; source/allocation binding is enforced by `operation_digest`, `source_guard` and outbound source digest; expiry is rechecked at begin/submit. Doc wording "binds allocation" means the operation, not the cached quote. |
| S4 | Note | Judge admission is counted at `prepare_operation`. A quote that expires before `begin_operation` keeps its admission. | Matches "admitted, never auto-refund". A slow queue can use cap without outbound generation. |
| S5 | Pre-existing | An admin can pair an allowlisted `api_key_env` with any `base_url`. With `network_access=full` and no vault mounts, a probe/turn sends that key to that host. | Not introduced by SPEC_08. The environment network policy/vault mounts narrow it when configured. Operator awareness. |

The security reviewer traced and found sound: auth/actor/admin gating on every Console route; no
cross-owner private reads; no request/template/skill/memory privilege grant; env-reference
allowlist and secret non-echo; no SSRF via environment metadata; advisory-locked, atomic
Judge/budget/reservation and submit fence; no SQL injection, pickle or subprocess. The journey
reviewer traced navigation (4 groups / 12 pages, deep links), quickstart/409, playground,
sessions confirm-and-resume, return-to-production, Router preview/quote/review/dispatch,
estimate-soft consent, deployments, memory and explicit-only probes as sound, apart from the
items above.

## RAN at `bbcb515` (owned PG16 port 55447, started and stopped by this owner)

| Command | Result / log |
|---|---|
| `C:/Python313/python.exe -m unittest discover -s tests -p test_*.py` | exit 0; 506 tests, 532.3 s; 0 failures/skips; [backend.log](verification/spec08/review/backend.log). Ran after the `card_engine` fix; later edits were UI-only. |
| `cmd /c npm test --prefix ui` | 119 pass, 0 fail/skip; [frontend.log](verification/spec08/review/frontend.log) |
| `cmd /c npm run build --prefix ui` | exit 0; existing >1200 kB warning; [build.log](verification/spec08/review/build.log) |
| `python ui/tests/agentConsole.browser.py -v` | 4 journeys OK, 78.8 s; [browser.log](verification/spec08/review/browser.log) (103 lines of existing `ConnectionAbortedError` noise from aborted long polls, as before) |
| archive (`core.autocrlf=false`) → `pip wheel` → `verify_wheel.py` → `pip install --target` → `verify_wheel.py --installed-root`; `test_wheel_resources.py` | all exit 0; 151 files / 12 migrations / 17 cards / 7 schemas; identity `2f46d80fe253013b631b5b0fbe188b9319e7f28806b9529a4de12d80ca26afbd`; wheel SHA256 `dc7d04784cf64819411f5b07d215da4045efbfffb180278d5d9484835302b3a0`; [wheel.log](verification/spec08/review/wheel.log), [installed-wheel.log](verification/spec08/review/installed-wheel.log) |

PG cleanup: 0 other client backends, `pg_ctl -m fast -w -t 12 stop` exit 0, status 3,
`postmaster.pid` absent. Temp evidence (screenshots, wheel, installed target) stays under
`%TEMP%/spec08-takeover`.

## NOT RUN

Real provider inference, credentialed pricing/MCP, GPU/model downloads, invoice settlement,
remote termination, real coding/ACP CLIs and push/deploy. The prior integration receipt
(`spec08-verification.json`, candidate `c3900b4`) remains historical evidence for that candidate.
