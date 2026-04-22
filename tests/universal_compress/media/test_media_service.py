import subprocess
import sys
import threading
from pathlib import Path

import pytest

from universal_compress.models import CancelledError
from universal_compress.media.service import MediaCompressionService


def test_media_service_requires_ffmpeg_when_missing(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_text("video", encoding="utf-8")
    service = MediaCompressionService(ffmpeg_resolver=lambda: None)

    with pytest.raises(RuntimeError, match="ffmpeg"):
        service.compress_sources([source], tmp_path / "out", "Zbalansowany")


def test_media_service_rejects_non_media_sources(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("hello", encoding="utf-8")
    service = MediaCompressionService(ffmpeg_resolver=lambda: "ffmpeg")

    with pytest.raises(ValueError, match="audio i video"):
        service.compress_sources([source], tmp_path / "out", "Zbalansowany")


def test_media_service_uses_speed_focused_video_preset_for_fast_profile(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_text("video", encoding="utf-8")
    commands = []

    class DummyProcess:
        stdout = []

        def wait(self):
            return 0

        def poll(self):
            return 0

        def kill(self):
            return None

    service = MediaCompressionService(
        ffmpeg_resolver=lambda: "ffmpeg",
        duration_probe=lambda path: None,
        process_factory=lambda command, **kwargs: commands.append(command) or DummyProcess(),
    )

    service.compress_sources([source], tmp_path / "out", "Szybciej")

    command = commands[0]
    assert command[command.index("-preset") + 1] == "superfast"


def test_media_service_imports_from_launcher_context():
    repo_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {repo_root.as_posix()!r}); "
                "import Code.universal_compress.media.service"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_media_service_respects_cancelled_request_before_start(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_text("video", encoding="utf-8")
    cancel_event = threading.Event()
    cancel_event.set()

    service = MediaCompressionService(
        ffmpeg_resolver=lambda: "ffmpeg",
        process_factory=lambda *args, **kwargs: pytest.fail("ffmpeg process should not start after cancellation"),
    )

    with pytest.raises(CancelledError, match="anulowana"):
        service.compress_sources([source], tmp_path / "out", "Szybciej", cancel_event=cancel_event)
