"""SPEC_18 pack B, generation options (B01-B04, B06): real HTTP and PostgreSQL. No provider, GPU or network is used."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from project_assistant import execution_governance as governance, limb_worker as worker
from project_assistant.studio import comfy_router
from project_docs import http, repository as repo, story_generation_options as options, story_openapi as story
from story_pack_b_fixture import PackBFixture

ROUTER_ENV = {"OPENBENCH_AGENT_KEY_ENVS": "COMFY_API_KEY", "COMFY_API_KEY": "synthetic-router-key-9f31",
              "COMFY_ROUTER_MEDIA_ORIGINS": "https://media.example.test"}
VENDOR_ENV = {"SEEDANCE_API_URL": "http://127.0.0.1:9", "SEEDANCE_API_KEY": "synthetic-vendor-key-7c42"}
LOCKS = ("OPENBENCH_PRODUCTION_POLICY", "OPENBENCH_AGENT_KEY_ENVS", "COMFY_API_KEY", "COMFY_ROUTER_MEDIA_ORIGINS",
         "COMFY_ROUTER_BASE_URL", "SEEDANCE_API_URL", "SEEDANCE_API_KEY")
OPEN = {"flux-soul-cast", "h3-optimize", "h3-reference", "h3-short-video-v3", "local-smoke", "ltx25-cinema", "ltx25-openjutsu"}
CLOSED = {"kling-v2-master", "seedance-20-pro", "rh-cloud-h3-burst"}


def cards():
    return {card["card_id"]: card for card in (worker.load_studio_card(path) for path in sorted(worker.CARDS_DIR.glob("*.json")))}


def by_code(data):
    return {app["appCode"]: app for app in data["apps"]}


class OptionsPureTests(unittest.TestCase):
    def test_tier_follows_the_card_driver(self):
        found = cards()
        self.assertGreaterEqual(len(found), 17)
        for card_id, card in found.items():
            expected = "router" if card_id.startswith("router-") else "closed" if card_id in CLOSED else "open_weights"
            self.assertEqual(options.tier_of(card), expected, card_id)
        self.assertTrue(OPEN | CLOSED <= set(found))

    def test_slots_are_inferred_from_the_inputs_a_card_really_has(self):
        found = cards()
        self.assertEqual(options.slot_params(found["flux-soul-cast"]), {})  # prompt and seed only
        self.assertEqual(options.slots_of(options.slot_params(found["router-flux-3-image"])),
                         {"aspectRatio": True, "resolution": ["768sq", "1k", "1.5k", "2k", "4k"]})
        self.assertEqual(options.slot_params(found["router-flux-3-image"])["aspectRatio"]["key"], "input.aspect_ratio")
        self.assertEqual(options.slots_of(options.slot_params(found["h3-reference"])), {"aspectRatio": True})  # the aspect_ratio slot
        self.assertEqual(options.slot_params(found["h3-reference"])["aspectRatio"]["key"], "252.aspect_ratio")
        self.assertEqual(options.slot_params(found["router-dreamina-seedance-2-5-260628"])["aspectRatio"]["key"], "input.ratio")
        # LTX carries its aspect in the resolution value: no separate ratio input
        self.assertEqual(list(options.slots_of(options.slot_params(found["router-ltx-2-5-pro"]))), ["resolution"])
        for card_id, card in found.items():
            nodes = {f"{n['nodeId']}.{n['fieldName']}": n for n in card["nodes"]}
            for name, param in options.slot_params(card).items():
                self.assertIn(param["key"], nodes, (card_id, name))  # a key generation_job accepts as modelParams
                self.assertEqual(param["options"], nodes[param["key"]].get("options"), (card_id, name))

    def test_usage_scopes_default_to_every_scope(self):
        card = worker.load_studio_card("flux-soul-cast")
        self.assertIsNone(options.declared_scopes(card))
        self.assertTrue(all(options.in_scope(card, scope) for scope in story.USAGE_SCOPES))
        for declared in ([], "CHARACTER", {"CHARACTER": 1}, None, 7):
            card["engine_config"]["usage_scopes"] = declared
            self.assertIsNone(options.declared_scopes(card), declared)  # nothing usable declared: offered everywhere
        card["engine_config"]["usage_scopes"] = ["character", "Scene_Prop"]
        self.assertEqual(options.declared_scopes(card), {"CHARACTER", "SCENE_PROP"})
        self.assertEqual([scope for scope in story.USAGE_SCOPES if options.in_scope(card, scope)], ["CHARACTER", "SCENE_PROP"])

    def test_elapsed_time_is_submission_to_completion_or_unknown(self):
        self.assertEqual(options.elapsed("2026-10-01T00:00:00+00:00", "2026-10-01T00:01:30.500000+00:00"), 90.5)
        self.assertEqual(options.elapsed("2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"), 0)
        for created, finished in (("2026-10-01T00:05:00+00:00", "2026-10-01T00:00:00+00:00"), ("broken", "2026-10-01T00:00:00+00:00"),
                                  (None, "2026-10-01T00:00:00+00:00"), ("2026-10-01T00:00:00", "2026-10-01T00:00:00+00:00")):
            self.assertIsNone(options.elapsed(created, finished), (created, finished))

    def test_every_style_has_a_sample_image_on_the_static_path_convention(self):
        slugs = ["sci-fi-noir", "cel-shaded-anime", "dark-fantasy", "neo-noir", "natural-light"]
        self.assertEqual([s["sampleImage"] for s in story.STYLES], [f"/projects/assets/style-samples/{slug}.svg" for slug in slugs])
        self.assertEqual([s["stylePresetId"] for s in story.STYLES], ["88123", "88124", "88125", "88126", "88127"])
        self.assertEqual(http.STATIC_TYPES[".svg"], "image/svg+xml")
        self.assertEqual((http.STATIC_TYPES[".webp"], http.STATIC_TYPES[".mp4"]), ("image/webp", "video/mp4"))  # look samples
        root = (http.STATIC_DIR / "assets").resolve()
        for style in story.STYLES:
            relative = style["sampleImage"][len("/projects/assets/"):]  # what _send_static resolves below static/projects/assets
            self.assertIn(root, (root / relative).resolve().parents)


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for Story HTTP tests")
class GenerationOptionsHTTPTests(PackBFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.env = patch.dict(os.environ)  # a deployment lock or a configured provider on this machine must not leak in
        self.env.start()
        for name in LOCKS:
            os.environ.pop(name, None)

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def hybrid(self):
        self.ok(f"/projects/pj_{self.slug}/production-policy", "PUT", {"productionPolicy": "hybrid_studio"})

    def asset_options(self, code="CAST-01", query=""):
        return self.ok(f"/assets/{self.asset(code)['assetId']}/generation-options{query}")

    def shot_options(self, index=0):
        return self.ok(f"/shots/{self.scene_shots()[index]['shotId']}/generation-options")

    def test_options_list_the_cards_each_kind_of_target_can_use(self):
        self.prepare()
        assets, shots = self.asset_options(), self.shot_options()
        image, video = by_code(assets), by_code(shots)
        self.assertEqual(set(assets), {"apps", "defaultAppCode", "style"})
        self.assertTrue({"FLUX3_SOUL_CAST", "LOCAL_SDXL_SMOKE", "router-flux-3-image"} <= set(image))
        self.assertTrue({"LTX25_CINEMA_SHOT", "H3_REF2VA_PASS1", "H3_SHORT_VIDEO_V3", "router-ltx-2-5-pro", "kling-v2-master"} <= set(video))
        self.assertFalse(set(image) & set(video))  # a reference image is never offered a video card, nor a shot an image card
        self.assertNotIn("NANO_PRO_G2_I2I_OFFICIAL", image)  # an alias is not a second workflow
        self.assertEqual(len({a["name"] for a in assets["apps"]}), len(assets["apps"]))
        self.assertEqual(image["FLUX3_SOUL_CAST"], {"appCode": "FLUX3_SOUL_CAST", "name": "FLUX 3 Klein Soul Cast & Keyframe",
            "tier": "open_weights", "configured": True, "reason": None, "outputs": ["REFERENCE"], "estimate": None, "quotable": False})
        self.assertEqual(video["LTX25_CINEMA_SHOT"]["outputs"], ["VIDEO"])
        self.assertEqual(video["LTX25_CINEMA_SHOT"]["tier"], "open_weights")
        self.assertEqual((assets["defaultAppCode"], shots["defaultAppCode"]), ("FLUX3_SOUL_CAST", "LTX25_CINEMA_SHOT"))
        self.assertEqual(self.asset_options("SET-01")["defaultAppCode"], "FLUX3_SOUL_CAST")  # scenes and props use the same image cards
        self.assertEqual({a["appCode"] for a in self.asset_options("PROP-01")["apps"]}, set(image))

    def test_open_weights_only_disables_the_other_cards_with_a_reason_and_does_not_hide_them(self):
        self.prepare()
        for data, remote in ((self.asset_options(), {"router"}), (self.shot_options(), {"router", "closed"})):
            for app in data["apps"]:
                if app["tier"] == "open_weights":
                    self.assertEqual((app["configured"], app["reason"]), (True, None), app["appCode"])
                else:
                    self.assertEqual((app["configured"], app["reason"]), (False, "blocked_by_policy"), app["appCode"])
            self.assertEqual({a["tier"] for a in data["apps"]} - {"open_weights"}, remote)  # listed, not hidden
        router = by_code(self.asset_options())["router-flux-3-image"]
        self.assertEqual((router["tier"], router["quotable"]), ("router", True))
        with patch.dict(os.environ, {"OPENBENCH_PRODUCTION_POLICY": "hybrid_studio"}):  # a deployment hybrid does not opt the project in
            self.assertEqual(by_code(self.asset_options())["router-flux-3-image"]["reason"], "blocked_by_policy")

    def test_hybrid_project_reports_whether_each_remote_card_is_configured(self):
        self.prepare()
        self.hybrid()
        image, video = by_code(self.asset_options()), by_code(self.shot_options())
        for app in (image["router-flux-3-image"], video["router-ltx-2-5-pro"], video["SEEDANCE_2_FAST_MULTIMODAL_VIDEO"]):
            self.assertEqual((app["configured"], app["reason"]), (False, "not_configured"), app["appCode"])
        self.assertTrue(image["FLUX3_SOUL_CAST"]["configured"])  # a local card needs no provider setting
        with patch.dict(os.environ, {**ROUTER_ENV, **VENDOR_ENV}):
            asset_data, shot_data = self.asset_options(), self.shot_options()
            image, video = by_code(asset_data), by_code(shot_data)
            for app in (image["router-flux-3-image"], video["router-ltx-2-5-pro"], video["SEEDANCE_2_FAST_MULTIMODAL_VIDEO"]):
                self.assertEqual((app["configured"], app["reason"]), (True, None), app["appCode"])
            self.assertEqual(video["SEEDANCE_2_FAST_MULTIMODAL_VIDEO"]["tier"], "closed")
            self.assertEqual(shot_data["defaultAppCode"], "LTX25_CINEMA_SHOT")
            for secret in ("synthetic-router-key-9f31", "synthetic-vendor-key-7c42", "COMFY_API_KEY", "SEEDANCE_API", "media.example.test", "127.0.0.1", "http://", "https://"):
                self.assertNotIn(secret, json.dumps([asset_data, shot_data]), secret)
        repo.update_project_meta(self.conn, self.slug, privacy_mode="mask_numbers")
        self.conn.commit()
        with patch.dict(os.environ, {**ROUTER_ENV, **VENDOR_ENV}):
            masked = by_code(self.asset_options())
            self.assertEqual((masked["router-flux-3-image"]["configured"], masked["router-flux-3-image"]["reason"]), (False, "blocked_by_privacy"))
            self.assertTrue(masked["FLUX3_SOUL_CAST"]["configured"])  # local rendering stays available in numeric masking mode

    def test_default_app_falls_back_to_the_first_configured_one(self):
        self.prepare()
        with patch.object(options, "DEFAULT_CARDS", {"image": "router-flux-3-image", "video": "no-such-card"}):
            self.assertEqual(self.asset_options()["defaultAppCode"], "FLUX3_SOUL_CAST")  # the preferred card is blocked here
            self.assertEqual(self.shot_options()["defaultAppCode"], next(a["appCode"] for a in self.shot_options()["apps"] if a["configured"]))
        with patch.object(worker, "provider_configuration_status", return_value={"configured": False, "reason": "x"}), \
                patch.object(worker, "enforce_card_policy", side_effect=worker.WorkerError("closed")):
            self.assertIsNone(self.asset_options()["defaultAppCode"])  # nothing can run: no default, not a made-up one

    def test_style_is_the_global_style_of_the_episode_the_target_belongs_to(self):
        self.prepare()
        fallback = {"stylePresetId": "88123", "name": "Sci-Fi Noir Anamorphic"}
        self.assertEqual(self.asset_options()["style"], fallback)
        self.ok(f"/episodes/{self.ep}/settings", "PUT", {"aspectRatio": "9:16", "stylePresetId": "88125"})
        dark = {"stylePresetId": "88125", "name": "Dark Fantasy Concept"}
        self.assertEqual(self.asset_options()["style"], dark)
        self.assertEqual(self.shot_options()["style"], dark)
        second = self.ok(f"/projects/pj_{self.slug}/episodes", "POST", {"title": "Second"})["episodeId"]
        self.ok(f"/episodes/{second}/settings", "PUT", {"stylePresetId": "88126"})
        self.assertEqual(self.asset_options(query=f"?episodeId={second}")["style"], {"stylePresetId": "88126", "name": "High-Contrast Neo-Noir"})
        self.assertEqual(self.asset_options()["style"], dark)  # without a choice, the first episode
        self.assertEqual(self.call(f"/assets/{self.asset()['assetId']}/generation-options?episodeId=ep_nowhere_01")[0], 404)
        other = self.slug + "-o"
        self.extra_projects.append(other)
        self.ok("/projects", "POST", {"title": "Another production", "slug": other})
        self.assertEqual(self.call(f"/assets/{self.asset()['assetId']}/generation-options?episodeId=ep_{other}_01")[0], 404)  # not this production's
        saved = story.record(self.conn, self.ep)
        saved["settings"] = {"stylePresetId": "not-a-style"}  # a preset that no longer exists
        story.store(self.conn, self.ep, "episode", saved, self.slug)
        self.conn.commit()
        self.assertEqual(self.asset_options()["style"], fallback)

    def test_estimate_needs_three_successful_runs_of_the_same_card_in_the_same_project(self):
        self.prepare()
        card = lambda: by_code(self.asset_options())["FLUX3_SOUL_CAST"]
        self.assertIsNone(card()["estimate"])
        self.add_runs("flux-soul-cast", [10, 40])
        self.assertIsNone(card()["estimate"])  # two runs prove nothing
        self.add_runs("flux-soul-cast", [100], status="FAILED")
        self.add_runs("flux-soul-cast", [100], status="CANCELED")
        self.add_runs("flux-soul-cast", [100], status="RUNNING")
        self.add_runs("flux-soul-cast", [100], status="QUEUED", finished=False)
        self.add_runs("flux-soul-cast", [100], finished=False)
        self.add_runs("flux-soul-cast", [100, 100], job={"allocation": {"stages": []}})  # several cards ran in those tasks
        self.add_runs("local-smoke", [100, 100, 100])
        self.add_runs("flux-soul-cast", [100, 100, 100], slug=self.other_project())
        self.assertIsNone(card()["estimate"])  # failed, unfinished, multi-card, another card and another project do not count
        self.add_runs("flux-soul-cast", [20])
        self.assertEqual(card()["estimate"], {"seconds": 20, "samples": 3})  # the median of 10, 40 and 20
        self.add_runs("flux-soul-cast", [30, 50])
        self.assertEqual(card()["estimate"], {"seconds": 30, "samples": 5})
        smoke = by_code(self.asset_options())["LOCAL_SDXL_SMOKE"]
        self.assertEqual(smoke["estimate"], {"seconds": 100, "samples": 3})
        self.assertIsNone(by_code(self.asset_options())["router-flux-3-image"]["estimate"])
        self.assertTrue(isinstance(card()["estimate"]["seconds"], int) and isinstance(card()["estimate"]["samples"], int))

    def test_estimate_is_the_median_of_the_last_twenty_runs(self):
        self.prepare()
        self.add_runs("flux-soul-cast", [1000] * 5 + [10] * 10 + [30] * 10)  # 25 runs, oldest first
        estimate = by_code(self.asset_options())["FLUX3_SOUL_CAST"]["estimate"]
        self.assertEqual(estimate, {"seconds": 20, "samples": 20})  # the five slow, oldest runs fall out of the window
        other = self.other_project()
        self.add_runs("flux-soul-cast", [7, 7, 8, 8], slug=other)
        self.assertEqual(by_code(self.asset_options())["FLUX3_SOUL_CAST"]["estimate"], estimate)

    def test_estimate_is_never_zero(self):
        self.prepare()
        self.add_runs("flux-soul-cast", [0, 0.2, 0.4])
        self.assertEqual(by_code(self.asset_options())["FLUX3_SOUL_CAST"]["estimate"], {"seconds": 1, "samples": 3})
        self.add_runs("flux-soul-cast", [0] * 20)
        estimate = by_code(self.asset_options())["FLUX3_SOUL_CAST"]["estimate"]
        self.assertEqual(estimate, {"seconds": 1, "samples": 20})
        self.assertGreaterEqual(estimate["seconds"], 1)

    def test_a_shot_reads_the_runs_of_its_own_video_card(self):
        self.prepare()
        self.add_runs("ltx25-cinema", [60, 90, 120], job={})
        self.add_runs("flux-soul-cast", [5, 5, 5])
        shot = by_code(self.shot_options())["LTX25_CINEMA_SHOT"]
        self.assertEqual(shot["estimate"], {"seconds": 90, "samples": 3})
        self.assertNotIn("FLUX3_SOUL_CAST", by_code(self.shot_options()))

    def test_options_never_queue_price_reserve_or_contact_a_provider(self):
        self.prepare()
        self.hybrid()
        self.add_runs("flux-soul-cast", [5, 6, 7])
        asset, shot = self.asset(), self.scene_shots()[0]

        def counts():
            with self.conn.cursor() as cur:
                cur.execute("""SELECT (SELECT count(*) FROM projectops.story_record WHERE project_slug=%s),
                                      (SELECT count(*) FROM projectops.limb_task WHERE project_slug=%s),
                                      (SELECT count(*) FROM projectops.agent_usage_reservation WHERE project_slug=%s)""", (self.slug,) * 3)
                found = cur.fetchone()
            self.conn.rollback()
            return found
        before = counts()
        with patch.dict(os.environ, {**ROUTER_ENV, **VENDOR_ENV}), \
                patch.object(story._POOL, "submit", side_effect=AssertionError("queued work")), \
                patch.object(governance, "prepare_operation", side_effect=AssertionError("reserved budget")), \
                patch.object(comfy_router, "quote", side_effect=AssertionError("priced a job")), \
                patch.object(worker, "execute_story_card", side_effect=AssertionError("rendered")), \
                patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            for path in (f"/assets/{asset['assetId']}/generation-options", f"/shots/{shot['shotId']}/generation-options"):
                data = self.ok(path)
                self.assertTrue(any(app["quotable"] and app["configured"] for app in data["apps"]), path)  # a configured Router card is on offer
        self.assertEqual(counts(), before)

    def test_quotable_is_true_only_for_router_cards_and_matches_what_quotes_accept(self):
        self.prepare()
        self.hybrid()
        found = cards()
        for data in (self.asset_options(), self.shot_options()):
            for app in data["apps"]:
                card = next(c for c in found.values() if c["label"] == app["name"])
                self.assertEqual(app["quotable"], card["engine_config"]["driver"] == "comfy_router", app["appCode"])
                self.assertEqual(app["quotable"], app["tier"] == "router", app["appCode"])
            self.assertTrue(any(app["quotable"] for app in data["apps"]))
        status, payload = self.call(f"/assets/{self.asset()['assetId']}/router-quotes", "POST", {"appCode": "FLUX3_SOUL_CAST", "kind": "image"})
        self.assertEqual((status, payload["code"]), (422, "DRAMA_VALIDATION_FAILED"))  # not quotable: the quote route refuses it too

    def test_usage_scope_declared_by_a_card_filters_the_catalog_and_the_asset_options(self):
        card = worker.load_studio_card("flux-soul-cast")
        card["card_id"], card["label"] = "test-scope-" + self.slug[-10:], "Scoped test card"
        card["engine_config"] = dict(card["engine_config"], webappId=str(int(time.time() * 1000000)), usage_scopes=["CHARACTER"])
        card = worker.validate_studio_card(card)
        self.assertEqual(card["engine_config"]["usage_scopes"], ["CHARACTER"])  # survives the card loader
        with worker._OPENAPI_LOCK:
            for key in (card["card_id"], card["engine_config"]["webappId"]):
                worker._OPENAPI_CARDS[key] = (card, {"1": {"class_type": "SaveImage", "inputs": {}}})
        self.extra_cards.append(card["card_id"])
        self.prepare()
        listed = lambda scope="": {a["appCode"] for a in self.ok(f"/catalog/apps?capability=IMAGE{scope}")["items"]}
        self.assertIn(card["card_id"], listed())  # no scope asked: nothing changes
        self.assertIn(card["card_id"], listed("&usageScope=CHARACTER"))
        for scope in ("SCENE_PROP", "SCENE_PROP_EDIT", "FREE_CREATION_T2I", "FREE_CREATION_I2I"):
            self.assertNotIn(card["card_id"], listed("&usageScope=" + scope), scope)
        for scope in story.USAGE_SCOPES:
            self.assertTrue({"FLUX3_SOUL_CAST", "LOCAL_SDXL_SMOKE", "router-flux-3-image"} <= listed("&usageScope=" + scope), scope)  # declares none: everywhere
        self.assertEqual(self.call("/catalog/apps?capability=IMAGE&usageScope=ANYTHING")[0], 422)
        self.assertIn(card["card_id"], by_code(self.asset_options("CAST-01")))  # a character
        self.assertNotIn(card["card_id"], by_code(self.asset_options("SET-01")))  # a scene
        self.assertNotIn(card["card_id"], by_code(self.asset_options("PROP-01")))  # a prop
        self.assertTrue({"FLUX3_SOUL_CAST"} <= set(by_code(self.asset_options("SET-01"))))

    def test_options_need_a_signed_in_crew_member_but_not_write_access(self):
        self.prepare()
        asset, shot = self.asset(), self.scene_shots()[0]
        for path in (f"/assets/{asset['assetId']}/generation-options", f"/shots/{shot['shotId']}/generation-options"):
            self.assertEqual(self.request(story.BASE + path, authenticated=False)[0], 401)
        self.assertEqual(self.call(f"/assets/as_{self.slug}_bmissing/generation-options")[0], 404)
        self.assertEqual(self.call(f"/shots/sh_{self.slug}_bmissing/generation-options")[0], 404)
        self.assertEqual(self.call(f"/assets/{asset['assetId']}/generation-options", "POST", {})[0], 404)  # a read route only
        repo.upsert_member(self.conn, self.actor, "Viewer", "viewer")
        self.conn.commit()
        self.assertTrue(self.ok(f"/assets/{asset['assetId']}/generation-options")["apps"])
        self.assertTrue(self.ok(f"/shots/{shot['shotId']}/generation-options")["apps"])

    def test_the_ui_can_send_the_app_code_and_model_params_the_options_describe(self):
        self.prepare()
        asset = self.asset()
        data = self.asset_options()
        app = by_code(data)[data["defaultAppCode"]]
        queued = []
        with patch.object(story._POOL, "submit", side_effect=lambda *args: queued.append(args)):
            body = {"appCode": app["appCode"], "modelParams": {"3.seed": 7}, "promptOverride": "A courier at dawn"}
            first = self.ok(f"/assets/{asset['assetId']}/image-generations", "POST", body)
            by_slot = self.ok(f"/assets/{asset['assetId']}/image-generations", "POST", {**body, "modelParams": {"seed": 7}})
        self.assertEqual(len(queued), 2)
        for task in (first, by_slot):
            job = story.record(self.conn, task["taskId"])["_job"]
            self.assertEqual(job["card"]["card_id"], "flux-soul-cast")  # the described appCode resolves to that card
            self.assertEqual(job["values"], {"3.seed": 7, "6.text": "A courier at dawn"})  # nodeId.fieldName and slot names agree
        self.assertEqual(self.call(f"/assets/{asset['assetId']}/image-generations", "POST", {"appCode": app["appCode"], "modelParams": {"nope": 1}})[0], 422)
        # every slot parameter the options report is accepted as modelParams, on the very card it was reported for
        self.hybrid()
        router = by_code(self.asset_options())["router-flux-3-image"]
        params = {param["key"]: param["options"][-1] for param in router["slotParams"].values()}
        self.assertEqual(set(params), {"input.aspect_ratio", "input.resolution"})
        _, job = story.generation_job(self.conn, self.me, asset["assetId"], "image", {"appCode": router["appCode"], "modelParams": params})
        self.conn.rollback()
        self.assertEqual(job["card"]["card_id"], "router-flux-3-image")
        self.assertEqual(job["values"], {"input.aspect_ratio": "21:9", "input.resolution": "4k"})

    def test_catalog_styles_carry_the_sample_image_and_svg_is_served_with_its_type(self):
        styles = self.ok("/catalog/styles")["items"]
        self.assertEqual(styles, story.STYLES)
        self.assertTrue(all(s["sampleImage"].startswith("/projects/assets/style-samples/") and s["sampleImage"].endswith(".svg") for s in styles))
        with TemporaryDirectory() as folder:
            (Path(folder) / "assets" / "style-samples").mkdir(parents=True)
            for style in styles:
                (Path(folder) / style["sampleImage"][len("/projects/"):]).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            with patch.object(http, "STATIC_DIR", Path(folder)):
                for style in styles:
                    status, body, headers = self.request(style["sampleImage"], authenticated=False)
                    self.assertEqual((status, headers["Content-Type"], body), (200, "image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg"/>'))
                self.assertEqual(self.request("/projects/assets/style-samples/missing.svg", authenticated=False)[0], 404)


if __name__ == "__main__":
    unittest.main()
