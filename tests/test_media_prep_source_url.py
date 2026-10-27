"""extract_frame may cut its frame from a named video of the task's own project (config.source_url)."""
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import ANY, Mock

from project_assistant.studio import media_prep, runtime

SLUG = 'demo'
ASSET = lambda n, slug=SLUG: f'/projects/api/{slug}/assets/pa_' + format(n, '032x')
ROW_VIDEO, OTHER_VIDEO, OUTPUT = ASSET(5), ASSET(6), ASSET(9)
HAVE_FFMPEG = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def studio_task(slug=SLUG, **extra):
    """One shot row whose 'Source Video' cell is ROW_VIDEO."""
    headers = ['Shot', 'Source Video']
    row = {'row_id': 'shot-2', 'tab_key': 'cinema-studio', 'table_id': 'shots', 'cells': ['S02', ROW_VIDEO]}
    task = {'id': 'task', 'row_id': 'shot-2', 'input': {
        'rows': [row], 'target': {'tab_key': 'cinema-studio', 'table_id': 'shots'},
        'tabs': [{'tab_key': 'cinema-studio', 'tables': [{'table_id': 'shots', 'headers': headers}]}]}}
    if slug is not None:
        task['project_slug'] = slug
    return dict(task, **extra)


def make_head(assets):
    """A head that serves `assets` ({url: (bytes, mime)}) and records what was uploaded."""
    head = Mock()
    head.lease_lost.return_value = False
    head.asset.side_effect = lambda task, url: assets[url]
    uploaded = {}

    def upload(task, raw, mime, filename):
        uploaded.update(raw=raw, mime=mime, filename=filename)
        return {'asset_url': OUTPUT, 'content_type': mime}
    head.upload.side_effect = upload
    head.uploaded = uploaded
    return head


