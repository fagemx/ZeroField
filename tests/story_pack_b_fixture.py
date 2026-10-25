"""Shared HTTP + PostgreSQL fixture of the SPEC_18 pack B backend tests.

It repeats the Story fixture of test_story_openapi (a studio-template production behind the real HTTP server) so that file
stays untouched. Use it as a mixin: ``class X(PackBFixture, unittest.TestCase)``; the database is OPENBENCH_TEST_DB_URI.
"""
from datetime import datetime, timedelta, timezone
import time
import uuid

from project_docs import markdown_import, repository as repo, story_openapi as story, templates
from project_docs.doc_schema import validate_doc
from project_assistant import limb_worker as worker
import test_product_http as product_fixture

SCRIPT = ("## Scene 01: Observatory\n@CAST-01 walks past @PROP-01.\n\n"
          "## Scene 02: Departure\n@CAST-01 leaves.")


class PackBFixture:
    request = product_fixture.ProductHTTPTests.request

    def setUp(self):
        product_fixture.ProductHTTPTests.setUp(self)
        for key, title, surface, md in templates.tab_specs("zerofield_studio", "Story Test", ""):
            doc, _ = markdown_import.markdown_to_doc(md, tab_keys=set(), image_src=lambda _: None)
            doc, _ = validate_doc(doc, slug=self.slug)
            templates.configure_doc(key, doc)
            repo.create_tab(self.conn, self.slug, key=key, title=title, parent_key=None, doc=doc,
                            actor_id=self.actor, surface_type=surface)
        self.ep = f"ep_{self.slug}_01"
        self.conn.commit()
        self.extra_projects, self.extra_cards = [], []

    def tearDown(self):
        self.conn.rollback()
        with worker._OPENAPI_LOCK:
            for key, (card, _) in list(worker._OPENAPI_CARDS.items()):
                if card["card_id"] in self.extra_cards:
                    worker._OPENAPI_CARDS.pop(key)
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM projectops.story_record WHERE owner_id=%s", (self.actor,))
            for slug in self.extra_projects:
                cur.execute("DELETE FROM projectops.flow_definition WHERE project_slug=%s", (slug,))
                cur.execute("DELETE FROM projectops.project WHERE slug=%s", (slug,))
        self.conn.commit()
        product_fixture.ProductHTTPTests.tearDown(self)

    def call(self, path, method="GET", body=None, headers=None):
        code, payload, _ = self.request(story.BASE + path, method=method, data=body, headers=headers)
        return code, payload

    def ok(self, path, method="GET", body=None, headers=None):
        code, payload = self.call(path, method, body, headers)
        self.assertEqual(code, 200, payload)
        self.assertEqual((payload["code"], payload["msg"], payload["errorMessages"]), (0, "success", None))
        return payload["data"]

    def prepare(self, script=SCRIPT):
        """Save and confirm a script, build its storyboard; return the cinema shots that belong to a scene."""
        self.ok(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": script})
        self.ok(f"/episodes/{self.ep}/asset-extractions", "POST", {})
        self.ok(f"/episodes/{self.ep}/storyboards", "POST", {})
        return self.scene_shots()

    def scene_shots(self):
        items = self.ok(f"/episodes/{self.ep}/shots?limit=100")["items"]
        return [s for s in items if s["tabKey"] == "cinema-studio" and s.get("sceneId")]

    def asset(self, code="CAST-01"):
        return next(a for a in self.ok(f"/episodes/{self.ep}/assets?limit=100")["items"] if a["assetCode"] == code)

    def await_task(self, task):
        end = time.monotonic() + 30
        while time.monotonic() < end:
            current = self.ok("/tasks/" + task["taskId"])
            if current["status"] not in ("QUEUED", "RUNNING"):
                return current
            time.sleep(.05)
        self.fail("Story task did not finish")

    def add_runs(self, card_id, seconds, *, status="SUCCEEDED", slug=None, job=None, finished=True):
        """Store finished generation tasks of one card, oldest first; each took the given number of seconds to finish."""
        slug = slug or self.slug
        begin = datetime(2026, 10, 1, tzinfo=timezone.utc)
        for i, took in enumerate(seconds):
            created = begin + timedelta(hours=i)
            identifier = "tk_test" + uuid.uuid4().hex
            task = {"taskId": identifier, "type": "ASSET_IMAGE_GENERATE", "status": status, "progress": None, "error": None,
                    "result": {}, "cost": None, "createdAt": created.isoformat(),
                    "finishedAt": (created + timedelta(seconds=took)).isoformat() if finished else None,
                    "_job": {"card": {"card_id": card_id}, **(job or {})}}
            story.store(self.conn, identifier, "task", task, slug, self.actor)
        self.conn.commit()

    def other_project(self, suffix="-other"):
        slug = self.slug + suffix
        repo.upsert_project(self.conn, slug, "Other production")
        self.conn.commit()
        self.extra_projects.append(slug)
        return slug
