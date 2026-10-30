"""Chained Layout Render (project_assistant/studio/layout_guides.py): the pin, the mid and end guides, and the row
columns that switch them on in the product's Layout Render stage."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from project_assistant import limb_worker as worker
from project_assistant.studio import layout_guides
import test_studio_worker as sw

ROOT = Path(__file__).resolve().parents[1]
GRAPH = json.loads((ROOT / "workflows" / "ltx25_layout_render.json").read_text(encoding="utf-8"))
ASSET = sw.ASSET


class ChainGuideTests(unittest.TestCase):
    def test_a_row_without_chain_images_renders_the_graph_as_it_was(self):
        graph = copy.deepcopy(GRAPH)
        self.assertEqual(layout_guides.add_chain_guides(graph, {"chain_in_frame": None, "end_keyframe": ""}), {})
        self.assertEqual(graph, GRAPH)

    def test_the_chain_in_frame_is_pinned_as_frame_zero(self):
        graph = copy.deepcopy(GRAPH)
        bindings = layout_guides.add_chain_guides(graph, {"chain_in_frame": ASSET(5)})
        (slot, binding), = bindings.items()
        loader = slot.split(".")[0]
        self.assertEqual((graph[loader]["class_type"], binding["source"], binding["upload"]), ("LoadImage", "chain_in_frame", "image"))
        pin = graph["40"]["inputs"]["latent"][0]
        self.assertEqual(graph[pin]["class_type"], "LTXVImgToVideoInplace")
        self.assertEqual((graph[pin]["inputs"]["latent"], graph[pin]["inputs"]["strength"], graph[pin]["inputs"]["vae"]), (["21", 0], 1.0, ["5", 0]))
        scale = graph[graph[pin]["inputs"]["image"][0]]["inputs"]
        self.assertEqual((scale["image"], scale["width"], scale["height"]), ([loader, 0], 1280, 704))  # the latent's size
        self.assertEqual(graph["53"]["inputs"]["positive"], ["42", 0])  # no guide: the sampler still reads the skeleton guide

    def test_end_and_mid_keys_chain_after_the_last_guide_into_sampler_crop_and_concat(self):
        graph = copy.deepcopy(GRAPH)
        bindings = layout_guides.add_chain_guides(graph, {"mid_keyframe": ASSET(6), "end_keyframe": ASSET(7)})
        self.assertEqual(sorted(b["source"] for b in bindings.values()), ["end_keyframe", "mid_keyframe"])
        last = graph["53"]["inputs"]["positive"][0]
        mid = graph[last]["inputs"]
        end = graph[mid["positive"][0]]["inputs"]
        self.assertEqual((graph[last]["class_type"], mid["frame_idx"], mid["strength"]), ("LTXVAddGuide", 96, 0.8))  # middle of 193
        self.assertEqual((end["frame_idx"], end["strength"], end["positive"], end["negative"], end["latent"]),
                         (-1, 0.9, ["42", 0], ["42", 1], ["42", 2]))
        self.assertEqual((graph["53"]["inputs"]["negative"], graph["17"]["inputs"]["positive"], graph["17"]["inputs"]["negative"],
                          graph["15"]["inputs"]["video_latent"]), ([last, 1], [last, 0], [last, 1], [last, 2]))
        self.assertEqual(graph["40"]["inputs"]["latent"], ["21", 0])  # no pin without a chain-in frame

    def test_the_mid_frame_can_be_set_and_is_kept_on_a_multiple_of_eight(self):
        graph = copy.deepcopy(GRAPH)
        layout_guides.add_chain_guides(graph, {"mid_keyframe": ASSET(6)}, {"mid_frame": 70})
        self.assertEqual(graph[graph["53"]["inputs"]["positive"][0]]["inputs"]["frame_idx"], 64)

    def test_the_row_columns_switch_the_chain_on_in_the_product_layout_stage(self):
        import run_studio
        task = sw.studio_task()
        task["input"]["tabs"][0]["tables"][0]["headers"] += ["Previs", "Actor Matte", "Pose Skeleton", "Chain In Frame", "Mid Key", "End Key"]
        task["input"]["rows"][1]["cells"] += [ASSET(9), ASSET(8), ASSET(7), ASSET(10), ASSET(11), ASSET(12)]
        ctx = worker.resolve_studio_context(task)
        self.assertEqual((ctx["chain_in_frame"], ctx["mid_keyframe"], ctx["end_keyframe"]), (ASSET(10), ASSET(11), ASSET(12)))
        self.assertEqual(ctx["anchor_keyframe"], ASSET(3))  # "End Key" is not read as the shot's keyframe
        cfg = run_studio.worker_configs("http://127.0.0.1:8188")["layout"]["video_gen"]
        head, client = Mock(), Mock()
        head.asset.side_effect = lambda task, url: (url.encode(), "video/webm" if url in (ASSET(7), ASSET(8), ASSET(9)) else "image/png")
        client.upload_media.side_effect = lambda raw, mime, prefix: raw.decode()[-2:] + "." + prefix
        layout = json.loads(Path(cfg["workflow"]).read_text(encoding="utf-8"))
        worker.bind_external_workflow(layout, dict(ctx, compiled_prompt="beats", seed=7), cfg, task, head, client)
        images = sorted(n["inputs"]["image"] for n in layout.values() if n["class_type"] == "LoadImage")
        self.assertEqual(images, ["03.input", "0a.input", "0b.input", "0c.input"])  # the key, then chain-in, mid and end
        pin = layout[layout["40"]["inputs"]["latent"][0]]
        self.assertEqual(pin["class_type"], "LTXVImgToVideoInplace")
        guides = [n for n in layout.values() if n["class_type"] == "LTXVAddGuide" and n["inputs"].get("frame_idx") in (-1, 96)]
        self.assertEqual(sorted(g["inputs"]["frame_idx"] for g in guides), [-1, 96])
        self.assertEqual((layout["20"]["inputs"]["video"], layout["30"]["inputs"]["string_a"]), ("09.source_video", "beats"))

    def test_a_plain_layout_row_binds_exactly_as_before(self):
        import run_studio
        cfg = run_studio.worker_configs("http://127.0.0.1:8188")["layout"]["video_gen"]
        head, client = Mock(), Mock()
        head.asset.side_effect = lambda task, url: (url.encode(), "video/webm" if url in (ASSET(7), ASSET(8), ASSET(9)) else "image/png")
        client.upload_media.side_effect = lambda raw, mime, prefix: raw.decode()[-2:] + "." + prefix
        layout = json.loads(Path(cfg["workflow"]).read_text(encoding="utf-8"))
        before = set(layout)
        worker.bind_external_workflow(layout, {"previs_video": ASSET(9), "actor_matte": ASSET(8), "pose_skeleton": ASSET(7),
                                               "anchor_keyframe": ASSET(4), "compiled_prompt": "beats", "seed": 7},
                                      cfg, sw.studio_task(), head, client)
        self.assertEqual(set(layout), before)


if __name__ == "__main__":
    unittest.main()
