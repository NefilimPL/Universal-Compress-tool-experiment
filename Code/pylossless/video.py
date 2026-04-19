from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from .models import CancelledError
from .utils import atomic_replace, choose_final_dest, create_temp_in_dir, ensure_dir, safe_stem


VIDEO_EXTENSIONS = {
    '.3gp',
    '.asf',
    '.avi',
    '.m2ts',
    '.m4v',
    '.mkv',
    '.mov',
    '.mp4',
    '.mpeg',
    '.mpg',
    '.mts',
    '.ts',
    '.webm',
    '.wmv',
}

VIDEO_PROFILES = {
    'balanced': {
        'label': 'Balans',
        'codec_label': 'H.264 / AVC',
        'ffmpeg_codec': 'libx264',
        'crf': 26,
        'preset': 'slow',
        'audio_bitrate': '128',
        'max_height': 'source',
    },
    'strong': {
        'label': 'Mocna',
        'codec_label': 'H.265 / HEVC',
        'ffmpeg_codec': 'libx265',
        'crf': 30,
        'preset': 'slow',
        'audio_bitrate': '96',
        'max_height': 'source',
    },
    'max': {
        'label': 'Max 720p',
        'codec_label': 'H.265 / HEVC',
        'ffmpeg_codec': 'libx265',
        'crf': 34,
        'preset': 'veryslow',
        'audio_bitrate': '64',
        'max_height': '720',
    },
}
VIDEO_PROFILE_ORDER = ['balanced', 'strong', 'max']


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def find_ffmpeg() -> str | None:
    return shutil.which('ffmpeg')


def find_ffprobe() -> str | None:
    return shutil.which('ffprobe')


def resolve_video_output_dir(source_path: Path, chosen_dir: str | None) -> Path:
    if chosen_dir:
        return ensure_dir(Path(chosen_dir))
    parent = source_path.resolve().parent
    if parent.exists():
        return parent
    return ensure_dir(source_path.parent)


def build_scale_filter(max_height: str) -> str | None:
    if max_height == 'source':
        return None
    height = int(max_height)
    return f"scale=-2:'min({height},ih)'"


def resolve_video_output_path(source_path: Path, output_dir: str | None, overwrite: bool) -> tuple[Path, Path]:
    base_dir = resolve_video_output_dir(source_path, output_dir)
    final_dest = choose_final_dest(base_dir, f"{safe_stem(source_path.stem)}_compressed.mp4", overwrite)
    temp_dest = create_temp_in_dir(base_dir, '.mp4')
    return temp_dest, final_dest


def probe_duration_seconds(source_path: Path) -> float | None:
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None

    result = subprocess.run(
        [
            ffprobe,
            '-v',
            'error',
            '-show_entries',
            'format=duration',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            str(source_path),
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    if result.returncode != 0:
        return None

    raw = result.stdout.strip()
    if not raw:
        return None

    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def build_ffmpeg_command(
    ffmpeg_path: str,
    source_path: Path,
    dest_path: Path,
    profile: str,
) -> list[str]:
    meta = VIDEO_PROFILES.get(profile)
    if meta is None:
        raise ValueError(f'Nieobslugiwany profil video: {profile}')

    command = [
        ffmpeg_path,
        '-hide_banner',
        '-y',
        '-progress',
        'pipe:1',
        '-nostats',
        '-i',
        str(source_path),
        '-map_metadata',
        '0',
        '-map',
        '0:v:0',
        '-map',
        '0:a?',
        '-c:v',
        meta['ffmpeg_codec'],
        '-preset',
        meta['preset'],
        '-crf',
        str(meta['crf']),
        '-pix_fmt',
        'yuv420p',
        '-c:a',
        'aac',
        '-b:a',
        f"{meta['audio_bitrate']}k",
        '-movflags',
        '+faststart',
    ]

    scale_filter = build_scale_filter(str(meta['max_height']))
    if scale_filter:
        command.extend(['-vf', scale_filter])

    command.append(str(dest_path))
    return command


def _report_video_progress(
    line: str,
    total_duration: float | None,
    phase: str,
    progress_cb: Callable[[int, int, str], None],
) -> None:
    if not line.startswith('out_time_ms='):
        return
    if total_duration is None or total_duration <= 0:
        return

    try:
        out_time_ms = int(line.split('=', 1)[1].strip())
    except ValueError:
        return

    total_ms = max(1, int(total_duration * 1000))
    done_ms = max(0, min(total_ms, out_time_ms // 1000))
    progress_cb(done_ms, total_ms, phase)


def transcode_video_job(
    source_path: Path,
    output_dir: str | None,
    overwrite: bool,
    profile: str,
    cancel_event: threading.Event,
    progress_cb: Callable[[int, int, str], None],
    log_cb: Callable[[str], None],
) -> dict:
    if not source_path.exists() or not source_path.is_file():
        raise ValueError('Wskazany plik video nie istnieje lub nie jest plikiem.')
    if not is_video_file(source_path):
        raise ValueError('Tryb transkodowania video obsluguje tylko pliki video.')

    meta = VIDEO_PROFILES.get(profile)
    if meta is None:
        raise ValueError(f'Nieobslugiwany profil video: {profile}')

    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        raise RuntimeError(
            'Nie znaleziono programu ffmpeg w PATH. Zainstaluj FFmpeg i dodaj go do PATH, aby uzyc mocniejszej kompresji video.'
        )

    temp_dest, final_dest = resolve_video_output_path(source_path, output_dir, overwrite)
    total_duration = probe_duration_seconds(source_path)
    phase = f"Transkodowanie video: {meta['codec_label']} | profil {meta['label']}"
    command = build_ffmpeg_command(ffmpeg_path, source_path, temp_dest, profile)

    log_cb(
        'FFmpeg: '
        + f"{meta['codec_label']}, profil {meta['label']}, CRF {meta['crf']}, preset {meta['preset']}, audio {meta['audio_bitrate']}k, wysokosc {meta['max_height']}"
    )
    if total_duration is None:
        progress_cb(0, 1, phase)

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
    )

    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            if cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                raise CancelledError('Transkodowanie video zostalo anulowane.')

            line = raw_line.strip()
            if not line:
                continue
            _report_video_progress(line, total_duration, phase, progress_cb)
            if line.startswith('progress='):
                continue
            if line.startswith(('frame=', 'fps=', 'bitrate=', 'total_size=', 'out_time_ms=', 'speed=')):
                continue
            log_cb(line)

        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f'FFmpeg zakonczyl sie kodem {return_code}. Sprawdz dziennik, aby zobaczyc szczegoly.')

        atomic_replace(temp_dest, final_dest)
        output_size = final_dest.stat().st_size
        source_size = source_path.stat().st_size
        ratio = 0.0 if source_size == 0 else (output_size / source_size) * 100.0
        progress_cb(1, 1, phase)
        return {
            'dest': str(final_dest),
            'size': output_size,
            'algorithm': meta['codec_label'],
            'ratio': ratio,
            'source_size': source_size,
            'mode': 'video_transcode',
            'profile': profile,
            'crf': meta['crf'],
            'preset': meta['preset'],
            'audio_bitrate': meta['audio_bitrate'],
            'max_height': meta['max_height'],
        }
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if temp_dest.exists():
            temp_dest.unlink(missing_ok=True)
