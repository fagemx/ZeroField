# Studio routing and resource allocation (SPEC_07)

The five-entry Story workbench and editable production tabs remain authoritative. `limb_worker` is a compatibility facade over the responsibility-specific `project_assistant/studio/` package; old imports, shared registry identity and facade mock seams remain supported.

## Default and explicit permission

- Every new production defaults to `open_weights_only`. The badge means a **catalog policy lock**, not independently verified model weights, visual quality or contest eligibility. Audit imported graphs, dependencies and licenses yourself.
- An existing Showrunner/admin can explicitly select **Hybrid Studio** in the production toolbar, or `PUT /aivideo/open/v1/projects/pj_<slug>/production-policy` with `{productionPolicy:"hybrid_studio"}`. Ordinary crew cannot change this permission; viewers cannot dispatch.
- `OPENBENCH_PRODUCTION_POLICY=open_weights_only` is a deployment ceiling that even a project admin cannot relax. An unset ceiling still defaults every project to open-only; setting the ceiling to `hybrid_studio` alone does not authorize a project to spend.
- Original prompts/media are not exported to commercial cards in numeric masking mode. Card inputs, request bodies and agent advice cannot grant commercial permission.

## Configuring graphless providers

The ten shipped cards include seven local open-weights graphs and three graphless commercial/cloud templates. `vendor_api` and `runninghub_cloud` do **not** need local ComfyUI. Local/partner graph execution retains the existing Comfy client and official Comfy SDK path.

`SEEDANCE_API_URL` / `SEEDANCE_API_KEY`, `KLING_API_URL` / `KLING_API_KEY` and `RUNNINGHUB_API_URL` / `RUNNINGHUB_API_KEY` are operator-managed configuration references. The vendor templates require the **ZeroField `zerofield_media_v1` adapter contract**, documented as `ADAPTER_CONTRACT` in `project_assistant/studio/model_router.py`. This is **not** an invented official Seedance/Kling API. Operators must supply a compatible adapter and verify the actual provider/cloud WebApp mapping. No live endpoint, pricing or credentials are shipped.

`SEEDANCE_2_FAST_MULTIMODAL_VIDEO` resolves to Seedance only with explicit effective hybrid permission and a configured endpoint; otherwise it resolves to `h3-reference` before submission. An explicitly selected commercial card is denied under contest policy, not silently submitted elsewhere. There is no fallback after an ambiguous paid submission.

## Plan, review, dispatch

1. In Cinema Studio/OpenJutsu, select shots, a resource mode and either **Automatic shot allocation** or your own card (including imported cards).
2. **Preview allocation** calls the exact endpoint:
   `POST /aivideo/open/v1/projects/{projectId}/episodes/{episodeId}/shots:plan-allocation`.
   Optional `shotIds`, `appCode` and `engineTier` narrow the normal `budgetMode`, `productionPolicy`, `timePressure` inputs. Local availability is probed once by the server; client-supplied health/availability is not trusted.
3. The preview shows assigned cards, complexity, tiers and blockers. Authorized Story preflight checks effective required media against the current shot/asset metadata and validates typed future preparation outputs; it does not read blobs, render or submit inference. Its `readiness_scope=configuration_and_inputs` is stronger than the pure allocator's configuration-only recommendation. Per-shot `input_blockers` are also included in the backward-compatible `configuration_blockers` aggregate and displayed as semantic EN/zh-TW messages. Counts are planned assignments. GPU seconds/billed credits remain uncalibrated (`null`); weighted cloud resource units are not currency and preparation overhead is excluded. No savings or model-quality guarantee is made.
4. Generate uses that **allocationId**, not a second client-side routing decision. It is owner/episode/selection/source/policy bound and consumed once. Inputs/cards/graphs are frozen server-side. Every assignment's inputs are revalidated before any batch work is scheduled or the allocation is consumed; a blocker refuses the entire batch. A changed source or policy requires another preview. Replaying the same POST idempotency key still returns the original dispatch.
5. Existing explicit image generation and per-shot card/node overrides remain available. `budgetMode=lab_economical` cannot submit commercial cards; `engineTier` must match the chosen card/allocation.

## Retakes, preparation and review chains

`POST /aivideo/open/v1/projects/{projectId}/episodes/{episodeId}/shots/{shotId}:escalate` accepts `strategy`:

