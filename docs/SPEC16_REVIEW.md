# SPEC16 independent review and repair record

## Initial review: BLOCK (historical, unchanged)

- Reviewed candidate: `3d303a24daf2c1af6304aac35d2f1cd353afabdf`.
- Seed: `591c3e602f5f35aabd681dbdfedda93dedd0e2f9`.
- Both independent safety and journey reviews concluded **BLOCK**. No P0 was reported; ordinary authoring and privacy defects remained despite passing earlier tests.
- The original integration receipt is preserved byte-for-byte at [initial-integration.json](verification/spec16/initial-integration.json). Its passing counts do **not** establish that the seven findings were covered or safe.
- The prior orchestration workflow's later serialization failure concerned undefined reviewer data after children completed. It does not invalidate or rerun the completed reviews.

Original, authoritative review artifacts (not nonexistent repository reports):

- `C:/Users/fagem/.pi/agent/sessions/--C--ai_project-ZeroField--/subagent-artifacts/outputs/8c7534f1-33f4-4e77-8a67-634dd0010586/spec16/review-safety.md`
- `C:/Users/fagem/.pi/agent/sessions/--C--ai_project-ZeroField--/subagent-artifacts/outputs/8c7534f1-33f4-4e77-8a67-634dd0010586/spec16/review-journey.md`

The initial safety reviewer used source/inline Node reproductions, not a real cross-account browser. The initial journey reviewer used mounted Chromium with injected transport and a substituted structural harness. Those evidence limits remain intact. The auth repair subsequently reproduced the cross-account upload with real PostgreSQL/token HTTP and a shared-cookie browser context before repairing it.

## Accepted findings and scoped dispositions

These are **repair/integration dispositions**, not an independent re-review pass.

| ID | Initial severity / finding | Exact repair | Integrated regression boundary |
|---|---|---|---|
| S1 | P1: A's pending private draft could upload as B after an external cookie login switch; hidden workspace remained active | `530c17dfe9540b6eae78d8218ab7735d9f6f45d0`, completed by `de16d5933420fff5988184f4ba71e20dbf5f875e` | Actor-bound requests, actual unmount/disposal and shared expected-actor validation before writing/legacy dispatch and replay. Real same-context two-tab switch in the preflight window, reconnect before/after detection, replay denial, disposed late ACK retaining newer A recovery, and the private legacy collision tool refusing with zero B-owned cache. |
| S2 | P2: private metadata-only recovery silently adopted the latest CAS base | `530c17dfe9540b6eae78d8218ab7735d9f6f45d0` | Saved version/metadata fingerprints and original base retained. Real root metadata-only recovery requires explicit conflict choice before PUT; source and branch stale CAS remain rejected. |
| J1 | P1: scene-loaded Enter/paste could remove inserted blocks or duplicate IDs before ACK | `165633d502cafa8281cb709484c171481b3953b0` | Draft-local scene membership/editor echo reconciliation. Real root Enter, multi-block paste, deletion, heading split and delayed real server ACK preserve text, unique bids, surrounding scenes and marks. |
| J2 | P1: removed B's retained shots could alias surviving C's reused positional scene ID | `891e654507c013702fcae9d461d44bfc24e5217f` | Atomic detach/remap and explicit merge lineage. Real PG/HTTP removal/reorder/merge/Undo/legacy rebuild tests; root removal/merge retains shot IDs/media/origins without B becoming C. |
| J3 | P1: uncontrolled outline drafts bypassed dirty tracking, recovery and navigation safety | `165633d502cafa8281cb709484c171481b3953b0` | Controlled metadata drafts registered with the existing bounded journal/tool controls. Real root network+storage failure blocks leaving, download retains text, durable recovery permits safe navigation, and divergent metadata keeps its old base without publication. |
| J4 | P2: outline cast/linked-shot UI lacked an actual producer projection | `891e654507c013702fcae9d461d44bfc24e5217f` | Authorized current `assetCodes`, `shotIds`, `shotLinks` projection using stable relationships only. Real root references and linked-shot navigation populated; projection excluded from persistence, hashes and snapshots. |
| J5 | P2: clean print sanitizer collapsed manuscript hard breaks/empty paragraphs | `dc836a0f4942119a4e066717e7b3d10cda064b02` | Fixed owned `p`/`pre` whitespace and empty-paragraph height without admitting author CSS/active elements. Real root export→sanitizer→iframe screen/print layout validates hard/blank/CJK breaks and empty paragraphs. |

All repairs start at the reviewed `3d303a2` baseline. Integration merged the exact commits with original attribution and did not overwrite them with older component snapshots. Locale fragment leaves were collision-checked into both root dictionaries, and production static assets were rebuilt by integration.

Repair reports:

`C:/Users/fagem/.pi/agent/sessions/--C--ai_project-ZeroField--/subagent-artifacts/outputs/34e6c269-450b-4448-afc4-79004addafbe/spec16/`:

- `review1-auth.md`
- `review1-authoring.md`
- `review1-structure.md`
- `review1-print.md`
- `review1-integration.md` (integration handoff)

## Confirmed S1 legacy-caller continuation at the first repair integration

At frozen repair integration `809000135e12608da310de5e55be0d9ee8510ee9`, the writing-namespace S1 regressions passed, but integration identified and **reproduced** a remaining actor-consistency gap in the private source-development tool's legacy `POST /episodes/{id}/story-collisions` caller.

One parent-authorized real root/PostgreSQL/token probe paused A's valid preflight, switched the shared cookie to B using the real second-tab login form, then released the request. The actual collision POST carried A's expected-actor header while the server authenticated B. It returned 200 with a synthetic private character marker, and an idempotency row owned by B retained that marker. No provider call occurred. This is confirmed private derived-data exposure, not merely source reasoning. The new writing-namespace gate alone is insufficient for this caller.

The probe used a separately created, positively owned `spec16_review1_probe_20261023` database, not concurrent schema setup in the running full-gate database. Its evidence is preserved under `integration-validation/review1/legacy-collision-probe.json` and `legacy-collision-probe-result.log`. A first setup-only duplicate `connect_timeout` argument failed before opening a connection; only one product probe executed.

**S1 remained blocking at this intermediate candidate.** The parent routed the narrow legacy auth-before-dispatch/replay correction to the original auth owner; integration did not replace that component or relabel the running gate as a pass for this missing case.

The owner returned exact `de16d5933420fff5988184f4ba71e20dbf5f875e`, directly descending from `8090001`, changing only the two HTTP handler seams and a three-test regression module. Legacy callers without an expectation retain their original auth/CSRF contract; a supplied expectation is checked against the authenticated actor before body-driven work, early responses and cached replay. It never grants authority.

After the untouched `8090001` full command finished **677 passed / zero skips**, integration fast-forwarded the exact correction. The original real-root probe was independently repeated in a **new** `spec16_review1_probe_fixed_20261023` fixture database: the request still carries A's header after B's real login, but now returns **401**, contains no synthetic private marker, creates **zero** B-owned idempotency rows and unmounts the old workspace. The guarded failed probe was not overwritten. Matching-header, header-less cookie/Bearer, CSRF, viewer and cached-replay compatibility checks also passed.

The owner's authoritative report is `C:/Users/fagem/.pi/agent/sessions/--C--ai_project-ZeroField--/subagent-artifacts/outputs/c690e8e3-00a9-43a6-9447-c7af2e1d792f/spec16/review1-auth-legacy.md`. These repairs have new integration evidence, but independent re-review remains pending.

## Integration candidate and evidence

Frozen final repaired product: **`de16d5933420fff5988184f4ba71e20dbf5f875e`**. Intermediate `8090001` remains historical passing-test evidence with a separately confirmed S1 BLOCK; it is not treated as the final gate. Any later documentation closeout is identified separately in the integration handoff. [Current verification](spec16-verification.json) records the actual new gates, artifact hashes, service cleanup and remaining limits; historical counts are not reused as a changed-backend gate.

Affected checks ran before freezing: 34 frontend tests and 19 real PG/auth/root review tests passed, zero skips. Initial integration harness failures (pending-route unregistration order and an incorrect expected message) are retained, not relabeled as product passes. No component source changes were needed beyond the exact four repairs; integration owns only locale registration, compiled output and the new real-product test harness.

At exact final `de16d59`, integration RAN **680 backend tests**, **270 frontend tests**, the production build, the real **768px logout** journey, and **113 installed-wheel tests** outside the checkout; zero test failures/errors/skips in those completed gates. All **170 declared installed-file identities** match the exact frozen Git archive. The initial installed command's too-short timebox interrupted its last case and is preserved as incomplete; the complete unchanged-candidate rerun passed. No changed-backend equivalence shortcut was used.

The full frontend/backend, final production-root journeys, compact logout/identity behavior, long-manuscript timings and exact installed-wheel/resource results belong to the current receipt. Component synthetic transports are expressly distinguished from real root HTTP/PG behavior. The print boundary is Chromium-rendered sanitized HTML, **not OS print/PDF saving**.

## Current review status

**Independent re-review pending.** The original BLOCK remains the valid historical verdict for `3d303a2`. Scoped repair readiness and passing integration regressions do not predeclare the next reviewers' result, user acceptance, model quality, billing guarantees or publication authorization.

No push, deployment, model/provider inference, root-checkout promotion, global default change or foreign service stop is authorized by this record.
