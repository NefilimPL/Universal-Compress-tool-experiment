from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

try:
    from pylossless.video import find_ffmpeg, is_video_file, probe_duration_seconds
except ModuleNotFoundError as exc:
    if exc.name != "pylossless":
        raise
    from Code.pylossless.video import find_ffmpeg, is_video_file, probe_duration_seconds

from ..models import CancelledError


AUDIO_EXTENSIONS = {
    ".aac",
    ".aiff",
    ".alac",
    ".flac",
    ".m4a",
    ".mp3",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}

VIDEO_PROFILES = {
    "Szybciej": {"codec": "libx264", "crf": "30", "preset": "superfast", "audio_bitrate": "128k"},
    "Zbalansowany": {"codec": "libx264", "crf": "27", "preset": "veryfast", "audio_bitrate": "128k"},
    "Mocniej kompresuj": {"codec": "libx265", "crf": "31", "preset": "medium", "audio_bitrate": "96k"},
    "Archiwum": {"codec": "libx265", "crf": "27", "preset": "slow", "audio_bitrate": "160k"},
}

AUDIO_PROFILES = {
    "Szybciej": {"codec": "aac", "bitrate": "160k", "suffix": ".m4a"},
    "Zbalansowany": {"codec": "aac", "bitrate": "128k", "suffix": ".m4a"},
    "Mocniej kompresuj": {"codec": "aac", "bitrate": "96k", "suffix": ".m4a"},
    "Archiwum": {"codec": "aac", "bitrate": "192k", "suffix": ".m4a"},
}


