from __future__ import annotations

import os
import shutil
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Code'))

from pylossless.video import (
    build_ffmpeg_command,
    build_scale_filter,
    find_ffmpeg,
    is_video_file,
    resolve_video_output_path,
    transcode_video_job,
)
from tests._paths import make_temp_dir


class VideoToolsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = make_temp_dir("video_tests")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_is_video_file_detects_common_extensions(self):
        self.assertTrue(is_video_file(Path('sample.ts')))
        self.assertTrue(is_video_file(Path('sample.MP4')))
        self.assertFalse(is_video_file(Path('sample.txt')))

    def test_build_scale_filter_returns_none_for_source(self):
        self.assertIsNone(build_scale_filter('source'))
        self.assertEqual(build_scale_filter('720'), "scale=-2:'min(720,ih)'")

    def test_build_ffmpeg_command_uses_profile_settings(self):
        command = build_ffmpeg_command('ffmpeg', Path('input.ts'), Path('out.mp4'), 'strong')
        self.assertIn('libx265', command)
        self.assertIn('30', command)
        self.assertIn('96k', command)
        self.assertNotIn('-vf', command)

    def test_build_ffmpeg_command_adds_resize_for_max_profile(self):
        command = build_ffmpeg_command('ffmpeg', Path('input.ts'), Path('out.mp4'), 'max')
        self.assertIn('-vf', command)
        self.assertIn("scale=-2:'min(720,ih)'", command)

    def test_resolve_video_output_path_uses_compressed_suffix(self):
        source = self.temp_dir / 'movie.ts'
        source.write_bytes(b'123')
        temp_dest, final_dest = resolve_video_output_path(source, None, overwrite=False)
        self.assertEqual(final_dest.name, 'movie_compressed.mp4')
        self.assertEqual(final_dest.parent, source.parent)
        self.assertEqual(temp_dest.suffix, '.mp4')
        temp_dest.unlink(missing_ok=True)

    def test_find_ffmpeg_detects_winget_package_layout(self):
        package_dir = self.temp_dir / 'Microsoft' / 'WinGet' / 'Packages' / 'Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe' / 'ffmpeg-8.1-full_build' / 'bin'
        package_dir.mkdir(parents=True)
        ffmpeg_path = package_dir / 'ffmpeg.exe'
        ffmpeg_path.write_bytes(b'')

        with patch('pylossless.video.shutil.which', return_value=None), patch.dict(os.environ, {'LOCALAPPDATA': str(self.temp_dir)}, clear=False):
            found = find_ffmpeg()

        self.assertEqual(Path(found), ffmpeg_path)

    def test_transcode_video_job_requires_ffmpeg(self):
        source = self.temp_dir / 'movie.ts'
        source.write_bytes(b'123')
        with patch('pylossless.video.find_ffmpeg', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'ffmpeg'):
                transcode_video_job(
                    source_path=source,
                    output_dir=None,
                    overwrite=True,
                    profile='strong',
                    cancel_event=threading.Event(),
                    progress_cb=lambda *_: None,
                    log_cb=lambda *_: None,
                )


if __name__ == '__main__':
    unittest.main()
