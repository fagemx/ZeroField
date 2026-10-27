"""Crew planning routes on a story shot (SPEC_20 R7, R19, R20); registered in story_openapi.dispatch.

    POST /aivideo/open/v1/shots/{shotId}/beat-proposals     body {"seconds"?: 4|6|8|10, "note"?: text}
    POST /aivideo/open/v1/shots/{shotId}/camera-proposals   body {"note"?: text}
        Queue the Cinematographer's beat sheet (§4.4) or camera and optics job for the shot. data: the job
        {"jobId", "kind", "role", "shotId", "status": "queued", ...}; poll GET .../crew-jobs. The job ends in
        cell-scoped table proposals on the shot ("Action & Audio Prompt", or "Optical Rig" and "Camera Motion"),
        reviewed in the shot's proposals; nothing is written until the director adopts one.
        A second request while the same member's job of that kind for this shot is active returns that job.
    GET /aivideo/open/v1/shots/{shotId}/crew-jobs
        The member's crew jobs for this shot, newest first ({items, nextCursor}): status, source ("model" or
        "rule_fallback"), result (proposalIds, compiled text or camera), attempts with validation errors, failure.

Errors ({code, message, requestId, details?}):
    409 DRAMA_CREW_NOT_READY       no usable model for the Cinematographer (a crew readiness blocker: worker stopped,
                                   model unreachable or missing, policy, credentials, pricing). Nothing is written.
                                   details: {"agentKey", "blockers": [{code, agentKey, fix, ...}]} (SPEC_20 §4.2)
    409 DRAMA_OPERATION_NOT_ALLOWED a read-only crew member (story_openapi.dispatch)
    404 DRAMA_NOT_FOUND            unknown shot
    422 DRAMA_VALIDATION_FAILED    unknown body field, a length outside 4/6/8/10, a sheet without the needed column

Cancel a job from the crew board: POST /projects/api/{slug}/orchestration/crew-jobs/{jobId}/cancel.
The composer entry of SPEC_19 ("ask the crew for beats") lands with SPEC_19's generation desk; it calls the same route.
"""
from __future__ import annotations

from project_assistant import crew_jobs
from project_docs import story_openapi as story

TAILS = {'beat-proposals': 'beats', 'camera-proposals': 'camera'}
ROUTES = tuple(TAILS) + ('crew-jobs',)


def route(conn, me, method, slug, identifier, tail, body, query):
    """The dispatcher has found the shot and checked the member (writers only for POST)."""
    if method == 'POST' and tail in TAILS:
        return crew_jobs.request(conn, me, slug, TAILS[tail], identifier, body)
    if method == 'GET' and tail == 'crew-jobs':
        return story.page(crew_jobs.listing(conn, me, slug, identifier), query)
    raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Resource not found.')