class MediaCompressionService:
    def __init__(
        self,
        ffmpeg_resolver: Callable[[], str | None] | None = None,
        duration_probe: Callable[[Path], float | None] | None = None,
        process_factory=None,
    ) -> None:
        self._ffmpeg_resolver = ffmpeg_resolver or find_ffmpeg
        self._duration_probe = duration_probe or probe_duration_seconds
        self._process_factory = process_factory or subprocess.Popen

    def compress_sources(
        self,
        sources: list[Path],
        output_dir: Path,
        profile_name: str,
        progress_callback: Callable[[int, int, str], None] | None = None,
        log_callback: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[Path]:
        self._ensure_not_cancelled(cancel_event)
        ffmpeg_path = self._ffmpeg_resolver()
        if not ffmpeg_path:
            raise RuntimeError(
                "Nie znaleziono programu ffmpeg. Dodaj ffmpeg.exe do PATH albo zainstaluj go przed kompresja mediow."
            )

        if not sources:
            raise ValueError("Media Studio wymaga przynajmniej jednego pliku audio albo video.")

        output_dir.mkdir(parents=True, exist_ok=True)
        total_units = max(1, len(sources) * 1000)
        outputs: list[Path] = []

        for index, source in enumerate(sources, start=1):
            self._ensure_not_cancelled(cancel_event)
            source = Path(source)
            if not source.exists() or not source.is_file():
                raise ValueError(f"Plik mediow nie istnieje albo nie jest plikiem: {source}")

            if is_video_file(source):
                output_path = self._compress_one_video(
                    ffmpeg_path=ffmpeg_path,
                    source=source,
                    output_dir=output_dir,
                    profile_name=profile_name,
                    item_index=index,
                    item_count=len(sources),
                    total_units=total_units,
                    progress_callback=progress_callback,
                    log_callback=log_callback,
                    cancel_event=cancel_event,
                )
            elif self._is_audio_file(source):
                output_path = self._compress_one_audio(
                    ffmpeg_path=ffmpeg_path,
                    source=source,
                    output_dir=output_dir,
                    profile_name=profile_name,
                    item_index=index,
                    item_count=len(sources),
                    total_units=total_units,
                    progress_callback=progress_callback,
                    log_callback=log_callback,
                    cancel_event=cancel_event,
                )
            else:
                raise ValueError("Media Studio obsluguje tylko pliki audio i video.")

            outputs.append(output_path)

        return outputs

    def _compress_one_video(
        self,
        *,
        ffmpeg_path: str,
        source: Path,
        output_dir: Path,
        profile_name: str,
        item_index: int,
        item_count: int,
        total_units: int,
        progress_callback: Callable[[int, int, str], None] | None,
        log_callback: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
    ) -> Path:
        profile = VIDEO_PROFILES.get(profile_name, VIDEO_PROFILES["Zbalansowany"])
        output_path = self._unique_output_path(output_dir, source.stem, ".mp4")
        duration = self._duration_probe(source)
        detail_prefix = f"Media {item_index}/{item_count}: {source.name}"

        command = [
            ffmpeg_path,
            "-hide_banner",
            "-y",
            "-progress",
            "pipe:1",
            "-nostats",
            "-i",
            str(source),
            "-map_metadata",
            "0",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            profile["codec"],
            "-preset",
            profile["preset"],
            "-crf",
            profile["crf"],
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            profile["audio_bitrate"],
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        if log_callback is not None:
            log_callback(
                f"Video {source.name}: {profile['codec']}, CRF {profile['crf']}, preset {profile['preset']}, audio {profile['audio_bitrate']}"
            )

        try:
            self._run_ffmpeg_command(
                command=command,
                duration=duration,
                detail_prefix=detail_prefix,
                item_index=item_index,
                item_count=item_count,
                total_units=total_units,
                progress_callback=progress_callback,
                log_callback=log_callback,
                cancel_event=cancel_event,
            )
        except Exception:
            output_path.unlink(missing_ok=True)
            raise
        return output_path

    def _compress_one_audio(
        self,
        *,
        ffmpeg_path: str,
        source: Path,
        output_dir: Path,
        profile_name: str,
        item_index: int,
        item_count: int,
        total_units: int,
        progress_callback: Callable[[int, int, str], None] | None,
        log_callback: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
    ) -> Path:
        profile = AUDIO_PROFILES.get(profile_name, AUDIO_PROFILES["Zbalansowany"])
        output_path = self._unique_output_path(output_dir, source.stem, str(profile["suffix"]))
        duration = self._duration_probe(source)
        detail_prefix = f"Media {item_index}/{item_count}: {source.name}"

        command = [
            ffmpeg_path,
            "-hide_banner",
            "-y",
            "-progress",
            "pipe:1",
            "-nostats",
            "-i",
            str(source),
            "-map_metadata",
            "0",
            "-vn",
            "-c:a",
            profile["codec"],
            "-b:a",
            profile["bitrate"],
            str(output_path),
        ]

        if log_callback is not None:
            log_callback(f"Audio {source.name}: {profile['codec']}, bitrate {profile['bitrate']}")

        try:
            self._run_ffmpeg_command(
                command=command,
                duration=duration,
                detail_prefix=detail_prefix,
                item_index=item_index,
                item_count=item_count,
                total_units=total_units,
                progress_callback=progress_callback,
                log_callback=log_callback,
                cancel_event=cancel_event,
            )
        except Exception:
            output_path.unlink(missing_ok=True)
            raise
        return output_path

    def _run_ffmpeg_command(
        self,
        *,
        command: list[str],
        duration: float | None,
        detail_prefix: str,
        item_index: int,
        item_count: int,
        total_units: int,
        progress_callback: Callable[[int, int, str], None] | None,
        log_callback: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
    ) -> None:
        self._ensure_not_cancelled(cancel_event)
        if progress_callback is not None:
            progress_callback((item_index - 1) * 1000, total_units, f"{detail_prefix} - start")

        process = self._process_factory(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                self._ensure_not_cancelled(cancel_event)
                line = raw_line.strip()
                if not line:
                    continue
                self._forward_ffmpeg_progress(
                    line=line,
                    duration=duration,
                    detail_prefix=detail_prefix,
                    item_index=item_index,
                    item_count=item_count,
                    total_units=total_units,
                    progress_callback=progress_callback,
                )
                if line.startswith(("frame=", "fps=", "bitrate=", "total_size=", "out_time_ms=", "speed=", "progress=")):
                    continue
                if log_callback is not None:
                    log_callback(line)

            return_code = process.wait()
            self._ensure_not_cancelled(cancel_event)
            if return_code != 0:
                raise RuntimeError(f"FFmpeg zakonczyl sie kodem {return_code}. Sprawdz log, aby zobaczyc szczegoly.")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

        if progress_callback is not None:
            progress_callback(item_index * 1000, total_units, f"{detail_prefix} - zakonczono")

    def _forward_ffmpeg_progress(
        self,
        *,
        line: str,
        duration: float | None,
        detail_prefix: str,
        item_index: int,
        item_count: int,
        total_units: int,
        progress_callback: Callable[[int, int, str], None] | None,
    ) -> None:
        if progress_callback is None or not line.startswith("out_time_ms="):
            return
        if duration is None or duration <= 0:
            return

        try:
            out_time_ms = int(line.split("=", 1)[1].strip())
        except ValueError:
            return

        total_ms = max(1, int(duration * 1000))
        local_done = max(0, min(total_ms, out_time_ms // 1000))
        local_ratio = local_done / total_ms
        done_units = ((item_index - 1) * 1000) + int(local_ratio * 1000)
        progress_callback(min(done_units, total_units), total_units, f"{detail_prefix} ({item_index}/{item_count})")

    def _is_audio_file(self, path: Path) -> bool:
        return path.suffix.lower() in AUDIO_EXTENSIONS

    def _unique_output_path(self, output_dir: Path, stem: str, suffix: str) -> Path:
        base = output_dir / f"{stem}_compressed{suffix}"
        if not base.exists():
            return base

        counter = 2
        while True:
            candidate = output_dir / f"{stem}_compressed_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def _ensure_not_cancelled(self, cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("Operacja zostala anulowana.")
