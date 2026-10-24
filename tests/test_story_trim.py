"""Per-shot trim: validation, persistence, reset on a new take, and the cut honoured by film export.

The FFmpeg cases cut real tiny clips: a numbered clip (frame N has luma N*6) shows which source frame every
exported frame came from, so "frame-accurate" is measured and not assumed.
"""
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from project_docs import repository as repo, story_openapi as story, story_trim
from project_assistant import limb_worker as worker
from project_assistant.studio import media_prep
import test_story_openapi as fixture

FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
STEP = 6
UNTRIMMED = {"in": 0, "out": None}


def clip_bytes(seconds, *, fps=24, color="blue", audio=False, numbered=False):
    """A tiny mp4. numbered=True paints frame N with luma N*STEP (lossless, so the number survives the cut)."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "clip.mp4"
        args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r={fps}:d={seconds}"]
        if audio:
            args += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}", "-c:a", "aac"]
        if numbered:
            args += ["-vf", f"geq=lum='N*{STEP}':cb=128:cr=128,format=yuv420p", "-qp", "0"]
        subprocess.run(args + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], check=True, timeout=30)
        return path.read_bytes()


def probe(path):
    """(video frame count, container duration) of a media file."""
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=nb_read_frames:format=duration", "-of", "json", str(path)], check=True, capture_output=True, timeout=30).stdout
    data = json.loads(out)
    return int(data["streams"][0]["nb_read_frames"]), float(data["format"]["duration"])


def source_frames(path):
    """The source frame number behind every frame of a numbered clip's cut."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-fps_mode", "passthrough", "-vf", "scale=16:16",
                          "-pix_fmt", "yuv420p", "-f", "rawvideo", "-"], check=True, capture_output=True, timeout=30).stdout
    size = 16 * 16 * 3 // 2
    return [round(raw[i * size + 8 * 16 + 8] / STEP) for i in range(len(raw) // size)]


class TrimRuleTests(unittest.TestCase):
    def rejected(self, body):
        with self.assertRaises(story.StoryError) as caught:
            story_trim.parse(body)
        self.assertEqual((caught.exception.status, caught.exception.code), (422, "DRAMA_VALIDATION_FAILED"), body)

    def test_frame_accurate_points_are_accepted_and_omitted_keys_mean_untrimmed(self):
        self.assertEqual(story_trim.parse({"in": 10 / 24, "out": 34 / 24}), {"in": 10 / 24, "out": 34 / 24})
        self.assertEqual(story_trim.parse({"in": 0, "out": None}), UNTRIMMED)
        self.assertEqual(story_trim.parse({}), UNTRIMMED)
        self.assertEqual(story_trim.parse({"in": 2}), {"in": 2, "out": None})
        self.assertEqual(story_trim.parse({"out": 3}), {"in": 0, "out": 3})
        self.assertEqual(story_trim.parse({"in": 1, "out": 1.0417}), {"in": 1, "out": 1.0417})  # one 24 fps frame is enough
        self.assertEqual(story_trim.parse({"in": 599.5, "out": 600}), {"in": 599.5, "out": 600})
        self.assertEqual(story_trim.parse({"in": 600}), {"in": 600, "out": None})

    def test_everything_that_is_not_a_clean_span_of_seconds_is_refused(self):
        for body in ({"in": -0.001}, {"in": -1, "out": 5}, {"in": 601}, {"out": 600.001}, {"in": 1, "out": 1}, {"in": 2, "out": 1},
                     {"in": 1, "out": 1.04}, {"in": 0, "out": 0.04}, {"in": 0.5, "out": 0.54},   # not more than 0.04 s long
                     {"in": float("nan")}, {"out": float("nan")}, {"in": float("inf")}, {"out": float("inf")}, {"in": -float("inf")},
                     {"in": "1"}, {"out": "3"}, {"in": True}, {"out": True}, {"in": None}, {"in": [1]}, {"out": {"s": 1}},
                     {"in": 10 ** 400}, {"out": 10 ** 400}):
            self.rejected(body)

    def test_a_trim_only_reads_back_while_its_take_is_the_selected_one(self):
        meta = {"episodeId": "ep", "trim": {"in": 1.0, "out": 2.5, "takeUrl": "/a"}}
        self.assertEqual(story_trim.view(meta, "/a"), {"in": 1.0, "out": 2.5})
        self.assertEqual(story_trim.view(meta, "/b"), UNTRIMMED)
        self.assertEqual(story_trim.view(meta, None), UNTRIMMED)
        self.assertEqual(story_trim.view({}, "/a"), UNTRIMMED)
        self.assertEqual(story_trim.view({"trim": "corrupt"}, "/a"), UNTRIMMED)
        # a shot without any take can still hold a trim (nothing is selected yet)
        self.assertEqual(story_trim.view({"trim": {"in": 1.0, "out": None, "takeUrl": None}}, None), {"in": 1.0, "out": None})
        self.assertNotIn("trim", story_trim.strip(meta))

    def test_film_clips_pair_each_url_with_its_own_trim_and_never_cut_previs(self):
        shot = lambda index, url, previs=None, trim=None: {"shotIndex": index, "tabKey": "cinema-studio", "selectedVideoUrl": url,
                                                           "previsVideoUrl": previs, "reviewStatus": "", **({"trim": trim} if trim else {})}
        items = [shot("S10", "/s10", trim={"in": 2.0, "out": None}), shot("S02", "/s02", trim={"in": 0.5, "out": 1.5}),
                 shot("S03", None, "/p03", trim={"in": 0.25, "out": 0.5}), shot("S04", "/s04", trim=UNTRIMMED), shot("S05", "/s05")]
        clips = story.film_shots(items, fill_previs=True)
        self.assertEqual([url for _, url in clips], ["/s02", "/p03", "/s04", "/s05", "/s10"])
        self.assertEqual(story.film_cut(items, fill_previs=True), [url for _, url in clips])
        self.assertEqual(story_trim.film_trims(clips), [{"in": 0.5, "out": 1.5}, None, None, None, {"in": 2.0, "out": None}])
        job = {"urls": [url for _, url in clips], "trims": story_trim.film_trims(clips)}
        self.assertEqual(story_trim.film_rows(job)[0], {"row_id": "0", "cells": ["/s02"], "trim": {"in": 0.5, "out": 1.5}})
        self.assertEqual(story_trim.film_rows(job)[1], {"row_id": "1", "cells": ["/p03"]})
        self.assertEqual(story_trim.film_rows(job)[4]["trim"], {"in": 2.0, "out": None})

    def test_jobs_queued_before_trims_existed_play_whole(self):
        self.assertEqual(story_trim.film_rows({"urls": ["/a", "/b"], "config": {}}), [{"row_id": "0", "cells": ["/a"]}, {"row_id": "1", "cells": ["/b"]}])
        self.assertEqual(story_trim.film_rows({"urls": ["/a", "/b"], "trims": [None]}), [{"row_id": "0", "cells": ["/a"]}, {"row_id": "1", "cells": ["/b"]}])


class AssemblyArgumentTests(unittest.TestCase):
    """The FFmpeg command lines of assemble_files, captured without running FFmpeg."""

    def assemble(self, clips, durations, config=None):
        commands = []

        class Process:
            def __init__(self, args, **kwargs):
                assert args[:5] == ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"], args
                # scratch paths are random per run: keep their file names only
                commands.append([Path(a).name if "openbench-render-" in a else a for a in args[5:]])
                self.returncode = 0
            poll = lambda self: 0
            kill = wait = lambda self: None

        def probe_run(args, **kwargs):
            seconds = durations[Path(args[-1]).name]
            streams = [{"codec_type": "video", "duration": str(seconds)}, {"codec_type": "audio"}]
            return SimpleNamespace(stdout=json.dumps({"streams": streams, "format": {"duration": str(seconds)}}).encode())

        fake = SimpleNamespace(run=probe_run, Popen=Process, SubprocessError=subprocess.SubprocessError, DEVNULL=subprocess.DEVNULL)
        with patch.object(media_prep, "subprocess", fake):
            media_prep.assemble_files(clips, Path("movie.mp4"), dict({"width": 160, "height": 90, "fps": 24}, **(config or {})))
        return commands

    def test_a_trim_seeks_before_the_input_and_cuts_a_whole_number_of_frames(self):
        trimmed = self.assemble([(Path("a.mp4"), "video/mp4", None, {"in": 1.0, "out": 3.0})], {"a.mp4": 5.0})[0]
        self.assertEqual(trimmed[trimmed.index("-ss"):trimmed.index("-ss") + 3], ["-ss", "1.000000", "-i"])
        self.assertLess(trimmed.index("-ss"), trimmed.index("-i"))
        self.assertEqual(trimmed.count("-ss"), 1)
        self.assertEqual(trimmed[trimmed.index("-frames:v"):trimmed.index("-frames:v") + 4], ["-frames:v", "48", "-t", "2.000000"])
        self.assertTrue(trimmed[trimmed.index("-vf") + 1].startswith("setpts=PTS-STARTPTS,scale=160:90"))
        self.assertEqual(trimmed[-3:-1], ["-movflags", "+faststart"])

    def test_untrimmed_clips_keep_their_command_line_exactly(self):
        plain = self.assemble([(Path("a.mp4"), "video/mp4", None)], {"a.mp4": 5.0})[0]
        self.assertEqual(plain, [
            "-i", "a.mp4", "-map", "0:v:0", "-map", "0:a:0",
            "-vf", "scale=160:90:force_original_aspect_ratio=decrease,pad=160:90:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-af", "apad", "-shortest",
            "-t", "5.0", "-movflags", "+faststart", "clip-0000.mp4"])
        # an explicit "no cut" four-tuple is the same command as the three-tuple
        self.assertEqual(self.assemble([(Path("a.mp4"), "video/mp4", None, None)], {"a.mp4": 5.0})[0], plain)

    def test_concat_order_and_faststart_are_unchanged_and_stills_are_not_trimmed(self):
        commands = self.assemble([(Path("a.mp4"), "video/mp4", None, {"in": 0.5, "out": 1.5}), (Path("b.mp4"), "video/mp4", None),
                                  (Path("c.png"), "image/png", None, {"in": 1, "out": 2})], {"a.mp4": 3.0, "b.mp4": 2.0, "c.png": 1.0})
        self.assertEqual(len(commands), 4)
        still = commands[2]
        self.assertNotIn("-ss", still)
        self.assertEqual(still[:2], ["-loop", "1"])
        self.assertEqual(still[still.index("-t"):still.index("-t") + 2], ["-t", "4.0"])
        concat = commands[3]
        self.assertEqual(concat[concat.index("-f"):concat.index("-f") + 2], ["-f", "concat"])
        self.assertEqual(concat[-5:-1], ["-c", "copy", "-movflags", "+faststart"])
        self.assertTrue(all(name in " ".join(commands[i]) for i, name in enumerate(["clip-0000", "clip-0001", "clip-0002"])))

    def test_an_out_past_the_end_plays_to_the_end_and_a_paired_narration_is_cut_with_the_video(self):
        beyond = self.assemble([(Path("a.mp4"), "video/mp4", None, {"in": 4.0, "out": 99})], {"a.mp4": 5.0})[0]
        self.assertEqual(beyond[beyond.index("-frames:v"):beyond.index("-frames:v") + 4], ["-frames:v", "24", "-t", "1.000000"])
        narrated = self.assemble([(Path("a.mp4"), "video/mp4", Path("voice.mp3"), {"in": 1.0, "out": None})], {"a.mp4": 5.0, "voice.mp3": 5.0})[0]
        self.assertEqual(narrated.count("-ss"), 2)
        for at in [i for i, token in enumerate(narrated) if token == "-ss"]:
            self.assertEqual(narrated[at + 2], "-i")
        self.assertEqual(narrated[narrated.index("-frames:v") + 1], "96")

    def test_a_trim_that_leaves_no_frame_or_is_malformed_fails_the_export_with_a_message(self):
        for trim in ({"in": 5.0, "out": None}, {"in": 7, "out": 9}, {"in": 4.99, "out": None}, {"in": "x"}, {"in": -1}, {"in": float("nan")}):
            with self.subTest(trim=trim), self.assertRaisesRegex(worker.WorkerError, "Clip 1 "):
                self.assemble([(Path("a.mp4"), "video/mp4", None, trim)], {"a.mp4": 5.0})
        with self.assertRaisesRegex(worker.WorkerError, "Clip 2 "):
            self.assemble([(Path("a.mp4"), "video/mp4", None), (Path("b.mp4"), "video/mp4", None, {"in": 6})], {"a.mp4": 5.0, "b.mp4": 5.0})

    def test_the_worker_hands_a_rows_trim_to_its_clip(self):
        video = "/projects/api/test/assets/pa_" + "b" * 32
        other = "/projects/api/test/assets/pa_" + "c" * 32
        task = {"id": "t", "input": {"rows": [{"row_id": "0", "cells": [video], "trim": {"in": 0.5, "out": 1.5}}, {"row_id": "1", "cells": [other]}]}}
        head = SimpleNamespace(asset=lambda task, url: (b"fixture", "video/mp4"), upload=lambda task, data, mime: {"asset_url": "/x"})
        captured = []
        def render(clips, destination, config):
            captured.extend(clips)
            destination.write_bytes(b"fixture")
        with patch.object(worker, "assemble_files", side_effect=render):
            worker.ffmpeg(task, {}, head)
        self.assertEqual([len(c) for c in captured], [4, 3])
        self.assertEqual(captured[0][3], {"in": 0.5, "out": 1.5})


@unittest.skipUnless(FFMPEG, "FFmpeg and FFprobe needed for real media")
class RealAssemblyTests(unittest.TestCase):
    def test_cuts_are_frame_accurate_and_the_film_is_the_sum_of_its_cuts(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for name, audio in (("a", True), ("b", False), ("c", True)):
                paths.append(Path(folder) / (name + ".mp4"))
                paths[-1].write_bytes(clip_bytes(1.5, numbered=True, audio=audio))   # 36 frames each
            movie = Path(folder) / "movie.mp4"
            worker.assemble_files([(paths[0], "video/mp4", None, {"in": 10 / 24, "out": 30 / 24}), (paths[1], "video/mp4", None, {"in": 0, "out": 0.5}),
                                   (paths[2], "video/mp4", None)], movie, {"width": 64, "height": 64, "fps": 24})
            frames, duration = probe(movie)
            self.assertEqual(frames, 20 + 12 + 36)
            self.assertAlmostEqual(duration, frames / 24, delta=1 / 24)
            self.assertEqual(source_frames(movie), list(range(10, 30)) + list(range(0, 12)) + list(range(0, 36)))
            data = movie.read_bytes()
            self.assertLess(data.find(b"moov"), data.find(b"mdat"))

    def test_cut_points_between_frames_and_beyond_the_take_land_on_whole_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "src.mp4"
            source.write_bytes(clip_bytes(1.5, numbered=True, audio=True))
            for trim, expected in (({"in": 0.52, "out": 1.3}, list(range(13, 32))),      # 13 (0.5417 s) .. 31 (1.2917 s)
                                   ({"in": 1 / 24, "out": None}, list(range(1, 36))),
                                   ({"in": 0.0416666667, "out": 1.0}, list(range(1, 24))),
                                   ({"in": 20 / 24, "out": 600}, list(range(20, 36)))):
                with self.subTest(trim=trim):
                    movie = Path(folder) / "movie.mp4"
                    worker.assemble_files([(source, "video/mp4", None, trim)], movie, {"width": 64, "height": 64, "fps": 24})
                    self.assertEqual(source_frames(movie), expected)

    def test_a_slower_take_is_cut_by_time_not_by_frame_number(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "slow.mp4"
            source.write_bytes(clip_bytes(3, fps=8, numbered=True))   # 24 frames at 8 fps
            movie = Path(folder) / "movie.mp4"
            worker.assemble_files([(source, "video/mp4", None, {"in": 0.5, "out": 1.5})], movie, {"width": 64, "height": 64, "fps": 24})
            frames = source_frames(movie)
            self.assertEqual(len(frames), 24)
            self.assertEqual((frames[0], frames[-1]), (4, 11))   # source frames 4..11 are 0.5 s .. 1.5 s at 8 fps


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for Story HTTP tests")
class ShotTrimHTTPTests(unittest.TestCase):
    setUp = fixture.StoryHTTPTests.setUp
    tearDown = fixture.StoryHTTPTests.tearDown
    request = fixture.StoryHTTPTests.request
    call = fixture.StoryHTTPTests.call
    ok = fixture.StoryHTTPTests.ok
    prepare = fixture.StoryHTTPTests.prepare
    await_task = fixture.StoryHTTPTests.await_task
    generation_inputs = fixture.StoryHTTPTests.generation_inputs

    def url(self, letter):
        return f"/projects/api/{self.slug}/assets/pa_" + letter * 32

    def take(self, shot, url, column="video"):
        """Write a video URL into the shot's sheet row, as a manual edit or a worker would (column "previs": the previs cell)."""
        slug, row = story.find_row(self.conn, shot["shotId"], "shot")
        index = (next(i for i, header in enumerate(row["headers"]) if re.search(r"previs|blockout", header, re.I))
                 if column == "previs" else story.media_column(row, column))
        story.mutate_row(self.conn, self.me, slug, row["tabKey"], row["rid"], {index: f"[Video]({url})"})
        self.conn.commit()

    def asset(self, data, content_type="video/mp4"):
        identifier = repo.put_asset(self.conn, self.slug, data=data, content_type=content_type, actor_id=self.actor)
        self.conn.commit()
        return f"/projects/api/{self.slug}/assets/{identifier}"

    def trim(self, shot, body):
        return self.ok(f"/shots/{shot['shotId']}/trim", "PUT", body)

    def current(self, shot):
        return self.ok("/shots/" + shot["shotId"])["trim"]

    def test_every_shot_payload_carries_the_untrimmed_default(self):
        first, second = self.prepare()
        listed = {s["shotId"]: s for s in self.ok(f"/episodes/{self.ep}/shots?limit=100")["items"]}
        self.assertTrue(listed and all(s["trim"] == UNTRIMMED for s in listed.values()))
        self.assertEqual(self.ok("/shots/" + first["shotId"])["trim"], UNTRIMMED)
        self.assertEqual(self.ok("/shots/" + first["shotId"], "PATCH", {"description": "Edited"})["trim"], UNTRIMMED)
        scene = self.ok(f"/episodes/{self.ep}/scenes")["items"][0]
        self.assertEqual(self.ok("/scenes/" + scene["sceneId"] + "/shots", "POST", {"description": "Insert"})["trim"], UNTRIMMED)
        self.assertEqual(self.ok("/shot-merges", "POST", {"shotIds": [first["shotId"], second["shotId"]]})["trim"], UNTRIMMED)

    def test_put_trim_validates_persists_and_returns_the_updated_shot(self):
        shot = self.prepare()[0]
        self.take(shot, self.url("a"))
        updated = self.trim(shot, {"in": 10 / 24, "out": 34 / 24})
        self.assertEqual((updated["shotId"], updated["trim"], updated["selectedVideoUrl"]), (shot["shotId"], {"in": 10 / 24, "out": 34 / 24}, self.url("a")))
        self.assertEqual(self.current(shot), {"in": 10 / 24, "out": 34 / 24})
        listed = next(s for s in self.ok(f"/episodes/{self.ep}/shots?limit=100")["items"] if s["shotId"] == shot["shotId"])
        self.assertEqual(listed["trim"], {"in": 10 / 24, "out": 34 / 24})
        self.assertEqual(self.trim(shot, {"in": 10 / 24, "out": 34 / 24}), updated)   # PUT is idempotent
        self.assertEqual(self.trim(shot, {"in": 2, "out": None})["trim"], {"in": 2, "out": None})
        self.assertEqual(self.trim(shot, {"out": 3.5})["trim"], {"in": 0, "out": 3.5})
        self.assertEqual(self.trim(shot, {})["trim"], UNTRIMMED)   # an empty body clears it
        self.assertEqual(self.trim(shot, {"in": 1, "out": 2})["trim"], {"in": 1, "out": 2})
        self.assertEqual(self.trim(shot, {"in": 0, "out": None})["trim"], UNTRIMMED)
        self.assertNotIn("trim", story.shot_meta(self.conn, shot["shotId"]))
        # the rest of the shot's meta is left alone
        self.assertEqual(story.shot_meta(self.conn, shot["shotId"])["sceneId"], shot["sceneId"])

    def test_invalid_trims_and_unknown_routes_are_refused(self):
        shot = self.prepare()[0]
        self.trim(shot, {"in": 1, "out": 2})
        for body in ({"in": -1}, {"in": 5, "out": 5}, {"in": 5, "out": 4}, {"in": 1, "out": 1.04}, {"out": 600.5}, {"in": 700}, {"in": "1"},
                     {"out": "2"}, {"in": True}, {"in": None}, {"out": [2]}):
            code, payload = self.call(f"/shots/{shot['shotId']}/trim", "PUT", body)
            self.assertEqual((code, payload["code"]), (422, "DRAMA_VALIDATION_FAILED"), body)
        for token in (b'{"in": NaN}', b'{"out": Infinity}', b'{"in": -Infinity, "out": 1}', b'{"in": 1e999}'):
            code, payload, _ = self.request(story.BASE + f"/shots/{shot['shotId']}/trim", method="PUT", raw=token, headers={"Content-Type": "application/json"})
            self.assertEqual((code, payload["code"]), (422, "DRAMA_VALIDATION_FAILED"), token)
        self.assertEqual(self.current(shot), {"in": 1, "out": 2})   # nothing refused changed it
        self.assertEqual(self.call(f"/shots/sh_{self.slug}_bmissing/trim", "PUT", {"in": 1})[0], 404)
        asset = self.ok(f"/episodes/{self.ep}/assets")["items"][0]
        self.assertEqual(self.call(f"/assets/{asset['assetId']}/trim", "PUT", {"in": 1})[0], 404)
        self.assertEqual(self.call(f"/shots/{shot['shotId']}/trim", "POST", {"in": 1})[0], 404)

    def test_trimming_needs_a_crew_member_who_can_write(self):
        shot = self.prepare()[0]
        path = f"/shots/{shot['shotId']}/trim"
        self.assertEqual(self.request(story.BASE + path, method="PUT", data={"in": 1}, authenticated=False)[0], 401)
        repo.upsert_member(self.conn, self.actor, "Viewer", "viewer"); self.conn.commit()
        self.assertEqual(self.call(path, "PUT", {"in": 1})[0], 409)
        self.assertEqual(self.current(shot), UNTRIMMED)

    def test_selecting_a_take_always_resets_the_trim(self):
        shot = self.prepare()[0]
        self.take(shot, self.url("a"))
        self.take(shot, self.url("b"))
        takes = {c["url"]: c["videoId"] for c in self.ok(f"/shots/{shot['shotId']}/videos")["items"]}
        self.assertEqual(set(takes), {self.url("a"), self.url("b")})
        self.assertEqual(self.ok("/shots/" + shot["shotId"])["selectedVideoUrl"], self.url("b"))
        self.trim(shot, {"in": 0.5, "out": 2})
        self.ok(f"/shots/{shot['shotId']}/selected-video", "PUT", {"videoId": takes[self.url("a")]})
        self.assertEqual(self.ok("/shots/" + shot["shotId"])["selectedVideoUrl"], self.url("a"))
        self.assertEqual(self.current(shot), UNTRIMMED)
        self.assertNotIn("trim", story.shot_meta(self.conn, shot["shotId"]))
        self.trim(shot, {"in": 0.5, "out": 2})
        self.ok(f"/shots/{shot['shotId']}/selected-video", "PUT", {"videoId": takes[self.url("b")]})
        self.ok(f"/shots/{shot['shotId']}/selected-video", "PUT", {"videoId": takes[self.url("a")]})
        self.assertEqual(self.current(shot), UNTRIMMED)   # coming back to a take does not bring its old cut back
        # picking the take that is already selected is still a pick: the cut starts over
        self.trim(shot, {"in": 1, "out": 2})
        self.ok(f"/shots/{shot['shotId']}/selected-video", "PUT", {"videoId": takes[self.url("a")]})
        self.assertEqual(self.current(shot), UNTRIMMED)
        # a refused pick changes nothing
        self.trim(shot, {"in": 1, "out": 2})
        self.assertEqual(self.call(f"/shots/{shot['shotId']}/selected-video", "PUT", {"videoId": "vd_unknown"})[0], 404)
        self.assertEqual(self.current(shot), {"in": 1, "out": 2})

    def test_a_take_swapped_in_the_sheet_reads_untrimmed_without_any_api_call(self):
        shot = self.prepare()[0]
        self.take(shot, self.url("a"))
        self.trim(shot, {"in": 1, "out": 2})
        self.take(shot, self.url("c"))
        self.assertEqual(self.current(shot), UNTRIMMED)
        self.take(shot, "")
        self.assertEqual(self.current(shot), UNTRIMMED)

    def test_split_keeps_the_cut_on_the_first_half_only(self):
        shot = self.prepare()[0]
        self.take(shot, self.url("a"))
        self.trim(shot, {"in": 1, "out": 2})
        first, second = self.ok(f"/shots/{shot['shotId']}/splits", "POST", {})["shots"]
        self.assertEqual((first["trim"], second["trim"]), ({"in": 1, "out": 2}, UNTRIMMED))
        self.assertNotIn("trim", story.shot_meta(self.conn, second["shotId"]))
        self.assertEqual(story.shot_meta(self.conn, second["shotId"])["sceneId"], shot["sceneId"])

    @unittest.skipUnless(FFMPEG, "FFmpeg and FFprobe needed for real media")
    def test_a_reshoot_that_replaces_the_selected_take_resets_the_trim(self):
        shot = self.prepare()[0]
        old, new = clip_bytes(0.5, color="blue"), clip_bytes(0.5, color="red")
        source = self.generation_inputs(shot["shotId"], old)
        self.assertEqual(self.ok("/shots/" + shot["shotId"])["selectedVideoUrl"], source)
        self.trim(shot, {"in": 0.1, "out": 0.4})
        def render(task, card, values, head):
            return head.upload(task, new, "video/mp4")
        with patch.object(worker, "execute_story_card", side_effect=render):
            done = self.await_task(self.ok(f"/shots/{shot['shotId']}/video-generations", "POST", {"appCode": "2109942725885075458", "modelParams": {"driving_video": source}}))
        self.assertEqual((done["status"], done["result"]["selected"]), ("SUCCEEDED", True), done)
        view = self.ok("/shots/" + shot["shotId"])
        self.assertNotEqual(view["selectedVideoUrl"], source)
        self.assertEqual(view["trim"], UNTRIMMED)
        self.assertNotIn("trim", story.shot_meta(self.conn, shot["shotId"]))

    @unittest.skipUnless(FFMPEG, "FFmpeg and FFprobe needed for real media")
    def test_a_reshoot_is_a_new_take_even_when_the_render_is_byte_identical(self):
        shot = self.prepare()[0]
        raw = clip_bytes(0.5, color="green")
        source = self.generation_inputs(shot["shotId"], raw)
        self.trim(shot, {"in": 0.1, "out": 0.4})
        with patch.object(worker, "execute_story_card", side_effect=lambda task, card, values, head: head.upload(task, raw, "video/mp4")):
            done = self.await_task(self.ok(f"/shots/{shot['shotId']}/video-generations", "POST", {"appCode": "2109942725885075458", "modelParams": {"driving_video": source}}))
        self.assertEqual((done["status"], done["result"]["selected"]), ("SUCCEEDED", True), done)
        self.assertEqual(self.ok("/shots/" + shot["shotId"])["selectedVideoUrl"], source)   # content-addressed: the very same asset
        self.assertEqual(self.current(shot), UNTRIMMED)

    def export(self, **body):
        film = self.await_task(self.ok(f"/episodes/{self.ep}/films", "POST", body))
        self.assertEqual(film["status"], "SUCCEEDED", film)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "film.mp4"
            path.write_bytes(self.request(film["result"]["videoUrl"])[1])
            return probe(path), path.read_bytes(), film

    @unittest.skipUnless(FFMPEG, "FFmpeg and FFprobe needed for real media")
    def test_film_export_cuts_each_take_and_leaves_previs_alone(self):
        one, two = self.prepare()
        scene = self.ok(f"/episodes/{self.ep}/scenes")["items"][1]
        third = self.ok("/scenes/" + scene["sceneId"] + "/shots", "POST", {"description": "Previs only", "shotIndex": "SC02-S09"})
        self.take(one, self.asset(clip_bytes(3, color="blue", audio=True)))       # 72 frames
        self.take(two, self.asset(clip_bytes(2, color="red")))                    # 48 frames, no audio
        self.take(third, self.asset(clip_bytes(1, color="green")), column="previs")  # 24 frames of previs
        self.assertEqual(self.ok("/shots/" + third["shotId"])["selectedVideoUrl"], None)

        (frames, _), _, _ = self.export()
        self.assertEqual(frames, 72 + 48)

        self.trim(one, {"in": 0.5, "out": 1.5})           # 24 frames
        self.trim(two, {"in": 0.25})                       # 1.75 s of 2 s -> 42 frames
        self.trim(third, {"in": 0.25, "out": 0.5})         # previs stands in for a missing take: never cut
        (frames, duration), data, film = self.export()
        self.assertEqual(frames, 24 + 42)
        self.assertAlmostEqual(duration, frames / 24, delta=1 / 24)
        self.assertLess(data.find(b"moov"), data.find(b"mdat"))
        (frames, duration), _, _ = self.export(fillPrevis=True)
        self.assertEqual(frames, 24 + 42 + 24)
        self.assertAlmostEqual(duration, frames / 24, delta=1 / 24)

        task = story.record(self.conn, film["taskId"])["_job"]
        self.assertEqual(task["trims"], [{"in": 0.5, "out": 1.5}, {"in": 0.25, "out": None}])
        self.assertEqual(len(task["trims"]), len(task["urls"]))

        self.trim(one, {})
        self.trim(two, {})
        (frames, _), _, _ = self.export()
        self.assertEqual(frames, 72 + 48)

    @unittest.skipUnless(FFMPEG, "FFmpeg and FFprobe needed for real media")
    def test_film_export_cuts_on_the_frame_the_trim_names(self):
        one, two = self.prepare()
        self.take(one, self.asset(clip_bytes(1.5, numbered=True, audio=True)))
        self.take(two, self.asset(clip_bytes(1.5, numbered=True)))
        self.trim(one, {"in": 10 / 24, "out": 30 / 24})
        self.trim(two, {"in": 6 / 24})
        (frames, duration), data, _ = self.export()
        self.assertEqual(frames, 20 + 30)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "film.mp4"
            path.write_bytes(data)
            self.assertEqual(source_frames(path), list(range(10, 30)) + list(range(6, 36)))

    @unittest.skipUnless(FFMPEG, "FFmpeg and FFprobe needed for real media")
    def test_a_trim_beyond_the_take_fails_the_export_with_a_readable_error(self):
        one, two = self.prepare()
        self.take(one, self.asset(clip_bytes(1, color="blue")))
        self.take(two, self.asset(clip_bytes(1, color="red")))
        self.trim(two, {"in": 5, "out": 6})
        film = self.await_task(self.ok(f"/episodes/{self.ep}/films", "POST", {}))
        self.assertEqual(film["status"], "FAILED", film)
        self.assertIn("Clip 2 is trimmed to start at 5.00s", film["error"]["message"])
        self.trim(two, {})
        self.assertEqual(self.export()[0][0], 24 + 24)

    def test_a_film_without_trims_exports_every_clip_whole(self):
        one, two = self.prepare()
        self.take(one, self.url("a"))
        self.take(two, self.url("b"))
        with patch.object(story._POOL, "submit") as submit:
            task = self.ok(f"/episodes/{self.ep}/films", "POST", {})
            submit.assert_called_once()
        job = story.record(self.conn, task["taskId"])["_job"]
        self.assertEqual((job["urls"], job["trims"], job["config"]), ([self.url("a"), self.url("b")], [None, None], {}))
        self.assertEqual(story_trim.film_rows(job), [{"row_id": "0", "cells": [self.url("a")]}, {"row_id": "1", "cells": [self.url("b")]}])
