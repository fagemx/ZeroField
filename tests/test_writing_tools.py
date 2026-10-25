import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from project_docs import writing_tools as tools
from tests.test_writing_tools_fixtures import InterfaceFixtures, OTHER, doc


class ToolsTests(InterfaceFixtures, unittest.TestCase):
    def test_dispatched_unhandled_identity(self):
        self.assertIs(tools.dispatch(None, self.scope, "GET", "other", {}, {}), self.store.UNHANDLED)

    def test_asset_extension_no_duplicate_asset_authority(self):
        saved = tools.create_bible(None, self.scope, {"entryKind": "asset_extension", "assetId": self.asset["assetId"], "notes": "Handwritten note"})
        self.assertEqual(saved["asset"]["name"], "keeper")
        self.assertNotIn("name", saved)
        for patch in ({"name": "Different"}, {"prompt": "Visual"}, {"title": "Duplicate"}, {"memory": "bypass"}):
            with self.assertRaises(tools.story.StoryError):
                tools.patch_bible(None, self.scope, saved["bibleId"], {"baseVersion": 1, "clientMutationId": "m", "patch": patch})
        with self.assertRaises(tools.story.StoryError):
            tools.create_bible(None, self.scope, {"entryKind": "asset_extension", "assetId": "as_else_b_cast"})
        with self.assertRaises(tools.story.StoryError):
            tools.create_bible(None, self.scope, {"entryKind": "asset_extension", "assetId": self.asset["assetId"]})

    def test_bible_long_notes_respect_combined_unicode_cap(self):
        saved = tools.create_bible(None, self.scope, {"entryKind": "note", "title": "Long notes", "notes": "中" * 450_000, "research": "x" * 50_000})
        self.assertEqual(len(saved["notes"]), 450_000)
        with self.assertRaises(tools.story.StoryError) as caught:
            tools.patch_bible(None, self.scope, saved["bibleId"], {"baseVersion": 1, "clientMutationId": "oversize", "patch": {"research": "x" * 50_001}})
        self.assertEqual(caught.exception.status, 413)
        self.assertEqual(self.store.get_record(None, self.scope, "writing_bible", saved["bibleId"])["version"], 1)

    def test_multi_resource_metadata_locks_follow_actual_record_id_order(self):
        for identifier in ("wbib_z", "wbib_a"):
            self.store.insert_record(None, self.scope, "writing_bible", identifier,
                {"bibleId": identifier, "entryKind": "note", "title": identifier, "notes": "keeper", "visibility": "project", "bibleScope": "project", "episodeId": None})
        preview = tools.build_preview(None, self.scope, {"kind": "replace", "query": "keeper", "replacement": "courier",
                    "scope": [{"kind": "bible", "id": "wbib_z"}, {"kind": "bible", "id": "wbib_a"}]})
        with patch.object(self.store, "get_record", wraps=self.store.get_record) as reads:
            tools.apply_preview(None, self.scope, preview, {"actions": preview["allowedActions"]})
        self.assertEqual([call.args[3] for call in reads.call_args_list if call.kwargs.get("lock")], ["wbib_a", "wbib_z"])

    def test_project_bible_cannot_be_scanned_twice_via_episode_aliases(self):
        saved = tools.create_bible(None, self.scope, {"entryKind": "note", "title": "Notes", "notes": "keeper"})
        with self.assertRaises(tools.story.StoryError):
            tools.search(None, self.scope, {"query": "keeper", "scope": [{"kind": "bible", "id": saved["bibleId"]},
                {"kind": "bible", "id": saved["bibleId"], "episodeId": "ep_demo_02"}]})

    def test_bible_receipt_reauth_and_body_binding(self):
        saved = tools.create_bible(None, self.scope, {"entryKind": "note", "title": "Notes"})
        body = {"baseVersion": 1, "clientMutationId": "mut1", "patch": {"notes": "written"}}
        first = tools.patch_bible(None, self.scope, saved["bibleId"], body)
        self.assertEqual(tools.patch_bible(None, self.scope, saved["bibleId"], body), first)
        with self.assertRaises(tools.story.StoryError):
            tools.patch_bible(None, self.scope, saved["bibleId"], {**body, "patch": {"notes": "different"}})
        self.store.active = False
        with self.assertRaises(tools.story.StoryError) as caught:
            tools.patch_bible(None, self.scope, saved["bibleId"], body)
        self.assertEqual(caught.exception.status, 403)

    def test_events_reorder_orphan_and_explicit_state_conflicts(self):
        subject = self.asset["assetId"]
        event = {"eventId": "evt1", "subjectId": subject, "episodeId": "ep_demo_01", "sceneKey": "wsc_arrival",
                 "kind": "physical", "note": "Intact", "stateKey": "seal", "stateValue": "intact"}
        saved = tools.create_bible(None, self.scope, {"entryKind": "asset_extension", "assetId": subject,
                "events": [event, {**event, "eventId": "evt2", "stateValue": "broken"}]})
        self.assertFalse(saved["events"][0]["productionRelevant"])
        self.assertEqual(saved["continuityWarnings"][0]["kind"], "conflicting_explicit_states")
        self.store.docs["ep_demo_01"]["structure"]["scenes"].insert(0, {"sceneKey": "wsc_before"})
        reread = tools.bible_view(None, self.scope, self.store.get_record(None, self.scope, "writing_bible", saved["bibleId"]))
        self.assertFalse(reread["events"][0]["orphaned"])
        self.store.docs["ep_demo_01"]["structure"]["scenes"] = []
        orphan = tools.bible_view(None, self.scope, self.store.get_record(None, self.scope, "writing_bible", saved["bibleId"]))
        self.assertTrue(orphan["events"][0]["orphaned"])
        tools.patch_bible(None, self.scope, saved["bibleId"], {"baseVersion": 1, "clientMutationId": "m", "patch": {"events": self.store.get_record(None, self.scope, "writing_bible", saved["bibleId"])["events"]}})
        with self.assertRaises(tools.story.StoryError):
            tools.create_bible(None, self.scope, {"entryKind": "asset_extension", "assetId": subject, "events": [{**event, "episodeId": "ep_else_01"}]})

    def test_appearances_separate_explicit_refs_mentions_shots(self):
        self.store.docs["ep_demo_01"]["doc"] = doc("keeper keeper @CAST-01")
        tools.story.shots.return_value = [{"shotId": "sh_demo_b_1", "assets": ["CAST-01"], "storyOrigin": {"sceneKeys": ["wsc_arrival"]}}]
        row = tools.appearances(None, self.scope, {})["rows"][0]
        self.assertEqual(row["explicitSceneCount"], 1)
        self.assertEqual(row["mentionCount"], 2)
        self.assertEqual(row["cells"][0]["shotCount"], 1)
        self.assertEqual(row["cells"][0]["shotIds"], ["sh_demo_b_1"])

    def test_unicode_casefold_offsets_emoji_cjk_and_ascii_wholeword(self):
        value = "😀 Straße STRASSE 中中 keeper keepers"
        self.store.docs["ep_demo_01"]["doc"] = doc(value)
        hits = tools.search(None, self.scope, {"query": "strasse"})["items"]
        self.assertEqual([(m["start"], m["end"]) for m in hits], [(2, 8), (9, 16)])
        self.assertEqual(value[hits[0]["start"]:hits[0]["end"]], "Straße")
        self.assertEqual(tools.search(None, self.scope, {"query": "中"})["total"], 2)
        self.assertEqual(tools.search(None, self.scope, {"query": "keeper", "wholeWord": True})["total"], 1)
        with self.assertRaises(tools.story.StoryError):
            tools.search(None, self.scope, {"query": "中", "wholeWord": True})
        with self.assertRaises(tools.story.StoryError):
            tools.search(None, self.scope, {"query": "a+", "regex": True})

    def test_cursor_content_bound_and_limits(self):
        self.store.docs["ep_demo_01"]["doc"] = doc("word " * 101)
        first = tools.search(None, self.scope, {"query": "word"})
        self.assertEqual(len(first["items"]), 100)
        self.assertEqual(len(tools.search(None, self.scope, {"query": "word", "cursor": first["nextCursor"]})["items"]), 1)
        self.store.docs["ep_demo_01"]["doc"] = doc("word " * 102)
        with self.assertRaises(tools.story.StoryError):
            tools.search(None, self.scope, {"query": "word", "cursor": first["nextCursor"]})
        self.store.docs["ep_demo_01"]["doc"] = doc("a " * 1001)
        with self.assertRaises(tools.story.StoryError) as caught:
            tools.search(None, self.scope, {"query": "a"})
        self.assertEqual(caught.exception.status, 413)
        with self.assertRaises(tools.story.StoryError):
            tools.search(None, self.scope, {"query": "a", "scope": [{"sourceRef": {"kind": "working"}}] * 21})

    def test_nested_paragraph_search_does_not_invent_cross_paragraph_matches(self):
        from project_docs.doc_schema import validate_doc
        nested = {"type": "doc", "content": [{"type": "bulletList", "attrs": {"bid": "b_list"}, "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "keep"}]},
                                                     {"type": "paragraph", "content": [{"type": "text", "text": "er keeper"}]}]}]}]}
        self.store.docs[self.scope.episode_id]["doc"] = validate_doc(nested, slug="demo")[0]
        result = tools.search(None, self.scope, {"query": "keeper"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["start"], 3)
        preview = tools.build_preview(None, self.scope, {"kind": "replace", "query": "keeper", "replacement": "courier"})
        tools.apply_preview(None, self.scope, preview, {"actions": preview["allowedActions"]})
        self.assertIn("er courier", tools.block_text(self.store.docs[self.scope.episode_id]["doc"]["content"][0]))

    def test_bible_catalog_is_bounded_summary_and_type_filter(self):
        world = tools.create_bible(None, self.scope, {"entryKind": "world", "title": "Rules", "research": "Full research"})
        tools.create_bible(None, self.scope, {"entryKind": "note", "title": "Notes", "notes": "Full note"})
        page = tools.dispatch(None, self.scope, "GET", "bible", {}, {"filter": "world"})
        self.assertEqual([item["bibleId"] for item in page["items"]], [world["bibleId"]])
        self.assertNotIn("research", page["items"][0])
        self.assertNotIn("events", page["items"][0])

    def test_protected_tag_matches_and_replacement_cannot_recode_ids(self):
        matches = tools.search(None, self.scope, {"query": "CAST"})["items"]
        self.assertTrue(matches[0]["protected"])
        with self.assertRaises(tools.story.StoryError):
            tools.build_preview(None, self.scope, {"kind": "replace", "query": "CAST", "replacement": "SET", "matchIds": [matches[0]["matchId"]]})
        with self.assertRaises(tools.story.StoryError):
            tools.build_preview(None, self.scope, {"kind": "replace", "query": "keeper", "replacement": "@CAST-02"})

    def test_selected_replace_not_recursive_and_marks_retained(self):
        value = doc("keeper keeper @CAST-01")
        value["content"][0]["content"] = [{"type": "text", "text": "keep", "marks": [{"type": "bold"}]},
                                                {"type": "text", "text": "er keeper @CAST-01"}]
        self.store.docs["ep_demo_01"]["doc"] = value
        preview = tools.build_preview(None, self.scope, {"kind": "replace", "query": "keeper", "replacement": "keeper keeper"})
        result = tools.apply_preview(None, self.scope, preview, {"actions": [{"actionId": preview["allowedActions"][0]["actionId"]}]})
        self.assertEqual(result["replaced"], 1)
        current = self.store.docs["ep_demo_01"]["doc"]
        self.assertEqual(tools.block_text(current["content"][0]), "keeper keeper keeper @CAST-01")
        self.assertEqual(current["content"][0]["content"][0]["marks"], [{"type": "bold"}])
        self.assertEqual(current["content"][0]["attrs"]["bid"], "b_text")

    def test_any_selected_resource_stale_or_locked_means_no_first_write(self):
        specs = [{"sourceRef": {"kind": "working"}}, {"episodeId": "ep_demo_02", "sourceRef": {"kind": "working"}}]
        preview = tools.build_preview(None, self.scope, {"kind": "replace", "query": "keeper", "replacement": "courier", "scope": specs})
        before = copy.deepcopy(self.store.docs["ep_demo_01"])
        self.store.docs["ep_demo_02"]["doc"] = doc("keeper is changed")
        selection = {"actions": preview["allowedActions"]}
        with self.assertRaises(tools.story.StoryError) as caught:
            tools.apply_preview(None, self.scope, preview, selection)
        self.assertEqual(caught.exception.code, "DRAMA_WRITING_PREVIEW_STALE")
        self.assertEqual(self.store.docs["ep_demo_01"], before)
        tools.service._run_ops.assert_not_called()
        self.store.docs["ep_demo_02"]["doc"] = copy.deepcopy(before["doc"])
        tools.repo.tab_locks.return_value = {"b_text": OTHER}
        with self.assertRaises(tools.story.StoryError):
            tools.apply_preview(None, self.scope, preview, selection)
        tools.service._run_ops.assert_not_called()

    def test_immutable_snapshot_and_foreign_private_sources_fail_closed(self):
        self.store.insert_record(None, self.scope, "writing_version", "wver_1", {"doc": doc("keeper"), "visibility": "project"})
        query = {"query": "keeper", "scope": [{"sourceRef": {"kind": "version", "id": "wver_1"}}]}
        hit = tools.search(None, self.scope, query)["items"][0]
        self.assertFalse(hit["editable"])
        with self.assertRaises(tools.story.StoryError):
            tools.build_preview(None, self.scope, {**query, "kind": "replace", "replacement": "courier", "matchIds": [hit["matchId"]]})
        self.store.insert_record(None, self.scope, "writing_branch", "wbr_1", {"doc": doc("secret"), "branchId": "wbr_1", "ownerId": OTHER})
        with self.assertRaises(tools.story.StoryError):
            tools.search(None, self.scope, {"query": "secret", "scope": [{"sourceRef": {"kind": "branch", "id": "wbr_1"}}]})
        with self.assertRaises(tools.story.StoryError):
            tools.search(None, self.scope, {"query": "keeper", "scope": [{"episodeId": "ep_else_01", "sourceRef": {"kind": "working"}}]})

    def test_frozen_selection_rejects_arbitrary_or_duplicate_mutations(self):
        preview = tools.build_preview(None, self.scope, {"kind": "replace", "query": "keeper", "replacement": "courier"})
        action = preview["allowedActions"][0]
        for selection in ({"actions": [{**action, "after": "evil"}]}, {"actions": [action, action]}, {"actions": [{"actionId": "not-frozen"}]}):
            with self.assertRaises(tools.story.StoryError):
                tools.apply_preview(None, self.scope, preview, selection)
        tools.service._run_ops.assert_not_called()

    def test_all_1000_frozen_matches_across_1000_blocks_apply_in_bounded_batches(self):
        from project_docs.doc_schema import validate_doc
        manuscript = {"type": "doc", "content": [
            {"type": "paragraph", "attrs": {"bid": "b_long_" + str(i)},
             "content": [{"type": "text", "text": "x" * 490 + "needle" + " tail"}]} for i in range(1000)]}
        self.store.docs["ep_demo_01"]["doc"] = validate_doc(manuscript, slug="demo")[0]
        # Include the 999 paragraph separators in the <=500,000-code-point
        # cap, not just inline leaf text.
        for n in self.store.docs["ep_demo_01"]["doc"]["content"]:
            n["content"][0]["text"] = n["content"][0]["text"][:-2]
        preview = tools.build_preview(None, self.scope, {"kind": "replace", "query": "needle", "replacement": "pin"})
        self.assertEqual(len(preview["allowedActions"]), 1000)
        result = tools.apply_preview(None, self.scope, preview, {"actions": preview["allowedActions"]})
        self.assertEqual(result["replaced"], 1000)
        self.assertEqual(tools.service._run_ops.call_count, 5)
        self.assertTrue(all(len(call.args[5]) <= 200 for call in tools.service._run_ops.call_args_list))
        self.assertNotIn("needle", "".join(tools.block_text(n) for n in self.store.docs["ep_demo_01"]["doc"]["content"]))

    def test_replacement_cannot_manufacture_structural_tag_across_boundary(self):
        self.store.docs["ep_demo_01"]["doc"] = doc("xCAST-01")
        preview = tools.build_preview(None, self.scope, {"kind": "replace", "query": "x", "replacement": "@"})
        with self.assertRaises(tools.story.StoryError):
            tools.apply_preview(None, self.scope, preview, {"actions": preview["allowedActions"]})
        tools.service._run_ops.assert_not_called()

    def test_viewer_read_search_but_not_mutating_preview(self):
        viewer = SimpleNamespace(actor_id=self.scope.actor_id, can_write=False, can_edit=False)
        scope = self.store.scope_for(None, viewer, self.scope.episode_id)
        self.assertEqual(tools.search(None, scope, {"query": "keeper"})["total"], 1)
        with self.assertRaises(tools.story.StoryError):
            tools.build_preview(None, scope, {"kind": "replace", "query": "keeper", "replacement": "new"})


if __name__ == "__main__":
    unittest.main()
