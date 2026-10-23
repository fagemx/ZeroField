# Character and movement demonstration

Delivered 2026-10-23 (Asia/Taipei). This is a local previs demonstration rendered by the implemented product code, not an AI-generated replacement film.

## Watch
- `movement-demo.mp4`: H.264, 1280×704, 24 fps, 241 frames, 10.041667 seconds, faststart.
- `movement-demo.webm`: original product WebCodecs output, with its authored plan embedded.
- `movement-contact-sheet.jpg`: the whole sequence sampled at one-second intervals.
- `movement-contact.png`: final look-and-touch pose extracted from the delivered video.

In the product: open Cinema Studio → 3D Stage → Movement demo. Play or scrub it; Download demo video saves the same sequence locally. Back to shot restores the shot view. Viewing/downloading the demonstration does not overwrite the shot or its draft.

## What changed
- Continuous skinned shirt/sleeves and trousers replace the exposed mannequin segments. The original semantic rig, bone lengths, fingers and skeleton pass remain compatible. Neutral facial direction cues, smooth hair, a connected wrist and a sloped shoulder/collar improve readability.
- The existing Walk in action now uses the shared contact-aware walkTo skill: alternate lifted feet, support-foot contacts, arm swing, weight transfer and a settled finish.
- A ten-second plan uses the ordinary skills/acting/pins pipeline: 0–4 s walk, 4–5 s settle, 5–6.5 s look at the visible partner, 6.5–8.5 s reach, then hold the visible contact through 10 s.
- Final rig ankle orientation follows the solved toe direction. The visible touch pad is placed under actual fingertips, not just under the wrist target.
- The existing stage renders the floor/partner/contact prop and exports the video. Export locks shot navigation; stage disposal releases skinned skeleton resources; demo keyframe exports use their own identity.

## Verification
- `npm test --prefix ui`: 192 passed, 0 failed, 0 skipped. This run includes the final wrist/hair, contact prop and export changes.
- `npm run build --prefix ui`: passed. Existing large-entry chunk warning remains.
- `git diff --check` on changed Previs and locale/test paths: passed.
- Behavioral checks cover connected garment surfaces, normalized skinning weights, real sleeve deformation, rig/hand landmarks, ordinary walking, planted feet, final hand/fingertip contact and toe retargeting.
- Browser capture used the actual PrevisStage component in an isolated local page. Download demo video produced the original WebM. FFmpeg converted it to MP4 and extracted the delivered stills.
- Chrome decoded and played the exported MP4 to its end: ended=true, 10.041667 seconds, readyState=4, 1280×704, no media error.
- Independent character and motion/code reviewers inspected the full time-sampled sequence and final contact frame. No blocking issue remained. Earlier findings about floating wrists, mismatched hair, wrist-only contact, export navigation and skeleton disposal were repaired before delivery.

## Limits and retained work
This is an improved procedural previs character and motion demonstration, not finished character animation or facial performance. The last pose has a relaxed knee bend; no obvious floating, detached parts or penetration was seen in the reviewed frames. GPU inference/provider quality was not involved or evaluated.

All pre-existing SPEC12/SPEC13 work was preserved. No push, deployment, model download or paid call occurred. Temporary capture source and the controller-owned preview server were removed; delivered media remains here. Earlier `first-character-preview.png` and `accepted-contact-preview.png` are work-in-progress inspection records; the `movement-*` files are the final deliverables.
