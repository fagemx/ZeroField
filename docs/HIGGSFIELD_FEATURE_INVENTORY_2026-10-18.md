# Higgsfield Feature Inventory

Research date: 18 October 2026, Asia/Taipei.

This inventory covers Higgsfield's website navigation, creative workspaces, tool menus, Apps categories, model selectors, integrations, and community surfaces. Its purpose is to support ZeroField's competition research across the whole product, without prematurely selecting Genjutsu as the only reference.

Higgsfield combines proprietary models, third-party models, task-specific controls, reusable assets, agent workflows, and distribution/community features. A product name, a model-selector label, and a trained foundation model are not interchangeable concepts.

## Evidence and coverage

| Status | Meaning |
| --- | --- |
| UI | The current page, controls, or form was inspected in the browser. This does not mean a generation was executed. |
| Entry | A live navigation entry, catalog card, landing page, or workspace entry was inspected; deeper execution was not examined. |
| Docs | Supported by official documentation or the connected Higgsfield model catalog. |
| Gated | Opening the tool encountered the account's first-use questionnaire. |

All four expandable global menus were inspected: Image, Video, Audio, and Plugins. All eight Apps category pages were opened. The tables distinguish form inspection from entry-only discovery. No generation, training, publishing, paid job, plugin installation, or account-setup submission was performed. Dynamic template feeds and every parameter combination of every model were not exhaustively traversed. This is a feature inventory, not a quality benchmark or certification that every advertised feature works.

## Global navigation

