# Official Comfy Router component (SPEC_08 lean)

This is a **model driver**, not the historical graph-platform `router` naming,
ZeroField `zerofield_media_v1` vendor adapter, local `/prompt`, or another scheduler.
The existing local/SDK graphs, graphless vendor/cloud adapters, M8 private media
principal, allocation ownership/source/column checks and review gates remain intact.
No global model, credentials, CLI config or existing custom profile is changed.

## Verified public protocol, not spec assumptions

Captured public source evidence and hashes: [reference manifest](references/comfy-router-public/sources.json).
Primary contract: <https://docs.comfy.org/router-openapi.yaml>, OpenAPI 3.0.2,
Comfy Router API version `1.0`. Seven exact per-model schema snapshots are packaged
under `workflows/router/` and identified by their official document revision.

**Correction to SPEC_08's `/price` label:** the documented price operation is
`POST /v2/models/{provider}/{model}/estimate`, with the **same native JSON body**
as generation. No guessed `/price` request or custom vendor envelope is used.

- Catalog detail: `GET /v2/models/{provider}/{model}`; a successful matching ID is
  required before quoting. A published schema is not proof of a key's entitlement.
- Submit: `POST /v2/models/{provider}/{model}/requests`, authenticated with
  `Authorization: Bearer` and a server-derived workspace-unique `Idempotency-Key`.
  Expect HTTP **201**, `request_id`, `status: IN_QUEUE`.
- Poll: `GET .../requests/{request_id}/status`; states `IN_QUEUE`, `IN_PROGRESS`,
  `COMPLETED`. A terminal `error_type` is failure, not output success.
- Collect: `GET .../requests/{request_id}` once completed; parse the model's
  **native output**, not a Comfy-shaped envelope. Derive these same-origin paths;
  do not send credentials to server-returned handle URLs.
- Queued dispatch is pinned to its provider leg (official contract: no fallback
  loop). This client never selects alternate providers, retries ambiguous submit,
  resubmits on poll/download failure, or automatically refunds a protected trial.
- Official cancellation is only a request, not proof of remote termination or no
  charge. Existing local cancellation/revocation stops subsequent export/poll/
  publication. This component does not promise remote termination or paid replay.

Supported cards and pinned documents:

| Model | Schema revision | Native output |
|---|---|---|
| `ltx/ltx-2-5-pro` | `36d5297387ff` | `result.video_url` |
| `ltx/ltx-2-5-fast` | `36d5297387ff` | `result.video_url` |
| `bfl/flux-3-image` | `3184229fc5e3` | `result.sample` |
| `bfl/flux-3-video` | `14d51fd15b79` | `result.sample` |
| `minimax/minimax-h3` | `c0e2e941ffff` | `task.content.url` |
| `byteplus/dreamina-seedance-2-5-260628` | `ea6dda283563` | `content.video_url` |
| `higgsfield/higgsfield-genjutsu-motion-transfer-v1.0` | `77d0cffa3d15` | `video.url` |

Card IDs are `router-` plus the model segment. This is a conservative typed subset
of each schema, **not arbitrary future catalog support**: bounded explicit video
durations, no draft-cache mode, callbacks, opaque native JSON or provider override.
Image references use the shared five-slot ceiling (FLUX video has two keyframes).
MiniMax keeps native `first_frame`, `reference_image`, `base_video` and
`reference_audio` content roles; output audio is retained, including stereo.
LTX's verified routes are text-to-video: image conditioning is not invented.
Seedance's inline quantity/format flags are refused in favor of typed controls.
Unsupported combinations fail before media export/price/generation.

## Configuration and operator permission

Server-managed references only:

- `COMFY_API_KEY` must be present **and** in `OPENBENCH_AGENT_KEY_ENVS`.
  No plaintext key is accepted in cards, SQL, requests, logs or errors.
- `COMFY_ROUTER_BASE_URL`: default `https://api.comfy.org`. This is separate from
  existing graph SDK `COMFY_BASE_URL`; setting the SDK proxy to local 8189 never
  redirects official model requests there.
- `COMFY_ROUTER_ASSET_BASE_URL`: default `https://cloud.comfy.org`, the official
  **jobs/assets v2** surface, not the Router host or local `/upload/image`.
- `COMFY_ROUTER_MEDIA_ORIGINS`: explicit comma-separated output origins (or trusted
  card `media_origins`). Non-loopback deployments must configure these **before**
  quoting/submitting. No wildcard or arbitrary provider-returned download origin.
- `COMFY_MCP_URL`: default `https://cloud.comfy.org/mcp`; discovery only (below).

A card explicitly marked `driver=comfy_local` defaults to local 8188 even when
`COMFY_API_KEY` is present for Router. It does not export that unused key to local
ComfyUI or require its vault mount. An explicit card/server SDK choice and generic
legacy SDK client behavior remain supported; model-driver cards cannot enter the
graph client. Environment URL fields describe these contracts; actual Router/asset/
MCP endpoints are the server-managed variables above, not client policy grants.

