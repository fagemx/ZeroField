"""SPEC_19 R15/R16: @S02.end / @S02.start syntax, resolution into frozen snapshots, staleness and the worker's frame cut.

No database: resolution works on shot views as story_openapi.shots returns them. The frame cut needs FFmpeg.
"""
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import ANY, Mock

from project_assistant.studio import runtime
from project_docs import story_openapi as story, story_take_refs as take_refs, writing_impact

SLUG = 'demo'
URL = lambda n: f'/projects/api/{SLUG}/assets/pa_' + format(n, '032x')
HAVE_FFMPEG = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def shot(index, *, video=None, status='', trim=None, origin=None, lineage=None, rid=None):
    """A shot view with the fields resolution reads."""
    view = {'shotId': f'sh_{SLUG}_b{rid or index.lower()}', 'shotIndex': index, 'tabKey': 'cinema-studio', 'description': '',
            'selectedVideoUrl': video, 'reviewStatus': status, 'trim': trim or {'in': 0, 'out': None}}
    if origin:
        view['storyOrigin'] = origin
    if lineage:
        view['storyLineage'] = lineage
    return view


def segment(index, count=3, beat='beat-a'):
    return {'mapping': 'exact', 'beatKeys': [beat], 'recipes': [{'beatKeys': [beat], 'mode': 'cinematic', 'segmentIndex': index, 'segmentCount': count}]}


