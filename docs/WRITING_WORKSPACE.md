# Writing workspace (SPEC16)

**Story & World** now contains the authoring workspace; **Shot Stage**, the crew dock, Ctrl K and the Film overlay remain the other studio surfaces. Verification and its exact frozen candidate are recorded in [spec16-verification.json](spec16-verification.json). Overall acceptance remains the user's decision.

## What is saved, and where?

- **Working screenplay** is the existing collaborative episode tab—not a second editable copy in metadata. Its block identities, ownership, locks, annotations and revision history remain authoritative.
- **Idea / Novel** and **another draft** are private to their author, even from project administrators. They require current production access. Merely saving them does not share or adapt their prose.
- **Named versions** are explicitly shared, immutable text/structure/settings snapshots. Their catalog names and locks have separate CAS versions. A production-pinned version cannot be unlocked or archived.
- **Production baseline** is the immutable version matching actual confirmation/extraction. Saving or comparing a manuscript does not confirm it, update shots, generate media or debit the generation cap.

The footer distinguishes server ACK, dirty/saving, **saved on this device only**, conflict, failed recovery storage and lost authorization. A locally checkpointed draft is not server-saved. HTTP 200 with block conflicts is still a conflict.

Idle saves debounce around 800 ms; continued typing checkpoints/saves within five seconds. Ctrl/Cmd+S flushes. Space, page and episode changes flush first. Registered Bible/note forms checkpoint without silently publishing shared mutations. Version/adoption/export prerequisites require a server-saved manuscript, not an unrelated tool-form save.

Recovery is a bounded, actor/project/episode/resource/browser-tab-scoped IndexedDB journal (20 MiB per origin), not cross-device synchronization or a fully offline website. Reopening a differing checkpoint offers explicit review rather than overwriting the server. Authentication loss stops uploads; conflict does not force-rebase. Download the current draft if local storage fails. The production's token-auth **Sign out** control and development identity switch both use the identity-preservation boundary. Before identity changes, resolve manuscript conflicts and explicitly save, retain or discard unsynced private tool drafts; false means no logout request or redirect. Retaining a draft applies only to that exact current sequence; later edits need a new decision. A download request alone is not proof of completed OS storage. A changed identity in another tab is rejected by the mounted workspace's actor check; reauthenticate as the original author for recovery.

## Writing, structure and alternate versions

Choose the manuscript in the toolbar. Full-manuscript and scene editing use the same document model. **Scenes → Plot overview** edits author summaries, story time, Act, setup/payoff and up to eight plot lanes; an unfilled summary is honestly labeled an excerpt. Keyboard move buttons accompany structural actions. Move, add, split, merge, removal and Undo use frozen previews and before snapshots, with current-base checks.

Stable `sceneKey` / `beatKey` identify sources; positional scene numbers are compatibility/display values. Surviving block IDs, explicit lineage or unique exact content can retain identity. Repeated or uncertain text stays unresolved—not matched by title, order or similarity. Removed sources retain their shots and media.

**Versions** saves an explicitly shared snapshot or creates a private editable draft. Compare working text, snapshots or your drafts, then preview whole or selected-scene adoption. Confirm only the frozen actions you want. Adoption checkpoints the previous mainline and rechecks locks/hashes atomically. A stale preview needs a new preview, not a replacement replay key.

For an idea/novel, edit the private source and optional SPEC14 lenses/collision choices, then **Preview adaptation**. This is the existing bounded offline deterministic adapter, not new model inference. A persistent private candidate draft survives preview expiry; save edits to that draft and make a new promotion preview. Original psychological prose is not sanitized in place.

Corrected imported scene partitions can differ from legacy Scene/INT/EXT grammar. Promotion visibly discloses canonical heading insertion and the exact `> ` quoted-source conversion, including source block lineage. Original source/branch/version prose remains retained. Mainline serialization is deliberately converted, not falsely described as byte-identical to the original.

**Confirm screenplay & build text storyboard** performs actual extraction/confirmation and creates text shots only. Production format/style/density remain under **Format and style**. Asset imagery/variants and normal generation remain available through **Asset Vault** / **Asset sheet** and existing Shot Stage controls; writing tools never generate them automatically.