Default `open_weights_only` keeps the critical path local. Every hosted Router
card requires explicit current effective `hybrid_studio`, deployment ceiling,
privacy permission, active writable actor/project membership and current sponsor
agent/environment restrictions. Missing allowlisted credentials, vault mounts,
allowed network destinations, quote or Judge capacity block submission. These
are application controls, **not an OS sandbox or model/contest certification**.

`env_comfy_router` is seeded **disabled**, with Router/cloud/MCP URLs, exact host
allowlist, and empty `vault_keys` (no credential grant). Admins must explicitly
configure allowed credential mounts, permitted output storage hosts and the sponsor
agent's environment. A vault reference can use `{api_key_env: "COMFY_API_KEY"}`;
never select a media credential as the active chat model. Existing
`env_hybrid_cloud` is retained as a compatibility resource, not a second visible
UI environment. Local 8188 and proxy 8189 metadata upgrade only pristine seeds;
custom environments/profiles are not replaced. No SDK dependency upgrade was
needed: official Router and asset HTTP import without `comfy-sdk`; the existing
optional graph SDK path is unchanged. Public SDK **0.5.0** source was read for
asset-upload evidence, not installed or claimed as a tested live graph runtime.

## Estimate-only soft admission: default OFF

The official contract states verbatim:

> The answer is not a price lock: it is priced at the rates in force at
> `pricing_as_of`, and a run is charged at the rates in force when it is rated.

Even `source: exact` is **not** a hard maximum charge. `source: estimated` uses
`min_amount` / `max_amount`; `unknown` has neither. Missing/failed/nonfinite/
mismatched price is not zero. Official model access/price rollout can be unavailable.

The default project setting is `comfy_router_budget_mode: "hard"`. It refuses
these unlocked quotes before submission. Only an **active existing admin** may
version-save/audit `comfy_router_budget_mode: "estimate_soft"`. Nothing enables it
for existing projects in this component. This is configuration consent, not a paid
execution authorization for this engineering task. Request/task/quote fields cannot
grant soft mode. Other drivers' hard-bound requirements are unchanged.

Soft mode still applies all current currency/session/episode/project, rate,
concurrency, source, environment and Judge checks, but uses an **estimate**, not
a guaranteed billing cap. Reserve the official exact amount or estimated maximum,
rounded **up** to the ledger's four-decimal admission precision; the safe quote
response preserves the original amount. `TrustedQuote.hard_bound` remains false.
Switching back to hard mode or revoking permission is checked at queued begin
and immediately before opening the paid submit socket. Toggling never resets
Judge usage. A price increase after quote or accepted remote effect may exceed the
estimate; no local control can undo that charge.

`X-Comfy-Credits-Used` is converted at the documented $1 = 211 credits into
`reported_cost_usd` (eight-decimal storage); it is a **reported price, not a settled
invoice**. Keep the original reservation in `estimated_cost_usd` and the report
separate. Account reported overages in full, never clip to the estimate or call
it observed invoice settlement. Missing reports remain unknown. On ambiguity,
retain uncertain reservation/report capacity; no automatic retry/refund. Local
hardware and cloud reference storage are not certified free.

Counting unit: **one admitted generation stage project-wide**. Price, health,
MCP discovery, previews, reads, chat/grader and non-generation cache hits do not
spend a Judge trial. Batch N reserves N atomically before any item is scheduled;
replay does not count twice; the eleventh protected operation is denied before
submission. The inherited Judge10-run guard is not a per-tab/client counter.

## Quote then dispatch: reusable interfaces

A quote exports only already-authorized immutable media and performs networking
**outside DB transactions**. It caches a native payload for 120 seconds, keyed by
owner/project, validated expanded form/card, source media handles, policy and
configured origins. Admission binds the cached wire digest to the separate frozen
source/allocation operation digest and checks freshness/current credentials again.
The real submit must match both. The quote, uploads, price request, actual submit
and subsequent authenticated polls bind the same current credential value; rotation
cannot move a quote or job handle to a different credential/workspace.
Signed media URLs remain in process memory, never
SQL, public traces or logs. Restart loses quotes: obtain another quote, not paid replay.
Refreshing a media quote changes signed URLs and can invalidate an older queued
reservation; obtain a fresh reviewed request rather than silently changing its payload.

### Authenticated Story

`POST /aivideo/open/v1/shots/{shotId}/router-quotes` (also assets): same `appCode`,
`modelParams`, `promptOverride`, optional reviewed candidate reference and generation
options as the existing generation endpoint, plus optional `kind: image|video`.
Example input (not a live call performed here):

```json
{"appCode":"router-ltx-2-5-pro","modelParams":{"input.duration":2}}
```

