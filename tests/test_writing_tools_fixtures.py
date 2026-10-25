"""Interface-only in-memory scoped-store fixtures; not a PostgreSQL substitute.

Parser/output tests are real. Core-store/HTTP acceptance is separately required.
"""
import copy
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

from project_docs import blocks, writing_tools as tools, writing_files as files
from project_docs.doc_schema import validate_doc

ACTOR = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def doc(value, *, bid="b_text", slug="demo"):
    return validate_doc({"type": "doc", "content": [{"type": "paragraph", "attrs": {"bid": bid},
                           "content": [{"type": "text", "text": value}] if value else []}]}, slug=slug)[0]


@dataclass(frozen=True)
class Scope:
    me: object
    slug: str
    episode: dict
    episode_id: str
    actor_id: str
    credential_scope: str = "credential-hash"


class StoreFixture:
    UNHANDLED = object()

    def __init__(self):
        self.active = True
        self.records, self.receipts, self.docs = {}, {}, {}
        self.episodes = {"ep_demo_01": {"episodeId": "ep_demo_01", "slug": "demo", "tabKey": "director-brief", "title": "Episode 1"},
                         "ep_demo_02": {"episodeId": "ep_demo_02", "slug": "demo", "tabKey": "ep-02", "title": "Episode 2"},
                         "ep_else_01": {"episodeId": "ep_else_01", "slug": "else", "tabKey": "other", "title": "Other"}}
        self.me = SimpleNamespace(actor_id=ACTOR, can_edit=True, can_write=True)
        self.scope = self.scope_for(None, self.me, "ep_demo_01")
        for ep in self.episodes:
            self.docs[ep] = {"doc": doc("The keeper waits. @CAST-01"), "structure": {
                "scenes": [{"sceneKey": "wsc_arrival", "headingBid": "b_text", "beats": [{"beatKey": "wbt_wait", "blockBids": ["b_text"]}]}]}, "version": 1}

    def scope_for(self, conn, me, episode_id, *, write=False, credential_scope=""):
        if not self.active or (write and not me.can_write):
            tools.fail("Access revoked.", status=403, code="DRAMA_OPERATION_NOT_ALLOWED")
        ep = self.episodes[episode_id]
        return Scope(me, ep["slug"], ep, episode_id, me.actor_id, credential_scope)

    def doc_hash(self, value):
        return tools.fingerprint(value)

    def hash_value(self, value):
        return tools.fingerprint(value)[7:]

    def lock_project(self, conn, scope):
        self.project_locked = True

    def composition(self, value):
        from project_docs.writing_store import composition
        return composition(value)

    def resolve_ref(self, conn, scope, source_ref, *, write=False):
        self.scope_for(conn, scope.me, scope.episode_id, write=write)
        kind = source_ref["kind"]
        if kind == "working":
            data = self.docs[scope.episode_id]
        else:
            identifier = source_ref.get("id", "wsrc_" + source_ref.get("mode", ""))
            data = self.get_record(conn, scope, "writing_" + kind, identifier)
            if write and (kind == "version" or data.get("locked")):
                tools.fail("Readonly draft.", status=409, code="DRAMA_WRITING_LOCKED")
        return {**copy.deepcopy(data), "sourceRef": source_ref, "resourceId": data.get("sourceId") or data.get("branchId"), "docHash": self.doc_hash(data["doc"])}

    def get_record(self, conn, scope, kind, identifier, *, required=True, lock=False):
        value = self.records.get((kind, identifier))
        if value is None:
            if not required:
                return None
            tools.fail("Not found.", status=404, code="DRAMA_NOT_FOUND")
        if value["projectSlug"] != scope.slug or (kind != "writing_bible" and value["episodeId"] != scope.episode_id) or (
            value["visibility"] != "project" and value["ownerId"] != scope.actor_id):
            tools.fail("Not found.", status=404, code="DRAMA_NOT_FOUND")
        return copy.deepcopy(value)

    def insert_record(self, conn, scope, kind, identifier, data):
        if (kind, identifier) in self.records:
            tools.fail("Already exists.", status=409, code="DRAMA_WRITING_CONFLICT")
        value = {"schemaVersion": 1, "projectSlug": scope.slug, "episodeId": scope.episode_id, "ownerId": scope.actor_id,
                 "version": 1, "createdAt": "2026-10-23T00:00:00+00:00", "updatedAt": "2026-10-23T00:00:00+00:00",
                 "visibility": "private", **copy.deepcopy(data)}
        self.records[kind, identifier] = value
        return copy.deepcopy(value)

    def cas_record(self, conn, scope, kind, identifier, *, base_version, changes):
        value = self.get_record(conn, scope, kind, identifier)
        if value["version"] != base_version:
            tools.fail("Changed.", status=409, code="DRAMA_WRITING_CONFLICT")
        value.update(copy.deepcopy(changes), version=base_version + 1)
        self.records[kind, identifier] = value
        return value

    def list_records(self, conn, scope, kind, *, query=None):
        return {"items": [self.get_record(conn, scope, kind, key) for k, key in self.records if k == kind], "nextCursor": None}

    def create_preview(self, conn, scope, kind, proposal):
        identifier = "wprev_" + str(len(self.records))
        return self.insert_record(conn, scope, "writing_preview", identifier, {**proposal, "previewId": identifier, "status": "pending"})

    def get_preview(self, conn, scope, identifier, *, lock=False):
        return self.get_record(conn, scope, "writing_preview", identifier)

    def replay_receipt(self, conn, scope, key, mutation, body_hash):
        receipt = self.receipts.get((scope.actor_id, scope.credential_scope, scope.episode_id, key, mutation))
        if receipt and receipt[0] != body_hash:
            tools.fail("Mutation reused.", status=409, code="DRAMA_WRITING_CONFLICT")
        return copy.deepcopy(receipt[1]) if receipt else None

    def save_receipt(self, conn, scope, key, mutation, body_hash, ack):
        self.receipts[scope.actor_id, scope.credential_scope, scope.episode_id, key, mutation] = body_hash, copy.deepcopy(ack)
        return ack


class InterfaceFixtures:
    def setUp(self):
        self.store = StoreFixture()
        self.scope = self.store.scope
        self.asset = {"assetId": "as_demo_b_cast", "assetCode": "CAST-01", "name": "keeper", "selectedImageUrl": None}
        self.patches = [patch.object(tools, "_store", return_value=self.store), patch.object(files, "_store", return_value=self.store),
                        patch.object(tools.story, "assets", return_value=[self.asset]), patch.object(tools.story, "shots", return_value=[]),
                        patch("project_assistant.orchestrator.lock_project"), patch.object(tools.repo, "get_tab_for_update", side_effect=self.tab),
                        patch.object(tools.repo, "tab_locks", return_value={}), patch.object(tools.service, "_run_ops", side_effect=self.run_ops)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def tab(self, conn, slug, key):
        ep = next(e for e in self.store.episodes if self.store.episodes[e]["tabKey"] == key)
        return {"key": key, "title": "Script", "revision": 1, "updated_at": "now", "doc": self.store.docs[ep]["doc"]}

    def run_ops(self, conn, me, slug, key, tab, ops, session_id, **kwargs):
        result = blocks.apply_ops(tab["doc"], ops, blocks.Actor(me.actor_id, me.can_edit), locks={}, now="now")
        ep = next(e for e in self.store.episodes if self.store.episodes[e]["tabKey"] == key)
        if not result.conflicts:
            self.store.docs[ep]["doc"] = result.doc
        return result, result.doc, 2, "now"
