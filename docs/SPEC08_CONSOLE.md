# Lean Agent Console: use, authority and evidence

**USER_PAUSE_REQUESTED:** Integration engineering gates are complete, but no reviewers/new
stage/new writer are authorized. [Portable handoff](SPEC08_HANDOFF.md) records the safe stop.

Product candidate: **`c3900b440e75c015ef9d6c686667ef8887daaea2`**, on service
`8c3eb4a767aaca2694d48cb338147daa95e5838e`, Router `d7cb6031d16e53daa08959bf633e087db1548571`.
This integration changes verification tooling/docs only, not product or compiled assets.
[Current frozen receipt](spec08-verification.json) records actual commands, counts,
resource hashes and RAN/READ/NOT RUN. Integration RAN backend506/frontend119 (zero
failures/skips), build340 modules and installed-wheel151-resource identity (12 migrations,
17 cards,7 native schemas); browser4 at the unchanged candidate is READ, not rerun.
Owned PG16 port55447 is stopped/status3/PID absent. Independent security/journey reviews are **pending**.
Engineering/journey fixtures are not overall acceptance or semantic/model/billing proof.

## Enter and build

Open a production, then **Agent Console** in the Studio header or daily dock.
`/projects/{slug}/#/agent-console/quickstart` is a deep link; Ctrl+K searches pages/resources.
The production stays mounted/inert, with media paused. Return restores the prior
page/shot and unsent overrides; entering respects the existing document/cell flush guard.
Console drafts use actor/project-local browser sessionStorage, not durable cross-device
storage or a secret vault. Changing production does not carry another production's draft.
English is first-run/fallback; Traditional Chinese is explicitly selectable.

Exactly four groups/twelve page IDs (no separate enterprise Files/Batches/cache/log/CLI pages):

| Group | Page IDs / function |
|---|---|
| workspace | `dashboard` current owner activity/aggregate budget; `api_keys` provider ENV references/project default/explicit read-only probes |
| build | `playground` compile preview or explicit live M8 run; `skills` versioned instruction Markdown/history |
| managed_agents | `quickstart`12 templates/blank/literal requirement draft; `agents` form/raw configuration; `sessions` live M8 progress/gates/scorecards; `deployments` manual/cron; `environments` controls/bridge metadata; `memory_store` scoped versions/history/consolidation |
| analytics | `usage_cost` combined ledger/tokens/cache/fingerprint/private logs; `spend_rate_limits` active currency/rate/Judge/Router mode controls |

1. Quickstart drafts one of the exact12 templates, blank, or your literal requirements.
   Natural-language drafting is deterministic instruction copying, not model understanding
   or inferred permissions. Inspect form/raw JSON; **Save version** explicitly before launch.
   A409 keeps your draft; explicitly load the current saved version before replacing it.
2. Mount saved skills and scoped memory, choose tools and `auto`/`always_ask`/`disabled`,
   provider/effort/environment, and an independent grader rubric with0..3 revisions.
   Skills/templates/memory/spend settings cannot grant tools, scope, credentials or policy.
3. Playground **Compile dry-run** shows actual compiled input/payload without inference/tools.
   **Run live saved agent** queues an existing M8 session, not a new scheduler; raw live
   configuration requires explicit **Save-and-Run**. Actual consumed context is distinct
   from preview. Viewer execution/configuration controls are disabled and server-denied.
4. In Sessions, selecting a Needs You option is not approval: **Confirm and resume** is
   required. Shared runtime rechecks current authority/source before the frozen action.
   Proposals/races retain existing guarded review/winner gates. Independent grading is
   tool-free, bounded and isolated from worker history/personas/skills; failed/exhausted
   grading stays failed Needs You, never approved completion. Actual video grading mounts
   a real timestamped eight-frame sheet without rerendering the candidate.
5. Interrupt cancels the attempt; it is not a resumable OS pause or provider refund.
   Expired/revoked/canceled work cannot publish late. Unknown paid effects are not retried.

Seven new callable tools: `studio_ingest_script`, `studio_manage_asset`,
`studio_plan_allocation`, `studio_dispatch_shot`, `studio_inspect_frames`,
`studio_edit_timeline`, `consult_advisor`. Both daily chat and managed built-in turns use
the shared current/frozen ceilings. Existing tools/delegation and operator workers remain;
this Console does not launch coding/ACP CLIs or generic MCP tools/call generation.

## Resources, privacy and scheduled work

All Console endpoints require current `cp.actor`; agent/provider/environment/limit mutations
require existing admin `me.can_edit`. Admin configuration/cancellation authority is **not**
access to another owner's chats/sessions/gates/traces/private memory. Computed `studio:*`
profiles are immutable read-only `server_media`; the private `_PRINCIPAL`, M8 admission,
lease/proposal/race/winner/cancel authority remain unchanged.

Providers store only server-allowlisted ENV **references**, never key values. A versioned
project default is inherited only by built-in profiles whose raw provider config is exactly
`{}`; explicit configs/custom profiles remain unchanged, as do global defaults. Rotation,
revocation or default changes stop stale continuations/publication. Effort reaches supported
provider payloads; an unsupported explicit value fails without stripping/retrying/fallback.

Environments retain local8188/proxy8189, disabled Router/cloud, and disabled ACP metadata.
Configure allowed hosts, reference mounts and current agent binding explicitly. GET is not
an automatic network probe. An explicit health/discovery probe can report reachable, never
model entitlement, successful inference or billing. Official cloud MCP is discovery-only
initialize/initialized/tools-list/DELETE; local stdio is not started. SDK internal networking
requires the supported full-network environment. These application controls are **not an
OS sandbox, hardware-cost guarantee or remote termination guarantee**.