The quote returns normal Story envelope data: `model`, `amount_usd`,
`reservation_usd`, `source`, `pricing_as_of`, `expires_at`, `input_digest`,
`hard_bound: false`, `budget_mode: estimate_soft`, and a plain warning.
It does not toggle project permission or debit a trial. Then use existing
`video-generations` / `image-generations`, with the same inputs and idempotency key.
For a batch/allocation, quote **each** final frozen shot/card form first (use card
defaults when allocation does); existing owner-bound `allocationId` and all-input
preflight remain mandatory for the allocation path. A missing quote blocks the
whole transaction. Explicit Router allocation does not probe local ComfyUI.

Only already-existing references can be quoted. Router stages that depend on
future generation/preparation cannot be prequoted and are refused **before partial
admission**. Review/persist that source first, then obtain another quote/allocation.
This limit does not remove existing local/vendor/cloud preparation chains.

### Authenticated self-hosted v2

`POST /openapi/v2/quote/ai-app/{cardId}` with `X-Project-Slug` and only
`{nodeInfoList:[...]}`. Fully expanded hidden/default media grants must belong to
the authenticated actor and production **before any export**. Then call existing
`/openapi/v2/run/ai-app/{cardId}` with the same nonempty input list and query the existing task.
Supply `Idempotency-Key`: actor/credential/project/path/body-bound 24-hour replay
returns the same task, including concurrent calls. Its task grant and replay record
commit before executor launch. A changed body conflicts; a restart does not replay
an ambiguous paid effect even if the process-local task is no longer available.
No body callback, actor/project field, price or quote flag is authority. Original
SDK/local/imported graph execution keeps its current source/grant checkpoints.

### Python service seams (trusted server code only)

- `comfy_router.configuration_status(card)`: no network; `configured` and
  `connection_state: not_checked`, verified model revision, price protocol.
- `comfy_router.health(head, model)`: guarded catalog-detail read; reachable is not
  successful inference/billing. Supply the existing live governed Head callbacks.
- `comfy_router.quote(ctx, task, card, values, head)`: authorized outside-transaction
  export/estimate; safe public quote metadata only. Never accept the Head/ctx from JSON.
- `comfy_router.prepared(...)`: pure cache lookup; no networking under admission locks.
- `governance.prepare_operation(..., router_request={task,values})`: binds quote and
  wire digest, preserves default hard behavior and atomically reserves currency/Judge.
- `governance.router_submission(...)`: current exact-payload/soft/cap/policy/source/
  lease/credential check and one-attempt marker at the real outbound boundary.
- `store.analytics(...)` adds separate `reported_cost_usd`; `budget_summary(...)`
  adds `comfy_router_budget_mode` and an honest cost-basis notice. No raw owner traces.

The lean service/UI owner must whitelist this single mode setting, require current
admin/version checks, display the estimate-only warning/price-vs-invoice distinction,
and expose no excluded enterprise pages/services. Do not label configured as connected.

## Official Comfy MCP: discovery only

Official documentation: <https://docs.comfy.org/agent-tools/mcp.md> and
<https://github.com/Comfy-Org/comfy-mcp>. Cloud is **Streamable HTTP** at
`https://cloud.comfy.org/mcp`, with `X-API-Key` for headless clients. Local
`comfy-mcp` is a separate **stdio** server driving comfy-cli; it is not an HTTP
path on local ComfyUI 8188 or proxy 8189.

`comfy_mcp.configuration_status()` is no-network metadata. The callable
`comfy_mcp.discover(ctx, card)` performs only MCP **2025-06-18** `initialize`,
`notifications/initialized`, and one bounded `tools/list` page (JSON or SSE), with
session/protocol headers and best-effort session DELETE. Current actor/environment/
credential boundaries apply to every request. It returns safe names, `has_more`,
`connection_state: reachable`, and **`generation_enabled: false`**; it does not
return server instructions, schemas/descriptions, secrets or raw errors.
No `tools/call`, shell/download command execution, OAuth login, local CLI launch,
arbitrary MCP registry or MCP generation path exists. Generation stays on the
allocation/Router/Judge boundary. Local stdio state is honestly `not_started`.

## Evidence and remaining limits

`tests/test_comfy_router.py` uses actual authenticated HTTP, disposable PG16 and
FFmpeg with clearly synthetic native Router/model responses. It covers all seven
schema/card routes; Story and v2 quote/dispatch/persist; native MiniMax image/video/
audio references; bounded stereo MP4/+faststart; allocation and private M8 proposals;
unknown/failed/expired price; malformed inputs and forged flags; current revocation;
soft/hard changes; reported over-estimate prices; project last-slot races/batches;
ambiguity, timeout/cancel; and official MCP HTTP/SSE discovery without execution.
Existing driver/facade/SDK/import/allocation/security suites remain regression gates.

No real provider inference, credentialed pricing/MCP/catalog call, model/GPU
download, CLI agent, deployment, billing reconciliation or contest certification
was performed. Fixture success is not model quality or real-provider/billing acceptance.
