"""The launcher's built-in media workers: one set per server, serving every production on it (SPEC_20 R14, decision 7).

Scope stays an explicit list. ``allowed_projects`` names every production: the launcher writes the whole list at
startup and ``grant_project`` adds a production inside the transaction that creates it, so every
``allowed_projects ? slug`` / ``project_slug = ANY(allowed_projects)`` check keeps its meaning and no wildcard exists.

The ids are the ones the launcher always gave the showcase workers (``zerofield-studio:zerofield-showcase:<stage>``),
so pipelines bound before the scope widened stay bound. The id set is the durable marker of a local worker: HTTP
registration mints random ids, so only the launcher writes these rows.

Each local worker runs one fixed graph, so it only claims tasks bound to it (``flow_runner.claim``); an unbound step
waits for a worker the production chose instead of whichever local graph polls first.
"""
from __future__ import annotations

import json
import secrets
import uuid

from project_assistant import limbs
from project_docs import repository as repo

STAGES = ("image", "cinema", "v2v", "motion", "lookkey", "look", "swapkey", "swap", "layoutkey", "layout",
          "extract", "structure", "assemble", "split", "anchor")
_IDENTITY_SLUG = "zerofield-showcase"  # the ids predate the server-wide scope; changing this orphans saved pipelines


def worker_id(stage):
    if stage not in STAGES:
        raise ValueError(f"Unknown built-in worker stage: {stage}")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"zerofield-studio:{_IDENTITY_SLUG}:{stage}"))


IDS = {worker_id(stage): stage for stage in STAGES}


def is_local(identifier):
    return str(identifier) in IDS


def register(conn, configs, actor_id):
    """Upsert one enabled worker per stage, scoped to every production on the server, with a fresh token that only
    the launcher holds (in memory)."""
    registered = {}
    for stage, capabilities in configs.items():
        identifier, token = worker_id(stage), secrets.token_urlsafe(32)
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO projectops.agent_limb(id,name,capabilities,allowed_projects,token_hash,created_by)
                VALUES(%s,%s,%s::jsonb,(SELECT COALESCE(jsonb_agg(slug ORDER BY slug),'[]'::jsonb) FROM projectops.project),%s,%s)
                ON CONFLICT(id) DO UPDATE SET capabilities=EXCLUDED.capabilities,allowed_projects=EXCLUDED.allowed_projects,
                token_hash=EXCLUDED.token_hash,enabled=TRUE,last_seen_at=NULL""",
                        (identifier, "ZeroField Studio / " + stage, json.dumps(list(capabilities)), limbs.token_hash(token), actor_id))
        registered[stage] = {"id": identifier, "token": token, "capabilities": capabilities}
    return registered


def existing(conn, slug=None):
    """Enabled local workers by stage; with ``slug``, only those already serving that production."""
    with conn.cursor() as cur:
        cur.execute("""SELECT id::text,capabilities FROM projectops.agent_limb WHERE id=ANY(%s::uuid[]) AND enabled
                       AND (%s::text IS NULL OR allowed_projects ? %s)""", (list(IDS), slug, slug))
        return {IDS[row[0]]: {"id": row[0], "capabilities": repo._loads(row[1])} for row in cur.fetchall()}


def grant_project(conn, slug):
    """Add a new production to every local worker's scope in its creating transaction; returns the enabled ones."""
    with conn.cursor() as cur:
        # One lock order for every creation: concurrent creations queue instead of deadlocking.
        cur.execute("SELECT id FROM projectops.agent_limb WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE", (list(IDS),))
        if not cur.fetchall():
            return {}
        cur.execute("""UPDATE projectops.agent_limb SET allowed_projects=allowed_projects||jsonb_build_array(%s::text)
                       WHERE id=ANY(%s::uuid[]) AND NOT allowed_projects ? %s""", (slug, list(IDS), slug))
    return existing(conn, slug)


