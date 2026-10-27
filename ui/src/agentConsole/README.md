# Lean Agent Console UI contract

This component consumes service `8c3eb4a767aaca2694d48cb338147daa95e5838e`.
It adds no backend service, scheduler, CLI launcher or authority principal.
`model.js` is the exact four-group/twelve-page and twelve-template wire-ID map.

## Routes and state

- `/projects/{slug}/#/agent-console[/page[/resource]]` opens the full-screen Console.
  Hash back/forward retains page/resource selection. The Studio top entry and daily
  dock jump use the existing production flush guard before entering.
- Production remains mounted, hidden and inert. Existing media is paused; ordinary
  production refresh polling is suppressed. Return restores the prior production
  hash and keyboard focus. The active shot/episode and unsent shot overrides also
  survive a Console refresh; they are never automatically submitted.
- Local Console drafts and shot overrides use **sessionStorage**, separated by
  project and current actor (memory-entry drafts additionally by store). This is
  browser-local draft recovery, not SQL storage, a credential vault or permission.
  Do not paste secrets. Production cell/document drafts retain their existing flush
  guard; entering Console does not discard them. Reload/replace of a saved version
  is explicit and confirms replacement of unsaved local edits.
- Page/resource requests and session long polls abort on unmount/project changes.
  Mutation requests abort on route changes, not as a promise of server/provider
  cancellation. No operation is automatically retried. Overview/budget refreshes
  every five seconds; terminal sessions stop polling.

## Page -> actual consumed API -> visible result

Base `C = /projects/api/{slug}/agent-console`. Browser writes include same-origin
credentials and `X-Requested-With: projects`; POSTs have a fresh idempotency header.
Current actor, membership, scope, admin and version authority always remain server-side.

| Wire page | Actual APIs | Visible result |
| --- | --- | --- |
| dashboard | GET C/dashboard, /automation, /gpu, /queue?days; POST /automation, /reservations/{key}/reconcile | Current-owner counts/recent sessions, heartbeat metadata, aggregate usage, budget/Judge admissions; SPEC_20 automation switch (R40), read-only local GPU panel (R38), project-wide queue and failures with admin reconcile (R39) |
| api_keys | GET C/api-keys, /providers, /model-setup; POST /providers, /api-keys/default, /connections/health, /model-setup, /model-check; GET /providers/{key}/history | Versioned references/default, server allowlist, explicit read-only probe result, not canned connectivity; SPEC_20 R36 model setup (local Ollama preset) and a governed step-by-step health check (model, chat, tools, JSON schema, image, context length) |
| playground | POST C/playground mode=dry_run or live | Real compiled instructions/tools/payload (no inference in dry-run); explicit saved live or raw Save-and-Run queues an existing M8 session |
| skills | GET/POST C/skills; GET /skills/{key}/history | Versioned Markdown instructions and recommended tool IDs; no permission grant |
| quickstart | GET C/quickstart; POST C/quickstart/draft | Exact twelve localized cards, blank or literal natural-language instruction draft; nothing saved/launched implicitly |
| agents | GET/POST C/agents; GET /agents/{key}/history | Form/raw writable fields, skills/tool policies/multiagent/grader/memory/env; stored and effective provider kept separate; immutable studio:* descriptors |
| sessions | GET C/sessions, /sessions/{id}/events?cursor&wait; POST /sessions/{id}/resume, /interrupt, /cancel | Existing private M8 messages/tasks/dispatches, consumed context, isolated grader scorecards; selection alone cannot confirm a gate |
| deployments | GET/POST C/deployments; POST /deployments/{key}/trigger | Durable trigger/session receipt, manual or numeric cron/IANA timezone configuration; existing worker owns due execution |
| environments | GET/POST C/environments; SPEC_20 R41 (admin) GET/POST /projects/api/{slug}/service-accounts, POST .../{key}/revoke, GET .../{key}/audit?limit | Versioned URL/reference/host/package metadata; local8188/proxy8189, Router/SDK/MCP/CLI supported states, no arbitrary launch; SPEC_20 R41 External agents section: issue a service-account token, ready-to-paste `zerofield-mcp` setup, accounts with scope/expiry/last use/calls, revoke, per-account audit |
| memory_store | GET/POST C/memory-stores?episode_id; GET /{key}/entries; POST C/memory-entries, /memory-stores/consolidate; GET /memory-entries/{uuid}/history | Scoped versioned stores/entries/mounts, reviewed source-digest consolidation and history; foreign private stores remain unavailable |
| usage_cost | GET C/usage-cost?days | Anonymous aggregates and owner-private ledger/cache/fingerprint/log diagnostics; estimate/report/unknown distinctions |
| spend_rate_limits | GET/POST C/spend-rate-limits | Current versioned spend/rate/model-pricing controls, strict effective Judge10, explicit admin-only estimate-soft consent |

### Session gates and Router

Question gates send the actual offered option ID only after **Confirm and resume**.
Proposal/race gates load the current owner's existing
`/projects/api/{slug}/orchestration/board` and reuse `ProposalRaceView` and existing
resolve authority; they do not grant access to another owner's proposals.