class SyntaxTests(unittest.TestCase):
    def codes(self, text):
        return [(code, edge) for _, _, code, edge in take_refs.tokens(text)]

    def test_shot_tags_match_and_asset_codes_never_do(self):
        self.assertEqual(self.codes('[0-1s] @S02.end then @s3.start, @12.end and @3A.end.'),
                         [('S02', 'end'), ('s3', 'start'), ('12', 'end'), ('3A', 'end')])
        # Asset codes always have a hyphen and never .start/.end (SPEC_19 4.5).
        for text in ('@CAST-01:night walks.', '@CAST-01#night walks.', '@SET-01 at dusk.', '@PROP-07 glints.', '@CAST-01.end',
                     '@SET-01.start', '@LOC-02:rain', '@STYLE-01'):
            with self.subTest(text=text):
                self.assertEqual(self.codes(text), [])

    def test_glued_wrong_case_and_overlong_forms_are_not_tags(self):
        for text in ('mail@S02.end', 'x-@S02.end', '!-@S02.end', ':@S02.end', '#@S02.end', '@@S02.end', '_@S02.end',
                     '@S02.endgame', '@S02.END', '@S02.Start', '@S1234.end', '@SC01-S02.end', '@S02end', '@S02.', '@.end'):
            with self.subTest(text=text):
                self.assertEqual(self.codes(text), [])

    def test_cjk_neighbours_follow_the_editors_ascii_rule(self):
        # \w and \b are ASCII, as in JavaScript: the server and the prompt editor agree on these tags.
        self.assertEqual(self.codes('接續@S02.end的動作，參考@S03.start。'), [('S02', 'end'), ('S03', 'start')])


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.s01 = shot('S01', video=URL(1), status='Approved', trim={'in': 0.4, 'out': 3.8})
        self.s02 = shot('S02', video=URL(2))
        self.s03 = shot('S03')
        self.shots = [self.s01, self.s02, self.s03]

    def error(self, text, shots=None, uses=None, *, this=None):
        with self.assertRaises(story.StoryError) as caught:
            take_refs.resolve(text, self.shots if shots is None else shots, this or self.s03, uses)
        return caught.exception

    def test_an_adopted_take_is_quoted_at_its_cut_points(self):
        end, start = take_refs.resolve('Continue @S01.end; match @S01.start.', self.shots, self.s03)
        self.assertEqual(end, {'shotId': self.s01['shotId'], 'shotIndex': 'S01', 'edge': 'end', 'takeUrl': URL(1), 'at': 3.8,
                               'frameUrl': None, 'use': 'reference', 'adopted': True, 'lastFrameAt': None})
        self.assertEqual((start['edge'], start['at'], start['takeUrl'], start['adopted']), ('start', 0.4, URL(1), True))

    def test_an_unadopted_shot_is_quoted_with_its_newest_take(self):
        [ref] = take_refs.resolve('@S02.end', self.shots, self.s03)
        self.assertEqual((ref['takeUrl'], ref['adopted']), (URL(2), False))
        # Untrimmed: the out point is the take's last frame, known once the worker has probed the take.
        self.assertIsNone(ref['at'])
        self.assertEqual(take_refs.resolve('@S02.start', self.shots, self.s03)[0]['at'], 0.0)

    def test_the_shot_label_is_matched_without_case_and_each_tag_once(self):
        found = take_refs.resolve('@s01.end then @S01.end again', self.shots, self.s03)
        self.assertEqual([(r['shotIndex'], r['edge']) for r in found], [('S01', 'end')])

    def test_asset_codes_need_no_shot(self):
        self.assertEqual(take_refs.resolve('@CAST-01:night walks into @SET-01. @CAST-01#night turns.', [], self.s03), [])

    def test_unknown_tags_are_400_and_listed(self):
        error = self.error('@S99.end then @S01.end and @s98.start')
        self.assertEqual((error.status, error.code), (400, 'DRAMA_VALIDATION_FAILED'))
        self.assertEqual(error.details, {'unknownTakeRefs': ['@S99.end', '@s98.start']})
        self.assertIn('@S99.end', str(error))
        error = self.error('@S01.end', shots=self.shots + [shot('s01', video=URL(9), rid='other')])
        self.assertEqual((error.status, error.details), (400, {'unknownTakeRefs': [], 'ambiguousTakeRefs': ['@S01.end']}))

    def test_a_shot_without_any_take_is_409(self):
        error = self.error('@S03.end', this=self.s02)
        self.assertEqual((error.status, error.code, error.details), (409, 'DRAMA_STAGE_PRECONDITION', {'takeRefsWithoutTake': ['@S03.end']}))

    def test_a_shot_cannot_quote_itself(self):
        error = self.error('@S01.end', this=self.s01)
        self.assertEqual((error.status, error.code), (422, 'DRAMA_VALIDATION_FAILED'))

    def test_explicit_uses_and_their_validation(self):
        found = take_refs.resolve('@S01.end, @S02.start', self.shots, self.s03, {'s01.end': 'first_frame', '@S02.start': 'reference'})
        self.assertEqual([r['use'] for r in found], ['first_frame', 'reference'])
        for uses in ([], 'first_frame', {'S01.end': 'first'}, {'S01.end': None}, {'S01.END': 'reference'}, {'S01': 'reference'},
                     {'S04.end': 'reference'}, {'S01.end': 'first_frame', 'S02.start': 'first_frame'},
                     {'S01.end': 'reference', 's01.end': 'reference'}, {7: 'reference'}):
            with self.subTest(uses=uses):
                self.assertEqual(self.error('@S01.end, @S02.start', uses=uses).status, 422)
        # Without a tag in the prompt, takeRefUses can name nothing.
        self.assertEqual(take_refs.resolve('No tags.', [], self.s03, {}), [])
        self.assertEqual(self.error('No tags.', shots=[], uses={'S01.end': 'reference'}).status, 422)

    def test_at_most_six_takes_per_prompt(self):
        shots = [shot(f'S{i:02d}', video=URL(i)) for i in range(1, 9)]
        text = ' '.join(f'@S{i:02d}.end' for i in range(1, 8))
        with self.assertRaises(story.StoryError) as caught:
            take_refs.resolve(text, shots, shot('S20'))
        self.assertEqual(caught.exception.status, 422)

    def test_default_use_is_first_frame_only_inside_one_continuous_action(self):
        before = shot('S04', video=URL(4), origin=segment(0), rid='s04')
        after = shot('S05', video=URL(5), origin=segment(1), rid='s05')
        use = lambda text, this, *others: take_refs.resolve(text, [before, after, this, *others], this)[0]['use']
        # Adjacent segments of one screenplay beat: the next shot continues from the previous one's last frame.
        self.assertEqual(use('@S04.end', after), 'first_frame')
        self.assertEqual(use('@S04.start', after), 'reference')
        later = shot('S06', video=URL(6), origin=segment(2), rid='s06')
        self.assertEqual(use('@S04.end', later), 'reference')  # not adjacent
        other_beat = shot('S07', origin=segment(1, beat='beat-b'), rid='s07')
        self.assertEqual(use('@S04.end', other_beat), 'reference')
        recount = shot('S08', origin=segment(1, count=4), rid='s08')
        self.assertEqual(use('@S04.end', recount), 'reference')  # the beat was cut differently
        loose = shot('S09', origin={**segment(1), 'mapping': 'scene_only'}, rid='s09')
        self.assertEqual(use('@S04.end', loose), 'reference')
        # The second half of a split continues the first half.
        half = shot('S04B', lineage={'operation': 'split', 'fromShotIds': [before['shotId']]}, rid='s04b')
        self.assertEqual(use('@S04.end', half), 'first_frame')
        self.assertEqual(use('@S05.end', half), 'reference')
        # No evidence of one action: reference.
        self.assertEqual(take_refs.resolve('@S01.end', self.shots, self.s03)[0]['use'], 'reference')