| Entry | Product role and observed contents | Evidence |
| --- | --- | --- |
| [Explore](https://higgsfield.ai/) | Product discovery, featured releases, effects, community work, and model entry points. | Official page and navigation |
| [Image](https://higgsfield.ai/ai/image?model=gpt_image_2) | Image generation plus references, Elements, model choice, aspect ratio, quality, resolution, and batch controls. Separate feature and model lists in its menu. | UI |
| [Video](https://higgsfield.ai/ai/video) | Create Video, Edit Video, Motion Control; a large menu of independent studios and utilities. | UI |
| [Audio](https://higgsfield.ai/audio) | Text to Speech, Voice Change, Translate. | UI |
| [Genjutsu](https://higgsfield.ai/ai/video?model=genjutsu) | Motion transfer and object replacement driven by an existing video. | UI |
| [Katana](https://higgsfield.ai/katana) | Recreate an edit using reference video, character/detail images, and optional instructions; the inspected page hands off to Claude. Community preset categories include Personalized edits, Style transfer, Motion transfer. | UI |
| [AI Influencer](https://higgsfield.ai/ai-influencer-studio) | Menu-based character builder, optional face reference, and a separate Motion mode. | UI |
| [Academy](https://higgsfield.ai/academy) | Lessons, practical homework, PDF materials, course completion certificate, and links to advanced tutorials. | UI |
| [MCP](https://higgsfield.ai/mcp) / [ChatGPT Plugin](https://higgsfield.ai/mcp?tab=chatgpt) | Assistant integrations and workflow recipes. Public page also lists Claude, Claude Code, Telegram, CLI, and Other. | Docs and live navigation |
| [API](https://open.higgsfield.ai/explore) | Programmatic model catalog and generation API documentation. The global menu links to the developer console. | Official API documentation; no credential console inspected |
| [Ads Studio](https://higgsfield.ai/ads-studio) | Two explicit starting tools: performing static ads and Ad Multiplier. Website-derived brand kit and product import are described on the page. | UI; static-ad creation not submitted |
| [Effects](https://higgsfield.ai/effects/use) | Effect recipe selection with per-recipe media slots, optional prompt, resolution, and aspect ratio. | UI |
| [Cinema Studio](https://higgsfield.ai/generate) | Film project workspace with reusable Elements and director controls. Version 4.0 was inspected. | UI |
| [Contests](https://higgsfield.ai/contests/higgsfield-global-film-festival) | Higgsfield's own contests, rules, timeline, submissions, shortlist, judging/voting status, and film viewing. Separate from the Comfy competition. | UI |
| [Marketing Studio](https://higgsfield.ai/marketing-studio) | Product and creator advertising workspace; UGC, Product shot, Motion, Ads, Posters, Marketplace, TikTok, plus Ad Reference and Product Link. | UI |
| [Supercomputer](https://higgsfield.ai/supercomputer) | Agent chat, projects, Skills, connectors, memory entry, Apps, Games, and Faceless Studio. Showcase workflows include marketing, explainers, websites, brand kits, and motion graphics. | UI; no chat submitted or private memory inspected |
| [Edit](https://higgsfield.ai/layers) | Advertised image-to-editable-layers workspace; Inpaint links here as well. | Gated by first-use questionnaire |
| [Community](https://higgsfield.ai/community) | Discovery, Projects, Shots, Creators, Contests, Originals; open projects, creator profiles, Grants, and creator partnership links. | UI |
| [Plugins](https://higgsfield.ai/plugins/after-effects) | Photoshop, Premiere Pro, After Effects, DaVinci Resolve, Figma, Blender, Minecraft. | All seven menu entries inspected; After Effects landing page inspected |
| [Canvas](https://higgsfield.ai/canvas) | Board workspace; entry offers Long Video, Simple Seedance, Extend Video, Image Edit, and StoryBoard With Elements templates. | UI entry; no board created; node behavior supported by Docs |
| [Originals](https://higgsfield.ai/original-series) | Film/series distribution and discovery: Choice, First Look, On Our Radar, Coming Soon, and contest-to-series promotion. | UI |
| Assets, team, pricing, enterprise | Shared media library, collaboration and plan/service entry points. | Navigation only; no purchase, invitation, permission, or account changes |

## Image creation and reusable assets

| Tool | Input and intended result | Observed controls or limit | Evidence |
| --- | --- | --- | --- |
| [Create Image](https://higgsfield.ai/ai/image?model=gpt_image_2) | Text and reference assets to images. | References, Elements, aspect ratio, quality, resolution, and batch size. | UI |
| [Cinematic Cameras](https://higgsfield.ai/generate?mode=image&imageModel=cinematic-v1) | Image generation with cinematography controls. | Dedicated Image-menu entry; related Cinema video controls inspected separately. | Entry |
| [Soul Moodboard](https://higgsfield.ai/moodboard) | Reference-image collection to reusable visual direction. | Build your moodboard; curated aesthetics such as Warm ambient, Y2K studio, Flash editorial, Retro BW. | UI |
| [Soul ID Character](https://higgsfield.ai/character) | Multi-angle photos to a trained reusable character identity. | Create character links to an upload workflow. | UI entry; no training |
| [AI Influencer](https://higgsfield.ai/ai-influencer-studio) | Menu configuration and optional photo to a character sheet; separate Motion workflow. | 19 attribute categories observed, including type, gender, build, hair, age, proportions, facial features, and accessories; Randomize; Explore/History. | UI |
| [Photodump](https://higgsfield.ai/ai/image?model=soul-v2&modal-photo-dump=true) | Aesthetic photo-set workflow associated with Soul. | Current navigation exists; opening it redirected to the first-use questionnaire. | Gated |
| [Image Relight](https://higgsfield.ai/apps/relight) | Image to relit image. | Six direction shortcuts, interactive direction, soft/hard light, brightness, and color. | UI |
| [Inpaint](https://higgsfield.ai/layers?model=nano_banana_pro_inpaint) | Select an area and describe a change. | Linked to Layers in the current Image menu. | Entry; Layers gated |
| [Upscale](https://higgsfield.ai/upscale) | Uploaded media to increased resolution/quality. | Upload Media; page accepts images or videos in its copy. Detailed controls require an input. | UI entry |
| [Face Swap](https://higgsfield.ai/apps/face-swap) | Source face plus target photo/video to face replacement. | Photo/video generation-type choices and the source/target workflow are explained on the landing page. | Landing UI, no upload |
| [Character Swap 2.0](https://higgsfield.ai/apps/character-swap) | Source character plus target scene/pose to a recast image. | Distinct from face-only replacement. | Landing UI, no upload |
| [Soul / Soul Cinema](https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-soul-to-generate-images) | Fashion/editorial and cinematic still generation. | Soul ID, Soul HEX color transfer; Moodboards for Soul 2.0. | Live model menu plus Docs |
| [Popcorn](https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-popcorn) | Storyboard sequence generation with references. | Official guide describes Manual, Auto, and Instadump; up to eight frames. | Docs and footer entry, not a current workspace walkthrough |
| [Fashion Factory](https://higgsfield.ai/fashion-factory) | Fashion-focused workflow entry. | Official URL redirected to an image-generation modal route. | Entry; inner workflow not inspected |

## Video production and editing

| Tool | Input and intended result | Observed controls or limit | Evidence |
| --- | --- | --- | --- |
| [Cinema Studio 4.0](https://higgsfield.ai/generate) | Brief and references to cinematic shots; reusable project assets. | References 0/50; Film setup, Camera, Color palette, Lighting, movement, audio, duration, ratio, batch. The inspected page offered 1080p. | UI |
| Cinema Film setup | Film language across generated footage. | Genre, Era, Tempo tabs. | UI |
| Cinema Camera | Camera/lens aesthetic and depth of field. | Modern, 35mm Film, 8mm Film, DV Camcorder; Clean Sharp, Anamorphic, vintage lenses; f/1.4, f/4, f/11. | UI |
| Cinema Movement | Specify camera movement in a shot. | Dolly, tracking, pan, tilt, crane, drone orbit, rack focus, handheld, POV, Snorricam, robot arm, bullet time, whip pan, helicopter, and others. UI states movement choices are inserted into the prompt and order matters. | UI |
| [Genjutsu Motion transfer](https://higgsfield.ai/ai/video?model=genjutsu) | Existing performance to a rebuilt cast/scene. | 4–30 second source, up to 30 images, optional prompt, style choices, 480p/720p/1080p. | UI |
| Genjutsu Objects swap | Existing footage plus reference assets to a selected replacement. | Separate mode; same visible video/image limits and quality choices. | UI |
| [DoP](https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-dop) | Keyframe image to a directed camera/VFX shot. | Motion/effect presets; official documentation calls it Higgsfield's proprietary model. | Live model menu and Docs |
| [Faceless Studio](https://higgsfield.ai/faceless-studio) | Channel idea, reference, or script to recurring faceless content. | Education, History, Kids, Storytelling; channel idea, Reference, Upload script, Next. | UI entry; later channel-creation stages not submitted |
| [3D Jutsu](https://higgsfield.ai/3d-jutsu) | Prompt/reference to a staged 3D scene and then video. | Scene brief, attachments, model settings, duration, ratio. Page describes movable props, cameras, light, animation, and export to Seedance 2.5. | UI entry; no scene generated |
| [Shorts Studio](https://higgsfield.ai/shorts-studio) | Uploaded footage to a styled short. | Current upload limit is two minutes; language detection, vertical/horizontal, preset library, create a preset from references. | UI |
| [Explainer](https://higgsfield.ai/explainer) | Topic, attached files, or link to an explainer. | Preset, duration, voice, ratio, subtitles. | UI |
| [Mixed Media](https://higgsfield.ai/mixed-media) | Video to stylized animation/collage. | 1–10 second input; FPS, resolution, preset-specific color controls; sketch, paper, comic, collage and other looks. | UI |
| [Edit Video](https://higgsfield.ai/ai/video/edit) | Targeted scene, element, style, and composition changes. | Edit-tool picker plus examples of relight, draw-to-edit, object swap, reframing, cleanup, recolor. | UI tool menu and guidance |
| Extend Video | Continue a source clip. | Dedicated entry in the Edit Video tool picker. | Entry; Cinema extension also documented |
| [Reframe](https://higgsfield.ai/ai/video/reframe) | Resize/reposition footage for another format. | Source duration 4 seconds to 1 minute; Ratio and Quality controls. | UI; promotional preview had a media-loading error |
| Video Upscale | Increase video resolution. | Dedicated Edit Video tool; FLUX.3 Upscale also appears as a model entry. | Live menu and official release notes |
| Remove Background | Source video to cutout or mask. | Up to 200 MB, prompt identifying elements to remove/keep, Cutout video or Alpha mask. | UI |
| SDR to HDR | Convert source footage to HDR. | Source up to 60 seconds; H.265 10-bit output shown. | UI |
| FPS Boost | Increase frame rate. | Dedicated Edit Video tool-picker entry. | Entry, no detailed parameter inspection |
| Depth Map | Extract depth information from media. | Dedicated Edit Video tool-picker entry. | Entry, no detailed parameter inspection |
| [Video Relight](https://higgsfield.ai/apps/video-relight) | Re-light existing footage. | Six named presets plus Auto; custom direction, color, brightness, diffusion, two-light prompt, save preset. | UI |
| [Video Color Palette](https://higgsfield.ai/apps/video-rehex) | Apply a preset or reference-derived palette to footage. | Presets; From image or Color wheel; add, edit, reorder colors; save palette. | UI |
| [Lipsync Studio](https://higgsfield.ai/lipsync-studio) | Image/video plus speech to a talking clip. | Upload image, audio text or generated/uploaded audio, scene prompt, model, duration, resolution. | UI |
| [Draw to Video](https://higgsfield.ai/ai/video?video-inpaint=true&generationType=video) | Sketch-guided video creation. | Explicit Video-menu entry. | Entry only |
| [Draw to Edit](https://higgsfield.ai/ai/video?image-inpaint=true) | Draw on video frames to guide an edit. | Explicit Video-menu entry and editing guidance. | Entry only |
| [Kling Motion Control](https://higgsfield.ai/ai/video/motion) | Transfer video motion to an image subject. | A separate current menu entry from Genjutsu. | Entry only |

## Advertising workflows

| Tool | What it packages | Evidence |
| --- | --- | --- |
| [Marketing Studio](https://higgsfield.ai/marketing-studio) | UGC, Product shot, Motion, Ads, Posters, Marketplace, TikTok; image/video modes, avatar/product inputs, aspect ratio, batch, and templates. | UI |
| Marketing Ad Reference | Reference ad video plus product and avatar; preserve an ad's format while replacing its subject matter. | Upload/PRODUCT/AVATAR/CONTINUE form inspected |
| Marketing Product Link | Product-URL-based creation. | URL input and CONTINUE form inspected; not submitted |
| [Ads Studio static ads](https://higgsfield.ai/ads-studio) | Website-derived brand assets and product imports for static campaign variants. | Landing UI and official description; setup not completed |
| [Ad Multiplier](https://higgsfield.ai/ads-studio/ad-multiplier) | Existing ad to variations in cast, product, setting, language, hook, or CTA. | UI: 4–30 second source, up to 20 images, optional Change hook and Change CTA, quality selector |
| [Click to Ad](https://higgsfield.ai/apps/link-to-video-ad) | Product links to UGC/professional ads. | Opening this route redirected to Marketing Studio's Product Link modal; these are connected entry points, not evidence of two independent implementations |
| [Virality Predictor](https://higgsfield.ai/apps/virality-predictor) | Estimate a video's hook/virality potential before publishing. | Current Apps catalog; no predictive-accuracy validation |

## Audio

| Tool | Input and output | Evidence |
| --- | --- | --- |
| [Text to Speech](https://higgsfield.ai/audio?voiceMode=voiceover) | Script/reference media to generated speech. | UI: model choice, optional script and voice details, batch size; the inspected Seed Audio form accepts up to three voice/audio or image inputs |
| [Voice Change](https://higgsfield.ai/audio?voiceMode=change-voice) | Source video plus selected/uploaded voice to a changed voice track. | UI: required voice and video |
| [Translate](https://higgsfield.ai/audio?voiceMode=translate) | Source video to translated/revoiced content with lip sync described by the page. | UI: video upload and target language |

Audio generation, voice change, translation, native video audio, and Lipsync Studio are related but separate workflows.

## Apps directory

These are the entries visible in the eight category pages during the inspection. Many are named templates or wrappers around shared capabilities. They must not be added up and described as independent foundation-model capabilities. Dynamic catalog pagination and every template's individual upload form were not exhaustively tested.

| Category | Entries observed |
| --- | --- |
| [Professional](https://higgsfield.ai/apps/camera-motion) | Angles 2.0; What's Next?; Shots; Zooms; Behind the Scenes; Transitions; Expand image; Color grading; Virality Predictor. |
| [Enhance & Style](https://higgsfield.ai/apps/enhance-style) | AI Stylist; Relight; Skin Enhancer; Outfit Swap; Style Snap; Outfit Vending; Glitter Sticker; Outfit Shot. |
| [Face & Identity](https://higgsfield.ai/apps/face-identity) | Recast; Character Swap 2.0; Face Swap; Commercial Faces; Video Face Swap; Headshot Generator. |
| [Video Editing](https://higgsfield.ai/apps/video-editing) | ClipCut; Urban Cuts; Sticker Match Cut; Breakdown; Japanese Show; Video Background Remover. |
| [Ads & Products](https://higgsfield.ai/apps/ads-products) | Click to Ad; ASMR Add-On; ASMR Classic; Poster; Bullet Time Scene; Chameleon; ASMR Host; Packshot; Macro Scene; Magic button; Truck Ad; Giant Product; Bullet Time White; Kick Ad; Billboard Ad; Graffiti Ad; Bullet Time Splash; Fridge Ad; Volcano Ad; Macroshot product. |
| [Games & Characters](https://higgsfield.ai/apps/games-characters) | Game Dump; Nano Strike; Nano Theft; Simlife; Plushies; 3D Render; 3D Figure; Pixel Game; Brick Cube; Sketch-to-Real. |
| [Extras](https://higgsfield.ai/apps/extras) | Paint App; Signboard; Micro-Beasts; AI Meme Generator; Background Remover. |
| [Trending Templates](https://higgsfield.ai/apps/trending-templates) | Yes Kiss; Latex; J-Magazine; Roller Coaster; 60s Cafe; Victory Card; Sand Worm; Skibidi; J-Poster; Mascot; Storm Creature; Burning Sunset; On Fire; Comic Book; Cloud Surf; Mukbang; Melting Doodle; Giallo Horror; Renaissance; Rap God. |

Examples of distinct capabilities behind these names: generate new viewpoints (Angles), propose nine shots (Shots), generate nine zoom levels (Zooms), suggest eight narrative continuations (What's Next?), create transitions, relight, change outfits, replace faces or characters, split image components, place a product in an ad scene, and produce stylized character imagery. Counts such as nine shots or eight continuations come from the live catalog descriptions, not a completed generation test.

The Extras Background Remover card had inconsistent copy describing headshots; its title alone should not be used as evidence of its precise implementation. Likewise, a 3D Render/3D Figure style template does not establish that it exports an editable 3D mesh. The separate 3D Jutsu workspace explicitly describes editable scene objects.

## Model choices in the current global menus

The lists below record visible menu labels, not a claim that they are all Higgsfield-trained models or the complete API catalog. Availability, versions, limits, and aliases can change.

| Menu | Visible choices |
| --- | --- |
| Image | Higgsfield Soul 2.0; Higgsfield Soul Cinema; GPT Image 2.5 Sunburst; GPT Image 2.5 Flare; Nano Banana 2.1; Seedream 5.0 Pro; Nano Banana Pro; FLUX 3 Image; Recraft V4.1; Grok Imagine 2.0; FLUX.2; Z-Image; Topaz. |
| Video | Seedance 2.5; Higgsfield Genjutsu; Gemini Omni Flash 1.1; FLUX.3 Video; FLUX.3 Upscale; Kling 3.0; Kling Motion Control; MiniMax H3; Wan 3.0; Grok Imagine 1.5 Lite; Grok Imagine 1.5; Kling 3.0 Omni Edit; Google Veo 3.1; HappyHorse; Minimax Hailuo 2.3; Higgsfield DOP. |
| Audio | Seed Audio 1.0; Eleven v4; Eleven v4 Turbo; Eleven v3; Qwen Audio 3.0; MiniMax Speech 2.8 HD; Seed Speech. |

Official sources identify [DoP as a proprietary Higgsfield model](https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-dop) and [Soul as an in-house model family](https://higgsfield.ai/blog/how-we-built-cinema-studio). The [Cinema guide](https://higgsfield.ai/creator-hub/help-center/tools/how-do-i-use-cinema-studio) says Cinema Studio 4.0 runs on Seedance 2.5. The surveyed Genjutsu pages/API describe its capabilities and endpoint but do not establish its training architecture. A provider label in a catalog is not sufficient to resolve that question.

## Agent workflows and integrations

Supercomputer's inspected interface includes chat, projects, Skills, connectors, memory, and links to Apps, Games, and Faceless Studio. Its Skills catalog lists Product UGC, Higgsfield Faceless Video, Shorts Maker, TV Commercials, YouTube Covers, Short-form Drama, Personal Clipper, Motion Design, Animated Infographics, Cinematic Videos, UGC Videos, and Localization. The catalog distinguishes Skills and Use cases; they are not necessarily separate models. Showcase entries additionally include Ad Multiplier, Brandkit, editorial motion graphics, and website building.

The [MCP page](https://higgsfield.ai/mcp) provides client-specific connection paths and recipes for generation, editing, ad strategy, reference-ad adaptation, hook variants, and explainer production. The [API catalog](https://open.higgsfield.ai/explore) exposes programmatic model interfaces. This inspection did not install a connector or inspect API secrets.

| Integration entry | Observed role | Coverage |
| --- | --- | --- |
| [After Effects](https://higgsfield.ai/plugins/after-effects) | Generate media inside the application; reframe, remove background, draw-to-edit, upscale, and agent bridge described. | Landing page inspected; not installed |
| [Premiere Pro](https://higgsfield.ai/plugins/premiere-pro) | Video workflow integration. | Current Plugins menu; shared Adobe landing description |
| [Photoshop](https://higgsfield.ai/plugins/photoshop) | Image workflow integration. | Current Plugins menu |
| [DaVinci Resolve](https://higgsfield.ai/plugins/davinci) | Video workflow integration. | Current Plugins menu |
| [Figma](https://higgsfield.ai/plugins/figma) | Image/video tools in Figma. | Current Plugins menu; Canvas/FigJam integration also documented |
| [Blender](https://higgsfield.ai/plugins/blender) | Image/video tools and agent-assisted 3D workflows. | Current Plugins menu and official release notes |
| [Minecraft](https://higgsfield.ai/plugins/minecraft) | AI generation integration in Minecraft. | Current Plugins menu only |

Additional footer/platform entries include [AI Motion Designer](https://higgsfield.ai/ai-motion-designer), [Games](https://higgsfield.ai/games-intro), [Collab](https://higgsfield.ai/chat-intro), and a browser Reference Extension. These were identified as separate entry points; local software execution and deployed-game behavior were not tested.

## Community and distribution

Community exposes Discovery, Projects, Shots, Creators, Contests, and Originals. Open projects and creator profiles make production work discoverable. Grants and creator partnership links provide creator-support programs. Academy adds lessons, assignments, and certificates. Originals presents films and episodic work, including contest winners promoted into series development.

The user's screenshot of a 15-minute film is evidence of a film-viewing/submission page and its full-project link. It does not by itself establish that one model generated the entire film in one invocation. Inspecting a finished public film and reconstructing its production workflow are separate tasks.

## Relevance to the Comfy competition

The [official competition](https://comfy.org/open-source-higgsfield) asks for open-source creative applications built using the Comfy Developer Platform (Router and/or SDK). It allows partner models generally; Open Weights Only is a separate category. ZeroField's current project instructions deliberately set a stricter open-weights-only implementation direction. This inventory does not change those instructions or the implementation scope.

The broader product map leaves several research directions open: a cinematic production workspace, an ad-variation workflow, a character-and-wardrobe workflow, an explainer/faceless pipeline, a video finishing toolkit, 3D-guided shot planning, or reproducible multi-model orchestration. Choosing among them should follow a focused output test and a complete user journey, rather than assuming Genjutsu is the sole target.

Higgsfield already advertises AI-assisted directing, reusable assets, parallel model workflows, and side-by-side comparisons. Those concepts alone do not establish ZeroField's originality. Likewise, writing Motion Transfer or Object Swap into a local specification does not demonstrate that a selected open model achieves the required preservation of timing, identity, background, and occlusion.

## Remaining verification

- Complete the user's first-use questionnaire before inspecting the full Layers/Inpaint and Photodump workspaces.
- Inspect a populated Canvas and generated 3D Jutsu scene if interaction-level comparison is needed; only their entry/template surfaces were examined here.
- Inspect detailed forms for menu-only entries such as Draw to Video, Draw to Edit, FPS Boost, Depth Map, and individual model variants.
- For any shortlisted feature, run controlled tests with authorized original inputs and an explicit generation budget; record input/output settings, latency, cost, failures, and repeatability.
- Treat public API, web UI, assistant integrations, legacy landing pages, and current menu labels as different surfaces. They can expose different limits and versions.

Official references used alongside live UI: [tool guide](https://higgsfield.ai/creator-hub/help-center/tools/which-higgsfield-tool-should-i-use), [Canvas guide](https://higgsfield.ai/creator-hub/help-center/tools/how-do-i-use-canvas), [Cinema guide](https://higgsfield.ai/creator-hub/help-center/tools/how-do-i-use-cinema-studio), [Soul guide](https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-soul-to-generate-images), [Popcorn guide](https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-popcorn), [Katana announcement](https://higgsfield.ai/blog/higgsfield-katana), [Ad Multiplier announcement](https://higgsfield.ai/blog/ad-multiplier-ads-studio), [changelog](https://higgsfield.ai/creator-hub/changelog).
