"""Crew planning routes (SPEC_20 R7, R19, R20, R21, R22, R23); registered in story_openapi.dispatch.

Every route queues one crew job (project_assistant.crew_jobs) for its target and answers the queued job; poll the
target's crew-jobs. A job ends in proposals only: cell-scoped table proposals reviewed where they land, or writing
preview candidates the director picks from. Nothing is written until the director adopts one. A second request while
the same member's job of that kind for that target is active returns that job.

    Shot (the Cinematographer; Art for appearances)
    POST /aivideo/open/v1/shots/{shotId}/beat-proposals        body {"seconds"?: 4|6|8|10, "note"?}
    POST /aivideo/open/v1/shots/{shotId}/camera-proposals      body {"note"?}
        Beat sheet (§4.4) in "Action & Audio Prompt"; camera and optics in "Optical Rig" and "Camera Motion".
    POST /aivideo/open/v1/shots/{shotId}/appearance-proposals  body {"note"?}
        Who is in the shot, with its scene as context: the @CAST tags of its prompt (an insert binds only the scene).

    Asset (Art, on the Soul Cast; reviewed on the StoryWorld asset card)
    POST /aivideo/open/v1/assets/{assetId}/description-proposals  body {"note"?}
        The "Locked Appearance" cell: appearance only, no composition words.
    POST /aivideo/open/v1/assets/{assetId}/look-proposals         body {"note"?, "kind"?: OUTFIT|POSE|LOOK, "key"?}
        A new look row (CAST-01:<key>) for a cast member.

    Scene (Art)
    POST /aivideo/open/v1/scenes/{sceneId}/appearance-proposals  body {"note"?}
        Who is in each of the scene's shots: one proposal per shot whose tags change.

    Episode (the Screenwriter; candidates appear in the script view)
    POST /aivideo/open/v1/episodes/{episodeId}/adaptation-proposals  body {"sourceMode"?: idea|novel, "targetScenes"?: 1-12, "note"?}
    POST /aivideo/open/v1/episodes/{episodeId}/breakdown-proposals   body {"note"?}
        Writing-preview candidates (the crew's and the rule version) with each one's storyboard impact.

    GET /aivideo/open/v1/{shots|assets|scenes|episodes}/{id}/crew-jobs
        The member's crew jobs for this target, newest first ({items, nextCursor}): status, source ("model" or
        "rule_fallback"), result (proposalIds, or candidates with previewIds), attempts with validation errors, failure.

Errors ({code, message, requestId, details?}):
    409 DRAMA_CREW_NOT_READY       no usable model for the role (a crew readiness blocker: worker stopped, model
                                   unreachable or missing, policy, credentials, pricing). Nothing is written.
                                   details: {"agentKey", "blockers": [{code, agentKey, fix, ...}]} (SPEC_20 §4.2)
    409 DRAMA_OPERATION_NOT_ALLOWED a read-only crew member
    404 DRAMA_NOT_FOUND            unknown target
    422 DRAMA_VALIDATION_FAILED    unknown body field or value, a target that cannot take the job (no column, a look
                                   asked on a set, a shot outside any scene, no saved idea or novel, no script)

Cancel a job from the crew board: POST /projects/api/{slug}/orchestration/crew-jobs/{jobId}/cancel.
The composer entry of SPEC_19 ("ask the crew for beats") lands with SPEC_19's generation desk; it calls the same route.
"""
from __future__ import annotations

from project_assistant import crew_jobs
from project_docs import story_openapi as story

TARGET_TAILS = {
    'shot': {'beat-proposals': 'beats', 'camera-proposals': 'camera', 'appearance-proposals': 'appearances'},
    'asset': {'description-proposals': 'description', 'look-proposals': 'look'},
    'scene': {'appearance-proposals': 'appearances'},
    'episode': {'adaptation-proposals': 'adaptation', 'breakdown-proposals': 'breakdown'},
}
TAILS = TARGET_TAILS['shot']  # the shot routes' table, kept for existing imports


def tails(entity):
    """The crew tails a target kind answers (its job routes plus crew-jobs)."""
    return tuple(TARGET_TAILS.get(entity, {})) + ('crew-jobs',)


ROUTES = tails('shot')


def route(conn, me, method, slug, identifier, tail, body, query, entity='shot'):
    """The dispatcher has found the target; the member is checked here too (writers only for POST)."""
    story.authorize(conn, me, slug, write=method != 'GET')
    jobs = TARGET_TAILS.get(entity, {})
    if method == 'POST' and tail in jobs:
        return crew_jobs.request(conn, me, slug, jobs[tail], {'kind': entity, 'id': identifier}, body)
    if method == 'GET' and tail == 'crew-jobs':
        return story.page(crew_jobs.listing(conn, me, slug, identifier), query)
    raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Resource not found.')