class StaleTests(unittest.TestCase):
    def snapshot(self, edge='end', at=3.8, last=3.958333):
        return {'shotId': 'sh_demo_bs01', 'shotIndex': 'S01', 'edge': edge, 'takeUrl': URL(1), 'at': at, 'frameUrl': URL(50),
                'use': 'first_frame', 'adopted': True, 'lastFrameAt': last}

    def test_nothing_changed_is_not_stale(self):
        self.assertFalse(take_refs.is_stale(self.snapshot(), URL(1), {'in': 0.4, 'out': 3.8}))
        self.assertFalse(take_refs.is_stale(self.snapshot(at=3.958333), URL(1), {'in': 0, 'out': None}))  # untrimmed
        self.assertFalse(take_refs.is_stale(self.snapshot('start', 0.4), URL(1), {'in': 0.4, 'out': 2}))

    def test_another_take_is_stale(self):
        self.assertTrue(take_refs.is_stale(self.snapshot(), URL(2), {'in': 0.4, 'out': 3.8}))
        self.assertTrue(take_refs.is_stale(self.snapshot(), None, None))  # the shot or its take is gone

    def test_a_moved_cut_point_is_stale(self):
        self.assertTrue(take_refs.is_stale(self.snapshot(), URL(1), {'in': 0.4, 'out': 3.5}))
        self.assertTrue(take_refs.is_stale(self.snapshot(), URL(1), {'in': 0, 'out': None}))  # trim removed: the last frame
        self.assertTrue(take_refs.is_stale(self.snapshot(at=3.958333), URL(1), {'in': 0, 'out': 3}))
        self.assertTrue(take_refs.is_stale(self.snapshot('start', 0.4), URL(1), {'in': 0.6, 'out': None}))
        # The in point does not move the out point, and the other way round.
        self.assertFalse(take_refs.is_stale(self.snapshot(), URL(1), {'in': 1.0, 'out': 3.8}))
        self.assertFalse(take_refs.is_stale(self.snapshot('start', 0.4), URL(1), {'in': 0.4, 'out': None}))
        # An out point past the take's end still cuts at its last frame: the same frame.
        self.assertFalse(take_refs.is_stale(self.snapshot(at=3.958333), URL(1), {'in': 0, 'out': 9}))

    def test_edge_seconds(self):
        self.assertEqual(take_refs.edge_seconds('end', {'in': 0, 'out': 3.8}), 3.8)
        self.assertEqual(take_refs.edge_seconds('end', {'in': 0, 'out': 9}, 3.958333), 3.958333)
        self.assertEqual(take_refs.edge_seconds('end', {'in': 0, 'out': None}, 3.958333), 3.958333)
        self.assertIsNone(take_refs.edge_seconds('end', {'in': 0, 'out': None}))
        self.assertEqual(take_refs.edge_seconds('start', {'in': 0.4, 'out': None}), 0.4)
        self.assertEqual(take_refs.edge_seconds('start', None), 0.0)