class SourceUrlRejectionTests(unittest.TestCase):
    """Everything here is refused before a byte is fetched, so no FFmpeg is needed."""

    def refuse(self, source_url, pattern, *, task=None, mode='extract_frame', assets=None):
        head = make_head(assets if assets is not None else {ROW_VIDEO: (b'row', 'video/mp4'), OTHER_VIDEO: (b'other', 'video/mp4')})
        with self.assertRaisesRegex(runtime.WorkerError, pattern):
            media_prep.ffmpeg(task or studio_task(), {'mode': mode, 'timestamp_sec': 0, 'source_url': source_url}, head)
        head.upload.assert_not_called()
        return head

    def test_external_urls_are_refused_without_any_fetch(self):
        asset_path = OTHER_VIDEO
        for url in ('http://example.com/clip.mp4', 'https://example.com' + asset_path, 'HTTP://localhost' + asset_path,
                    '//example.com' + asset_path, 'file:///etc/passwd', 'ftp://example.com/a.mp4', 'example.com/clip.mp4',
                    'projects/api/demo/assets/pa_' + '0' * 32, '/other/api/demo/assets/pa_' + '0' * 32):
            with self.subTest(url=url):
                self.refuse(url, 'external').asset.assert_not_called()

    def test_another_projects_asset_is_refused(self):
        head = self.refuse(ASSET(6, slug='other'), 'another project')
        head.asset.assert_not_called()
        # The comparison is against the task's own project, not a fixed name.
        head = make_head({OTHER_VIDEO: (b'x', 'video/mp4')})
        with self.assertRaisesRegex(runtime.WorkerError, 'another project'):
            media_prep.ffmpeg(studio_task(slug='other'), {'mode': 'extract_frame', 'source_url': OTHER_VIDEO}, head)
        head.asset.assert_not_called()

    def test_malformed_asset_ids_and_paths_are_refused(self):
        valid = 'pa_' + '0' * 32
        for url in (f'/projects/api/{SLUG}/assets/pa_123', f'/projects/api/{SLUG}/assets/pa_' + 'g' * 32, f'/projects/api/{SLUG}/assets/pa_' + 'A' * 32,
                    f'/projects/api/{SLUG}/assets/' + '0' * 32, f'/projects/api/{SLUG}/assets/{valid}0', f'/projects/api/{SLUG}/assets/{valid}/',
                    f'/projects/api/{SLUG}/assets/{valid}/extra', f'/projects/api/{SLUG}/assets/', f'/projects/api/{SLUG}/assets',
                    f'/projects/api/{SLUG}/{valid}', f'/projects/api/assets/{valid}', '/projects/api/', '/projects/api/demo',
                    f'/projects/api//assets/{valid}', f'/projects/api/{SLUG}/files/{valid}', f'/projects/api/{SLUG}/assets/{valid}\n'):
            with self.subTest(url=url):
                self.refuse(url, 'source_url').asset.assert_not_called()

    def test_path_escapes_queries_and_encodings_are_refused(self):
        valid = 'pa_' + '0' * 32
        for url in (f'/projects/api/{SLUG}/assets/../../other/assets/{valid}', f'/projects/api/{SLUG}/../other/assets/{valid}',
                    f'/projects/api/../assets/{valid}', f'/projects/api/{SLUG}/assets/./{valid}', f'/projects/api/{SLUG}/assets/{valid}/..',
                    f'/projects/api/{SLUG}/assets/{valid}?download=1', f'/projects/api/{SLUG}/assets/{valid}#t=2',
                    f'/projects/api/{SLUG}/assets/%2e%2e/{valid}', f'/projects/api/{SLUG}/assets/{valid[:-2]}%30%30',
                    f'/projects/api/{SLUG}\\assets\\{valid}', f'/projects/api/{SLUG}/assets/{valid} ', f' /projects/api/{SLUG}/assets/{valid}'):
            with self.subTest(url=url):
                self.refuse(url, 'source_url').asset.assert_not_called()

    def test_non_string_empty_and_unverifiable_values_are_refused(self):
        for value in ('', 0, False, 42, ['a'], {'url': OTHER_VIDEO}, b'/projects/api/demo/assets/pa_' + b'0' * 32):
            with self.subTest(value=value):
                self.refuse(value, 'must be a project asset URL string').asset.assert_not_called()
        for task in (studio_task(slug=None), studio_task(slug=''), studio_task(slug=None, project_slug=7)):
            with self.subTest(project_slug=task.get('project_slug')):
                self.refuse(OTHER_VIDEO, 'project_slug', task=task).asset.assert_not_called()

    def test_source_url_is_only_for_extract_frame(self):
        for mode in ('frame_sheet', 'motion_structure', 'ingredients_sheet', 'time_strata'):
            with self.subTest(mode=mode):
                self.refuse(OTHER_VIDEO, 'only supported by the extract_frame mode', mode=mode).asset.assert_not_called()

    def test_only_a_video_within_64_mb_is_accepted(self):
        for blob, pattern in (((b'png', 'image/png'), 'video asset'), ((b'wav', 'audio/wav'), 'video asset'),
                              ((b'x', ''), 'video asset'), ((b'', 'video/mp4'), 'empty'),
                              ((bytes(runtime.MAX_MEDIA + 1), 'video/mp4'), '64 MB')):
            with self.subTest(mime=blob[1], size=len(blob[0])):
                head = self.refuse(OTHER_VIDEO, pattern, assets={ROW_VIDEO: (b'row', 'video/mp4'), OTHER_VIDEO: blob})
                head.asset.assert_called_once_with(ANY, OTHER_VIDEO)  # fetched through the head, nothing from the row

    def test_none_means_absent(self):
        head = make_head({ROW_VIDEO: (b'not a video', 'video/mp4')})
        with self.assertRaises(runtime.WorkerError) as caught:  # fails later, in FFprobe, on the row's own video
            media_prep.ffmpeg(studio_task(), {'mode': 'extract_frame', 'source_url': None}, head)
        self.assertNotIn('source_url', str(caught.exception))
        head.asset.assert_called_once_with(ANY, ROW_VIDEO)


