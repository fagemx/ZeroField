# SPEC_08 execution envelope (lean runtime component)

This component adds no Console routes/pages and no Router protocol implementation.
The existing Story/M8 state machines, private media principal, guarded proposals,
allocation preflight and project production policy remain authoritative.

## Callers and transactions

- `agent_runtime.run_agent(...)` is the shared daily-chat / managed built-in turn
  envelope. Supply trusted `ctx.original_objective` separately from conversation
  context. It installs governance hooks, reloads current resources and applies
  frozen/current tool ceilings. No global provider/model defaults are changed.
- `execution_governance.install(ctx)` installs the default `execution_guard` and
  `runtime_cost_hook` for an existing trusted context. Existing explicit hooks are
  retained for compatibility. Direct tool callers without hooks remain fail-closed
  for media/export/advisor. The remote tool context installs real hooks too.
- New service callers should set a stable, owner-private
  `ctx.accounting_session_key`, validated `ctx.episode_id`, optional finite
  `ctx.budget_cap_usd`, original objective and absolute deadline. The fallback key
  is run ID / message ID / process-local turn identity, not a durable service
  idempotency implementation. Ephemeral Playground turns sharing a session must also
  supply a server-minted `ctx.execution_key` per turn, reused only for the same
  idempotent attempt. Never populate context authority from arbitrary JSON.
- Store/admission helpers take an existing short transaction. Callers own commit
  or rollback. `transaction(ctx, action)` is the connection-owning variant.
  Commit admission before networking/inference; revalidate at outbound/publication
  boundaries. No transaction/project lock is held across model calls or FFmpeg.

## Outcome grading and publication

Enabled grading stages proposal tools in memory. No staged revision is published
for human approval until independently passed; source/profile/policy/privacy
stamps are checked again inside the proposal tool's locked publication boundary.
Managed structured output is likewise graded before `prepare_dispatch_output`.
Existing pending human/tool-action gates suspend the turn without grading or
reexecuting the action. Asynchronous tool-initiated M8 media inherits the sponsor
objective, grading configuration and original accounting session/narrower cap. The
actual produced asset is independently checked before a proposal exists; video
grading mounts a real timestamped eight-frame sheet prepared outside transactions.
Media references stay immutable across prose revisions, with no rerender. Exhausted
media failure opens an existing control-only Needs You gate: acknowledging it
closes the attempt, never resumes an accepted paid generation.

The grader receives only objective, configured rubric, candidate (including staged
proposal arguments / authorized contact-sheet images) and its currently mounted,
scoped allowed memory. It does **not** receive worker history, tool conversation,
skills or either persona's privileged prompt. Its fixed instructions expose no
models' tools. JSON requires exactly boolean `passed`, integer `score` 0..100,
bounded string `feedback`, and bounded `checklist` objects `{criterion, passed}`.
Malformed/unavailable grading fails safely. Feedback redacts bearer credentials
and query-bearing links.

Failure allows 0..3 **tool-free content revisions** followed by independent checks,
within the original turn deadline and lease (each isolated request is also bounded
to 45 seconds; media renewals still cannot exceed its original M8 deadline). Revisions cannot add tools, move
staged proposals to a different page/table or redo external actions. Exhaustion
is an honest failed scorecard and an existing owner-only Needs You question gate,
not approved completion. Scorecards/revision attempts enter the private trace.
Revocation/deadline expiry can prevent even the gate write; the worker then fails
without publishing the candidate or automatically retrying paid effects.

Remote completion also has a persisted one-attempt grading fence and candidate
replay digest. Enabled remote proposal tools must return the candidate through
completion, not publish it ahead of grading. The built-in specialist can grade a
remote candidate. Automatic remote/CLI revision is not launched: when no permitted
built-in worker revision is available the failed scorecard remains Needs You.
No real CLI was launched or tested. Registered external workers remain trusted
operator processes outside this application: their own inference/CPU/network/billing
is not observed or certified by the server ledger. Current profile/environment/worker
bindings and all server tool/grader/export boundaries are enforced; do not present
unreported external metrics as zero or launch opaque commercial external work from
new Console services without an enforceable operation-bound admission contract. Existing CLI/profile settings are preserved;
governed opaque CLI execution without an enforceable cost bound pauses with a
configuration blocker, without provider fallback.

