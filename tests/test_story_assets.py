"""A world asset carries what the Cast & Sets view shows: its look, voice, status and notes (no database needed)."""
import unittest

from project_docs import story_openapi as story

URL = "/projects/api/demo/assets/pa_" + "a" * 32


def row(*cells):
    return {"rid": "b1", "cells": list(cells), "headers": [], "tableId": "t", "tabKey": "soul-cast"}


class AssetViewTests(unittest.TestCase):
    def test_a_character_row_exposes_voice_status_and_notes(self):
        view = story.asset_view("demo", row("CAST-01", "Kael", "courier", f"[Image]({URL})", "Calm, measured delivery", "Approved", "Keep the coat"))
        self.assertEqual((view["voice"], view["status"], view["notes"]), ("Calm, measured delivery", "Approved", "Keep the coat"))
        self.assertEqual((view["type"], view["isDefault"], view["kind"], view["selectedImageUrl"]), ("CHARACTER", True, None, URL))

    def test_a_look_keeps_its_kind_out_of_the_notes(self):
        view = story.asset_view("demo", row("CAST-01:night", "Night", "night jacket", "", "", "Queued", "OUTFIT"))
        self.assertEqual((view["kind"], view["notes"], view["isDefault"]), ("OUTFIT", "", False))
        free = story.asset_view("demo", row("CAST-01:rain", "Rain", "wet coat", "", "", "Queued", "a free note"))
        self.assertEqual((free["kind"], free["notes"]), (None, "a free note"))

    def test_a_short_row_has_empty_extras_and_the_type_follows_the_code(self):
        view = story.asset_view("demo", row("SET-01", "Observatory", "dome", ""))
        self.assertEqual((view["voice"], view["status"], view["notes"], view["type"]), ("", "", "", "SCENE"))
        self.assertEqual(story.asset_view("demo", row("PROP-02", "Recorder", "", ""))["type"], "PROP")


if __name__ == "__main__":
    unittest.main()
