# Character and walking demonstration — authorized implementation

User request (2026-10-23, Asia/Taipei): improve the mannequin and walking first, then show a complete demonstration of walking in, settling, turning the head toward a person, and reaching to touch an object.

Owner: the existing `review_3d_controller` collaboration agent now owns implementation, integration, visual review, and delivery. The parent remains the conversational interface.

Approved direction: preserve Three.js, the semantic rig and shared motion/camera pipeline; improve the character's continuous silhouette and readable neutral clay styling, real stepping, grounded feet, weight transfer and transitions. Reuse current SPEC12 work. Do not replace the renderer, introduce a scheduler, or expand into a full physics/facial-animation system.

Required result:

- A visibly improved actor in the actual Previs implementation, with coherent torso/shoulder/neck/limb shapes instead of exposed ball-joint assembly.
- The visible Walk in action produces stepping rather than rigid root translation.
- A clear demonstration, approximately 8–12 seconds as appropriate, with a visible listener/look target and tangible contact object: enter, come to rest, turn toward the person, reach and hold contact.
- A playable local video and representative still/contact sheet, rendered from the implemented scene, plus a convenient in-product replay/demo entry where appropriate. A screenshot or code-only fixture is insufficient.
- Relevant behavioral/regression verification, a production UI build, and independent visual/code review. Actual motion and appearance take precedence over accumulating test counts.

Constraints: preserve all existing uncommitted SPEC12/SPEC13 work and other authors' files. Inspect live workspace before editing shared files; own only the bounded 3D change and its supporting tests/docs/assets. English-first UI with semantic en/zh-TW keys for visible additions. No paid providers, model downloads, pushes, deployments or unrelated product redesign. Local browser rendering and FFmpeg export are authorized by the requested demonstration.

References: `docs/verification/3d-review-20261023/review-notes.md` and its current component captures. The previous isolated audit harness and server were removed.

Delivery must state what was actually integrated, what was visually observed, tests/build results, demonstration paths, and any remaining limitations. Preserve review captures. Clean up only task-owned temporary processes and scratch files, keeping the demonstration runnable/reviewable.