class SentenceTests(unittest.TestCase):
    FIRST = {'shotIndex': 'S01', 'edge': 'end', 'use': 'first_frame', 'frameUrl': URL(50)}
    MATCH = {'shotIndex': 'S03', 'edge': 'start', 'use': 'reference', 'frameUrl': URL(51)}

    def test_each_use_and_edge_has_its_sentence(self):
        self.assertEqual(take_refs.describe(self.FIRST), 'Continue directly from the final frame of shot S01.')
        self.assertEqual(take_refs.describe({**self.FIRST, 'edge': 'start'}), 'Begin from the opening frame of shot S01.')
        self.assertEqual(take_refs.describe(self.MATCH), 'Match the setting and lighting of shot S03.')

    def test_tags_become_sentences_where_they_stand(self):
        text = '[0-1s] @S01.end @CAST-01 turns.\n[1-3s] @s03.start, CAST-01 walks. @S09.end stays.'
        self.assertEqual(take_refs.expand(text, [self.FIRST, self.MATCH]),
                         '[0-1s] Continue directly from the final frame of shot S01. @CAST-01 turns.\n'
                         '[1-3s] Match the setting and lighting of shot S03, CAST-01 walks. @S09.end stays.')
        self.assertEqual(take_refs.expand('接續@S01.end的動作', [self.FIRST]), '接續 Continue directly from the final frame of shot S01. 的動作')
        self.assertEqual(take_refs.expand('（@S01.end）', [self.FIRST]), '（Continue directly from the final frame of shot S01）')
        self.assertEqual(take_refs.expand('@S01.end', []), '@S01.end')


class ProvenanceTests(unittest.TestCase):
    BASE = {'schemaVersion': 1, 'shotId': 'sh_demo_bs03', 'originKnown': True}
    REF = {'shotId': 'sh_demo_bs01', 'edge': 'end', 'takeUrl': URL(1), 'at': 3.8}

    def test_take_refs_are_stored_only_when_a_take_was_quoted(self):
        self.assertEqual(writing_impact.with_take_refs(self.BASE, []), self.BASE)
        self.assertNotIn('takeRefs', writing_impact.with_take_refs(self.BASE, []))
        quoted = writing_impact.with_take_refs(self.BASE, [self.REF])
        self.assertEqual(quoted, {**self.BASE, 'takeRefs': [self.REF]})
        self.assertEqual(writing_impact.with_take_refs(quoted, []), self.BASE)
        self.assertIsNone(writing_impact.with_take_refs(None, []))

    def test_equal_bytes_with_different_quotes_have_no_single_history(self):
        record = lambda provenance: {'url': URL(9), 'storyProvenance': provenance}
        quoted = {**self.BASE, 'takeRefs': [self.REF]}
        other = {**self.BASE, 'takeRefs': [{**self.REF, 'at': 3.5}]}
        self.assertEqual(writing_impact.candidate_evidence([record(quoted), record(dict(quoted))], URL(9)), quoted)
        self.assertIsNone(writing_impact.candidate_evidence([record(quoted), record(other)], URL(9)))
        self.assertIsNone(writing_impact.candidate_evidence([record(quoted), record(self.BASE)], URL(9)))
        # A provenance from before take references quoted nothing, like an empty list.
        self.assertEqual(writing_impact.candidate_evidence([record(self.BASE), record({**self.BASE, 'takeRefs': []})], URL(9)), self.BASE)


class CompilerInputTests(unittest.TestCase):
    def test_worker_input_carries_only_prepared_frames(self):
        source = {'rows': []}
        self.assertIs(take_refs.worker_input(source, []), source)
        ref = {'shotId': 'sh_demo_bs01', 'shotIndex': 'S01', 'edge': 'end', 'takeUrl': URL(1), 'at': 1, 'frameUrl': URL(50),
               'use': 'reference', 'adopted': True, 'lastFrameAt': 1}
        self.assertEqual(take_refs.worker_input(source, [ref]),
                         {'rows': [], 'take_refs': [{'shotIndex': 'S01', 'edge': 'end', 'use': 'reference', 'frameUrl': URL(50)}]})
        self.assertEqual(source, {'rows': []})

    def test_malformed_compiler_refs_are_refused(self):
        good = {'shotIndex': 'S01', 'edge': 'end', 'use': 'reference', 'frameUrl': URL(50)}
        self.assertEqual(take_refs.compiler_refs({'take_refs': [good]}), [good])
        for bad in ([{**good, 'frameUrl': 'https://example.com/a.png'}], [{**good, 'frameUrl': None}], [{**good, 'use': 'driving'}],
                    [{**good, 'edge': 'middle'}], [{**good, 'shotIndex': 2}], ['S01.end'], 'S01.end',
                    [{**good, 'use': 'first_frame'}, {**good, 'use': 'first_frame', 'frameUrl': URL(51)}], [good] * 7):
            with self.subTest(bad=bad), self.assertRaises(runtime.WorkerError):
                take_refs.compiler_refs({'take_refs': bad})


