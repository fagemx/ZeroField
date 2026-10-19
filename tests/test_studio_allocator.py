"""Offline allocator contracts: no inference, credentials, database or GPU needed."""
import copy
import os
import unittest
from unittest.mock import patch

from project_assistant import agent_registry
from project_assistant.studio import agent_allocator as allocator, card_engine, runtime


B_ROLL = {"shotId": "sh_empty", "description": "Atmospheric @SET-01", "cameraMotion": "Static Tripod"}
DIALOGUE = {"shotId": "sh_dialogue", "description": "@CAST-01:night speaks softly", "cameraMotion": "Slow Push"}
HERO = {"shotId": "sh_fight", "description": "@CAST-01 @CAST-02 fight with hand contact", "cameraMotion": "Orbit 360"}


class AllocatorTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        # Deliberately fictitious loopback adapter configuration: never contacted.
        for prefix in ("SEEDANCE", "KLING", "RUNNINGHUB"):
            os.environ[prefix + "_API_URL"] = "http://127.0.0.1:1/adapter"
            os.environ[prefix + "_API_KEY"] = "fixture-only"
        self.options = dict(production_policy="hybrid_studio", local_comfy_online=True)

    def select(self, shot, **options):
        return allocator.select_card_for_shot(shot, **(self.options | options))

    def test_complexity_profiles_and_cast_variants(self):
        expected = [(B_ROLL, 15, "b_roll"), (DIALOGUE, 35, "standard"), (HERO, 95, "hero")]
        for shot, score, tier in expected:
            with self.subTest(tier=tier):
                profile = allocator.evaluate_shot_complexity(shot)
                self.assertEqual((profile["complexity_score"], profile["complexity_tier"]), (score, tier))
        for text in ("@CAST-01:night @CAST-01#day dialogue", "@cast-01 @CAST-01:night"):
            profile = allocator.evaluate_shot_complexity({"description": text})
            self.assertEqual(profile["cast_count"], 1)
            self.assertEqual(profile["complexity_tier"], "standard")

    def test_action_token_boundaries_and_legacy_rows(self):
        profile = allocator.evaluate_shot_complexity({"headers": ["Action & Audio Prompt", "Camera Motion", "Status"],
            "cells": ["@CAST-01 @CAST-02 擁抱 手部", "手持", "重抽"]})
        self.assertEqual(profile["complexity_tier"], "hero")
        self.assertEqual(profile["retake_count"], 1)
        self.assertEqual(allocator.evaluate_shot_complexity({"description": "handler handles a candle"})["complexity_score"], 15)
        self.assertEqual(allocator.evaluate_shot_complexity({"headers": ["角色", "狀態"], "cells": ["@CAST-01", "重抽"]})["retake_count"], 1)

    def test_retake_floor_history_dedup_and_score_consistency(self):
        for shot in (B_ROLL | {"retake_count": 1}, DIALOGUE | {"status": "Retake"}, B_ROLL | {"status": "重抽"},
                     B_ROLL | {"videos": [{"videoId": "vd_1", "status": "REJECTED"}]}):
            p = allocator.evaluate_shot_complexity(shot)
            self.assertEqual(p["complexity_tier"], "hero")
            self.assertGreaterEqual(p["complexity_score"], 65)
        shot = B_ROLL | {"retakeCount": 2, "status": "Retake", "videos": [
            {"videoId": "vd_1", "status": "Retake"}, {"videoId": "vd_1", "status": "Retake"},
            {"videoId": "vd_2", "rejected": True}, {"id": "im_1", "kind": "image", "status": "Retake"}]}
        self.assertEqual(allocator.evaluate_shot_complexity(shot)["retake_count"], 2)
        self.assertEqual(allocator.evaluate_shot_complexity(HERO | {"retake_count": 20})["complexity_score"], 100)
        for status in ("Approved", "已完成", "Pending Review", "等待審核", "READY"):
            self.assertEqual(allocator.evaluate_shot_complexity(B_ROLL | {"status": status})["retake_count"], 0)

    def test_all_budget_modes_and_time_pressure(self):
        for shot in (B_ROLL, DIALOGUE, HERO):
            plan = self.select(shot, budget_mode="lab_economical")
            self.assertEqual(plan["tier"], "open_weights")
            self.assertTrue(plan["ready"])
        self.assertEqual(self.select(B_ROLL)["tier"], "open_weights")
        self.assertEqual(self.select(DIALOGUE)["tier"], "open_weights")
        self.assertEqual(self.select(HERO)["tier"], "closed_hero")
        self.assertEqual(self.select(DIALOGUE, time_pressure="high")["tier"], "closed_hero")
        self.assertEqual(self.select(B_ROLL | {"retake_count": 1})["tier"], "closed_hero")
        self.assertEqual(self.select(DIALOGUE, budget_mode="deadline_rush")["tier"], "closed_hero")

    def test_contest_default_deployment_lock_and_lab_never_spend(self):
        for mode in allocator.BUDGET_MODES:
            for policy in (None, "open_weights_only"):
                plan = self.select(HERO, budget_mode=mode, production_policy=policy)
                self.assertEqual((plan["tier"], plan["driver"]), ("open_weights", "comfy_local"))
        os.environ["OPENBENCH_PRODUCTION_POLICY"] = "open_weights_only"
        plan = self.select(HERO, budget_mode="deadline_rush")
        self.assertEqual(plan["tier"], "open_weights")
        os.environ["OPENBENCH_PRODUCTION_POLICY"] = "hybrid_studio"
        self.assertEqual(self.select(HERO, production_policy=None)["tier"], "open_weights")
        for policy, mode in (("open_weights_only", "deadline_rush"), ("hybrid_studio", "lab_economical")):
            plan = self.select(HERO, budget_mode=mode, production_policy=policy, local_comfy_online=False)
            self.assertEqual(plan["tier"], "open_weights")
            self.assertFalse(plan["ready"])
            self.assertIn("local_comfy_offline", plan["configuration_blockers"])

    def test_offline_availability_and_configuration_boundaries(self):
        for shot in (B_ROLL, DIALOGUE, HERO):
            self.assertEqual(self.select(shot, local_comfy_online=False)["driver"], "vendor_api")
        plan = self.select(HERO, availability={"seedance-20-pro": False})
        self.assertEqual(plan["assigned_card_id"], "kling-v2-master")
        os.environ.pop("SEEDANCE_API_KEY")
        self.assertEqual(self.select(HERO)["assigned_card_id"], "kling-v2-master")
        os.environ.pop("KLING_API_URL")
        plan = self.select(HERO)
        self.assertEqual(plan["tier"], "open_weights")
        self.assertIn("configured_open_fallback", plan["reasons"])
        blocked = self.select(HERO, local_comfy_online=False)
        self.assertFalse(blocked["ready"])
        self.assertIn("provider_not_configured", blocked["configuration_blockers"])
        self.assertNotIn("127.0.0.1", str(blocked))
        self.assertNotIn("fixture-only", str(blocked))
        self.assertFalse(self.select(HERO, production_policy=None, local_comfy_online=None)["ready"])

    def test_card_metadata_controls_policy_and_fallback(self):
        original = card_engine.load_studio_card
        def load(name):
            card = original(name)
            if name == "seedance-20-pro":
                card["engine_config"]["fallback_open_card_id"] = "ltx25-cinema"
            return card
        os.environ.pop("SEEDANCE_API_KEY")
        os.environ.pop("KLING_API_KEY")
        with patch.object(card_engine, "load_studio_card", side_effect=load):
            self.assertEqual(self.select(HERO)["assigned_card_id"], "ltx25-cinema")
        def paid_fallback(name):
            card = original(name)
            if name == "seedance-20-pro":
                card["engine_config"]["fallback_open_card_id"] = "rh-cloud-h3-burst"
            return card
        with patch.object(card_engine, "load_studio_card", side_effect=paid_fallback):
            with self.assertRaises(runtime.WorkerError):
                self.select(HERO)
        def disguised(name):
            card = original(name)
            card["engine_config"]["tier"] = "closed_hero"
            return card
        with patch.object(card_engine, "load_studio_card", side_effect=disguised):
            with self.assertRaises(runtime.WorkerError):
                self.select(B_ROLL, production_policy="open_weights_only")

    def test_deadline_batch_bounds_local_and_distributes_remote(self):
        shots = [B_ROLL | {"shotId": f"sh_{i}"} for i in range(5)] + [DIALOGUE, HERO]
        plan = allocator.plan_allocation(shots, budget_mode="deadline_rush", **self.options)
        self.assertEqual([a["driver"] for a in plan["allocations"][:2]], ["comfy_local"] * 2)
        remote = plan["allocations"][2:]
        self.assertTrue(all(a["driver"] != "comfy_local" for a in remote))
        self.assertEqual({a["driver"] for a in remote}, {"vendor_api", "runninghub_cloud"})
        self.assertEqual(plan["summary"]["open_weights_shot_count"], 2)
        self.assertEqual(plan, allocator.plan_allocation(shots, budget_mode="deadline_rush", **self.options))
        contest = allocator.plan_allocation(shots, budget_mode="deadline_rush", **(self.options | {"production_policy": "open_weights_only"}))
        self.assertEqual(contest["summary"]["open_weights_shot_count"], len(shots))

    def test_deadline_no_remote_capacity_does_not_overflow_local_queue(self):
        offline = {name: False for name in ("seedance-20-pro", "kling-v2-master", "rh-cloud-h3-burst")}
        plan = allocator.plan_allocation([B_ROLL] * 4, budget_mode="deadline_rush", availability=offline, **self.options)
        self.assertEqual(plan["summary"]["open_weights_shot_count"], 2)
        self.assertFalse(plan["ready"])
        self.assertFalse(plan["allocations"][2]["ready"])
        for local in (False, None):
            result = allocator.plan_allocation([B_ROLL] * 4, budget_mode="deadline_rush", **(self.options | {"local_comfy_online": local}))
            self.assertEqual(result["summary"]["open_weights_shot_count"], 0)

    def test_resource_estimates_are_units_not_fabricated_gpu_time_or_prices(self):
        plan = allocator.plan_allocation([B_ROLL | {"durationSeconds": 3}, HERO | {"durationSeconds": 7}], **self.options)
        summary = plan["summary"]
        weight = card_engine.load_studio_card("seedance-20-pro")["engine_config"]["cost_weight"]
        self.assertEqual(summary["estimated_cloud_resource_units"], 7 * weight)
        self.assertEqual(summary["estimated_local_output_seconds"], 3)
        self.assertIsNone(summary["estimated_cloud_credits"])
        self.assertIsNone(summary["estimated_local_gpu_seconds"])
        self.assertEqual(allocator.plan_allocation([])["summary"]["estimated_cloud_credits"], 0)

    def test_structural_steps_use_existing_ffmpeg_and_metadata_slots(self):
        plan = self.select(HERO, budget_mode="lab_economical")
        self.assertEqual([p["config"]["mode"] for p in plan["preparation_steps"]], ["motion_structure", "frame_sheet"])
        self.assertEqual(plan["preparation_steps"][0]["config"]["structure_type"], "layout_silhouette")
        self.assertIn("source_video", plan["stages"][-1]["inputs"])
        plan = allocator.escalate_shot_on_retake(DIALOGUE, strategy="open_structural_lock", **self.options)
        self.assertIn(plan["assigned_card_id"], ("h3-reference", "ltx25-openjutsu"))
        self.assertEqual(plan["complexity_tier"], "hero")
        self.assertTrue(plan["preparation_steps"])

    def test_retake_strategies_and_policy_blockers(self):
        plan = allocator.escalate_shot_on_retake(DIALOGUE, **self.options)
        self.assertEqual(plan["assigned_card_id"], "seedance-20-pro")
        race = allocator.escalate_shot_on_retake(DIALOGUE, strategy="ab_race", **self.options)
        self.assertEqual([p["tier"] for p in race["race_plans"]], ["open_weights", "closed_hero"])
        blocked_race = allocator.escalate_shot_on_retake(DIALOGUE, strategy="ab_race", **(self.options | {"local_comfy_online": False}))
        self.assertFalse(blocked_race["ready"])
        for mode, policy in (("lab_economical", "hybrid_studio"), ("deadline_rush", "open_weights_only")):
            for strategy in ("closed_hero", "ab_race", "closed_to_open_4k"):
                result = allocator.escalate_shot_on_retake(HERO, strategy=strategy, budget_mode=mode,
                    **(self.options | {"production_policy": policy}))
                self.assertFalse(result["ready"])
                self.assertTrue(all(s.get("tier", "open_weights") == "open_weights" for s in result["stages"]))

    def assert_stage_dependencies(self, plan):
        seen = set()
        for stage in plan["stages"]:
            self.assertNotIn(stage["step_id"], seen)
            self.assertTrue(set(stage["depends_on"]) <= seen)
            seen.add(stage["step_id"])
        self.assertEqual(plan["status"], "planned")
        self.assertTrue(plan["requires_user_confirmation"])

    def test_closed_to_open_source_handoff_and_ingredients(self):
        plan = allocator.plan_shot_chain(HERO, chain_mode="closed_hero_to_open_4k_optimize", **self.options)
        self.assert_stage_dependencies(plan)
        self.assertEqual(plan["assigned_card_id"], "h3-optimize")
        self.assertEqual(plan["handoffs"][0]["token"], "@source")
        self.assertEqual(plan["handoffs"][0]["source"]["from_step"], "hero")
        self.assertIn("ingredients_sheet", plan["stages"][-1]["inputs"])
        self.assertFalse(next(s for s in plan["stages"] if s["kind"] == "approval")["satisfied"])
        existing = allocator.plan_shot_chain(HERO, chain_mode="closed_hero_to_open_4k_optimize", approved_source="vd_approved", **self.options)
        self.assertEqual(existing["handoffs"][0]["source"], {"approved_source_id": "vd_approved"})
        self.assertEqual([s.get("card_id") for s in existing["stages"] if s["kind"] == "generate"], ["h3-optimize"])
        self.assert_stage_dependencies(existing)

    def test_open_previz_requires_composition_approval_before_paid_final(self):
        plan = allocator.plan_shot_chain(HERO, chain_mode="open_previz_to_closed_hero", **self.options)
        self.assert_stage_dependencies(plan)
        self.assertEqual([s.get("card_id") for s in plan["stages"] if s["kind"] == "generate"], ["ltx25-cinema", "seedance-20-pro"])
        self.assertEqual(next(s for s in plan["stages"] if s["kind"] == "approval")["condition"], "composition_approved")
        self.assertIn("anchor_keyframe", plan["stages"][-1]["inputs"])
        existing = allocator.plan_shot_chain(HERO, chain_mode="open_previz_to_closed_hero", approved_source="im_approved", **self.options)
        self.assert_stage_dependencies(existing)
        self.assertEqual(existing["stages"][-1]["inputs"]["anchor_keyframe"], {"approved_source_id": "im_approved"})

    def test_chain_availability_and_source_validation(self):
        plan = allocator.plan_shot_chain(HERO, chain_mode="closed_hero_to_open_4k_optimize", **(self.options | {"local_comfy_online": False}))
        self.assertFalse(plan["ready"])
        for source in ("https://example.test/signed?token=secret", "/tmp/file.mp4", {}, "im_wrong"):
            with self.assertRaises(runtime.WorkerError):
                allocator.plan_shot_chain(HERO, chain_mode="closed_hero_to_open_4k_optimize", approved_source=source, **self.options)

    def test_input_validation(self):
        for options in ({"budget_mode": "bad"}, {"production_policy": "bad"}, {"time_pressure": "bad"},
                        {"availability": {"x": "yes"}}, {"availability": []}, {"local_comfy_online": 1},
                        {"b_roll_index": -1}, {"remote_index": True}):
            with self.subTest(options=options), self.assertRaises(runtime.WorkerError):
                self.select(HERO, **options)
        for shot in ("sh_unresolved", {"retake_count": -1}, {"retake_count": True}, {"headers": [], "cells": "bad"},
                     {"candidates": ["bad"]}, {1: "bad"}):
            with self.subTest(shot=shot), self.assertRaises(runtime.WorkerError):
                allocator.evaluate_shot_complexity(shot)
        for value in (float("nan"), float("inf"), -1, 0, True, "bad"):
            with self.assertRaises(runtime.WorkerError):
                allocator.plan_allocation([HERO | {"durationSeconds": value}])
        for args in (([], {"extra": True}), (None, {}), ([], {"budget_mode": "bad"})):
            with self.assertRaises(runtime.WorkerError):
                allocator.plan_allocation(args[0], **args[1])
        with self.assertRaises(runtime.WorkerError):
            allocator.plan_shot_chain(HERO, chain_mode="bad")
        with self.assertRaises(runtime.WorkerError):
            allocator.escalate_shot_on_retake(HERO, strategy="bad")
        os.environ["OPENBENCH_PRODUCTION_POLICY"] = "invalid"
        with self.assertRaises(runtime.WorkerError):
            self.select(HERO)

    def test_no_mutation_execution_or_health_probe_and_package_exports(self):
        from project_assistant import studio, limb_worker
        snapshot = copy.deepcopy(HERO)
        with patch.object(studio.model_router, "probe_local_comfy_status", side_effect=AssertionError("network")), \
             patch.object(studio.model_router.ModelRouter, "execute_card", side_effect=AssertionError("inference")), \
             patch("subprocess.run", side_effect=AssertionError("CLI")):
            self.select(HERO)
            allocator.plan_allocation([HERO], **self.options)
            allocator.escalate_shot_on_retake(HERO, **self.options)
            allocator.plan_shot_chain(HERO, chain_mode="open_previz_to_closed_hero", **self.options)
        self.assertEqual(HERO, snapshot)
        for name in allocator.__all__:
            self.assertIs(getattr(studio, name), getattr(allocator, name))
            self.assertIs(getattr(limb_worker, name), getattr(allocator, name))

    def test_agent_advice_is_capability_only_and_never_reconfigures(self):
        with patch.object(agent_registry, "save_agent", side_effect=AssertionError("write")), \
             patch("subprocess.run", side_effect=AssertionError("CLI")):
            for mode in allocator.BUDGET_MODES:
                for key in ("coordinator", "sheet_ops"):
                    result = agent_registry.recommend_agent_provider_tier(key, mode)
                    self.assertEqual(result["provider_tier"], "flagship_reasoning")
                    self.assertFalse(result["changes_configuration"])
                    self.assertFalse(result["launches_external_cli"])
                vision = agent_registry.recommend_agent_provider_tier("qa_critic", mode)
                self.assertIn("vision", vision["required_capabilities"])
                self.assertEqual(vision["reference_media"]["frames"], 8)
                self.assertEqual(agent_registry.recommend_agent_provider_tier("doc_writer", mode)["provider_tier"], "flagship_reasoning")
                for task in ("formatting", "translation"):
                    writer = agent_registry.recommend_agent_provider_tier("doc_writer", mode, task_kind=task)
                    self.assertEqual(writer["provider_kind_hint"], "openai_compat")
                    self.assertEqual(writer["provider_tier"], "economical_local")
        for args in (("bad", "lab_economical"), ("coordinator", "bad"), ([], "hybrid_balanced")):
            with self.assertRaises(agent_registry.AgentError):
                agent_registry.recommend_agent_provider_tier(*args)
        with self.assertRaises(agent_registry.AgentError):
            agent_registry.recommend_agent_provider_tier("doc_writer", task_kind="bad")


if __name__ == "__main__":
    unittest.main()