## Review only the affected shots

**Review story impact** previews each shot against its own actual origin, not a single latest episode hash. It shows old/new source, current/suggested text, manual overrides, retained media and any extraction changes. Manual replacements start unselected. Choose update-text fields, add text shots, keep intentional differences, explicitly bind sources or leave unresolved.

Apply is one transaction: changed selected sources/rows, locks or revoked authority reject the selected batch. An aggregate stale warning caused only by an **unselected** changed row does not invalidate fresh selected actions. The server's atomic recheck is authoritative; readonly refresh is advice, not permission.

Partial text updates retain camera, seed, overrides, manual previs, take history, selected media and unselected shots. Keeping a difference does not move its true generation origin. Old/unknown media is never relabeled as newly generated. Shot Stage source badges/links and Film warnings use live `GET writing/alignment`; failed reads are shown as unverified, not replaced by cached metadata. Unbound/legacy sources remain honest. Reverse links use stable scene/beat keys. Manually named shot labels retain existing film order; structural preview warns rather than silently relabeling them.

## World, search and files

**World, search & files** opens one tool panel without replacing the editor:

- **World & notes** extends existing asset identity with narrative fields, author-recorded events and physical-state notes. Names, appearance, images and variants stay with the production asset. New forms are private local drafts until explicit **Create shared entry / Save**. The matrix separates explicit `@` references/linked shots from name mentions; counts are not screen time. Missing/deleted scene references and explicit conflicting states are warnings, not psychological inference. This is not Console Memory Store.
- **Search & replace** is literal and explicitly scoped; no regex. English whole-word is labeled accordingly. Match ranges are server Unicode code points, not browser UTF-16 writes. Select matches, preview, select frozen changes, apply. Protected asset codes, immutable snapshots and locks remain protected; one stale selected resource rejects the batch. Search defaults to the current manuscript, not every private source/history.
- **Import & export** accepts UTF-8/BOM TXT/MD (2 MB) and bounded DOCX (8 MiB compressed, 64 MiB expanded, 2,000 ZIP parts, 10,000 paragraphs). Preview/correct complete section boundaries before confirmation. Imports create a private source or script draft; adopting the mainline is separate. Existing private source replacement is not implicit. No macros, external relationship fetching, arbitrary URLs or filesystem paths.
- TXT, Markdown and DOCX export real fixed files from an explicitly chosen authorized source/range. DOCX is text conversion, not Word-layout fidelity; unsupported tables/images/objects/revisions/etc. are disclosed. Summaries/bible inclusion is explicit; unrelated private sources and notes are excluded by default. Download handles are owner-bound, expire after 30 minutes and recheck current access.
- **Print / Save as PDF** opens escaped, sandboxed clean HTML and the browser print dialog. It is not a server-generated PDF or a claim that printing/saving completed. Canceling print is safe.

## Experience and limits

Focus mode hides writing sidebars; Esc leaves it. Typography controls change display only: 14–24 px, 1.4–2.2 line height and 560–960 px width. Ctrl/Cmd+Shift+F opens writing search. Editing shortcuts do not fire Shot Stage A/R/G actions. English is default; Traditional Chinese uses the same fixed IDs/content.

Word count is CJK ideographs plus Latin words, excluding punctuation; character count includes whitespace. It is neither tokens nor estimated film duration. Text resources are bounded to 500,000 Unicode code points and the existing 2,000,000-byte validated-document limit; 1,000 structure units and 200 planned shots still apply. Large manuscript block saves are bounded batches, not a raised global request limit.

Real production-browser measurements at the frozen candidate cover 50,000/500,000-character, 100-scene fixtures, input-to-animation-frame, scene switching, search and comparison. See the receipt for exact results and repeat variability. They are local engineering timings, not an all-hardware latency guarantee. Long manuscripts use scene-loaded editing; search/diff remain bounded and can require narrower scope. A browser close during an unfinished local checkpoint can still lose the latest keystrokes; failed storage is not a backup guarantee.

No live provider/GPU quality, billing, remote cancellation, cross-device offline sync or universal accessibility certification is claimed by these writing tests. Existing M8 proposals, leases, policy, allocations and late-return protections remain in force.