## Currency, usage, rates and reservations

`reserve(...)` / `dispatched(...)` / `finalize(...)` implement atomic per-request
accounting under the existing project advisory lock. Worker, advisor, grader and
revision each reserve **actual provider rounds**. Their deterministic phase / turn /
round identities refuse duplicate submission, not merely duplicate ledger writes.
An ambiguous request is not automatically retried. Actual provider input/output /
cache token reports are recorded where available. Configured-rate arithmetic is
an estimate; it is not observed billing. Unknown counters/cost are not fabricated;
missing token metrics are marked in metadata and unknown money is SQL NULL.

Commercial text calls need admin-configured `model_pricing[model]` with exactly:
`kind`, `base_url`, `input_usd_per_million`, `output_usd_per_million`,
`max_input_tokens`, `max_output_tokens`, `byte_bounded_tokenizer: true`.
The operator must verify endpoint/model rates, byte-bounded input tokenization and
that `max_input_tokens` bounds that provider/model's accepted input context.
Requests exceeding the conservative byte ceiling are refused; the **full input
ceiling** and enforced output-token limit are reserved, not just an optimistic
prompt estimate. Commercial vision/opaque CLI pricing is not bounded by this
adapter and pauses. Wrong endpoint, absent pricing, expired quotes, nonfinite
money and cap violations never prove a free call.

Project-month, session, episode and optional narrower session/deployment caps
include reservations and uncertain spend, not only completed ledger rows. Unresolved
old reservations carry into the current month conservatively. Queued batches
reserve currency but do not occupy execution concurrency; actual starts enforce
current project/agent concurrency and RPM. Cancellation/error before submission
releases unstarted currency capacity. Submitted/ambiguous effects retain their
ceiling and uncertain capacity until explicit operator reconciliation, never an
automatic refund/retry. There is no automatic reconciliation/billing API here.

Both spend policies prevent the prohibited commercial dispatch. `pause` blocks it;
`downgrade_open_weights` requires a new explicitly permitted/reviewed open-weights
allocation rather than changing a frozen source/card/grant behind the crew's back.
An already permitted unpriced local/dry-run path remains usable. Local hardware
cost is unknown, not certified free; no 50% batch savings are assumed.

## Trusted quote seam for the next official Router owner

No `/price`, Router inference, MCP authentication or operator-credential call was
made by this component. The next owner must verify the official protocol first.

1. Obtain a quote **outside** DB transactions. Bind it to the exact frozen operation
   / canonical provider input identity, model, credential/environment and current
   source/allocation. Network price reads themselves consume no Judge trial.
2. Trusted deployment code may install
   `register_quote_provider(driver, resolver)`. The resolver is
   `resolver(card, operation_digest) -> TrustedQuote | None`; it must perform **no
   networking/DB access under the caller's lock**. Cache the prior verified quote
   against that exact digest. A request JSON estimate is never a resolver or grant.
3. Create `trusted_quote(amount_usd, operation_digest, expires_at, provenance,
   hard_bound=...)` using a semantic provenance ID, not an error or URL. Only attest
   `hard_bound=True` when a verified fixed-price / max-charge provider contract
   actually bounds the call. An estimate without that guarantee cannot enforce a
   hard currency cap and must pause, not be promoted to a free/guaranteed quote.
4. `prepare_operation(conn, ctx, request_key, card, operation_digest)` checks current
   Story policy, environment/credentials, quote freshness, currency and Judge
   admission before queueing. Allocation operation identities bind the frozen
   allocation/shot/stage/card; the Router integration must also bind/verify its
   canonical outbound inputs. `allocation_operations(...)` supplies current keys.