`POST C/sessions/{id}/router-quotes` receives either one exact native shot/card/form
or an owner-bound `allocation_id`. Quotes display exact source/input identity,
expiry, provenance and `hard_bound:false`. There is no fake `/price` or price lock.

The optional allocation preview uses existing Story
`POST /aivideo/open/v1/projects/pj_{slug}/episodes/{id}/shots:plan-allocation` and
current project production policy. It accepts only shot/card IDs because this API
uses **server card defaults**. Explicit `modelParams`/reference overrides instead
use the exact-form quote/dispatch path; they are never silently dropped into an
allocation. Existing Story preflight validates every assignment before dispatch.

After explicit review, **direct native** dispatch uses the identical form on the
existing Story image/video generation endpoint, or consumes the reviewed
`allocationId` through existing episode generation. Task polling shows actual
persisted output via the house `MediaCell`; it is distinct from managed-agent
M8 candidate/review gates. The agent-tool path continues through existing
`studio_dispatch_shot` confirmation and M8 review, without another scheduler.

Hard mode disables unlocked Router dispatch in the UI and the backend rechecks
current policy at the real boundary. Only an admin's explicit versioned save with
`estimate_soft_consent:true` can enable estimate-based admission. A checkbox or
quote alone cannot grant it. Estimates are not billing caps; provider reports are
not invoices; unknown local/cloud cost is not free. Judge used counts include
protected admissions/reservations and uncertainty, not just successful videos.
No automatic refund, paid replay or provider/model fallback is implemented here.

## Focused engineering checks

- `node --test ui/tests/agentConsole.test.mjs ui/tests/i18n.test.mjs ui/tests/storyWorkbench.test.mjs ui/tests/orchestration.test.mjs ui/tests/sheetWorkspace.test.mjs ui/tests/studio-ui.test.mjs ui/tests/assistant.test.mjs`
- `npm run build --prefix ui` (required; serves `static/projects`, not source).
- With only the owned PG16 cluster running on55447:
  `OPENBENCH_TEST_DB_URI=postgresql://postgres@127.0.0.1:55447/postgres python -X utf8 ui/tests/agentConsole.browser.py`
  Optional `OPENBENCH_UI_EVIDENCE_DIR` retains screenshots outside the checkout.

The browser harness uses real authenticated local API/PG, shared M8 runtime,
actual Story writes and FFmpeg. **LLM inference and native Router responses are
explicit deterministic loopback fixtures**, not real quality/billing observations.
The sole intercepted browser response changes quote expiry metadata to test the
expired-quote UI; normal quotes, hard-default refusal, explicit soft consent,
allocation, tenth submission/output and eleventh denial are real application paths.

The final repository/full backend/frontend and installed-wheel gate belong to
integration. The inherited Router packaging-tooling dependency is not waived.
Aborted browser reads can produce existing server ConnectionAbortedError/duplicate
error-write log noise; this UI does not rewrite backend transport handling.
Application controls are not an OS sandbox, calibrated hardware-cost guarantee,
remote termination guarantee, model-quality assessment or overall acceptance.

### SPEC_20 operations (R36, R38-R41)

All five live inside existing pages (R41 in Environments & Bridges); no page or group is added.
`/model-setup` and `/model-check` are showrunner-only; every model call in a check goes through
`ProviderAdmission` (local endpoints unbilled). `/gpu` probes only loopback ComfyUI/Ollama with a 2 s
timeout, no proxy and no redirects, and counts ComfyUI queue entries without returning them. `/queue`
withholds other members' text, runs and sessions. `/automation` (setting `automation.paused`) stops
automatic grading, crew pre-production and scheduled deployments; manual work is never blocked.

**External agents (R41)** sit on Environments & Bridges, the page that already lists the MCP/SDK/CLI bridges, not on
Providers & API Keys, which holds outbound model credentials and tells people never to paste tokens. The section is
showrunner-only (`can_edit`); other members see one line saying so, and no request is made. It uses the
service-account admin routes of `project_docs/agent_http.py` through `externalRequest`, not the Console base.
Creating a token takes a name (the key follows it until edited), a write mode, the tools to allow and an expiry
(1 to 365 days). The tool list comes from the server's `availableTools` (`name`, `label`, `category`, `writes`,
`generation`), so it follows the registry exposure; `propose_only` never offers generation tools and `generate`
says in words that it still cannot spend money (free local open-weights renders only, closed or paid plans refused).
The token is shown once with a copy button and a setup snippet (a `claude mcp add` command or an MCP JSON config) that
carries `ZEROFIELD_MCP_TOKEN`, `ZEROFIELD_PROJECT` and `ZEROFIELD_URL`; the URL is this page's own address when it is
loopback, otherwise the default `http://127.0.0.1:3020`. The token is kept in page memory only (never in
sessionStorage or a draft) so leaving the page and coming back does not lose it before it is hidden; a reload drops it.
If the account list reports `connect.http.url`, the Streamable HTTP address and its Bearer header are added to the
setup; without it the page shows stdio only. Each account lists status, scope, expiry, last use, call counts and
render requests, and can be revoked after an inline confirmation. "Recent activity" reads
`GET .../service-accounts/{key}/audit?limit=25..100` (admin only): each call (client, tool, result, reason code,
proposal ids), the issue and the revoke; argument hashes are never returned.
