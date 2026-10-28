"""The allocator never recommends a card whose model files are not installed."""
import os
import unittest
from unittest.mock import patch

from project_assistant import limb_worker as worker
from project_assistant.studio import agent_allocator as allocator
from project_docs import story_allocation

HERO = {"shotId": "sh_fight", "description": "@CAST-01 @CAST-02 fight with hand contact", "cameraMotion": "Orbit 360"}
DIALOGUE = {"shotId": "sh_dialogue", "description": "@CAST-01:night speaks softly", "cameraMotion": "Slow Push"}
H3_FILES = ["minimax_h3_ref2va_pruned_fp8_scaled.safetensors", "h3_upscaler_lms_v0.1.safetensors"]


class AllocatorModelTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.options = dict(production_policy="open_weights_only", local_comfy_online=True)

    def test_uninstalled_card_is_replaced_by_the_best_installed_card(self):
        plain = allocator.select_card_for_shot(HERO, **self.options)
        self.assertEqual(plain["assigned_card_id"], "h3-short-video-v3")
        plan = allocator.select_card_for_shot(HERO, model_gaps={"h3-short-video-v3": H3_FILES}, **self.options)
        self.assertEqual(plan["assigned_card_id"], "ltx25-cinema")
        self.assertTrue(plan["ready"])
        self.assertEqual(plan["configuration_blockers"], [])
        self.assertIn("available_alternative:ltx25-cinema", plan["reasons"])

    def test_standard_shot_and_batch_follow_the_same_rule(self):
        gaps = {"h3-short-video-v3": H3_FILES}
        for budget in ("lab_economical", "hybrid_balanced"):
            plan = allocator.select_card_for_shot(DIALOGUE, budget_mode=budget, model_gaps=gaps, **self.options)
            self.assertEqual(plan["assigned_card_id"], "ltx25-cinema")
        batch = allocator.plan_allocation([HERO, DIALOGUE], model_gaps=gaps, **self.options)
        self.assertEqual([a["assigned_card_id"] for a in batch["allocations"]], ["ltx25-cinema"] * 2)
        self.assertTrue(batch["ready"])

    def test_nothing_installed_stays_listed_with_a_readable_blocker(self):
        gaps = {"h3-short-video-v3": H3_FILES, "ltx25-cinema": ["ltx-2.5-video-vae-bf16.safetensors"]}
        plan = allocator.select_card_for_shot(HERO, model_gaps=gaps, **self.options)
        self.assertFalse(plan["ready"])
        self.assertEqual(plan["assigned_card_id"], "h3-short-video-v3")
        self.assertEqual(plan["configuration_blockers"], ["models_not_installed:h3-short-video-v3:" + ", ".join(H3_FILES)])

    def test_unknown_listing_never_blocks_and_input_is_validated(self):
        self.assertEqual(allocator.missing_model_files({"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "a.safetensors"}}}, None), [])
        for bad in ({"h3-short-video-v3": "x.safetensors"}, {"h3-short-video-v3": [1]}, ["x"]):
            with self.assertRaises(worker.WorkerError):
                allocator.select_card_for_shot(HERO, model_gaps=bad, **self.options)

    def test_required_and_missing_files_come_from_the_card_workflow(self):
        _, graph = worker._resolve_openapi_card_and_workflow("h3-short-video-v3")
        files = {value for _, _, value in allocator.required_model_files(graph)}
        self.assertIn("minimax_h3_ref2va_pruned_fp8_scaled.safetensors", files)
        listing = {"UNETLoader": {"unet_name": ["sub/minimax_h3_ref2va_pruned_fp8_scaled.safetensors"]}}
        missing = allocator.missing_model_files(graph, listing)
        self.assertNotIn("minimax_h3_ref2va_pruned_fp8_scaled.safetensors", missing)  # subfolder listings still match
        self.assertIn("h3_upscaler_lms_v0.1.safetensors", missing)  # whole loader class absent = custom node missing


class InstalledGapProbeTests(unittest.TestCase):
    def listing(self, installed):
        def fetch(url, **kwargs):
            name = url.rsplit("/", 1)[-1]
            if name not in installed:
                return {}
            return {name: {"input": {"required": {field: [files] for field, files in installed[name].items()}}}}
        return fetch

    def test_offline_or_unreachable_comfy_reports_no_gaps(self):
        with patch.object(worker, "json_fetch", side_effect=AssertionError("must not ask")):
            self.assertEqual(story_allocation.installed_model_gaps(False), {})
            self.assertEqual(story_allocation.installed_model_gaps(None), {})
        with patch.object(worker, "json_fetch", side_effect=OSError("refused")):
            self.assertEqual(story_allocation.installed_model_gaps(True), {})

    def test_cards_without_their_models_are_reported_per_card(self):
        installed = {"UNETLoader": {"unet_name": ["ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"]},
                     "CLIPLoader": {"clip_name": ["gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"]},
                     "VAELoader": {"vae_name": ["ltx-2.5-video-vae-bf16.safetensors", "ltx-2.5-audio-vae-bf16.safetensors"]}}
        with patch.object(worker, "json_fetch", side_effect=self.listing(installed)):
            gaps = story_allocation.installed_model_gaps(True)
        self.assertNotIn("ltx25-cinema", gaps)
        self.assertIn("h3-short-video-v3", gaps)
        self.assertIn("minimax_h3_ref2va_pruned_fp8_scaled.safetensors", gaps["h3-short-video-v3"])
        plan = allocator.select_card_for_shot(HERO, model_gaps=gaps, production_policy="open_weights_only", local_comfy_online=True)
        self.assertEqual((plan["assigned_card_id"], plan["ready"]), ("ltx25-cinema", True))

    def test_combo_form_listing_is_understood(self):
        self.assertEqual(story_allocation._combo_names(["COMBO", {"options": ["a", "b"]}]), ["a", "b"])
        self.assertEqual(story_allocation._combo_names([["a"], {}]), ["a"])
        self.assertEqual(story_allocation._combo_names("IMAGE"), [])


if __name__ == "__main__":
    unittest.main()