5. `begin_operation(conn, ctx, request_key, card=...)` rechecks current resources,
   quote expiry, caps and exact reserved model/driver before an actual start.
   Replays cannot start a finalized/dispatched reservation. `run_operation` wraps
   actual Story/M8 media/preparation/export work and settles success/uncertainty.
6. Keep private authority on the existing Head / in-process capability. Heads expose
   `outbound_check(url)` and `outbound_timeout(seconds)` for actual vendor uploads,
   submit/query/result downloads. Signed query strings stay in memory, not ledger
   metadata. The Router owner should reuse these hooks, not create a new scheduler.

Synthetic fixed-price test fixtures explicitly attest only their deterministic
loopback contract; they do not verify any commercial provider's billing/quote.

## Judge Live-Link protected generation admissions

Counting unit: **one admitted generation stage**, not one tab, chat, session,
completed film or successful render. A race counts both generation branches; a
multi-generation chain counts each generation stage. Read, price, preview, chat,
advisor/grader, FFmpeg preparation/export and cache hits without generation do not
consume a trial. Currency/RPM/concurrency checks still apply to those actual calls.

`generation_admit(conn, ctx, [(operation_key, operation_digest), ...])` atomically
reserves the full protected batch. Same owner/key/digest is a replay; a changed
identity is rejected. Existing allocation preflight revalidates **all** required
inputs before any batch admission/enqueue. Native explicit-card Story batches also
prepare and validate every `generation_job` (including actual `modelParams` media
overrides) before queueing any item; the public `generation(...)` API is retained. Operation 11 is refused before submit
when ten are protected/admitted. The count is conservative: admitted/canceled
requests are not automatically refunded, including remote ambiguity. Enabling
protection after queueing rechecks the whole queued session before a partial start.

`set_judge_protection(conn, me, slug, enabled=..., version=...)` is the admin-only
10-run preset. `save_settings` permits finite bounded admin cap/mode changes but
rejects `judge_trial_used_runs`: it is read-only. Toggling never resets usage and
cannot loosen production policy, allocation/source/credential or currency checks.
No reset endpoint is implemented. Existing user settings/profiles are not replaced.

## Environment controls and public reporting

Every actual server provider/media boundary rechecks current identity, membership,
original lease/deadline, current profile/environment, allowed destination and
credential allowlist/mount. Provider redirects are rejected. Text request/response
transport is bounded and environment timeouts constrain calls. Media/FFmpeg observes
current authority/deadlines. SDK-internal networking cannot be host-pinned by this
application, so SDK use requires an explicitly full-network environment. Optional
OS CPU/memory quotas unsupported by the in-process media runtime fail with an
explicit configuration blocker; they are not silently treated as a sandbox.
These are application controls, **not an OS sandbox or a remote cancellation promise**.

- `analytics(conn, me, slug, days=30)` returns project aggregates by date, agent,
  provider/model, usage kind and pricing provenance. It includes reported tokens,
  cache hits, estimated vs observed costs, unknown-price events, successful / cached /
  canceled / uncertain event counts. `successful_uncached_events` distinguishes
  actual successful work from cache reuse; zero is not provider-understanding proof.
- `budget_summary(conn, me, slug)` returns project-only accounted/pending/uncertain
  money (NULL when unknown), unknown-operation counts, caps and Judge remaining runs.
- Neither aggregation returns raw owner/session/run IDs, conversations, gate bodies,
  traces, media bytes, credential values or URLs. Admin cancellation/config authority
  still does not grant another owner's private session/memory access.
- New service/API code must whitelist the lean spend/rate/Judge/pricing fields; do
  not expose excluded OTel/retention/webhook/service-account/batch helpers merely
  because inherited foundation storage exists. No excluded service was added here.

Focused synthetic journeys and real PG/HTTP/FFmpeg prove these boundaries, not live
provider/model quality, calibrated GPU cost, real billing or the official Router
protocol. The later integration owner still owns the full repository/UI/build gate.
