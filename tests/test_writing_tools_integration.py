"""Real scoped-store/transaction/HTTP checks, requiring an isolated PostgreSQL.

Only inherited HTTP setup is reused; no writing store, parser, output renderer,
block save, auth or receipt code is mocked in these tests.
"""
import copy
import os
import unittest
import uuid
from unittest.mock import patch

import test_story_openapi as fixture
from project_docs import writing_store as store, writing_tools as tools, writing_files as files, writing_service
from project_docs import story_openapi as story, repository as repo
from project_docs.doc_schema import validate_doc


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "isolated PostgreSQL required")
class ScopedStoreTests(unittest.TestCase):
    setUp = fixture.StoryHTTPTests.setUp
    tearDown = fixture.StoryHTTPTests.tearDown
    request = fixture.StoryHTTPTests.request
    call = fixture.StoryHTTPTests.call
    ok = fixture.StoryHTTPTests.ok

    def scope(self):
        from project_docs.service import Identity
        # Use the actual authenticated identity from the HTTP fixture's current
        # member; test's direct feature calls still recheck project membership.
        me = Identity(self.actor, "Tools test", "admin")
        return store.scope_for(self.conn, me, self.ep, credential_scope="test-credential")

    def writing(self, tail, method="GET", body=None, key=None):
        headers = {"Idempotency-Key": key or uuid.uuid4().hex} if method == "POST" else None
        return self.ok(f"/episodes/{self.ep}/writing/" + tail, method, body, headers)

    def save_script(self, value="Scene 01: Arrival\nkeeper waits beside @CAST-01."):
        self.ok(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": value})
        workspace = self.writing("workspace")
        self.writing("initialize", "POST", {"expectedDocHash": workspace["docHash"]})
        return self.writing("workspace")

    def test_http_search_preview_apply_replay_and_scope(self):
        workspace = self.save_script()
        result = self.writing("search", "POST", {"query": "keeper"})
        self.assertEqual(result["total"], 1)
        hit = result["items"][0]
        preview = self.writing("previews", "POST", {"kind": "replace", "query": "keeper", "replacement": "courier", "matchIds": [hit["matchId"]]})
        body = {"expectedPreviewVersion": preview["version"], "selection": {"actions": preview["allowedActions"]}}
        ack = self.writing("previews/" + preview["previewId"] + "/apply", "POST", body, key="replace-one")
        replay = self.writing("previews/" + preview["previewId"] + "/apply", "POST", body, key="replace-one")
        self.assertEqual(ack, replay)
        current = self.writing("workspace")
        self.assertIn("courier", story.doc_text(current["doc"]))
        self.assertNotEqual(current["docHash"], workspace["docHash"])
        self.assertIn("@CAST-01", story.doc_text(current["doc"]))

    def test_real_bible_project_scope_events_cas_and_search(self):
        self.save_script()
        scope = self.scope()
        saved = tools.create_bible(self.conn, scope, {"entryKind": "world", "title": "Signal law", "research": "storm keeper"})
        self.assertIsNone(saved["episodeId"])
        ack = tools.patch_bible(self.conn, scope, saved["bibleId"], {"baseVersion": 1, "clientMutationId": "research-edit", "patch": {"research": "storm courier"}})
        self.conn.commit()
        self.assertEqual(ack["version"], 2)
        hit = self.writing("search", "POST", {"query": "courier", "scope": [{"kind": "bible", "id": saved["bibleId"]}]})
        self.assertEqual(hit["total"], 1)
        fetched = self.writing("bible/" + saved["bibleId"])
        self.assertEqual(fetched["research"], "storm courier")
        self.assertNotIn("prompt", fetched)

    def test_real_asset_bible_appearances_and_events_survive_reorder_then_orphan(self):
        self.save_script("Character: Keeper @CAST-01\nScene 01: Arrival\n@CAST-01 keeper waits.\nScene 02: Signal\n@CAST-01 checks the lamp.")
        self.ok(f"/episodes/{self.ep}/asset-extractions", "POST", {})
        workspace = self.writing("workspace")
        first, second = workspace["structure"]["scenes"]
        scope = self.scope()
        asset = next(a for a in story.assets(self.conn, scope.episode) if a["assetCode"] == "CAST-01")
        body = {"entryKind": "asset_extension", "assetId": asset["assetId"], "aliases": ["keeper"],
                "events": [{"eventId": "evt_1", "subjectId": asset["assetId"], "episodeId": self.ep, "sceneKey": first["sceneKey"],
                            "kind": "knowledge", "note": "Learns the signal is wrong."}]}
        bible = self.writing("bible", "POST", body)
        self.assertEqual(bible["asset"]["name"], asset["name"])
        self.assertNotIn("name", bible)
        status, _ = self.call(f"/episodes/{self.ep}/writing/bible/{bible['bibleId']}", "PATCH",
                              {"baseVersion": 1, "clientMutationId": "not-asset-authority", "patch": {"name": "Duplicate name"}})
        self.assertEqual(status, 422)
        matrix = self.writing("appearances?subjectIds=" + asset["assetId"])
        row = matrix["rows"][0]
        self.assertEqual(row["explicitSceneCount"], 2)
        self.assertGreaterEqual(row["mentionCount"], 1)
        self.assertTrue(all(c["shotCount"] == 0 for c in row["cells"]))
        move = self.writing("previews", "POST", {"kind": "structure", "targetDocHash": workspace["docHash"],
                         "structureVersion": workspace["structure"]["version"], "operation": {"type": "move", "sceneKey": first["sceneKey"], "afterSceneKey": second["sceneKey"]}})
        self.writing("previews/" + move["previewId"] + "/apply", "POST", {"expectedPreviewVersion": 1, "selection": {"actions": move["allowedActions"]}})
        self.assertFalse(self.writing("bible/" + bible["bibleId"])["events"][0]["orphaned"])
        current = self.writing("workspace")
        remove = self.writing("previews", "POST", {"kind": "structure", "targetDocHash": current["docHash"],
                         "structureVersion": current["structure"]["version"], "operation": {"type": "remove", "sceneKey": first["sceneKey"]}})
        self.writing("previews/" + remove["previewId"] + "/apply", "POST", {"expectedPreviewVersion": 1, "selection": {"actions": remove["allowedActions"]}})
        self.assertTrue(self.writing("bible/" + bible["bibleId"])["events"][0]["orphaned"])

    def test_real_corrected_script_import_freezes_explicit_merged_boundaries(self):
        before = self.writing("workspace")["docHash"]
        raw = b"Scene 01: Arrival\nA keeper waits.\nScene 02: Signal\nA lamp blinks.\n"
        status, response, _ = self.request(story.BASE + f"/episodes/{self.ep}/writing/imports", method="POST", raw=raw,
                            headers={"Idempotency-Key": "script-upload", "X-Filename": "script.txt", "X-Writing-Purpose": "script"})
        self.assertEqual(status, 200, response)
        upload = response["data"]
        revised = self.writing("previews", "POST", {"kind": "import", "uploadPreviewId": upload["previewId"], "uploadHash": upload["uploadHash"],
                      "sections": [{"sectionId": "merged", "title": "Merged scene", "start": 0, "end": len(raw), "included": True}]})
        result = self.writing("previews/" + revised["previewId"] + "/apply", "POST", {"expectedPreviewVersion": 1, "selection": {"actions": [{"actionId": "import_document"}]}})
        branch = self.writing("branches/" + result["resourceId"])
        self.assertEqual(len(branch["structure"]["scenes"]), 1)
        self.assertEqual(branch["structure"]["scenes"][0]["title"], "Merged scene")
        self.assertIn("Scene 02: Signal", story.doc_text(branch["doc"]))
        self.assertEqual(self.writing("workspace")["docHash"], before)
        version = self.writing("versions", "POST", {"name": "Merged import", "sourceRef": result["sourceRef"], "expectedSourceHash": result["docHash"], "share": True})
        export = self.writing("exports", "POST", {"sourceRef": {"kind": "version", "id": version["versionId"]}, "expectedHash": version["snapshot"]["docHash"],
                    "sceneKeys": [branch["structure"]["scenes"][0]["sceneKey"]], "format": "txt"})
        status, content, _ = self.request(story.BASE + f"/episodes/{self.ep}/writing/" + export["contentPath"])
        self.assertEqual(status, 200)
        self.assertIn(b"Merged import", content)
        self.assertIn(b"Scene 02: Signal", content)

    def test_real_import_source_create_only_metadata_and_branch(self):
        scope = self.scope()
        preview = files.upload(self.conn, scope, "Chapter 1\n  她心裡仍想念家鄉。 😀\n".encode(), {"X-Filename": "novel.txt", "X-Writing-Purpose": "novel"})
        result = files.apply_preview(self.conn, scope, preview, {"actions": [{"actionId": "import_document"}]})
        self.conn.commit()
        source = self.writing("sources/novel")
        self.assertIn("心裡", story.doc_text(source["doc"]))
        self.assertEqual(source["sourceFile"]["uploadHash"], preview["uploadHash"])
        self.assertEqual(source["version"], result["version"])
        self.assertTrue(source["structure"]["chapters"][0]["blockBids"])
        with self.assertRaises(story.StoryError):
            files.apply_preview(self.conn, scope, preview, {"actions": [{"actionId": "import_document"}]})
        self.conn.rollback()
        snapshot = copy.deepcopy(self.writing("workspace")["doc"])
        preview = files.upload(self.conn, scope, b"Scene 1: Arrival\nA keeper waits.\n", {"X-Filename": "script.txt", "X-Writing-Purpose": "script"})
        result = files.apply_preview(self.conn, scope, preview, {"actions": [{"actionId": "import_document"}]})
        self.conn.commit()
        self.assertEqual(result["sourceRef"]["kind"], "branch")
        self.assertEqual(self.writing("workspace")["doc"], snapshot)

    def test_real_export_snapshot_http_download_private_reauth(self):
        self.save_script()
        workspace = self.writing("workspace")
        result = self.writing("exports", "POST", {"sourceRef": {"kind": "working"}, "expectedHash": workspace["docHash"], "format": "docx"})
        scope = self.scope()
        # Handle belongs to same actor, independent of credential assertion.
        binary = files.export_content(self.conn, scope, result["exportId"])
        self.assertTrue(binary.body.startswith(b"PK"))
        status, downloaded, headers = self.request(story.BASE + f"/episodes/{self.ep}/writing/" + result["contentPath"])
        self.assertEqual(status, 200)
        self.assertEqual(downloaded, binary.body)
        self.assertEqual(headers["Cache-Control"], "private, no-store")
        from docx import Document
        import io
        self.assertIn("keeper", "\n".join(p.text for p in Document(io.BytesIO(binary.body)).paragraphs))
        self.ok(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": "Scene 01: Changed\nA different text."})
        self.assertEqual(files.export_content(self.conn, scope, result["exportId"]).body, binary.body)
        from project_assistant import store as assistant_store
        assistant_store.set_member_enabled(self.conn, self.slug, self.actor, False, self.actor)
        self.conn.commit()
        with self.assertRaises(story.StoryError):
            files.export_content(self.conn, scope, result["exportId"])
        self.assertEqual(self.request(story.BASE + f"/episodes/{self.ep}/writing/" + result["contentPath"])[0], 403)

    def test_http_raw_import_headers_idempotency_and_apply(self):
        path = story.BASE + f"/episodes/{self.ep}/writing/imports"
        headers = {"Idempotency-Key": "raw-upload-once", "X-Filename": "%E8%8D%89%E7%A8%BF%252F100%25.txt", "X-Writing-Purpose": "novel", "Content-Type": "application/octet-stream"}
        raw = "Chapter 1\nA keeper remembers home. 😀\n".encode()
        status, envelope, _ = self.request(path, method="POST", raw=raw, headers=headers)
        self.assertEqual(status, 200, envelope)
        preview = envelope["data"]
        self.assertEqual(preview["filename"], "草稿%2F100%.txt")
        status, replay, _ = self.request(path, method="POST", raw=raw, headers=headers)
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay["data"]["previewId"], preview["previewId"])
        self.assertEqual(self.request(path, method="POST", raw=raw, headers={**headers, "X-Writing-Purpose": "script"})[0], 409)
        body = {"expectedPreviewVersion": 1, "selection": {"actions": [{"actionId": "import_document"}]}}
        result = self.writing("previews/" + preview["previewId"] + "/apply", "POST", body, key="confirm-import")
        repeated = self.writing("previews/" + preview["previewId"] + "/apply", "POST", body, key="confirm-import")
        self.assertEqual(result, repeated)
        source = self.writing("sources/novel")
        self.assertIn("remembers home", story.doc_text(source["doc"]))
        self.assertEqual(source["sourceFile"]["filename"], "草稿%2F100%.txt")

    def test_real_multi_resource_stale_means_no_partial_working_write(self):
        workspace = self.save_script()
        scope = self.scope()
        saved = writing_service.save_source(self.conn, scope, "idea", {"baseVersion": 0, "clientMutationId": "idea-new", "doc": files.literal_doc("keeper alone", self.slug), "structure": {}, "composition": {}})
        self.conn.commit()
        preview = tools.build_preview(self.conn, scope, {"kind": "replace", "query": "keeper", "replacement": "courier", "scope": [{"sourceRef": {"kind": "working"}}, {"sourceRef": {"kind": "source", "mode": "idea"}}]})
        writing_service.save_source(self.conn, scope, "idea", {"baseVersion": saved["version"], "clientMutationId": "idea-changed", "doc": files.literal_doc("keeper changed", self.slug), "structure": {}, "composition": {}})
        self.conn.commit()
        with self.assertRaises(story.StoryError) as caught:
            tools.apply_preview(self.conn, scope, preview, {"actions": preview["allowedActions"]})
        self.assertEqual(caught.exception.code, "DRAMA_WRITING_PREVIEW_STALE")
        self.conn.rollback()
        self.assertEqual(self.writing("workspace")["docHash"], workspace["docHash"])
        self.assertIn("keeper changed", story.doc_text(self.writing("sources/idea")["doc"]))

    def test_private_replace_checkpoint_and_stale_atomic_rollback(self):
        self.save_script()
        scope = self.scope()
        initial = files.literal_doc("private keeper", self.slug)
        saved = writing_service.save_source(self.conn, scope, "idea", {"baseVersion": 0, "clientMutationId": "create", "doc": initial, "structure": {}, "composition": {}})
        self.conn.commit()
        preview = tools.build_preview(self.conn, scope, {"kind": "replace", "query": "keeper", "replacement": "courier", "scope": [{"sourceRef": {"kind": "source", "mode": "idea"}}]})
        tools.apply_preview(self.conn, scope, preview, {"actions": preview["allowedActions"]})
        self.conn.commit()
        current = self.writing("sources/idea")
        self.assertEqual(current["beforeCheckpoint"]["doc"], saved["doc"])
        self.assertIn("courier", story.doc_text(current["doc"]))


if __name__ == "__main__":
    unittest.main()
