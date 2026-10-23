# 3D review — 2026-10-23

Scope: current workspace, including SPEC12/13 work in progress. Read-only product audit; no product code changes, build, GPU render or provider call. The main application was not running on its documented port; captured the current PrevisStage component in an isolated Vite page with synthetic shots and no backend writes. This is not an end-to-end production journey test.

## Current captures
1. `01-stage-current.png`: initial default lens view and expanded help. Demonstrates the actual UI proportions and gray segmented actor. Camera composition uses a synthetic/default shot and is not evidence that every real shot is misframed.
2. `02-actor-front.png`: Empty stage, Stand, room-facing, locked camera, 35 mm. Current segmented torso, floating-looking neck, egg-shaped feature-poor face and stiff arms are directly visible.
3. `03-actor-body.png`: same actor with free camera moved back; shows body silhouette, limbs and feet. Camera guide overlaps actor; preview can be cluttered while composing.

## Recommendation
Preserve Three.js, the semantic plan/rig, camera sampling, and the shared preview/conditioning export. Improve the character silhouette and actual motion, then expose direct blocking. Use a readable display character/look and clean model-conditioning output from shared motion/camera state. The existing board/render looks and shot-grammar prototype are useful foundations; CozyClay is current work, not a new proposal.

## Findings
- Geometry: figure.js:83,125 uses ellipsoids/lathe parts and separate joints; build variants mainly scale the same shape (plan.js:106). Replace the visible proxy with continuous skinned low-poly geometry and intentional body proportions. Keep the rig semantics. Material polish alone does not solve the silhouette.
- Motion: plan.js:175 walkin translates root 2.2 m with pose:{}; visible Action writes only action (PrevisStage.jsx:290). Existing WIP walkTo runs through plan.use (plan.js:407), not that entry. Connect the current action to real stepping before adding more techniques.
- Directing UI: PrevisStage currently exposes few canned actions and camera presets, not actor marks/contact targets/beat editing. Existing prototype overhead.js:54 and perftrack.js:33 already provide reusable interaction ideas. Integrate within Stage rather than adding another workbench.
- WIP contact quality: motion QA evaluates solved XYZ (scene.js:191), whereas retarget (scene.js:83) does not align ankle-to-foot direction. A read-only Node geometry check found kneel QA clean while final foot tip was 1.19 cm below ground. Fix the final rig result, not by adding another acceptance process.
- Multiple actors: scene.js:185–200 solves/fixes only cast[0]; others use sampleActs. Treat as a single-actor capability limit before promising reliable pair contacts.
- Output: product preview and WebM export share Three stage.frame (PrevisStage.jsx:210); Blender stage_render.py is research, so no evidence of two current product renderers drifting. TextureLoader is asynchronous without readiness (scene.js:63), while render/export starts immediately (PrevisStage.jsx:194,227); gray-card export is a source-established race risk, not browser-reproduced.
- Editing state: localStorage drafts and WebM plan snapshots are separate from upstream generated seed. SPEC13 is actively wiring shot metadata; review should align with that work. Make active draft, rendered snapshot and upstream changes understandable. WebM fetch reads only first 8 KB (webm.js:94), unsuitable as sole growing motion storage.
- External motion: MSFlow command builder exists, but no product adapter or plan.xyz consumer found. Do not call this integrated motion generation.

## Priority
Now: fix Walk in wiring and final contact; replace/readably restyle actor continuous silhouette; reuse direct mark/facing/beat UI; collapse help and prioritize viewport.
Next: per-cast identity and shared targets, upstream plan/version reconciliation, a small set of reliable motion clips. Keep display look separate from conditioning.
Defer: full physics, face rig/lip-sync, another renderer, huge model pipeline or more motion generators before basic directing is reliable.

## Evidence limits
No live backend workflow, inference quality, performance benchmark, accessibility compliance, or GPU/export timing was tested. No measured FPS regression is claimed. Current source changed during review due to an authorized parallel SPEC13 session; SPEC12/13 are work in progress.
