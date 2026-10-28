"""SPEC_21 package C: the asset API (asset_meta, panels, the sheet, stress tests, STATE variants, the generation source).

Real HTTP and PostgreSQL (OPENBENCH_TEST_DB_URI); the renders are a stand-in for the Studio card worker, so no model, GPU,
ComfyUI or network is used. The three image cards are read by id: while package A's cards are not registered (or have no
width/height inputs yet) a minimal stand-in with the same id is registered for the test.
"""
import copy
import io
import os
import sys
import types
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from project_assistant import limb_worker as worker
from project_docs import repository as repo, story_assets as assets, story_openapi as story
from story_pack_b_fixture import PackBFixture

SOUL_CAST, REFERENCE_KEY, KLEIN_EDIT = "flux-soul-cast", "flux-reference-key", "flux-klein-edit"
GREY = (0x8A, 0x8A, 0x8A)


def near(found, wanted):
    return all(abs(a - b) <= 2 for a, b in zip(found, wanted))


def png(color, size=(48, 64)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def figure(size=(768, 1344), box=(200, 100, 567, 1299), color=(200, 0, 0)):
    """A front as the card renders it: one figure (``box``, inclusive) on the mid-grey backdrop, as PNG bytes."""
    picture = Image.new("RGB", size, GREY)
    ImageDraw.Draw(picture).rectangle(box, fill=color)
    out = io.BytesIO()
    picture.save(out, format="PNG")
    return out.getvalue()


def stand_in(card_id, refs):
    """A Klein image card: prompt, seed, the latent width/height and ``refs`` optional reference images."""
    nodes = [{"nodeId": "6", "fieldName": "text", "fieldType": "STRING", "label": "Prompt", "slot": "prompt", "defaultValue": "x"},
             {"nodeId": "3", "fieldName": "seed", "fieldType": "INT", "label": "Seed", "slot": "seed", "defaultValue": "7", "min": 0, "max": 281474976710655},
             {"nodeId": "5", "fieldName": "width", "fieldType": "INT", "label": "Width", "defaultValue": "1280"},
             {"nodeId": "5", "fieldName": "height", "fieldType": "INT", "label": "Height", "defaultValue": "720"}]
    nodes += [{"nodeId": str(20 + i), "fieldName": "image", "fieldType": "IMAGE", "label": f"Reference {i + 1}", "slot": "ref"} for i in range(refs)]
    card = worker.validate_studio_card({"card_id": card_id, "label": card_id, "output_mode": "image", "nodes": nodes,
        "engine_config": {"webappId": card_id, "workflow": f"workflows/{card_id}.json", "driver": "comfy_local",
                          "tier": "open_weights", "requires_comfyui": True, "output_node": "9"}})
    graph = {"5": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": 1280, "height": 720, "batch_size": 1}},
             "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}},
             "3": {"class_type": "KSampler", "inputs": {"seed": 7, "latent_image": ["5", 0]}},
             "9": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "spec21"}}}
    return card, graph


