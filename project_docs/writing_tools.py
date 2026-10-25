"""Scoped narrative sidecars and bounded literal search/atomic replacement.

Feature handlers use the caller's transaction. Preview consumption and HTTP
idempotency belong to writing_service, not this module. No provider or memory
store is involved in these authoring operations.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid

from project_docs import blocks, repository as repo, service, story_openapi as story
from project_docs.doc_schema import doc_text, node_text, validate_doc

MAX_TEXT = 500_000
MAX_RESOURCES = 20
MAX_SEARCH_TEXT = 2_000_000
MAX_MATCHES = 1000
TOKEN = re.compile(r"@(?:CAST|SET|LOC|PROP|STYLE)-\d+(?:[:#][A-Za-z0-9_-]+)?\b", re.I)
TEXT_FIELDS = {"role", "background", "constraints", "relationships", "rules", "research", "notes"}
BIBLE_FIELDS = TEXT_FIELDS | {"aliases", "events"}


def _store():
    from project_docs import writing_store
    return writing_store


def fail(message, *, code="DRAMA_VALIDATION_FAILED", status=422):
    raise story.StoryError(status, code, message)


def strict(body, allowed, required=()):
    if not isinstance(body, dict) or set(body) - set(allowed) or set(required) - set(body):
        fail("Missing or unsupported writing fields.")
    return body


def text(value, *, maximum=10_000, empty=True):
    if not isinstance(value, str) or (not empty and not value.strip()) or "\x00" in value:
        fail("Invalid text.")
    if len(value) > maximum:
        fail("Text exceeds the field limit.", status=413, code="DRAMA_WRITING_LIMIT_EXCEEDED")
    return value


def sequence(value, maximum=1000):
    if not isinstance(value, list) or len(value) > maximum:
        fail("Invalid or oversized list.")
    return value


def fresh_scope(conn, scope, *, write=False, episode_id=None):
    return _store().scope_for(conn, scope.me, episode_id or scope.episode_id,
                              write=write, credential_scope=scope.credential_scope)


def fingerprint(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                              separators=(",", ":")).encode()).hexdigest()


def checked_doc(doc, slug):
    try:
        doc, _ = validate_doc(doc, slug=slug)
    except ValueError:
        fail("Document exceeds supported size or structure.", code="DRAMA_WRITING_LIMIT_EXCEEDED", status=413)
    if len(doc_text(doc)) > MAX_TEXT:
        fail("Split this manuscript into smaller resources.", code="DRAMA_WRITING_LIMIT_EXCEEDED", status=413)
    return doc


def _asset(conn, scope, identifier):
    # Compare against the current project's authoritative rows. Never use an ID
    # prefix or a client-supplied asset name as proof of project membership.
    found = next((a for a in story.assets(conn, scope.episode) if a["assetId"] == identifier), None)
    if found is None:
        fail("Asset not found.", status=404, code="DRAMA_NOT_FOUND")
    return found


def _structure_scenes(resolved):
    structure = resolved.get("structure") or {}
    return structure.get("scenes", [])


def _events(conn, scope, events):
    result, ids = [], set()
    for event in sequence(events):
        strict(event, {"eventId", "subjectId", "episodeId", "sceneKey", "endSceneKey", "kind", "note",
                       "productionRelevant", "stateKey", "stateValue"}, {"eventId", "subjectId", "episodeId", "sceneKey", "kind", "note"})
        item = copy.deepcopy(event)
        for key in ("eventId", "subjectId", "episodeId", "sceneKey", "kind"):
            text(item[key], maximum=200, empty=False)
        if item["eventId"] in ids:
            fail("Duplicate event identity.")
        ids.add(item["eventId"])
        text(item["note"], maximum=MAX_TEXT)
        for key in ("stateKey", "stateValue", "endSceneKey"):
            if key in item:
                text(item[key], maximum=200)
        if type(item.get("productionRelevant", False)) is not bool:
            fail("productionRelevant must be a boolean.")
        item.setdefault("productionRelevant", False)
        other = fresh_scope(conn, scope, episode_id=item["episodeId"])
        if other.slug != scope.slug:
            fail("Event scene must belong to this production.")
        resolved = _store().resolve_ref(conn, other, {"kind": "working"})
        if resolved.get("structure", {}).get("initialized") is False:
            fail("Initialize stable scene identities before recording events.", status=409, code="DRAMA_WRITING_MAPPING_REQUIRED")
        scenes = _structure_scenes(resolved)
        known = {s["sceneKey"] for s in scenes}
        # Existing deleted events are retained and decorated at read time; new
        # references must be actual stable keys, not positional scene IDs.
        if item["sceneKey"] not in known or item.get("endSceneKey", item["sceneKey"]) not in known:
            fail("Event requires a current stable scene key.")
        result.append(item)
    return result


def _bible_patch(conn, scope, values, *, subject_id=None, old_events=()):
    strict(values, BIBLE_FIELDS)
    patch = copy.deepcopy(values)
    for key in TEXT_FIELDS & patch.keys():
        text(patch[key], maximum=MAX_TEXT)
    if "aliases" in patch:
        for alias in sequence(patch["aliases"], 50):
            text(alias, maximum=200, empty=False)
    if "events" in patch:
        # Preserve already-orphaned events verbatim; changing one requires a
        # valid current reference rather than guessing another scene.
        unchanged = {fingerprint(e) for e in old_events}
        validated = []
        for e in sequence(patch["events"]):
            if fingerprint(e) in unchanged:
                validated.append(copy.deepcopy(e))
            else:
                validated.extend(_events(conn, scope, [e]))
        if len({e["eventId"] for e in validated}) != len(validated):
            fail("Duplicate event identity.")
        if subject_id and any(e["subjectId"] != subject_id for e in validated):
            fail("Event subject does not match this setting.")
        patch["events"] = validated
    prose = [patch[k] for k in TEXT_FIELDS if k in patch]
    prose.extend(patch.get("aliases", []))
    prose.extend(e["note"] for e in patch.get("events", []))
    if sum(len(value) for value in prose) > MAX_TEXT or len(json.dumps(patch, ensure_ascii=False).encode()) > 2_000_000:
        fail("Setting exceeds 500,000 code points or 2 MB; split the notes.", status=413, code="DRAMA_WRITING_LIMIT_EXCEEDED")
    return patch


def bible_view(conn, scope, record):
    result = copy.deepcopy(record)
    if record.get("entryKind") == "asset_extension":
        result["asset"] = _asset(conn, scope, record["assetId"])
    warnings, scenes_by_ep, ranges = [], {}, {}
    for event in result.get("events", []):
        ep_id = event["episodeId"]
        if ep_id not in scenes_by_ep:
            other = fresh_scope(conn, scope, episode_id=ep_id)
            if other.slug != scope.slug:
                fail("Setting scene not found.", status=404, code="DRAMA_NOT_FOUND")
            scenes_by_ep[ep_id] = [s["sceneKey"] for s in _structure_scenes(_store().resolve_ref(conn, other, {"kind": "working"}))]
        keys = scenes_by_ep[ep_id]
        event["orphaned"] = event["sceneKey"] not in keys or event.get("endSceneKey", event["sceneKey"]) not in keys
        if event["orphaned"]:
            warnings.append({"kind": "orphaned_event", "eventId": event["eventId"]})
        elif event.get("stateKey") and "stateValue" in event:
            a, b = keys.index(event["sceneKey"]), keys.index(event.get("endSceneKey", event["sceneKey"]))
            start, end = min(a, b), max(a, b)
            group = (ep_id, event["subjectId"], event["stateKey"])
            for before in ranges.get(group, []):
                if before[0] <= end and start <= before[1] and before[2] != event["stateValue"]:
                    warnings.append({"kind": "conflicting_explicit_states", "eventIds": [before[3], event["eventId"]]})
            ranges.setdefault(group, []).append((start, end, event["stateValue"], event["eventId"]))
    result["continuityWarnings"] = warnings
    return result


def create_bible(conn, scope, body):
    scope = fresh_scope(conn, scope, write=True)
    strict(body, BIBLE_FIELDS | {"entryKind", "assetId", "title"}, {"entryKind"})
    kind = body["entryKind"]
    if not isinstance(kind, str) or kind not in {"asset_extension", "world", "note"}:
        fail("Unsupported setting type.")
    if kind == "asset_extension":
        if "title" in body or "assetId" not in body:
            fail("Asset settings use the existing asset identity, not a duplicate title.")
        _asset(conn, scope, body["assetId"])
        identifier = "wbib_" + hashlib.sha256((scope.slug + ":" + body["assetId"]).encode()).hexdigest()[:32]
        subject = body["assetId"]
    else:
        if "assetId" in body:
            fail("Standalone notes cannot own a production asset.")
        text(body.get("title"), maximum=200, empty=False)
        identifier = "wbib_" + uuid.uuid4().hex
        subject = identifier
    patch = _bible_patch(conn, scope, {k: v for k, v in body.items() if k in BIBLE_FIELDS}, subject_id=subject)
    data = {"bibleId": identifier, "entryKind": kind, "episodeId": None, "visibility": "project", "bibleScope": "project", **patch}
    data.update({"assetId": subject} if kind == "asset_extension" else {"title": body["title"]})
    return bible_view(conn, scope, _store().insert_record(conn, scope, "writing_bible", identifier, data))


def patch_bible(conn, scope, identifier, body):
    scope = fresh_scope(conn, scope, write=True)
    strict(body, {"baseVersion", "clientMutationId", "patch"}, {"baseVersion", "clientMutationId", "patch"})
    record = _store().get_record(conn, scope, "writing_bible", identifier)
    if record.get("entryKind") == "asset_extension":
        _asset(conn, scope, record["assetId"])
    patch = body["patch"]
    strict(patch, BIBLE_FIELDS | ({"title"} if record["entryKind"] != "asset_extension" else set()))
    if "title" in patch:
        text(patch["title"], maximum=200, empty=False)
    changes = _bible_patch(conn, scope, {k: v for k, v in patch.items() if k != "title"},
                           subject_id=record.get("assetId", identifier), old_events=record.get("events", []))
    if "title" in patch:
        changes["title"] = patch["title"]
    combined = {**record, **changes}
    _bible_patch(conn, scope, {k: combined[k] for k in BIBLE_FIELDS if k in combined},
                 subject_id=record.get("assetId", identifier), old_events=combined.get("events", []))
    mutation = text(body["clientMutationId"], maximum=200, empty=False)
    body_hash = fingerprint(body)
    receipt = _store().replay_receipt(conn, scope, "bible/" + identifier, mutation, body_hash)
    if receipt is not None:
        return receipt
    updated = _store().cas_record(conn, scope, "writing_bible", identifier,
                                    base_version=body["baseVersion"], changes=changes)
    ack = {"bibleId": identifier, "version": updated["version"], "savedAt": updated.get("updatedAt"), "clientMutationId": mutation}
    _store().save_receipt(conn, scope, "bible/" + identifier, mutation, body_hash, ack)
    return ack


def appearances(conn, scope, query):
    scope = fresh_scope(conn, scope)
    strict(query, {"subjectIds", "episodeId"})
    if query.get("episodeId"):
        other = fresh_scope(conn, scope, episode_id=query["episodeId"])
        if other.slug != scope.slug:
            fail("Episode not found.", status=404, code="DRAMA_NOT_FOUND")
        scope = other
    selected = query.get("subjectIds", [])
    if isinstance(selected, str):
        selected = selected.split(",") if selected else []
    sequence(selected, 100)
    for identifier in selected:
        text(identifier, maximum=200, empty=False)
    assets = story.assets(conn, scope.episode)
    by_id = {a["assetId"]: a for a in assets}
    if any(i not in by_id for i in selected):
        fail("Subject not found.", status=404, code="DRAMA_NOT_FOUND")
    selected = selected or [identifier for identifier, asset in by_id.items()
                            if asset["assetCode"].upper().startswith("CAST-") and ":" not in asset["assetCode"]]
    if len(selected) > 100:
        fail("Select at most 100 appearance subjects.", status=413, code="DRAMA_WRITING_LIMIT_EXCEEDED")
    resolved = _store().resolve_ref(conn, scope, {"kind": "working"})
    nodes = {n.get("attrs", {}).get("bid"): n for n in resolved["doc"].get("content", [])}
    shots = story.shots(conn, scope.episode)
    rows = []
    for identifier in selected:
        asset = by_id[identifier]
        code = asset["assetCode"].upper().replace("#", ":")
        # No alias counts are silently converted into appearance counts.
        sidecar_id = "wbib_" + hashlib.sha256((scope.slug + ":" + identifier).encode()).hexdigest()[:32]
        sidecar = _store().get_record(conn, scope, "writing_bible", sidecar_id, required=False) or {}
        names = [asset["name"], *sidecar.get("aliases", [])]
        cells = []
        for scene in _structure_scenes(resolved):
            bids = list(dict.fromkeys([scene.get("headingBid"), *scene.get("blockBids", []),
                                      *(b for beat in scene.get("beats", []) for b in beat.get("blockBids", []))]))
            prose = "\n".join(block_text(nodes[b]) for b in bids if b in nodes)
            refs = {m[0].lstrip("@").upper().replace("#", ":") for m in TOKEN.finditer(prose)}
            exact = code in refs or (":" not in code and any(r.split(":")[0] == code for r in refs))
            linked = [s["shotId"] for s in shots if any(r.upper().replace("#", ":") == code or
                      (":" not in code and r.upper().replace("#", ":").split(":")[0] == code) for r in s.get("assets", [])) and
                      (scene["sceneKey"] in (s.get("storyOrigin") or {}).get("sceneKeys", []) or
                       scene.get("legacySceneId") == s.get("sceneId"))]
            mentions = sum(len(list(literal_ranges(prose, name, case_sensitive=False))) for name in set(names) if name)
            cells.append({"sceneKey": scene["sceneKey"], "explicitReference": exact,
                          "shotIds": linked, "shotCount": len(linked), "mentionCount": mentions})
        rows.append({"subjectId": identifier, "asset": asset, "cells": cells,
                     "explicitSceneCount": sum(c["explicitReference"] for c in cells),
                     "mentionCount": sum(c["mentionCount"] for c in cells)})
    return {"episodeId": scope.episode_id, "rows": rows, "countsAre": "explicit_references_not_screen_time"}


def literal_ranges(value, query, *, case_sensitive=False, whole_word=False):
    """Return original Unicode-code-point ranges, even for expanding casefolds."""
    if case_sensitive:
        haystack, needle, boundaries = value, query, None
    else:
        parts, boundaries, offset = [], {0: 0}, 0
        for i, char in enumerate(value):
            part = char.casefold()
            parts.append(part)
            offset += len(part)
            boundaries[offset] = i + 1
        haystack, needle = "".join(parts), query.casefold()
    start = 0
    while needle:
        at = haystack.find(needle, start)
        if at < 0:
            break
        end = at + len(needle)
        start = end
        if boundaries is not None:
            if at not in boundaries or end not in boundaries:
                continue
            a, b = boundaries[at], boundaries[end]
        else:
            a, b = at, end
        if whole_word and ((a > 0 and value[a - 1].isascii() and (value[a - 1].isalnum() or value[a - 1] == "_")) or
                           (b < len(value) and value[b].isascii() and (value[b].isalnum() or value[b] == "_"))):
            continue
        yield a, b


def _leaves(node, path=()):
    if node.get("type") == "text":
        yield path, node["text"]
    elif node.get("type") == "hardBreak":
        yield path, "\n"
    for i, child in enumerate(node.get("content", [])):
        yield from _leaves(child, (*path, i))


def block_text(node):
    return "".join(value for _, value in _leaves(node))


def _text_blocks(node, path=()):
    if node.get("type") in {"paragraph", "heading"}:
        yield path, block_text(node)
    else:
        for i, child in enumerate(node.get("content", [])):
            yield from _text_blocks(child, (*path, i))


def _replace_block(block, actions):
    # Code-point ranges span formatting runs; preserve unaffected marks/IDs.
    # Reverse frozen ranges, never search the text produced by a replacement.
    _replace_value(block_text(block), actions)  # validate overlap/exact before
    for action in sorted(actions, key=lambda a: a["start"], reverse=True):
        offset, intersected = 0, []
        for path, value in _leaves(block):
            end = offset + len(value)
            if offset < action["end"] and action["start"] < end:
                intersected.append((path, value, offset, end))
            offset = end
        for i, (path, value, start, end) in enumerate(intersected):
            prefix = value[:max(0, action["start"] - start)]
            suffix = value[max(0, action["end"] - start):] if action["end"] < end else ""
            leaf = _node_at(block, path)
            if leaf["type"] == "hardBreak":
                leaf.clear()
                leaf["type"] = "text"
            leaf["text"] = prefix + (action["after"] if i == 0 else "") + suffix


def _node_at(node, path):
    for i in path:
        node = node["content"][i]
    return node


def _resources(conn, scope, specs, *, write=False):
    specs = [{"sourceRef": {"kind": "working"}}] if specs is None else specs
    sequence(specs, MAX_RESOURCES)
    if not specs:
        fail("Select at least one search resource.")
    resources, seen, physical_resources, total = [], set(), set(), 0
    for spec in specs:
        strict(spec, {"sourceRef", "episodeId", "kind", "id"})
        other = fresh_scope(conn, scope, write=write, episode_id=spec.get("episodeId"))
        if other.slug != scope.slug:
            fail("Resource not found.", status=404, code="DRAMA_NOT_FOUND")
        if spec.get("kind") == "bible":
            if "sourceRef" in spec:
                fail("Choose a single resource type.")
            record = _store().get_record(conn, other, "writing_bible", spec.get("id"))
            if record.get("assetId"):
                _asset(conn, other, record["assetId"])
            entries = [(key, (), record[key]) for key in sorted(TEXT_FIELDS) if key in record]
            entries += [("aliases", (i,), v) for i, v in enumerate(record.get("aliases", []))]
            entries += [("events", (i, "note"), e["note"]) for i, e in enumerate(record.get("events", []))]
            resource = {"scope": other, "spec": spec, "record": record, "hash": fingerprint(record),
                        "version": record["version"], "editable": bool(other.me.can_write), "entries": entries}
        else:
            strict(spec, {"sourceRef", "episodeId"}, {"sourceRef"})
            resolved = _store().resolve_ref(conn, other, spec["sourceRef"], write=write)
            doc = checked_doc(resolved["doc"], other.slug)
            entries = []
            for n, block in enumerate(doc.get("content", [])):
                for path, value in _text_blocks(block):
                    entries.append((block.get("attrs", {}).get("bid", str(n)), (n, *path), value))
            resource = {"scope": other, "spec": spec, "resolved": resolved, "hash": resolved["docHash"],
                        "version": resolved.get("version"), "editable": bool(other.me.can_write) and spec["sourceRef"]["kind"] != "version" and not resolved.get("locked", False),
                        "entries": entries}
        identity = fingerprint({"episodeId": other.episode_id, **spec})
        if "record" in resource:
            physical = "bible:" + resource["record"]["bibleId"]
        elif spec["sourceRef"]["kind"] == "working":
            physical = "tab:" + other.episode["tabKey"]
        else:
            resolved = resource["resolved"]
            identifier = resolved.get("resourceId") or resolved.get("sourceId") or resolved.get("branchId") or spec["sourceRef"].get("id")
            physical = spec["sourceRef"]["kind"] + ":" + identifier
        if identity in seen or physical in physical_resources:
            fail("Duplicate search resource.")
        seen.add(identity)
        physical_resources.add(physical)
        resource["identity"] = identity
        total += sum(len(e[2]) for e in resource["entries"])
        resources.append(resource)
    if total > MAX_SEARCH_TEXT:
        fail("Narrow the search scope.", status=413, code="DRAMA_WRITING_LIMIT_EXCEEDED")
    return resources


def _options(body):
    query = text(body.get("query"), maximum=200, empty=False)
    for key in ("caseSensitive", "wholeWord"):
        if type(body.get(key, False)) is not bool:
            fail("Search options must be booleans.")
    if body.get("wholeWord") and not query.isascii():
        fail("Whole-word matching is available only for English/ASCII queries.")
    return query, body.get("caseSensitive", False), body.get("wholeWord", False)


def _matches(resources, query, case_sensitive, whole_word):
    matches = []
    for resource in resources:
        for block_key, path, value in resource["entries"]:
            for start, end in literal_ranges(value, query, case_sensitive=case_sensitive, whole_word=whole_word):
                protected = any(start < t.end() and t.start() < end for t in TOKEN.finditer(value))
                # A replacement must not manufacture structural identifiers either.
                identity = {"resource": resource["identity"], "hash": resource["hash"], "blockKey": block_key,
                            "path": list(path), "start": start, "end": end, "query": query,
                            "caseSensitive": case_sensitive, "wholeWord": whole_word}
                scene_key = None
                for scene in _structure_scenes(resource.get("resolved", {})):
                    bids = [scene.get("headingBid"), *scene.get("blockBids", []),
                            *(b for beat in scene.get("beats", []) for b in beat.get("blockBids", []))]
                    if block_key in bids:
                        scene_key = scene["sceneKey"]
                        break
                matches.append({"matchId": "wm_" + fingerprint(identity)[7:], "resourceRef": resource["spec"],
                                "docHash": resource["hash"], "version": resource["version"], "blockKey": block_key,
                                "path": list(path), "start": start, "end": end, "rangeUnit": "unicode_code_points",
                                "before": value[start:end], "contextBefore": value[max(0, start - 60):start],
                                "contextAfter": value[end:end + 60], "sceneKey": scene_key,
                                "editable": resource["editable"] and not protected, "protected": protected})
                if len(matches) > MAX_MATCHES:
                    fail("More than 1,000 matches; narrow the query or scope.", status=413, code="DRAMA_WRITING_LIMIT_EXCEEDED")
    return matches


def search(conn, scope, body):
    scope = fresh_scope(conn, scope)
    strict(body, {"query", "scope", "caseSensitive", "wholeWord", "cursor"}, {"query"})
    query, sensitive, word = _options(body)
    resources = _resources(conn, scope, body.get("scope"))
    matches = _matches(resources, query, sensitive, word)
    # Cursor is bound to all current content and options; never paginate a new
    # manuscript under an old result index.
    binding = fingerprint({"hashes": [r["hash"] for r in resources], "specs": [r["spec"] for r in resources],
                           "query": query, "caseSensitive": sensitive, "wholeWord": word})[7:]
    cursor, start = body.get("cursor"), 0
    if cursor:
        try:
            token, number = cursor.rsplit(":", 1)
            start = int(number)
            if token != binding or start < 0 or start > len(matches):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            fail("Search cursor is stale.", status=409, code="DRAMA_WRITING_PREVIEW_STALE")
    end = start + 100
    return {"items": matches[start:end], "total": len(matches), "nextCursor": f"{binding}:{end}" if end < len(matches) else None,
            "rangeUnit": "unicode_code_points", "matchBoundary": "blocks", "warnings": []}


def build_preview(conn, scope, body):
    scope = fresh_scope(conn, scope, write=True)
    strict(body, {"kind", "query", "replacement", "scope", "caseSensitive", "wholeWord", "matchIds"}, {"kind", "query", "replacement"})
    if body["kind"] != "replace":
        fail("Unsupported preview kind.")
    query, sensitive, word = _options(body)
    replacement = text(body["replacement"], maximum=10_000)
    if TOKEN.search(replacement):
        fail("Ordinary replacement cannot create or reassign asset codes.")
    resources = _resources(conn, scope, body.get("scope"))
    matches = _matches(resources, query, sensitive, word)
    wanted = body.get("matchIds")
    if wanted is not None:
        sequence(wanted, MAX_MATCHES)
        for identifier in wanted:
            text(identifier, maximum=200, empty=False)
        if len(set(wanted)) != len(wanted) or set(wanted) - {m["matchId"] for m in matches}:
            fail("Selected matches are not in this exact search result.")
        matches = [m for m in matches if m["matchId"] in wanted]
    else:
        matches = [m for m in matches if m["editable"]]
    if any(not m["editable"] for m in matches):
        fail("Snapshots, locked text and asset references are read-only.", status=409, code="DRAMA_WRITING_LOCKED")
    if not matches:
        fail("Select at least one writable, unprotected match.")
    actions = [{**m, "actionId": m["matchId"], "after": replacement} for m in matches]
    return {"kind": "replace", "sourceFingerprints": [{"resourceRef": r["spec"], "docHash": r["hash"], "version": r["version"]} for r in resources],
            "targetFingerprints": [], "allowedActions": [{"actionId": a["actionId"]} for a in actions],
            "proposedChanges": {"actions": actions}, "warnings": ["Asset references and immutable snapshots are excluded."]}


def selected_actions(preview, selection):
    strict(selection, {"actions"}, {"actions"})
    available = {a["actionId"]: a for a in preview["proposedChanges"]["actions"]}
    chosen = []
    for item in sequence(selection["actions"], MAX_MATCHES):
        strict(item, {"actionId"}, {"actionId"})
        text(item["actionId"], maximum=200, empty=False)
        if item["actionId"] not in available or item["actionId"] in {a["actionId"] for a in chosen}:
            fail("Selection must be a unique frozen action subset.")
        chosen.append(available[item["actionId"]])
    if not chosen:
        fail("Select at least one action.")
    return chosen


def _replace_value(value, actions):
    original_tokens = TOKEN.findall(value)
    previous = len(value) + 1
    for action in sorted(actions, key=lambda a: a["start"], reverse=True):
        start, end = action["start"], action["end"]
        if not 0 <= start < end <= len(value) or end > previous or value[start:end] != action["before"]:
            fail("Overlapping or stale replacement range.", status=409, code="DRAMA_WRITING_PREVIEW_STALE")
        previous = start
        value = value[:start] + action["after"] + value[end:]
    if TOKEN.findall(value) != original_tokens:
        fail("Ordinary replacement cannot alter or manufacture asset references.")
    return value


def apply_preview(conn, scope, preview, selection):
    scope = fresh_scope(conn, scope, write=True)
    actions = selected_actions(preview, selection)
    specs = list({fingerprint(a["resourceRef"]): a["resourceRef"] for a in actions}.values())
    # Same global lock order as the rest of Story: project, sorted tab rows,
    # then metadata. Exceptions abort the caller's complete transaction.
    from project_assistant import orchestrator
    orchestrator.lock_project(conn, scope.slug)
    resources = _resources(conn, scope, specs, write=True)
    working = sorted({r["scope"].episode["tabKey"] for r in resources if r["spec"].get("sourceRef", {}).get("kind") == "working"})
    tabs = {key: repo.get_tab_for_update(conn, scope.slug, key) for key in working}
    metadata = []
    for resource in resources:
        if "record" in resource:
            metadata.append((resource["record"]["bibleId"], "writing_bible", resource))
        else:
            ref = resource["spec"]["sourceRef"]
            if ref["kind"] != "working":
                resolved = resource["resolved"]
                identifier = resolved.get("resourceId") or resolved.get("sourceId") or resolved.get("branchId") or ref.get("id")
                metadata.append((identifier, "writing_" + ref["kind"], resource))
    for identifier, kind, resource in sorted(metadata, key=lambda item: item[0]):
        locked = _store().get_record(conn, resource["scope"], kind, identifier, lock=True)
        locked_hash = fingerprint(locked) if kind == "writing_bible" else _store().doc_hash(locked["doc"])
        if locked_hash != resource["hash"] or locked["version"] != resource["version"] or locked.get("locked"):
            fail("Selected content changed or is locked.", status=409, code="DRAMA_WRITING_PREVIEW_STALE")
        resource["recordId"], resource["lockedRecord"] = identifier, locked
    plans = []
    for resource in sorted(resources, key=lambda r: r["identity"]):
        selected = [a for a in actions if a["resourceRef"] == resource["spec"]]
        if not resource["editable"] or any(a["docHash"] != resource["hash"] or a.get("version") != resource["version"] for a in selected):
            fail("Selected content changed; nothing was replaced.", status=409, code="DRAMA_WRITING_PREVIEW_STALE")
        groups = {}
        for action in selected:
            groups.setdefault((action["blockKey"], tuple(action["path"])), []).append(action)
        if "record" in resource:
            before = resource["record"]
            after = copy.deepcopy(before)
            for (field, path), group in groups.items():
                if field not in BIBLE_FIELDS:
                    fail("Unsupported setting replacement.")
                if not path:
                    after[field] = _replace_value(after[field], group)
                elif field == "aliases":
                    after[field][path[0]] = _replace_value(after[field][path[0]], group)
                elif field == "events" and len(path) == 2 and path[1] == "note":
                    after[field][path[0]]["note"] = _replace_value(after[field][path[0]]["note"], group)
                else:
                    fail("Unsupported setting range.")
            changes = _bible_patch(conn, resource["scope"], {k: after[k] for k in BIBLE_FIELDS if k in after},
                                     subject_id=after.get("assetId", after["bibleId"]), old_events=before.get("events", []))
            plans.append((resource, changes, None))
        else:
            before = resource["resolved"]["doc"]
            after = copy.deepcopy(before)
            for (_, path), group in groups.items():
                _replace_block(_node_at(after, path), group)
            after = checked_doc(after, scope.slug)
            ops = [{"op": "put", "bid": a["attrs"]["bid"], "base": a, "node": b}
                   for a, b in zip(before.get("content", []), after.get("content", [])) if a != b]
            # Frozen apply handles can cover all 1,000 matches. Existing block
            # API batches remain <=200, with complete preflight and one outer
            # transaction. Contractions first avoid a transient oversized doc.
            ops.sort(key=lambda op: len(json.dumps(op["node"], ensure_ascii=False).encode()) -
                                    len(json.dumps(op["base"], ensure_ascii=False).encode()))
            ref = resource["spec"]["sourceRef"]
            if ref["kind"] == "working":
                tab = tabs[resource["scope"].episode["tabKey"]]
                if _store().doc_hash(tab["doc"]) != resource["hash"]:
                    fail("Script changed; nothing was replaced.", status=409, code="DRAMA_WRITING_PREVIEW_STALE")
                simulated = tab["doc"]
                locks = repo.tab_locks(conn, scope.slug, resource["scope"].episode["tabKey"])
                for offset in range(0, len(ops), blocks.MAX_OPS):
                    checked = blocks.apply_ops(simulated, ops[offset:offset + blocks.MAX_OPS],
                                               blocks.Actor(scope.actor_id, scope.me.can_edit), locks=locks, now=story.now())
                    if checked.conflicts:
                        fail("Selected blocks are locked or changed.", status=409, code="DRAMA_WRITING_CONFLICT")
                    simulated = checked.doc
            else:
                record = resource["lockedRecord"]
                if record["version"] != resource["version"] or record.get("locked"):
                    fail("Private draft changed or is locked.", status=409, code="DRAMA_WRITING_CONFLICT")
            plans.append((resource, after, ops))
    result = []
    for resource, after, ops in plans:
        other = resource["scope"]
        if "record" in resource:
            current = resource["record"]
            saved = _store().cas_record(conn, other, "writing_bible", current["bibleId"], base_version=current["version"], changes=after)
        elif resource["spec"]["sourceRef"]["kind"] == "working":
            key = other.episode["tabKey"]
            session = "writing-replace-" + uuid.uuid4().hex
            for offset in range(0, len(ops), blocks.MAX_OPS):
                tab = repo.get_tab_for_update(conn, other.slug, key)
                ack, doc, revision, saved_at = service._run_ops(conn, other.me, other.slug, key, tab,
                                                              ops[offset:offset + blocks.MAX_OPS], session, atomic=True,
                                                              audit_extra={"via": "writing_replace"})
                if ack.conflicts:
                    fail("Replacement conflicted; nothing was replaced.", status=409, code="DRAMA_WRITING_CONFLICT")
            saved = {"docHash": _store().doc_hash(doc), "revision": revision, "savedAt": saved_at}
        else:
            ref = resource["spec"]["sourceRef"]
            from project_docs import writing_structure
            previous = resource["resolved"].get("structure") or {}
            structure = copy.deepcopy(previous) if ref["kind"] == "source" else writing_structure.reconcile_structure(after, previous)
            structure_hash = _store().hash_value(structure)
            saved = _store().cas_record(conn, other, "writing_source" if ref["kind"] == "source" else "writing_branch", resource["recordId"],
                                       base_version=resource["version"], changes={"doc": after, "docHash": _store().doc_hash(after), "structure": structure,
                                                                                "structureHash": structure.get("structureHash", structure_hash),
                                                                                "beforeCheckpoint": {"doc": resource["resolved"]["doc"], "structure": previous}})
        result.append({"resourceRef": resource["spec"], "version": saved.get("version"), "docHash": saved.get("docHash")})
    return {"replaced": len(actions), "resources": result}


def dispatch(conn, scope, method, tail, body, query, *, raw=None, headers=None):
    if method == "POST" and tail == "search":
        return search(conn, scope, body)
    if method == "GET" and tail == "appearances":
        return appearances(conn, scope, query)
    if tail == "bible":
        if method == "POST":
            return create_bible(conn, scope, body)
        if method == "GET":
            scope = fresh_scope(conn, scope)
            strict(query, {"cursor", "limit", "filter"})
            entry_filter = query.get("filter")
            if entry_filter not in (None, "", "asset_extension", "world", "note"):
                fail("Unsupported setting filter.")
            page = _store().list_records(conn, scope, "writing_bible", query={k: v for k, v in query.items() if k != "filter"})
            summaries = []
            for item in page["items"]:
                if entry_filter and item.get("entryKind") != entry_filter:
                    continue
                summary = {k: item[k] for k in ("bibleId", "entryKind", "assetId", "title", "aliases", "version", "createdAt", "updatedAt") if k in item}
                summary["eventCount"] = len(item.get("events", []))
                if item.get("assetId"):
                    summary["asset"] = _asset(conn, scope, item["assetId"])
                summaries.append(summary)
            return {"items": summaries, "nextCursor": page["nextCursor"]}
    match = re.fullmatch(r"bible/([A-Za-z0-9_-]{1,150})", tail)
    if match:
        if method == "PATCH":
            return patch_bible(conn, scope, match[1], body)
        if method == "GET":
            scope = fresh_scope(conn, scope)
            return bible_view(conn, scope, _store().get_record(conn, scope, "writing_bible", match[1]))
    return _store().UNHANDLED
