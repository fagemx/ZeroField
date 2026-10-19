# SPEC_07 corrective independent review

**Candidate:** `4b77295904990561c59ac877a3cfd91a807b5b08`  
**Previously reviewed:** `dda463b271169f3ccee0f9539983e78917aab7ce`

Exact HEAD verified; checkout remained clean. Product/tests/assets are unchanged from the validated `956536d` candidate. This report supersedes no historical evidence; the original BLOCK review remains preserved.

## Files Reviewed

- `project_assistant/studio/openapi_v2_hub.py` (48–85, 238–465).
- `project_docs/runtime_http.py` (186–203, 218–325).
- `project_docs/story_allocation.py` (43–341).
- `project_assistant/studio/agent_allocator.py` (152–169, 267–280).
- `project_assistant/studio/model_router.py` (authority contract and existing execution checkpoints).
- `ui/src/SheetWorkspace.jsx` (130–131 and both review mounts).
- `ui/src/StoryWorkbenchModals.jsx` (207–267).
- `ui/src/storyModel.js` (66–88), EN/zh-TW additions.
- `tests/test_studio_v2_authority.py` (1–407).
- `tests/test_story_allocation_preflight.py` (1–293).
- `ui/tests/shotReview.browser.py` (1–178), associated model tests.
- Four corrective handoffs, maintained documentation and actual saved gate/browser/wheel evidence.

## Original finding dispositions

| Original finding | Disposition and evidence |
|---|---|
| **P1: imported-default grant bypass** | **Resolved.** `openapi_v2_hub.py:431–455` authorizes expanded inputs before admission and freezes that same plan privately. `_media_slots()` includes hidden/unexposed defaults and distinguishes graph links. **RAN:** missing-account/wrong-project grants rejected before admission; valid owned defaults executed once despite mutation of public graph copies. **READ:** corresponding real HTTP/PostgreSQL regressions. Owner: v2 admission/reference seam. |
| **P1: stale v2 authority** | **Resolved.** `runtime_http.py:186–203,321–322` captures authenticated actor/project in a server-created capability. `openapi_v2_hub.py:259–278,309–328` rechecks it before reference access, upload, submission and polling; publication also checks authority. **RAN:** revoked grants/member/policy/privacy and missing capability fail closed; JSON-shaped authority rejected. **READ:** checkpoint revocation, late-publication, graphless and synthetic-SDK regressions. Owner: v2 execution authority. |
| **P2: false input-ready allocation** | **Resolved.** `story_allocation.py:43–170` validates existing metadata and typed future preparation outputs. Lines 219–222 revalidate every assignment before scheduling or consuming anything. **RAN:** legitimate structural preparation remains ready; missing references and invalid future-output roles block; a failing second assignment prevents all scheduling/consumption. **READ:** required-input, custom-card, deleted-media and escalation regressions. Owner: Story preflight/dispatch. |
| **P2: dropped bulk contact sheet** | **Resolved.** `agent_allocator.py:158–161` explicitly binds `frame_sheet` alongside structure. **RAN:** the subsequent real context compiler received both distinct references. **READ:** actual persisted FFmpeg preparation/final-consumer regression. Owner: allocator stage binding. |
| **P2: stale same-row review status** | **Resolved.** Workspace source identity reaches both mounts; `StoryWorkbenchModals.jsx:234–245` synchronizes eligibility and refreshes candidates without revision-keyed remounts. Superseded fetches are ignored. **READ:** actual Queued→Retake→Pending Review→Approved interactions preserve DOM identity and unsent overrides; held stale media response cannot replace the new selection. Owner: workspace/review synchronization. |
| **P2: missing approved-image action** | **Resolved.** `storyModel.js:66–70` chooses `referenceSourceImageId` when no selected video exists; selected video retains precedence. `StoryWorkbenchModals.jsx:254` submits that opaque source. **RAN:** model behavior tests. **READ:** actual image-only/video browser request assertions and backend approved-image handoff regression. Owner: review request construction. |

## Critical (must fix)

None identified in the corrective blast radius.

## Warnings (should fix)

No new concrete P0/P1/P2 issues identified.

## Suggestions (consider)

None required for this corrective scope.

## Verification

### RAN
- Exact HEAD, clean/staged-state, product-revision equivalence and source whitespace checks.
- Compatibility plus allocator tests: **26 passed**.
- Story UI model tests: **7 passed**.
- Bounded in-memory adversarial checks covering expanded defaults, wrong grants/projects, frozen inputs, replay suppression, missing/forged capability, current revocation, typed preparation, all-or-none dispatch and contact-sheet consumption.
- Independent hash comparison: **all 19 saved source/resource hashes match** current files; owned database PID file absent.

Synthetic checks used fixture bytes and mocked persistence/executors—not real database or inference.

### READ
- Final backend log: **389 tests, OK, no skips**.
- Final frontend log: **111 passed, no skips**.
- Production build and newly installed-wheel evidence; wheel SHA256 `bb77a19c89a191a54a5fce4a6a75883d451cf5af625e33fdc5ab8b8bc902bce1`.
- Three passing Playwright interaction tests, their actual assertions/log and all three screenshots.
- Tests demonstrate trusted local/SDK/facade paths remain supported. No M8 principal, remote-binding or existing-agent configuration relaxation appears in this fix diff.

### NOT RUN
Full suites/build/browser/wheel were not duplicated. No services restarted, live provider calls, paid inference, downloads or GPU execution occurred.

## Summary

All six original findings are resolved with connected regression evidence and bounded independent checks. No new blocker was identified in the fixes; provider compatibility, quality, billing, weights and contest eligibility remain outside this acceptance.

Skipped: full-gate reruns and live inference; checkpoint revocation cannot reverse an already accepted remote operation.  
**Verdict: OK with notes.**