_PROMPT = "Use the approved row context and references. Return asset_url for director review."
# The showcase's production lanes that need no showcase-only seed: (node, title, capability, stage, page, output column,
# other columns the stage reads). An output column of None appends the Director Cut to the brief.
STUDIO_LANES = (
    (("image", "Soul Cast References", "image_gen", "image", "soul-cast", "Reference Image", ()),),
    (("keyframe", "Shot Keyframe", "image_gen", "image", "cinema-studio", "Keyframe", ()),
     ("cinema", "Cinema Shot", "video_gen", "cinema", "cinema-studio", "Cinema Shot", ()),
     ("assemble", "Director Cut", "media_assemble", "assemble", "cinema-studio", None, ())),
    (("v2v", "OpenJutsu Remaster", "video_gen", "v2v", "openjutsu-lab", "Remastered Video", ("Source Driving Video",)),
     ("split", "Source / Remaster Comparison", "media_assemble", "split", "openjutsu-lab", "Split-Screen MP4", ("Source Driving Video",))),
    (("motion", "Previs Motion Pass", "video_gen", "motion", "cinema-studio", "Cinema Shot", ("Previs",)),
     ("lookkey", "Look Key", "image_gen", "lookkey", "cinema-studio", "Keyframe", ()),
     ("look", "Look Pass", "video_gen", "look", "cinema-studio", "Cinema Shot", ())),
    (("layoutkey", "Layout Key", "image_gen", "layoutkey", "cinema-studio", "Keyframe", ("Previs",)),
     ("layout", "Layout Render", "video_gen", "layout", "cinema-studio", "Cinema Shot", ("Previs", "Actor Matte", "Pose Skeleton"))),
)


def studio_pipeline(conn, slug, workers):
    """The default Comfy Pipeline of a studio production: the showcase lanes bound to the local workers.

    A lane keeps its steps up to the first one whose worker, page or columns are missing; the OpenJutsu preparation
    and Object Swap lanes are left out because they target columns only the showcase seed adds. Returns None when no
    step qualifies, so the caller keeps the template pipeline."""
    from project_assistant import flow_runner
    pages, tables = set(), {}
    for key in ("director-brief", "soul-cast", "cinema-studio", "openjutsu-lab"):
        tab = repo.get_tab(conn, slug, key)
        if tab:
            pages.add(key)
            found = flow_runner._table_data(tab["doc"], {})
            if found:
                tables[key] = found[0]
    nodes, edges, lane_no = [], [], 0
    for lane in STUDIO_LANES:
        previous = None
        for depth, (node_id, title, capability, stage, page, column, reads) in enumerate(lane):
            worker, table = workers.get(stage), tables.get(page)
            inputs = [page, "soul-cast"] if page != "soul-cast" else [page]
            if (not worker or capability not in worker.get("capabilities", (capability,)) or not table or not set(inputs) <= pages
                    or any(name not in table["headers"] for name in ((column,) if column else ()) + reads)
                    or (column is None and "director-brief" not in pages)):
                break
            if column:
                index = table["headers"].index(column)
                target = {"tab_key": page, "table_id": table["table_id"], "column_id": table["column_ids"][index], "col_index": index}
            else:
                target = {"tab_key": "director-brief", "kind": "doc", "mode": "append"}
            nodes.append({"id": node_id, "title": title, "capability": capability, "scope": "rows" if column else "aggregate",
                          "prompt": _PROMPT, "input_tabs": inputs, "row_source": {"tab_key": page}, "target": target,
                          "write_mode": "proposal", "limb_id": worker["id"], "x": 300 + depth * 340, "y": 60 + lane_no * 260})
            if previous:
                edges.append({"source": previous, "target": node_id})
            previous = node_id
        lane_no += previous is not None
    return flow_runner.validate_definition({"nodes": nodes, "edges": edges}) if nodes else None


def adopt_template_pipelines(conn, me, workers):
    """Bind every production whose Comfy Pipeline is still the untouched studio template; edited ones stay as they are.

    The template's steps carry no worker, so before this they could not run on a local worker at all."""
    from project_assistant import flow_runner
    from project_docs import templates
    template = flow_runner.validate_definition(templates.flow_specs("zerofield_studio")["comfy-pipeline"])
    with conn.cursor() as cur:
        cur.execute("SELECT project_slug,definition,revision FROM projectops.flow_definition WHERE tab_key='comfy-pipeline' ORDER BY project_slug")
        rows = cur.fetchall()
    adopted = []
    for slug, definition, revision in rows:
        if repo._loads(definition) != template:
            continue
        graph = studio_pipeline(conn, slug, workers)
        if not graph:
            continue
        try:
            flow_runner.save_definition(conn, me, slug, "comfy-pipeline", {"revision": revision, "definition": graph})
        except limbs.ExecutionError:
            continue  # e.g. the pipeline page was deleted; raised before any write
        adopted.append(slug)
    return adopted