Memory mounts enforce project/episode/user scope and read-only/read-write ceilings.
Archive preserves history and prevents consumption. Consolidation uses explicitly selected
accessible reviewed rows/proposals with source digests, not private conversation harvesting.

Deployments bind a saved agent/current matching environment, prompt/playbook, scope and
narrower budget. Manual trigger keys and cron slots deduplicate durably into the existing
M8 worker. Five-field numeric cron uses IANA timezone and current minute only: no downtime
backfill, DST fold runs once, nonexistent local minutes do not run. Creator/config/revoke
checks remain current; interrupted/unknown effects never automatically replay.

## Router: preview, quote, review, dispatch

Read [verified protocol/configuration](COMFY_ROUTER.md), not the original guessed `/price` label.
The actual native endpoint is **POST `/v2/models/{provider}/{model}/estimate`**, with the
same native JSON input as generation. Seven pinned model schemas/cards are a conservative
typed subset, not arbitrary catalog support. No model/executor/provider fallback is added.

Default `open_weights_only` keeps the critical path local. Hosted Router requires explicit
current admin-authorized hybrid within the deployment ceiling, unmasked allowed media,
current actor/environment/reference grants, output origins, currency/rate capacity and quote.
A request body/template/tool cannot confer that permission.

- In a current owner session, supply an exact shot/card/native input form **or** preview an
  owner/episode/selection/source/policy-bound allocation. Allocation uses server card defaults;
  explicit overrides use the identical form path. ALL assignments' configuration/required inputs
  are preflighted before any dispatch/reservation; missing inputs/quotes block the whole batch.
- **Obtain fresh native quote** performs actual authorized detail/export/estimate outside DB
  transactions, binding current inputs/source/credential to the frozen operation. No manually
  populated quote cache is required. Preview/quote does not debit Judge.
- Official estimates, including `source=exact`, are **not price locks**. Default `hard` refuses
  unlocked charges. Only a current admin's explicit versioned save plus risk consent enables
  project `comfy_router_budget_mode=estimate_soft`. Checkbox/task/quote alone grants nothing.
- In soft mode, inspect exact identity/expiry, explicitly review, then dispatch the identical
  allocation/form. Direct native Story output is visibly separate from managed M8 candidate
  review; tool dispatch retains always_ask/M8 proposal authority. Current mode/credential/source/
  policy/lease/environment/limits are rechecked at the real outbound boundary.
- Quotes are process-local120s. Expiry/restart/source changes require explicit fresh preview/
  quote/review. Future generated/preparation references cannot be prequoted: persist and review
  first. No ambiguous paid retry, fallback, automatic refund or stale/canceled publication.

Judge Live-Link protection is **project-wide strict10 admitted generation stages**, not
10 chats/sessions/films. BatchN reservesN atomically; races/chain generation stages count;
replay counts once; the eleventh is denied before outbound. Reads/preview/quote/chat/advisor/
grader/prep/export/cache without generation do not debit. Toggle never resets usage; canceled/
ambiguous admissions remain conservatively counted. Historical configured values above10
cannot raise the effective cap. Currency checks also include pending/uncertain reservations.

Usage keeps estimated reservations, provider-reported price, observed invoice cost and unknown
metrics separate. Router credits-derived reports are **not settled invoices**. Soft overages
are accounted fully, never clipped/hidden or called guaranteed billing caps. Unknown local
hardware/cloud storage cost is not zero/free; cache reuse is not semantic understanding.
`downgrade_open_weights` requires a new explicitly reviewed allocation, not silent rerouting.

## Verify without live providers

Use a dedicated test PostgreSQL and installed FFmpeg/FFprobe; full acceptance permits zero
failures **and zero skips**. Required commands are recorded in the receipt. Browser interactions
use actual local HTTP/PG/M8/FFmpeg with declared deterministic text/native Router fixtures;
only one expiry-response-metadata case is intercepted. The UI owner's unchanged-candidate
scripts/logs/screenshots are READ by integration, not relabeled as a newly run browser gate.

Packaging: freeze tracked source with `git -c core.autocrlf=false archive <product-sha>` into an owned temp directory
(no inherited `build/`), then use the **same Python**:

```text
python -m pip wheel --no-deps --no-build-isolation --no-index <frozen-source> --wheel-dir <owned-temp>/wheels
python scripts/verify_wheel.py <wheel> --source <frozen-source>
python -m pip install --no-deps --no-index --target <owned-temp>/installed <wheel>
python scripts/verify_wheel.py --installed-root <owned-temp>/installed --source <frozen-source>
```

The verifier derives actual counts/hashes from source, checks every migration/instruction/
module/card/schema/sample/compiled asset, imports installed native modules outside checkout
and exercises packaged resource lookup/card/native-schema parsing without networking.
Verify archive bytes against raw `git show <product-sha>:<path>`: Git for Windows may
otherwise CRLF-convert archive exports under core.autocrlf=true. The final wheel uses the
command-local false setting, not a global config change. `-E -P` ignores checkout
PYTHONPATH/cwd but retains already installed user-site runtime dependencies; nothing is fetched.
Historical missing `build.__main__` and failed scope/packaging receipts remain unchanged.
No real inference/GPU/credentialed pricing/MCP/CLI/model downloads/push/deploy, real semantic
quality, provider entitlement, invoice settlement or remote termination was observed.
