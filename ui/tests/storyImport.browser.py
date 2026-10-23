"""One-click upstream story journey over real HTTP/PG and the production UI.

Only image inference is synthetic; adaptation, extraction, shots, budgets,
asset writeback and task-group polling use the application. No provider is called.
"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from PIL import Image
from playwright.sync_api import sync_playwright, expect
import test_story_openapi as fixture
from project_assistant import limb_worker as worker


class StoryImportJourney(unittest.TestCase):
    def test_idea_to_storyboard_and_missing_asset_sheets(self):
        if not os.environ.get("OPENBENCH_TEST_DB_URI"):
            self.fail("A dedicated PostgreSQL test database is required.")
        app = fixture.StoryHTTPTests("test_catalog_envelope_validation_and_auth")
        app.setUp()
        errors = []
        evidence = Path(os.environ.get("OPENBENCH_UI_EVIDENCE_DIR", tempfile.mkdtemp(prefix="spec13-browser-")))
        evidence.mkdir(parents=True, exist_ok=True)
        png = io.BytesIO()
        Image.new("RGB", (32, 32), "#527c8a").save(png, format="PNG")
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1100},
                    extra_http_headers={"Authorization": "Bearer " + app.member_token})
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                try:
                    page.goto(f"http://127.0.0.1:{app.server.server_port}/projects/{app.slug}/#cinema-studio")
                    page.get_by_role("button", name="Start Creating", exact=True).click()
                    dialog = page.get_by_role("dialog", name="Start Creating", exact=True)
                    expect(dialog.get_by_label("Starting Material")).to_be_enabled()
                    dialog.get_by_label("Starting Material").select_option("idea")
                    dialog.get_by_label("Original Source").fill("A lone astronomer discovers a countdown and reaches for a brass dial.")
                    dialog.get_by_role("button", name="Confirm Script & Build Storyboard", exact=True).click()
                    expect(dialog).not_to_be_visible(timeout=30000)
                    shots = [shot for shot in app.ok(f"/episodes/{app.ep}/shots")["items"] if shot.get("sceneId")]
                    self.assertEqual(len(shots), 9)
                    self.assertEqual(len({shot["sceneId"] for shot in shots}), 3)
                    self.assertTrue(all(shot["previsPlan"]["set"] == "parallax" for shot in shots))
                    self.assertTrue(any(shot["dialogue"] for shot in shots))
                    page.get_by_role("button", name="Asset Vault", exact=True).click()
                    vault = page.get_by_role("dialog", name="Asset Vault", exact=True)
                    generate = vault.get_by_role("button", name="Generate Missing Asset Sheets", exact=True)
                    expect(generate).to_be_enabled()
                    missing = app.ok(f"/episodes/{app.ep}")["missingAssetCodes"]
                    self.assertGreater(len(missing), 0)
                    with patch.object(worker, "execute_story_card", side_effect=lambda task, card, values, head: head.upload(task, png.getvalue(), "image/png")):
                        with page.expect_response("**/asset-image-generations") as queued:
                            generate.click()
                        group = queued.value.json()["data"]
                        status = vault.get_by_role("status").filter(has_text="completed")
                        expect(status).to_contain_text("0 queued · 0 running", timeout=30000)
                        detail = app.ok("/task-groups/" + group["taskGroupId"])
                        self.assertEqual(detail["counts"]["succeeded"], str(len(missing)), json.dumps(detail))
                    self.assertEqual(app.ok(f"/episodes/{app.ep}")["missingAssetCodes"], [])
                    expect(generate).to_be_disabled()
                    page.screenshot(path=str(evidence / "idea-to-assets.png"), full_page=True)
                    self.assertEqual(errors, [])
                finally:
                    context.close()
                    browser.close()
        finally:
            app.tearDown()
            app.doCleanups()


if __name__ == "__main__":
    unittest.main(verbosity=2)
