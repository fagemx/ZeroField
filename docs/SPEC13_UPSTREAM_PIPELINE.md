# Upstream story preparation (SPEC_13)

Start Creating accepts an **Idea / Logline**, a **Novel / Story Chapter**, or a **Screenplay**. Screenplay remains the default. Text and Markdown files can be loaded into the selected mode. Idea and novel sources stay separate from the editable screenplay so an extraction retry keeps the director's screenplay edits.

**Adapt to Multi-Scene Script** saves a deterministic screenplay for the selected episode. **Confirm Script & Build Storyboard** also performs adaptation when the selected source needs it, then saves the settings and screenplay, extracts assets, confirms the script baseline and builds the storyboard. Adaptation runs offline and never implicitly calls a configured model provider. The existing optional script-refinement action remains separate.

The density choices are automatic beats, one shot per scene, and cinematic sentence/dialogue coverage. A single action sentence remains one shot, including in cinematic mode. API callers can explicitly select `cinematic_multi` to request establishing/detail coverage for that sentence. The first shot retains an ARRI Alexa optical rig. Subsequent coverage derives camera, lens and movement from dialogue, action and close-up cues.

Building again preserves existing shot labels, camera settings, prompts and takes, and appends missing beats. **Rebuild Scene Shots** explicitly refreshes that scene's narrative while retaining its existing shot identity, camera choices and media. A build accepts at most 200 planned shots; larger scripts should be divided into episodes.

Extraction recognizes explicit `Character: Name (traits)`, `@CAST` tags, character variants (`:night` or `#night`), scene environments and `Prop:` declarations. Scene prompts include foreground, midground and background depth cues. Existing asset images and manual rows remain available. This is a bounded rule-based adapter: names and prose it cannot confidently recognize still need director editing; it does not promise the narrative judgment of an LLM.

Each generated shot exposes `dialogue`, `previsPlan` and `readiness`. Its initial 3D Stage plan uses the generated lens, move, action and facing. A referenced `@SET` image supplies the parallax far card. Director drafts and plans stored in existing rendered clips take priority over the initial generated plan.

In **Asset Vault**, **Generate Missing Asset Sheets** uses the selected episode's missing character and set references, including variants. It queues the existing image-generation tasks using `flux-soul-cast` by default and shows group progress. The existing production policy, permissions, accounting and task cancellation behavior apply. No model download or inference is triggered by text adaptation, asset extraction or storyboard construction.

Asset tasks wait for available execution capacity before starting, within the environment/deadline limits and a maximum five-minute capacity wait. Current authority, cancellation, quotes and budgets are checked again before dispatch. A provider action that has started is never retried by this wait path.

API additions under `/aivideo/open/v1`:

- `POST /episodes/{episodeId}/script-adaptations` accepts `sourceText`, `sourceMode`, `targetScenes` and `breakdownMode`; the response includes `script.content` and `engine: "deterministic"`.
- `POST /episodes/{episodeId}/storyboards` and scene rebuilds accept an optional `breakdownMode`.
- Episode details expose `missingAssetCodes`; shot details expose `readiness`, `dialogue` and `previsPlan`.
- `POST /episodes/{episodeId}/asset-image-generations` returns `taskGroupId`, `taskIds` and `assetCodes`. Progress uses the existing `GET /task-groups/{taskGroupId}` route.

The backend must be restarted to load the new Python code. Frontend assets are served from `static/projects/` after `npm run build --prefix ui`.