- `closed_hero`: a commercial candidate, only with effective hybrid permission.
- `open_structural_lock`: actual persisted `line-worlds` layout video and 8-frame contact-sheet preparation tasks, followed by an open-weights candidate using those references. Bulk economical structural allocations likewise bind both structure and `frame_sheet` explicitly into the subsequent generation context.
- `ab_race`: actual open/closed branches produce existing M8 race proposals. Both candidates remain off the shot until the director uses the existing winner gate; generic proposal apply cannot bypass it.
- `closed_to_open_4k`: commercial acting candidate → **director proposal review** → actual ingredients-sheet preparation → local H3 Optimize candidate using reviewed `@source` → review. Required reference images must exist; missing material fails rather than being fabricated. The card name describes intended workflow, not verified 4K or character-consistency quality.

The same endpoint also accepts `chainMode=open_previz_to_closed_hero` or `closed_hero_to_open_4k_optimize`. Initial generation is followed by the existing proposal-approval barrier, then the prepared reference is handed downstream. A supplied `referenceSourceVideoId` / `referenceSourceImageId` must be the selected candidate from the same shot **and** the authoritative row must be `Approved` (legacy approved status supported); lossy wire status `READY` is not approval. Existing approved keyframes skip draft inference. Shot review exposes the approved-composition action for a selected video or, when no video is selected, a selected image; it submits the corresponding opaque candidate ID. Ordinary same-row status/media edits refresh eligibility and candidates without discarding unsent node overrides, and superseded candidate responses are ignored. Backend approval/ownership/policy validation remains authoritative. The existing selected-video Optimize action is unchanged.

These are an in-process **adapter to M8**, not another scheduler. Reserved `studio:*` profiles are computed and immutable, not remote workers or user-editable agent settings. Only an in-process object principal can claim their admissions/leases. Existing M8 tasks, dependencies, proposal gates, winner selection and cancellation own progression. Per-row source scope, exact video output column, requesting member, effective policy and lease are rechecked; no admin impersonation or remote permission relaxation is used. All candidate selection still uses existing guarded canvas writes.

Canceled/expired/late results cannot overwrite a newer row or selection. Internal media leases are never automatically retried, including on sweeper expiry. Reconcile any provider job before creating another allocation. A restart may interrupt the in-process worker; cancel the interrupted run and create a reviewed new request rather than assuming an exactly-once provider transaction. Remote cancellation/billing cannot be guaranteed.

## Authenticated lower-level API

All `/openapi/v2/*` HTTP endpoints now require the existing active crew identity. Browser writes keep CSRF checks. Upload and run requests also require `X-Project-Slug`; uploads/task queries/output retrieval are owner-granted, references must belong to the requested production, and hybrid policy is read from the authorized project, never forwarded from request-body assertions. Admission authorizes the fully expanded frozen media inputs, including hidden/unexposed imported defaults. A private server-created actor/project capability rechecks current crew/project access, policy/privacy and grants before execution, reference reads, remote upload/submission, polling and publication; serialized task fields cannot grant authority. Revocation prevents subsequent export/publication, not reversal of an already accepted provider operation. Trusted standalone Python calls retain their separate compatibility path and open-only default. Registry/media/task/capability process-local storage still has its original restart limits; a missing HTTP capability fails closed. Grants do not make it durable provider storage. Persistent Story candidate assets remain in PostgreSQL.

## Evidence and limits

The corrective product candidate is `956536dafff7832bcd1c765f459515d9ee536fe0`: the final integrated backend gate passed 389 tests with no skips; frontend passed 111 with no skips; build and a newly installed wheel passed. All six accepted findings at `dda463b271169f3ccee0f9539983e78917aab7ce` have regression evidence. Independent review of `4b77295904990561c59ac877a3cfd91a807b5b08` concluded **OK with notes**: all six original findings are resolved and no new blocker was identified. See the [durable review](SPEC07_REVIEW.md); this later closeout changes documentation only. See [SPEC_07 verification](spec07-verification.json) for commands actually run, exact revisions, the unchanged-candidate browser evidence read from the UI owner, historical bootstrap/review failures and their same-toolchain recovery. The thin Story/vendor/cloud paths used real HTTP, PostgreSQL and FFmpeg with **synthetic loopback commercial inference** and Comfy disabled. Structural/chain/race tests additionally substitute local inference to avoid GPU execution; preparation and review/writeback are real. No paid inference, real credentials, model downloads, GPU benchmark or real visual/model-weight verification was performed. Specialist provider-tier advice does not run Codex/CLI agents or rewrite existing agent configurations.