@unittest.skipUnless(HAVE_FFMPEG, 'FFmpeg and FFprobe are required')
class SourceUrlExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()

        def clip(name, colour, size, seconds):
            path = Path(cls.folder.name) / name
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
                            '-i', f'color=c={colour}:size={size}:rate=12:duration={seconds}',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True, capture_output=True)
            return path.read_bytes()
        cls.row_clip = clip('row.mp4', 'red', '64x48', 1)       # the task's own row: 1 s, red, 64x48
        cls.other_clip = clip('other.mp4', 'blue', '96x64', 2)  # another shot's take: 2 s, blue, 96x64

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def head(self):
        return make_head({ROW_VIDEO: (self.row_clip, 'video/mp4'), OTHER_VIDEO: (self.other_clip, 'video/mp4')})

    def frame(self, head):
        from PIL import Image
        self.assertEqual((head.uploaded['mime'], head.uploaded['filename']), ('image/png', 'first_frame.png'))
        with Image.open(io.BytesIO(head.uploaded['raw'])) as image:
            self.assertEqual(image.format, 'PNG')
            return image.size, image.convert('RGB').getpixel((image.width // 2, image.height // 2))

    def test_without_source_url_the_rows_own_video_is_used_and_the_result_is_unchanged(self):
        for config in ({'mode': 'extract_frame', 'timestamp_sec': 0.5}, {'mode': 'extract_frame', 'timestamp_sec': 0.5, 'source_url': None}):
            with self.subTest(config=config):
                head = self.head()
                result = media_prep.ffmpeg(studio_task(), config, head)
                head.asset.assert_called_once_with(ANY, ROW_VIDEO)
                size, (red, green, blue) = self.frame(head)
                self.assertEqual(size, (64, 48))
                self.assertGreater(red, 150)
                self.assertLess(blue, 100)
                self.assertEqual((result['reference_role'], result['text'], result['asset_id']), ('first_frame', OUTPUT, 'pa_' + format(9, '032x')))
                self.assertNotIn('source_url', result)
                self.assertNotIn('timestamp_sec', result)

    def test_a_valid_source_url_replaces_the_rows_video(self):
        head = self.head()
        result = media_prep.ffmpeg(studio_task(), {'mode': 'extract_frame', 'timestamp_sec': 1.5, 'source_url': OTHER_VIDEO}, head)
        # 1.5 s is past the row's own 1 s video, and inside the named 2 s one.
        head.asset.assert_called_once_with(ANY, OTHER_VIDEO)
        size, (red, green, blue) = self.frame(head)
        self.assertEqual(size, (96, 64))
        self.assertGreater(blue, 150)
        self.assertLess(red, 100)
        self.assertEqual((result['reference_role'], result['text'], result['content_type']), ('first_frame', OUTPUT, 'image/png'))
        self.assertEqual(result['asset_id'], 'pa_' + format(9, '032x'))
        self.assertEqual((result['source_url'], result['timestamp_sec']), (OTHER_VIDEO, 1.5))

    def test_the_source_may_be_the_rows_own_asset_url(self):
        head = self.head()
        result = media_prep.ffmpeg(studio_task(), {'mode': 'extract_frame', 'timestamp_sec': 0, 'source_url': ROW_VIDEO}, head)
        self.assertEqual(self.frame(head)[0], (64, 48))
        self.assertEqual((result['source_url'], result['timestamp_sec']), (ROW_VIDEO, 0.0))

    def test_snap_to_grid_still_applies_to_the_named_source(self):
        head = self.head()
        media_prep.ffmpeg(studio_task(), {'mode': 'extract_frame', 'timestamp_sec': 0.5, 'source_url': OTHER_VIDEO, 'grid_size': 32,
                                          'width': 200, 'height': 130}, head)
        self.assertEqual(self.frame(head)[0], (192, 128))  # 200x130 snapped to the 32 px grid

    def test_timestamp_range_is_checked_against_the_named_video(self):
        for stamp in (-0.1, 3, 2.5, float('inf'), float('nan')):
            with self.subTest(timestamp_sec=stamp):
                head = self.head()
                with self.assertRaisesRegex(runtime.WorkerError, 'timestamp'):
                    media_prep.ffmpeg(studio_task(), {'mode': 'extract_frame', 'timestamp_sec': stamp, 'source_url': OTHER_VIDEO}, head)
                head.upload.assert_not_called()
        # The same 1.5 s is out of range for the row's own 1 s video when no source_url is given.
        head = self.head()
        with self.assertRaisesRegex(runtime.WorkerError, 'timestamp'):
            media_prep.ffmpeg(studio_task(), {'mode': 'extract_frame', 'timestamp_sec': 1.5}, head)
        head.upload.assert_not_called()

    def test_a_file_that_is_not_a_video_fails_without_uploading(self):
        head = make_head({ROW_VIDEO: (self.row_clip, 'video/mp4'), OTHER_VIDEO: (b'definitely not a video', 'video/mp4')})
        with self.assertRaisesRegex(runtime.WorkerError, 'FFprobe'):
            media_prep.ffmpeg(studio_task(), {'mode': 'extract_frame', 'timestamp_sec': 0, 'source_url': OTHER_VIDEO}, head)
        head.upload.assert_not_called()


if __name__ == '__main__':
    unittest.main()
