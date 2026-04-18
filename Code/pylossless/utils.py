from __future__ import annotations

import os
import tempfile
from pathlib import Path


def human_size(num: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num)
    for unit in units:
        if abs(value) < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} TB"


def format_seconds(seconds: float) -> str:
    if seconds < 0 or seconds == float("inf"):
        return "?"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def safe_stem(name: str) -> str:
    bad = '<>:"/\\|?*\n\r\t'
    out = "".join("_" if ch in bad else ch for ch in name.strip())
    out = out.strip(" .")
    return out or "plik"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def choose_final_dest(base_dir: Path, base_name: str, overwrite: bool) -> Path:
    ensure_dir(base_dir)
    path = base_dir / base_name
    return path if overwrite else unique_path(path)


def create_temp_in_dir(base_dir: Path, suffix: str) -> Path:
    ensure_dir(base_dir)
    fd, raw = tempfile.mkstemp(prefix=".tmp_pylossless_", suffix=suffix, dir=str(base_dir))
    os.close(fd)
    return Path(raw)


def atomic_replace(src: Path, dest: Path) -> None:
    ensure_dir(dest.parent)
    src.replace(dest)


def read_text_file(path: Path) -> tuple[str, str]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1250"):
        try:
            return path.read_text(encoding=encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc
            break
    if last_error is None:
        raise ValueError("Nie uda?o si? odczyta? pliku tekstowego.")
    raise last_error