def make_head(assets):
    head = Mock()
    head.lease_lost.return_value = False
    head.asset.side_effect = lambda task, url: assets[url]
    uploads = []

    def upload(task, raw, mime, filename=None):
        uploads.append({'task': task, 'raw': raw, 'mime': mime, 'filename': filename})
        return {'asset_url': URL(70 + len(uploads)), 'content_type': mime}
    head.upload.side_effect = upload
    head.uploads = uploads
    return head


@unittest.skipUnless(HAVE_FFMPEG, 'FFmpeg and FFprobe are required')
class FrameCutTests(unittest.TestCase):
    """The worker cuts the quoted frame from the take with extract_frame's source_url and records where it came from."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'take.mp4'
            # 1 s at 12 fps: six red frames, then six blue ones; the last frame is at 11/12 s.
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-filter_complex',
                            'color=c=red:s=32x32:r=12:d=0.5[a];color=c=blue:s=32x32:r=12:d=0.5[b];[a][b]concat=n=2:v=1:a=0',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True, capture_output=True)
            cls.take = path.read_bytes()

    def snapshot(self, edge='end', at=None, **extra):
        return {'shotId': 'sh_demo_bs01', 'shotIndex': 'S01', 'edge': edge, 'takeUrl': URL(1), 'at': at, 'frameUrl': None,
                'use': 'first_frame', 'adopted': False, 'lastFrameAt': None, **extra}

    def colour(self, raw):
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.format, 'PNG')
            red, _, blue = image.convert('RGB').getpixel((16, 16))
        return 'red' if red > blue else 'blue'

    def test_an_untrimmed_end_is_the_takes_last_frame_cut_once(self):
        head = make_head({URL(1): (self.take, 'video/mp4')})
        operations = []
        [ref] = take_refs.prepare_frames('tk_1', SLUG, [self.snapshot()], head,
                                         operation=lambda key, action: operations.append(key) or action())
        self.assertEqual(ref['lastFrameAt'], 0.916666)  # 11/12 s, rounded down to the microsecond
        self.assertEqual((ref['at'], ref['frameUrl']), (0.916666, URL(71)))
        self.assertEqual(operations, ['takeref:0'])
        head.asset.assert_called_once_with(ANY, URL(1))  # one read for the probe and the cut
        [upload] = head.uploads
        self.assertEqual((upload['mime'], upload['filename'], upload['task']['project_slug']), ('image/png', 'first_frame.png', SLUG))
        self.assertEqual(self.colour(upload['raw']), 'blue')

    def test_cut_points_start_and_a_kept_frame(self):
        head = make_head({URL(1): (self.take, 'video/mp4')})
        out, start, past, kept = take_refs.prepare_frames('tk_2', SLUG, [
            self.snapshot(at=0.25), self.snapshot('start', 0.0), self.snapshot(at=5.0),
            self.snapshot(at=0.5, frameUrl=URL(60), lastFrameAt=0.916666)], head)
        self.assertEqual((out['at'], start['at'], past['at']), (0.25, 0.0, 0.916666))  # an out point past the end: the last frame
        self.assertEqual([self.colour(u['raw']) for u in head.uploads], ['red', 'red', 'blue'])
        self.assertEqual(kept, self.snapshot(at=0.5, frameUrl=URL(60), lastFrameAt=0.916666))  # a retry keeps its frozen frame
        self.assertEqual(head.asset.call_count, 3)

    def test_a_quoted_take_that_is_not_a_video_fails_before_any_upload(self):
        head = make_head({URL(1): (b'png', 'image/png')})
        with self.assertRaisesRegex(runtime.WorkerError, 'not a video'):
            take_refs.prepare_frames('tk_3', SLUG, [self.snapshot()], head)
        head.upload.assert_not_called()
        # extract_frame still refuses a take of another production: it checks the URL against the task's project_slug.
        head = make_head({URL(1): (self.take, 'video/mp4')})
        with self.assertRaisesRegex(runtime.WorkerError, 'another project'):
            take_refs.prepare_frames('tk_4', 'elsewhere', [self.snapshot()], head)
        head.upload.assert_not_called()


if __name__ == '__main__':
    unittest.main()
