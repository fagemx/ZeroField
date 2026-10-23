# Character and walking demonstration implementation plan

**Goal:** deliver improved continuous previs characters, a real Walk in action, and a playable ten-second walk/settle/look/touch demonstration from the product renderer.
**Architecture:** retain the semantic joint rig, plan/use/acts/pins, Three.js scene and existing WebCodecs export. Skin the visible character geometry; compile movement into existing motion data; give the existing Stage a local demonstration mode without replacing a user's shot draft.
**Tech stack:** Three.js, React, Node tests, browser WebCodecs, FFmpeg.

## Work ownership
- Character worker: figure.js, optional characterGeometry.js, dedicated character regression tests. Preserve joint/kp/material ownership contracts; replace exposed ball-joint silhouette with continuous garment/limb surfaces.
- Motion worker: plan.js, demoPlan.js, dedicated motion tests. Real planted walking, settle, head turn, hand-contact sequence; Walk in uses the same gait.
- Controller: scene.js, PrevisStage.jsx, precise locale additions, scene/demo integration tests and deliverable video. Preserve all existing SPEC12/13 uncommitted work.

## Delivery steps
- [x] Character: implement continuous skinned silhouette and readable neutral head; verify skin influences and semantic joints; capture first version.
- [x] Motion: connect Walk in to gait, provide ten-second plan and targets; verify planted intervals, settled root, head turn and contact interval.
- [x] Scene: preserve final ankle/foot orientation through retarget, apply head look, render visible listener/object and soft studio lighting through buildStage.
- [x] Product: local demo entry/replay/download within existing PrevisStage, no backend write or replacement of active shot; EN/zh-TW labels.
- [x] Capture with product renderer, inspect stills/sequence, fix visual defects, export WebM and MP4 with faststart plus contact sheet.
- [x] Run relevant tests and production UI build; obtain independent cross-review; preserve video and evidence, clean task-owned temporary processes.

No external models, full physics, face/lip-sync rig, new renderer, deployment, or whole-worktree commit. Current user approval already selects this direction; no additional design gate is needed.