class PanelPureTests(unittest.TestCase):
    def test_the_panel_table_is_the_spec_table(self):
        self.assertEqual(assets.PANEL_TABLE, {
            "face": (SOUL_CAST, (), (896, 1184)), "front": (REFERENCE_KEY, ("face",), (768, 1344)),
            "back": (REFERENCE_KEY, ("face",), (768, 1344)), "plate": (SOUL_CAST, (), (1344, 768)),
            "reverse": (KLEIN_EDIT, ("plate",), (1344, 768)), "angle": (KLEIN_EDIT, ("plate",), (1344, 768)),
            "product": (SOUL_CAST, (), (1024, 1024)), "stress": (REFERENCE_KEY, (), (1280, 704))})
        self.assertEqual(assets.PANELS, {"CHARACTER": ("face", "front", "back", "sheet"), "SCENE": ("plate", "reverse", "angle"), "PROP": ("product",)})

    def test_the_sheet_is_front_back_face_on_grey_and_deterministic(self):
        front, back = png((200, 0, 0), (768, 1344)), png((0, 200, 0), (768, 1344))
        for face_size in ((896, 1184), (300, 1184)):  # a narrow face gets a cell of 38 % of the sheet, the face centred in it
            face = png((0, 0, 200), face_size)
            sheet = assets.compose(front, back, face)
            self.assertEqual(sheet, assets.compose(front, back, face), "the same three pictures give the same file")
            with Image.open(io.BytesIO(sheet)) as image:
                picture = image.convert("RGB")
            self.assertEqual(picture.height, 1152)
            side = round(768 * 1152 / 1344)
            cell = picture.width - 2 * side
            self.assertGreaterEqual(cell / picture.width, 0.38, face_size)
            self.assertTrue(near(picture.getpixel((side // 2, 600)), (200, 0, 0)))
            self.assertTrue(near(picture.getpixel((side + side // 2, 600)), (0, 200, 0)))
            self.assertTrue(near(picture.getpixel((2 * side + cell // 2, 600)), (0, 0, 200)))
            if face_size[0] == 300:
                self.assertEqual(picture.getpixel((2 * side + 2, 600)), GREY)
                self.assertEqual(picture.getpixel((picture.width - 3, 600)), GREY)
        with Image.open(io.BytesIO(sheet)) as image:
            self.assertEqual(image.format, "PNG")

    def test_without_opencv_the_head_is_cut_at_15_percent_of_the_figure(self):
        with patch.dict(sys.modules, {"cv2": None}):  # the optional dependency is missing: import fails
            cropped = assets.crop_head(figure())
            self.assertEqual(cropped, assets.crop_head(figure()), "the same picture gives the same crop")
            self.assertIsNone(assets.crop_head(png(GREY, (768, 1344))), "nothing stands out: the picture is kept whole")
        line = int(100 + 0.15 * (1299 - 100))
        with Image.open(io.BytesIO(cropped)) as image:
            self.assertEqual((image.format, image.size), ("PNG", (768, 1344 - line)))  # full width, cut below the head
            picture = image.convert("RGB")
        self.assertEqual((picture.getpixel((384, 0)), picture.getpixel((10, 0))), ((200, 0, 0), GREY))

    def test_with_opencv_the_cut_is_below_the_largest_face(self):
        calls = []

        class Cascade:
            def __init__(self, path):
                calls.append(path)

            def empty(self):
                return False

            def detectMultiScale(self, gray, **options):
                calls.append((gray.shape, options))
                return [(10, 40, 30, 30), (300, 120, 60, 80), (5, 5, 10, 10)]
        fake = types.SimpleNamespace(cvtColor=lambda array, code: array[:, :, 0], COLOR_RGB2GRAY=7, error=RuntimeError,
                                     data=types.SimpleNamespace(haarcascades="cascades/"), CascadeClassifier=Cascade)
        with patch.dict(sys.modules, {"cv2": fake}):
            cropped = assets.crop_head(figure())
        self.assertEqual(calls, ["cascades/haarcascade_frontalface_default.xml",
                                 ((1344, 768), {"scaleFactor": 1.05, "minNeighbors": 5, "minSize": (24, 24)})])
        with Image.open(io.BytesIO(cropped)) as image:
            self.assertEqual(image.size, (768, 1344 - int(120 + 1.25 * 80)))  # the largest box: 60 x 80 at y 120

    def test_a_state_variant_opens_with_the_same_identity_sentence(self):
        prompt, change = assets.variant_text({"change": "soaked to the skin.", "prompt": "Hair plastered flat."}, "CAST-01", "STATE")
        self.assertEqual(prompt, "Same identity as @CAST-01: same face, body proportions and posture. Changed: soaked to the skin. Hair plastered flat.")
        self.assertEqual(change, "soaked to the skin.")
        with self.assertRaises(story.StoryError) as caught:
            assets.variant_text({"prompt": "wet"}, "CAST-01", "STATE")
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(assets.variant_text({"prompt": "Night coat", "change": "a long night coat"}, "CAST-01", "OUTFIT"), ("Night coat", "a long night coat"))

    def test_only_panel_renders_mark_their_candidates(self):
        self.assertEqual(assets.candidate_fields({"input": {"rows": []}}), {})
        self.assertEqual(assets.candidate_fields({"input": {"panel": "face"}}), {"panel": "face"})
        self.assertEqual(assets.candidate_fields({"input": {"panel": "stress", "variation": 3, "stress_with": ["CAST-02"], "stress_set": "SET-01"}}),
                         {"panel": "stress", "variation": 3, "with": ["CAST-02"], "set": "SET-01"})


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for Story HTTP tests")
class AssetPanelHTTPTests(PackBFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        for card_id, refs in ((SOUL_CAST, 0), (REFERENCE_KEY, 6), (KLEIN_EDIT, 3)):
            try:
                card = worker.load_studio_card(card_id)
            except worker.WorkerError:
                card = None
            if card and {"width", "height"} <= {node["fieldName"] for node in card["nodes"]}:
                continue  # package A's card, as registered
            with worker._OPENAPI_LOCK:
                worker._OPENAPI_CARDS[card_id] = stand_in(card_id, refs)
            self.extra_cards.append(card_id)
        self.prepare()

    # ---- helpers ----
    def generate(self, code, panel, **extra):
        return self.call(f"/assets/{self.asset(code)['assetId']}/image-generations", "POST", {"panel": panel, **extra})

    def queued(self, code, panel, **extra):
        with patch.object(story._POOL, "submit"):
            status, payload = self.generate(code, panel, **extra)
        self.assertEqual(status, 200, payload)
        data = payload["data"]
        return data["tasks"] if "tasks" in data else [data]

    def job(self, task):
        self.conn.rollback()
        return story.record(self.conn, task["taskId"])["_job"]

    def key(self, job, field):
        return next(f"{n['nodeId']}.{n['fieldName']}" for n in job["card"]["nodes"] if (n.get("slot") if field == "seed" else n["fieldName"]) == field)

    def size(self, job):
        nodes = {node["fieldName"]: f"{node['nodeId']}.{node['fieldName']}" for node in job["card"]["nodes"] if node["fieldName"] in ("width", "height")}
        return job["values"].get(nodes["width"]), job["values"].get(nodes["height"])

    def finish(self, tasks, pictures):
        """Run queued tasks through the real worker path, the card render replaced by ``pictures`` in order."""
        pending, seen = list(pictures), []

        def render(task, card, values, head):
            seen.append(task)
            return head.upload(task, pending.pop(0), "image/png")
        self.conn.rollback()
        with patch.object(worker, "execute_story_card", side_effect=render):
            for task in tasks:
                story.execute_task(task["taskId"])
        done = [self.ok("/tasks/" + task["taskId"]) for task in tasks]
        self.assertEqual([task["status"] for task in done], ["SUCCEEDED"] * len(tasks), done)
        return done, seen

    def picture(self, color, size=(48, 64), data=None):
        """A production picture (put_asset; ``data`` or a plain colour) as an image candidate of nothing yet: its URL."""
        aid = repo.put_asset(self.conn, self.slug, data=data or png(color, size), content_type="image/png", actor_id=self.actor)
        self.conn.commit()
        return f"/projects/api/{self.slug}/assets/{aid}"

    def candidate(self, code, panel, color, size=(48, 64), data=None):
        """A finished render of ``panel`` on ``code``: its imageId."""
        asset = self.asset(code)
        url = self.picture(color, size, data)
        story.store(self.conn, "ca_test_" + story.digest([asset["assetId"], url])[:20], "candidate",
                    {"entityId": asset["assetId"], "kind": "image", "url": url, "createdAt": story.now(), "panel": panel}, self.slug)
        self.conn.commit()
        return assets.image_id(asset["assetId"], url)

    def choose(self, code, panel, image_id):
        return self.ok(f"/assets/{self.asset(code)['assetId']}/panels/{panel}", "PUT", {"imageId": image_id})

    def reference_cell(self, code):
        return self.asset(code)["selectedImageUrl"]

    # ---- A6 ----
    def test_meta_is_read_written_bounded_and_needs_write_access(self):
        cast, scene, prop = (self.ok("/assets/" + self.asset(code)["assetId"]) for code in ("CAST-01", "SET-01", "PROP-01"))
        self.assertEqual(cast["meta"], {"acting": "", "geo": "", "light": "", "lock": "", "change": ""})
        self.assertEqual(cast["panels"], {"face": None, "front": None, "back": None, "sheet": None})
        self.assertEqual(scene["panels"], {"plate": None, "reverse": None, "angle": None})
        self.assertEqual(prop["panels"], {"product": None})
        path = f"/assets/{cast['assetId']}/meta"
        meta = self.ok(path, "PATCH", {"acting": "Weight on the balls of her feet.", "lock": "x" * 4000})
        self.assertEqual(meta, {"acting": "Weight on the balls of her feet.", "geo": "", "light": "", "lock": "x" * 4000, "change": ""})
        self.assertEqual(self.ok(path, "PATCH", {"geo": "Burner centre, wall behind."})["acting"], "Weight on the balls of her feet.")
        self.assertEqual(self.ok("/assets/" + cast["assetId"])["meta"]["geo"], "Burner centre, wall behind.")
        for body in ({"acting": "x" * 4001}, {"acting": 3}, {"mood": "calm"}):
            self.assertEqual(self.call(path, "PATCH", body)[0], 422, body)
        self.assertEqual(self.ok("/assets/" + cast["assetId"])["meta"]["lock"], "x" * 4000)
        repo.upsert_member(self.conn, self.actor, "Viewer", "viewer")
        self.conn.commit()
        self.assertEqual(self.call(path, "PATCH", {"acting": "denied"})[1]["code"], "DRAMA_OPERATION_NOT_ALLOWED")
        self.assertEqual(self.ok("/assets/" + cast["assetId"])["meta"]["acting"], "Weight on the balls of her feet.")  # viewers still read

    # ---- A7 ----
    def test_each_panel_picks_its_card_size_and_earlier_panels(self):
        (face,) = self.queued("CAST-01", "face", appCode="LOCAL_SDXL_SMOKE")  # the request's appCode is ignored
        job = self.job(face)
        self.assertEqual((job["card"]["card_id"], self.size(job), job["input"]["panel"]), (SOUL_CAST, (896, 1184), "face"))
        status, payload = self.generate("CAST-01", "front")
        self.assertEqual((status, payload["code"]), (409, "DRAMA_STAGE_PRECONDITION"))
        self.assertIn("face panel", payload["message"])
        status, payload = self.generate("CAST-01", "back")
        self.assertEqual(status, 409)
        self.assertIn("face panel", payload["message"])
        self.choose("CAST-01", "face", self.candidate("CAST-01", "face", "blue"))
        (back,) = self.queued("CAST-01", "back")  # the back needs the face only (SPEC_21 §2.3)
        self.assertEqual((self.job(back)["card"]["card_id"], self.size(self.job(back))), (REFERENCE_KEY, (768, 1344)))
        fronts = self.queued("CAST-01", "front", count=2)
        self.assertEqual(len(fronts), 2)
        job = self.job(fronts[0])
        self.assertEqual((job["card"]["card_id"], self.size(job)), (REFERENCE_KEY, (768, 1344)))
        face_url = self.ok("/assets/" + self.asset("CAST-01")["assetId"])["panels"]["face"]["url"]
        self.assertEqual(job["input"]["asset_meta"]["CAST-01"]["panels"], {"face": face_url})  # the compiler's image 1
        self.assertNotEqual(*(self.job(t)["values"].get(self.key(job, "seed")) for t in fronts))
        width = self.key(self.job(face), "width")
        self.assertEqual(self.size(self.job(self.queued("CAST-01", "face", modelParams={width: 640})[0]))[0], 640)  # explicit input wins
        (plate,) = self.queued("SET-01", "plate")
        self.assertEqual((self.job(plate)["card"]["card_id"], self.size(self.job(plate))), (SOUL_CAST, (1344, 768)))
        self.assertEqual(self.generate("SET-01", "reverse")[0], 409)
        self.choose("SET-01", "plate", self.candidate("SET-01", "plate", "gray"))
        (reverse,) = self.queued("SET-01", "angle")
        self.assertEqual((self.job(reverse)["card"]["card_id"], self.size(self.job(reverse))), (KLEIN_EDIT, (1344, 768)))
        (product,) = self.queued("PROP-01", "product")
        self.assertEqual((self.job(product)["card"]["card_id"], self.size(self.job(product))), (SOUL_CAST, (1024, 1024)))
        for code, panel in (("CAST-01", "plate"), ("PROP-01", "face"), ("CAST-01", "sheet"), ("CAST-01", "stress"), ("CAST-01", "side"), ("CAST-01", 3)):
            self.assertEqual(self.generate(code, panel)[0], 422, (code, panel))
        self.assertEqual(self.generate("CAST-01", "face", count=5)[0], 422)
        shot = self.scene_shots()[0]["shotId"]
        self.assertEqual(self.call(f"/shots/{shot}/image-generations", "POST", {"panel": "face"})[0], 422)
        self.assertEqual(self.call(f"/assets/{self.asset('CAST-01')['assetId']}/video-generations", "POST", {"panel": "face", "appCode": "ltx25-cinema"})[0], 422)

    # ---- A7, A8 ----
    def test_renders_stay_candidates_until_chosen_and_the_sheet_is_composed(self):
        asset = self.asset("CAST-01")
        identifier, before = asset["assetId"], asset["selectedImageUrl"]
        (face,) = self.queued("CAST-01", "face")
        done, seen = self.finish([face], [png((0, 0, 200), (896, 1184))])
        self.assertEqual(seen[0]["input"]["panel"], "face")  # the worker task carries the source keys
        self.assertFalse(done[0]["result"]["selected"])
        self.assertEqual(self.reference_cell("CAST-01"), before, "a panel render never writes the reference image cell")
        old = self.picture("purple")  # a candidate from before SPEC_21
        story.store(self.conn, "ca_old_" + identifier, "candidate", {"entityId": identifier, "kind": "image", "url": old, "createdAt": story.now()}, self.slug)
        self.conn.commit()
        everything = self.ok(f"/assets/{identifier}/images?limit=100")["items"]
        self.assertEqual({c["url"]: c["panel"] for c in everything}[old], None)
        faces = self.ok(f"/assets/{identifier}/images?panel=face")["items"]
        self.assertEqual([c["url"] for c in faces], [done[0]["result"]["imageUrl"]])
        self.assertEqual(self.call(f"/assets/{identifier}/images?panel=elbow")[0], 422)
        chosen = self.choose("CAST-01", "face", faces[0]["imageId"])
        self.assertEqual(chosen["panels"]["face"], {"url": faces[0]["url"], "imageId": faces[0]["imageId"]})
        self.assertIsNone(chosen["panels"]["sheet"])
        self.assertEqual(self.reference_cell("CAST-01"), before)
        front = self.candidate("CAST-01", "front", None, data=figure())
        original = next(c["url"] for c in self.ok(f"/assets/{identifier}/images?panel=front")["items"] if c["imageId"] == front)
        back = self.candidate("CAST-01", "back", (0, 200, 0), (768, 1344))
        cropped = self.choose("CAST-01", "front", front)["panels"]["front"]
        self.assertEqual((cropped["imageId"], cropped["originalUrl"]), (front, original))  # the candidate stays the chosen one
        self.assertNotEqual(cropped["url"], original)
        self.conn.rollback()
        with Image.open(io.BytesIO(repo.get_asset(self.conn, self.slug, cropped["url"].rsplit("/", 1)[1])[1])) as image:
            self.assertEqual(image.width, 768)
            self.assertLess(image.height, 1344)  # the head is cut off (the cut line itself: the pure tests)
        self.assertEqual(self.choose("CAST-01", "front", front)["panels"]["front"], cropped, "the same front gives the same crop")
        self.assertIn(original, [c["url"] for c in self.ok(f"/assets/{identifier}/images?panel=front")["items"]])
        self.assertNotIn(cropped["url"], [c["url"] for c in self.ok(f"/assets/{identifier}/images?limit=100")["items"]])
        sheet = self.choose("CAST-01", "back", back)["panels"]["sheet"]
        self.assertTrue(sheet["url"].startswith(f"/projects/api/{self.slug}/assets/pa_"))
        self.assertEqual(self.reference_cell("CAST-01"), sheet["url"])
        self.conn.rollback()
        content_type, data = repo.get_asset(self.conn, self.slug, sheet["url"].rsplit("/", 1)[1])
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual((content_type, image.height), ("image/png", 1152))
            picture = image.convert("RGB")
            self.assertTrue(near(picture.getpixel((5, 600)), GREY))  # the cropped front's backdrop, then its figure
            self.assertTrue(near(picture.getpixel((400, 600)), (200, 0, 0)))
        self.assertEqual(self.choose("CAST-01", "back", back)["panels"]["sheet"], sheet, "the same panels give the same sheet")
        self.assertEqual([c["url"] for c in self.ok(f"/assets/{identifier}/images?panel=sheet")["items"]], [sheet["url"]])
        self.assertEqual(self.call(f"/assets/{identifier}/panels/sheet", "PUT", {"imageId": front})[0], 422)
        self.assertEqual(self.call(f"/assets/{identifier}/panels/plate", "PUT", {"imageId": front})[0], 422)
        self.assertEqual(self.call(f"/assets/{identifier}/panels/face", "PUT", {"imageId": "im_nothing"})[0], 404)
        self.assertEqual(self.call(f"/assets/{identifier}/panels/face", "PUT", {})[0], 422)
        plate = self.candidate("SET-01", "plate", "gray")
        self.choose("SET-01", "plate", plate)
        self.assertEqual(assets.image_id(self.asset("SET-01")["assetId"], self.reference_cell("SET-01")), plate)
        product = self.candidate("PROP-01", "product", "orange")
        self.assertEqual(self.choose("PROP-01", "product", product)["panels"], {"product": {"url": self.reference_cell("PROP-01"), "imageId": product}})
        repo.upsert_member(self.conn, self.actor, "Viewer", "viewer")
        self.conn.commit()
        self.assertEqual(self.call(f"/assets/{identifier}/panels/face", "PUT", {"imageId": faces[0]["imageId"]})[0], 409)

    # ---- A9 ----
    def test_stress_tests_queue_variations_and_keep_marks(self):
        identifier = self.asset("CAST-01")["assetId"]
        path = f"/assets/{identifier}/stress-tests"
        self.assertEqual(self.call(path, "POST", {"count": 4})[1]["code"], "DRAMA_STAGE_PRECONDITION")  # nothing to recognise yet
        self.choose("CAST-01", "face", self.candidate("CAST-01", "face", "blue"))
        for body in ({"count": 3}, {"count": 11}, {"count": True}, {"count": "5"}, {"count": 4, "withAssets": ["CAST-99"]},
                     {"count": 4, "withAssets": ["CAST-01"]}, {"count": 4, "withAssets": "SET-01"}, {"count": 4, "setCode": "PROP-01"},
                     {"count": 4, "setCode": "SET-99"}, {"count": 4, "appCode": "flux-soul-cast"}):
            self.assertEqual(self.call(path, "POST", body)[0], 422, body)
        with patch.object(story._POOL, "submit"):
            queued = self.ok(path, "POST", {"count": 5, "withAssets": ["prop-01"], "setCode": "SET-01"})
        self.assertEqual(queued["count"], 5)
        jobs = [self.job(t) for t in queued["tasks"]]
        self.assertEqual([j["input"]["variation"] for j in jobs], [0, 1, 2, 3, 4])
        self.assertEqual({(j["card"]["card_id"], self.size(j), j["input"]["panel"]) for j in jobs}, {(REFERENCE_KEY, (1280, 704), "stress")})
        self.assertEqual({(tuple(j["input"]["stress_with"]), j["input"]["stress_set"]) for j in jobs}, {(("PROP-01",), "SET-01")})
        self.assertEqual(len({j["values"][self.key(j, "seed")] for j in jobs}), 5)
        self.finish(queued["tasks"], [png((10 * i, 0, 0)) for i in range(5)])
        listed = self.ok(path)
        self.assertEqual((listed["total"], listed["recognizable"]), (5, 0))
        self.assertEqual(sorted(i["variation"] for i in listed["items"]), [0, 1, 2, 3, 4])
        self.assertEqual({(tuple(i["with"]), i["set"], i["recognizable"]) for i in listed["items"]}, {(("PROP-01",), "SET-01", None)})
        first, second = listed["items"][:2]
        self.assertEqual(self.ok(f"{path}/{first['imageId']}", "PUT", {"recognizable": True})["recognizable"], True)
        self.ok(f"{path}/{second['imageId']}", "PUT", {"recognizable": False})
        self.ok(f"{path}/{first['imageId']}", "PUT", {"recognizable": True})
        marks = {i["imageId"]: i["recognizable"] for i in self.ok(path)["items"]}
        self.assertEqual((marks[first["imageId"]], marks[second["imageId"]], self.ok(path)["recognizable"]), (True, False, 1))
        self.assertEqual(self.call(f"{path}/{first['imageId']}", "PUT", {"recognizable": "yes"})[0], 422)
        self.assertEqual(self.call(f"{path}/im_unknown", "PUT", {"recognizable": True})[0], 404)
        self.assertEqual(self.reference_cell("CAST-01"), None, "stress renders are candidates only")

    # ---- A10 ----
    def test_state_variants_carry_their_change_and_edit_from_the_base(self):
        base = self.asset("CAST-01")
        path = f"/assets/{base['assetId']}/variants"
        self.assertEqual(self.call(path, "POST", {"name": "Wet", "key": "wet", "kind": "STATE", "prompt": "Hair plastered flat."})[0], 422)
        self.assertEqual(self.call(path, "POST", {"name": "Wet", "key": "wet", "kind": "SOAKED"})[0], 422)
        wet = self.ok(path, "POST", {"name": "Wet", "key": "wet", "kind": "STATE", "change": "soaked to the skin", "prompt": "Hair plastered flat."})
        self.assertEqual(wet["kind"], "STATE")
        self.assertEqual(wet["prompt"], "Same identity as @CAST-01: same face, body proportions and posture. Changed: soaked to the skin. Hair plastered flat.")
        self.assertEqual(self.ok("/assets/" + wet["assetId"])["meta"]["change"], "soaked to the skin")
        status, payload = self.call(f"/assets/{wet['assetId']}/image-generations", "POST", {"panel": "face"})
        self.assertEqual((status, payload["code"]), (409, "DRAMA_STAGE_PRECONDITION"))  # the base has no face and no picture
        url = self.picture("teal")
        story.mutate_row(self.conn, self.me, self.slug, "soul-cast", base["rowId"], {3: f"[Image]({url})"})
        self.conn.commit()
        with patch.object(story._POOL, "submit"):
            task = self.ok(f"/assets/{wet['assetId']}/image-generations", "POST", {"panel": "back"})
        job = self.job(task)
        self.assertEqual((job["card"]["card_id"], self.size(job)), (KLEIN_EDIT, (768, 1344)))
        self.assertEqual((job["input"]["base_panels"], job["input"]["change"]), ({"back": url}, "soaked to the skin"))
        self.choose("CAST-01", "face", self.candidate("CAST-01", "face", "blue"))
        with patch.object(story._POOL, "submit"):
            job = self.job(self.ok(f"/assets/{wet['assetId']}/image-generations", "POST", {"panel": "face"}))
        face = self.ok("/assets/" + base["assetId"])["panels"]["face"]["url"]
        self.assertEqual(job["input"]["base_panels"], {"face": face})
        front = self.choose("CAST-01", "front", self.candidate("CAST-01", "front", None, data=figure()))["panels"]["front"]
        with patch.object(story._POOL, "submit"):
            job = self.job(self.ok(f"/assets/{wet['assetId']}/image-generations", "POST", {"panel": "front"}))
        self.assertEqual(job["input"]["base_panels"], {"face": face, "front": front["originalUrl"]})  # edited with its head
        self.assertEqual(self.ok(path, "POST", {"name": "Night", "key": "night", "kind": "OUTFIT", "prompt": "Night coat"})["prompt"], "Night coat")
        kinds = [v["kind"] for v in self.ok(path)["items"]]
        self.assertEqual(sorted(kinds), ["OUTFIT", "STATE"])

    # ---- §2.5 and the shot image default ----
    def test_every_source_carries_asset_meta_and_first_frames_use_the_reference_card(self):
        shot = self.scene_shots()[0]["shotId"]
        with patch.object(story._POOL, "submit"):
            plain = self.job(self.ok(f"/shots/{shot}/image-generations", "POST", {}))  # no appCode: the studio's first-frame card
        self.assertEqual(plain["card"]["card_id"], REFERENCE_KEY)
        self.assertNotIn("asset_meta", plain["input"], "no asset has a record: the source is what it was")
        options = self.ok(f"/shots/{shot}/generation-options?kind=image")
        self.assertEqual(next(a for a in options["apps"] if a["appCode"] == options["defaultAppCode"])["outputs"], ["IMAGE"])
        catalog = {item["appCode"]: item["card_id"] for item in self.ok("/catalog/apps?capability=IMAGE&limit=100")["items"]}
        self.assertEqual(catalog[options["defaultAppCode"]], REFERENCE_KEY)
        self.assertEqual(catalog[self.ok(f"/assets/{self.asset('CAST-01')['assetId']}/generation-options")["defaultAppCode"]], SOUL_CAST)
        self.assertEqual(self.ok(f"/shots/{shot}/generation-options")["defaultAppCode"], "LTX25_CINEMA_SHOT")
        self.assertEqual(self.call(f"/shots/{shot}/generation-options?kind=audio")[0], 422)
        base = self.asset("CAST-01")
        self.ok(f"/assets/{base['assetId']}/meta", "PATCH", {"acting": "Checks the wall every few seconds.", "lock": "Saffron jacket."})
        wet = self.ok(f"/assets/{base['assetId']}/variants", "POST", {"name": "Wet", "key": "wet", "kind": "STATE", "change": "soaked"})
        self.ok(f"/assets/{wet['assetId']}/meta", "PATCH", {"lock": "Jacket dark with water."})
        face = self.candidate("CAST-01", "face", "blue")
        self.choose("CAST-01", "face", face)
        self.ok(f"/assets/{self.asset('SET-01')['assetId']}/meta", "PATCH", {"geo": "Basket centre.", "light": "Low sun from camera left."})
        with patch.object(story._POOL, "submit"):
            job = self.job(self.ok(f"/shots/{shot}/image-generations", "POST", {"appCode": "LOCAL_SDXL_SMOKE"}))
        face_url = self.ok("/assets/" + base["assetId"])["panels"]["face"]["url"]
        self.assertEqual(job["input"]["asset_meta"], {
            "CAST-01": {"acting": "Checks the wall every few seconds.", "geo": "", "light": "", "lock": "Saffron jacket.", "change": "", "panels": {"face": face_url}},
            "CAST-01:WET": {"acting": "Checks the wall every few seconds.", "geo": "", "light": "", "lock": "Jacket dark with water.", "change": "soaked", "panels": {}},
            "SET-01": {"acting": "", "geo": "Basket centre.", "light": "Low sun from camera left.", "lock": "", "change": "", "panels": {}}})
        self.assertEqual(story.snapshot(self.conn, self.slug, story.find_row(self.conn, shot, "shot")[1])["asset_meta"], job["input"]["asset_meta"])

    def test_prompt_preview_lists_the_reference_plan_and_dropped_blocks(self):
        shot = self.scene_shots()[0]["shotId"]
        path, body = f"/shots/{shot}/prompt-previews", {"kind": "image", "appCode": "LOCAL_SDXL_SMOKE"}
        preview = self.ok(path, "POST", body)
        self.assertEqual((preview["referencePlan"], preview["droppedBlocks"]), ([], []))
        compile_form = story.compile_card_form
        plan = [{"assetCode": "CAST-01", "role": "character_face", "panel": "face", "url": "/projects/api/x/assets/pa_1", "extra": 1}]

        def with_plan(task, card, values):
            ctx, form = compile_form(task, card, values)
            return dict(ctx, reference_plan=copy.deepcopy(plan), dropped_blocks=["PHYSICS", "OPTICS"]), form
        with patch.object(story, "compile_card_form", side_effect=with_plan):
            preview = self.ok(path, "POST", body)
        self.assertEqual(preview["referencePlan"], [{"assetCode": "CAST-01", "role": "character_face", "panel": "face", "url": "/projects/api/x/assets/pa_1"}])
        self.assertEqual(preview["droppedBlocks"], ["PHYSICS", "OPTICS"])


if __name__ == "__main__":
    unittest.main()
