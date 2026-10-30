# Verification history

Real-hardware walks of the crew and new-production path, and where each spec's receipt is. The latest full test run is in the [README](../README.md#develop-and-verify).

## SPEC_20: crew, providers, 3D plans and external agents

The automated checks of the crew, 3D, provider, console and external-agent work use fakes: fake OpenAI-compatible model endpoints, fake ACP agents, fake ComfyUI and GPU probes, and a simulated MCP Apps host page in headless Edge. The single sharded full backend run (1237 tests) and the full frontend run (592 tests) passed.

A first real-hardware run (2026-10-27, RTX 4090, Ollama `qwen3.8:27b` with a 16k context, ComfyUI with LTX-2.5 and FLUX 3 Klein) is recorded in the receipt's `real_acceptance` section:

- The [Models](../README.md#models) steps bring the crew to ready on the Agent Board. Two steps needed a change: the embedded database now moves off a taken port (Docker held 55432), and step 2 now says to point `OLLAMA_MODELS` at the app's model folder.
- A prompt of 6k to 11k tokens is answered from its first line, with the model 100% on the GPU at a 16384 context. Ollama silently cuts a prompt longer than the context.
- Continuity grades work under the default settings: 90/100 pass on one take, 64/100 retake on another that had a second person in frame.
- Crew evaluation set: beats 18.56%, continuity 24.29% (2 of 8 cases each pass every hard check); the blocking set has no crew job to run.
- A blank production was walked through the UI only, from a pasted three-scene screenplay through the crew's pre-production locks to two generated shots, grades and an exported 8-second film. It only got there with workarounds. The generate buttons on a new production fail because several pipeline steps write the same column, so shots were made from the Comfy Pipeline's single-step test. A pasted screenplay becomes one scene. Screenplay character cues are not detected, so the cast had to be added by hand. Template content (Kael, the observatory) appears in new productions.

The walk was repeated on 2026-10-28 (`real_acceptance.R44_rewalk`) after two fixes, with the crew and the continuity grader on a hosted open-weights model, DeepSeek V4.1 Flash 1017 on OpenRouter, under the `open_weights_only` policy (hosted-open-weights switch, allowed host, key reference and price ceiling as in [Models](../README.md#models); about $0.07 for the walk):

- A pasted screenplay now becomes one scene per heading, numbered headings included.
- Each pipeline column has a default step, so the Keyframe and Cinema Shot Run buttons, Re-shoot Take and Run Pipeline on selected shots reach FLUX 3 Klein and LTX-2.5 directly. Both are fixed.
- Pre-production took about 3 minutes in all, against about 10 minutes with the local model. The hosted grader scored the takes lower and with more detail than the local one: 28, 60, 68 and 76 out of 100. It caught a cut inside a take and a second runner in frame.
- Still open at that point: the pasted screenplay arrived as a private draft, template content appeared in new productions, character cues were not detected, scene 1 was bound to the template's set, and the allocation preview recommended a MiniMax H3 card that is not installed.

Those were fixed and pre-production was walked again the same day (`real_acceptance.R44_rewalk2`, same model, about $0.04, no rendering):

- A production started from a story has the template's pages, columns and pipeline but none of its sample brief, cast, sets or shots, and the pasted screenplay is the working screenplay from the start.
- Standard character cues (a name alone on its line) become cast cards, and scenes at the same location share one set.
- The allocation preview only recommends cards whose models the running ComfyUI lists.
- Panels keep polling after a failed request.
- Still open: the crew's own re-breakdown during pre-production can fold cue lines back into action lines. The pipeline canvas came up blank once and the studio refused a connection once; neither has a confirmed cause. A few English strings still have Chinese punctuation.

Still to do:

- fix the remaining blank-production break points (`real_acceptance.R44_rewalk2.break_points`);
- real MCP hosts (MCP Inspector, Goose with Ollama, Claude Code) and a real MCP Apps host;
- the crew under Docker Compose: `docker-compose.yml` no longer defaults to any model endpoint, but inside the container `127.0.0.1` is the container itself, not the host's Ollama, and a self-hosted model on another host is tiered closed; this path is untested (see [deployment](DEPLOYMENT.md)).

The receipt is [`docs/spec20-verification.json`](spec20-verification.json), with screenshots in [`docs/research/screenshots/spec20/`](research/screenshots/spec20/). The requirement-by-requirement status, including what is partial or deferred, is in [SPEC_20 section 11](specs/SPEC_20_PLANNING_AGENT_LAYER_AND_PROVIDER_PRINCIPLES.md).

## Earlier receipts

Original SPEC16 commands, candidate, PostgreSQL/authenticated production-browser journeys and long-script measurements remain in [the writing receipt](spec16-verification.json), with its original [review history](SPEC16_REVIEW.md). The separate three-space integration has [its own receipt](spec16-integration-verification.json) and [V12 review/dispositions](SPEC16A_REVIEW.md); this does not accept SPEC16 on the user's behalf. Sources/drafts and local-only recovery are distinct from shared snapshots and production baselines; see [writing usage and limits](WRITING_WORKSPACE.md).

Historical SPEC_08 frozen gates, installed-wheel identities and unchanged-candidate browser evidence are recorded in [the Console receipt](spec08-verification.json). [Console usage](SPEC08_CONSOLE.md) explains real versus deterministic preview, owner/admin authority, quote restart/expiry, strict project Judge10, and no paid replay/refund or OS-sandbox guarantee. Independent security/journey reviews are pending. No live provider/model/billing/GPU acceptance is claimed.

SPEC_07 integration verification is recorded in [its own receipt](spec07-verification.json); synthetic inference is explicitly distinguished from live provider/model execution. The previous SPEC_06 verification (306 backend / 108 frontend tests, build and packaged resources) is recorded in [the Story Workbench receipt](story-workbench-verification.json). Earlier verification is recorded in [the bilingual baseline receipt](bilingual-baseline.json). The [English baseline receipt](english-baseline.json) records the earlier checkpoint.
