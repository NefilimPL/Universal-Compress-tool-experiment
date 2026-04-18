from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import struct
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import zlib
except Exception:
    zlib = None

try:
    import gzip
except Exception:
    gzip = None

try:
    import bz2
except Exception:
    bz2 = None

try:
    import lzma
except Exception:
    lzma = None


APP_NAME = "PyLossless Studio"
APP_VERSION = "1.0"
CONTAINER_EXT = ".pylc"
MAGIC = b"PYLC1"
HEADER_FMT = ">I"
QUEUE_POLL_MS = 100
DEFAULT_CHUNK = 1024 * 1024


def get_script_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return Path.cwd()


SCRIPT_DIR = get_script_dir()
DEFAULT_ENCODE_DIR = SCRIPT_DIR / "wynik_zakodowany"
DEFAULT_DECODE_DIR = SCRIPT_DIR / "wynik_odkodowany"
SETTINGS_FILE = SCRIPT_DIR / "pylossless_settings.json"


ALGO_META = {
    "zlib": {"label": "ZLIB", "min": 0, "max": 9, "default": 6, "available": zlib is not None},
    "gzip": {"label": "GZIP", "min": 0, "max": 9, "default": 6, "available": gzip is not None},
    "bz2": {"label": "BZ2", "min": 1, "max": 9, "default": 9, "available": bz2 is not None},
    "lzma": {"label": "LZMA/XZ", "min": 0, "max": 9, "default": 6, "available": lzma is not None},
}
AVAILABLE_ALGOS = [name for name, meta in ALGO_META.items() if meta["available"]]


class CancelledError(Exception):
    pass


@dataclass
class SourceSpec:
    mode: str                 # "file" | "text"
    file_path: Optional[Path]
    text_bytes: Optional[bytes]
    text_name: str
    text_encoding: str = "utf-8"

    @property
    def total_size(self) -> int:
        if self.mode == "file" and self.file_path is not None:
            return self.file_path.stat().st_size
        return len(self.text_bytes or b"")

    @property
    def original_name(self) -> str:
        if self.mode == "file" and self.file_path is not None:
            return self.file_path.name
        return self.text_name

    @property
    def original_parent(self) -> str:
        if self.mode == "file" and self.file_path is not None:
            return str(self.file_path.resolve().parent)
        return ""

    @property
    def mtime_ns(self) -> Optional[int]:
        if self.mode == "file" and self.file_path is not None:
            return self.file_path.stat().st_mtime_ns
        return None


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
        return "—"
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


def clamp_level(algo: str, level: int) -> int:
    meta = ALGO_META[algo]
    return max(meta["min"], min(meta["max"], int(level)))


def resolve_encode_output_dir(source: SourceSpec, chosen_dir: str | None) -> Path:
    if chosen_dir:
        return ensure_dir(Path(chosen_dir))
    if source.mode == "file" and source.file_path is not None:
        parent = source.file_path.resolve().parent
        if parent.exists():
            return parent
    return ensure_dir(DEFAULT_ENCODE_DIR)


def resolve_decode_output_dir(header: dict, chosen_dir: str | None, prefer_original: bool) -> Path:
    if chosen_dir:
        return ensure_dir(Path(chosen_dir))
    if prefer_original:
        original_parent = header.get("original_parent") or ""
        if original_parent:
            try:
                parent = Path(original_parent)
                if parent.exists() and parent.is_dir():
                    return parent
            except Exception:
                pass
    return ensure_dir(DEFAULT_DECODE_DIR)


def iter_source_chunks(source: SourceSpec, chunk_size: int) -> Iterable[bytes]:
    if source.mode == "file":
        assert source.file_path is not None
        with source.file_path.open("rb") as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                yield data
    else:
        data = source.text_bytes or b""
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]


def compute_sha256(
    source: SourceSpec,
    chunk_size: int,
    cancel_event: threading.Event,
    progress_cb: Callable[[int, int, str], None],
) -> str:
    total = source.total_size
    done = 0
    h = hashlib.sha256()
    if total == 0:
        progress_cb(0, 0, "Analiza wejścia (SHA-256)")
        return h.hexdigest()
    for chunk in iter_source_chunks(source, chunk_size):
        if cancel_event.is_set():
            raise CancelledError("Operacja została anulowana.")
        h.update(chunk)
        done += len(chunk)
        progress_cb(done, total, "Analiza wejścia (SHA-256)")
    return h.hexdigest()


def build_header(source: SourceSpec, algo: str, level: int, sha256_hex: str) -> dict:
    return {
        "format_version": 1,
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "source_mode": source.mode,
        "original_name": source.original_name,
        "original_parent": source.original_parent,
        "original_size": source.total_size,
        "original_sha256": sha256_hex,
        "algorithm": algo,
        "level": level,
        "text_encoding": source.text_encoding if source.mode == "text" else None,
        "mtime_ns": source.mtime_ns,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def write_header(raw_f, header: dict) -> None:
    header_bytes = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    raw_f.write(MAGIC)
    raw_f.write(struct.pack(HEADER_FMT, len(header_bytes)))
    raw_f.write(header_bytes)


def read_container_header(path: Path) -> tuple[dict, int]:
    with path.open("rb") as f:
        magic = f.read(len(MAGIC))
        if magic != MAGIC:
            raise ValueError("To nie jest plik w formacie PYLC1.")
        length_raw = f.read(struct.calcsize(HEADER_FMT))
        if len(length_raw) != struct.calcsize(HEADER_FMT):
            raise ValueError("Uszkodzony nagłówek pliku.")
        header_len = struct.unpack(HEADER_FMT, length_raw)[0]
        header_bytes = f.read(header_len)
        if len(header_bytes) != header_len:
            raise ValueError("Nagłówek pliku jest niekompletny.")
        header = json.loads(header_bytes.decode("utf-8"))
        payload_offset = len(MAGIC) + struct.calcsize(HEADER_FMT) + header_len
        return header, payload_offset


class ZlibWriteAdapter:
    def __init__(self, raw_f, level: int):
        self.raw_f = raw_f
        self._comp = zlib.compressobj(level)
        self._closed = False

    def write(self, data: bytes) -> int:
        if self._closed:
            raise ValueError("Strumień zlib jest zamknięty.")
        if data:
            out = self._comp.compress(data)
            if out:
                self.raw_f.write(out)
        return len(data)

    def close(self) -> None:
        if self._closed:
            return
        tail = self._comp.flush(zlib.Z_FINISH)
        if tail:
            self.raw_f.write(tail)
        self._closed = True

    def flush(self) -> None:
        if self._closed:
            return
        out = self._comp.flush(zlib.Z_SYNC_FLUSH)
        if out:
            self.raw_f.write(out)
        self.raw_f.flush()


def open_compressed_writer(algo: str, raw_f, level: int):
    level = clamp_level(algo, level)

    if algo == "gzip":
        if gzip is None:
            raise RuntimeError("Moduł gzip nie jest dostępny w tym Pythonie.")
        return gzip.GzipFile(fileobj=raw_f, mode="wb", compresslevel=level, mtime=0)

    if algo == "bz2":
        if bz2 is None:
            raise RuntimeError("Moduł bz2 nie jest dostępny w tym Pythonie.")
        return bz2.BZ2File(raw_f, mode="wb", compresslevel=level)

    if algo == "lzma":
        if lzma is None:
            raise RuntimeError("Moduł lzma nie jest dostępny w tym Pythonie.")
        return lzma.LZMAFile(raw_f, mode="wb", preset=level, format=lzma.FORMAT_XZ)

    if algo == "zlib":
        if zlib is None:
            raise RuntimeError("Moduł zlib nie jest dostępny w tym Pythonie.")
        return ZlibWriteAdapter(raw_f, level=level)

    raise ValueError(f"Nieobsługiwany algorytm: {algo}")


def compress_to_container(
    source: SourceSpec,
    algo: str,
    level: int,
    dest_path: Path,
    chunk_size: int,
    header: dict,
    cancel_event: threading.Event,
    progress_cb: Callable[[int, int, str], None],
) -> int:
    total = source.total_size
    done = 0
    with dest_path.open("wb") as raw_f:
        write_header(raw_f, header)
        writer = open_compressed_writer(algo, raw_f, level)
        try:
            for chunk in iter_source_chunks(source, chunk_size):
                if cancel_event.is_set():
                    raise CancelledError("Operacja została anulowana.")
                writer.write(chunk)
                done += len(chunk)
                progress_cb(done, total, f"Kompresja: {algo.upper()}")
        finally:
            writer.close()
    return dest_path.stat().st_size


def estimate_size_bytes(data: bytes, algo: str, level: int) -> int:
    temp_dir = tempfile.mkdtemp(prefix="pylossless_est_")
    try:
        src = SourceSpec(mode="text", file_path=None, text_bytes=data, text_name="estimate.bin", text_encoding="utf-8")
        sha = hashlib.sha256(data).hexdigest()
        header = build_header(src, algo, level, sha)
        path = Path(temp_dir) / f"estimate_{algo}{CONTAINER_EXT}"
        size = compress_to_container(
            src,
            algo,
            level,
            path,
            DEFAULT_CHUNK,
            header,
            threading.Event(),
            lambda _a, _b, _c: None,
        )
        return size
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def estimate_output(
    source: SourceSpec,
    chunk_size: int,
    algo_mode: str,
    algo_single: str,
    auto_enabled: list[str],
    level: int,
) -> dict:
    total = source.total_size
    exact_limit = 16 * 1024 * 1024
    sample_limit = 4 * 1024 * 1024

    if source.mode == "file":
        assert source.file_path is not None
        with source.file_path.open("rb") as f:
            sample = f.read(exact_limit if total <= exact_limit else sample_limit)
    else:
        data = source.text_bytes or b""
        sample = data if len(data) <= exact_limit else data[:sample_limit]

    algos = [algo_single] if algo_mode == "single" else [a for a in auto_enabled if a in AVAILABLE_ALGOS]
    if not algos:
        raise ValueError("Brak aktywnych algorytmów do oszacowania.")

    result = {}
    exact = total <= exact_limit
    for algo in algos:
        used_level = clamp_level(algo, level)
        size = estimate_size_bytes(sample, algo, used_level)
        if exact:
            estimate = size
        else:
            ratio = size / max(1, len(sample))
            estimate = int(total * ratio)
        result[algo] = max(0, estimate)

    best_algo = min(result, key=result.get)
    return {
        "kind": "exact" if exact else "sample",
        "results": result,
        "best_algo": best_algo,
        "best_size": result[best_algo],
        "sample_bytes": len(sample),
    }


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
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dest)


def compress_job(
    source: SourceSpec,
    output_dir: str | None,
    algo_mode: str,
    algo_single: str,
    auto_enabled: list[str],
    level: int,
    chunk_size: int,
    overwrite: bool,
    cancel_event: threading.Event,
    progress_cb: Callable[[int, int, str], None],
    log_cb: Callable[[str], None],
) -> dict:
    if source.mode == "file" and source.file_path is None:
        raise ValueError("Nie wskazano pliku wejściowego.")
    if source.mode == "text" and source.text_bytes is None:
        raise ValueError("Brak tekstu do zakodowania.")

    base_dir = resolve_encode_output_dir(source, output_dir)
    base_name = f"{safe_stem(source.original_name)}{CONTAINER_EXT}"
    final_dest = choose_final_dest(base_dir, base_name, overwrite)

    candidate_algos = [algo_single] if algo_mode == "single" else [a for a in auto_enabled if a in AVAILABLE_ALGOS]
    if not candidate_algos:
        raise ValueError("Brak wybranych algorytmów do kompresji.")

    total_work = source.total_size * (1 + len(candidate_algos))
    progress_base = 0

    sha = compute_sha256(
        source,
        chunk_size,
        cancel_event,
        lambda done, total, phase: progress_cb(progress_base + done, total_work, phase),
    )
    progress_base += source.total_size

    best_temp: Optional[Path] = None
    best_algo: Optional[str] = None
    best_size: Optional[int] = None

    try:
        for idx, algo in enumerate(candidate_algos, start=1):
            if cancel_event.is_set():
                raise CancelledError("Operacja została anulowana.")

            used_level = clamp_level(algo, level)
            header = build_header(source, algo, used_level, sha)
            temp_path = create_temp_in_dir(base_dir, CONTAINER_EXT)

            log_cb(f"Test {idx}/{len(candidate_algos)}: {algo.upper()} (poziom {used_level})")

            size = compress_to_container(
                source,
                algo,
                used_level,
                temp_path,
                chunk_size,
                header,
                cancel_event,
                lambda done, total, phase, base=progress_base: progress_cb(base + done, total_work, phase),
            )
            progress_base += source.total_size
            log_cb(f"Wynik {algo.upper()}: {human_size(size)}")

            if best_size is None or size < best_size:
                if best_temp and best_temp.exists():
                    best_temp.unlink(missing_ok=True)
                best_temp = temp_path
                best_size = size
                best_algo = algo
            else:
                temp_path.unlink(missing_ok=True)

        if best_temp is None or best_algo is None or best_size is None:
            raise RuntimeError("Nie udało się wygenerować pliku wynikowego.")

        atomic_replace(best_temp, final_dest)
        ratio = 0.0 if source.total_size == 0 else (best_size / source.total_size) * 100.0
        return {
            "dest": str(final_dest),
            "size": best_size,
            "algorithm": best_algo,
            "ratio": ratio,
            "source_size": source.total_size,
            "sha256": sha,
        }

    finally:
        if best_temp and best_temp.exists() and str(best_temp) != str(final_dest):
            try:
                best_temp.unlink(missing_ok=True)
            except Exception:
                pass


def _stream_decompress_zlib(in_f, out_f, chunk_size: int, cancel_event: threading.Event, progress_cb, total_out: int, verify_hash: bool):
    decomp = zlib.decompressobj()
    h = hashlib.sha256() if verify_hash else None
    done_out = 0

    while True:
        if cancel_event.is_set():
            raise CancelledError("Operacja została anulowana.")

        comp_chunk = in_f.read(chunk_size)
        if not comp_chunk:
            tail = decomp.flush()
            if tail:
                out_f.write(tail)
                done_out += len(tail)
                if h:
                    h.update(tail)
                progress_cb(done_out, total_out, "Dekompresja: ZLIB")
            break

        data = decomp.decompress(comp_chunk)
        if data:
            out_f.write(data)
            done_out += len(data)
            if h:
                h.update(data)
            progress_cb(done_out, total_out, "Dekompresja: ZLIB")

        while decomp.unconsumed_tail:
            data = decomp.decompress(decomp.unconsumed_tail)
            if not data:
                break
            out_f.write(data)
            done_out += len(data)
            if h:
                h.update(data)
            progress_cb(done_out, total_out, "Dekompresja: ZLIB")

        if decomp.eof:
            break

    return done_out, h.hexdigest() if h else None


def decompress_job(
    archive_path: Path,
    output_dir: str | None,
    chunk_size: int,
    overwrite: bool,
    prefer_original_path: bool,
    verify_hash: bool,
    restore_mtime: bool,
    cancel_event: threading.Event,
    progress_cb: Callable[[int, int, str], None],
    log_cb: Callable[[str], None],
    load_text_to_memory: bool = False,
) -> dict:
    header, payload_offset = read_container_header(archive_path)

    out_dir = resolve_decode_output_dir(header, output_dir, prefer_original_path)
    original_name = safe_stem(header.get("original_name") or "odzyskany_plik")
    final_path = choose_final_dest(out_dir, original_name, overwrite)
    total_out = int(header.get("original_size") or 0)
    temp_out = create_temp_in_dir(final_path.parent, final_path.suffix or ".bin")
    algo = header.get("algorithm")

    log_cb(f"Dekodowanie: {algo}")

    try:
        with archive_path.open("rb") as raw_in, temp_out.open("wb") as out_f:
            raw_in.seek(payload_offset)

            if algo == "gzip":
                if gzip is None:
                    raise RuntimeError("Moduł gzip nie jest dostępny.")
                h = hashlib.sha256() if verify_hash else None
                done_out = 0
                with gzip.GzipFile(fileobj=raw_in, mode="rb") as gz:
                    while True:
                        if cancel_event.is_set():
                            raise CancelledError("Operacja została anulowana.")
                        chunk = gz.read(chunk_size)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        done_out += len(chunk)
                        if h:
                            h.update(chunk)
                        progress_cb(done_out, total_out, "Dekompresja: GZIP")
                digest = h.hexdigest() if h else None

            elif algo == "bz2":
                if bz2 is None:
                    raise RuntimeError("Moduł bz2 nie jest dostępny.")
                h = hashlib.sha256() if verify_hash else None
                done_out = 0
                with bz2.BZ2File(raw_in, mode="rb") as bz:
                    while True:
                        if cancel_event.is_set():
                            raise CancelledError("Operacja została anulowana.")
                        chunk = bz.read(chunk_size)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        done_out += len(chunk)
                        if h:
                            h.update(chunk)
                        progress_cb(done_out, total_out, "Dekompresja: BZ2")
                digest = h.hexdigest() if h else None

            elif algo == "lzma":
                if lzma is None:
                    raise RuntimeError("Moduł lzma nie jest dostępny.")
                h = hashlib.sha256() if verify_hash else None
                done_out = 0
                with lzma.LZMAFile(raw_in, mode="rb") as xz:
                    while True:
                        if cancel_event.is_set():
                            raise CancelledError("Operacja została anulowana.")
                        chunk = xz.read(chunk_size)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        done_out += len(chunk)
                        if h:
                            h.update(chunk)
                        progress_cb(done_out, total_out, "Dekompresja: LZMA")
                digest = h.hexdigest() if h else None

            elif algo == "zlib":
                if zlib is None:
                    raise RuntimeError("Moduł zlib nie jest dostępny.")
                done_out, digest = _stream_decompress_zlib(
                    raw_in, out_f, chunk_size, cancel_event, progress_cb, total_out, verify_hash
                )

            else:
                raise ValueError(f"Nieznany algorytm w archiwum: {algo}")

        actual_size = temp_out.stat().st_size
        if actual_size != total_out:
            raise ValueError(
                f"Rozmiar po dekodowaniu nie zgadza się z nagłówkiem: {actual_size} != {total_out}."
            )

        if verify_hash:
            expected = header.get("original_sha256")
            if expected and digest != expected:
                raise ValueError("Weryfikacja SHA-256 nie powiodła się. Plik lub archiwum może być uszkodzone.")

        if restore_mtime and header.get("mtime_ns") is not None:
            mtime_ns = int(header["mtime_ns"])
            os.utime(temp_out, ns=(mtime_ns, mtime_ns))

        text_value = None
        if load_text_to_memory and header.get("source_mode") == "text":
            encoding = header.get("text_encoding") or "utf-8"
            text_value = temp_out.read_text(encoding=encoding)

        atomic_replace(temp_out, final_path)

        return {
            "dest": str(final_path),
            "size": actual_size,
            "algorithm": algo,
            "source_mode": header.get("source_mode"),
            "text": text_value,
            "header": header,
        }

    finally:
        if temp_out.exists():
            try:
                temp_out.unlink(missing_ok=True)
            except Exception:
                pass


def verify_archive_job(
    archive_path: Path,
    chunk_size: int,
    cancel_event: threading.Event,
    progress_cb: Callable[[int, int, str], None],
    log_cb: Callable[[str], None],
) -> dict:
    header, payload_offset = read_container_header(archive_path)
    total_out = int(header.get("original_size") or 0)
    expected_hash = header.get("original_sha256")
    algo = header.get("algorithm")
    h = hashlib.sha256()
    sink = tempfile.TemporaryFile(mode="w+b")

    try:
        with archive_path.open("rb") as raw_in:
            raw_in.seek(payload_offset)

            if algo == "gzip":
                with gzip.GzipFile(fileobj=raw_in, mode="rb") as gz:
                    done = 0
                    while True:
                        if cancel_event.is_set():
                            raise CancelledError("Operacja została anulowana.")
                        chunk = gz.read(chunk_size)
                        if not chunk:
                            break
                        sink.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        progress_cb(done, total_out, "Test integralności: GZIP")

            elif algo == "bz2":
                with bz2.BZ2File(raw_in, mode="rb") as bz:
                    done = 0
                    while True:
                        if cancel_event.is_set():
                            raise CancelledError("Operacja została anulowana.")
                        chunk = bz.read(chunk_size)
                        if not chunk:
                            break
                        sink.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        progress_cb(done, total_out, "Test integralności: BZ2")

            elif algo == "lzma":
                with lzma.LZMAFile(raw_in, mode="rb") as xz:
                    done = 0
                    while True:
                        if cancel_event.is_set():
                            raise CancelledError("Operacja została anulowana.")
                        chunk = xz.read(chunk_size)
                        if not chunk:
                            break
                        sink.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        progress_cb(done, total_out, "Test integralności: LZMA")

            elif algo == "zlib":
                decomp = zlib.decompressobj()
                done = 0
                while True:
                    if cancel_event.is_set():
                        raise CancelledError("Operacja została anulowana.")
                    comp_chunk = raw_in.read(chunk_size)
                    if not comp_chunk:
                        tail = decomp.flush()
                        if tail:
                            sink.write(tail)
                            h.update(tail)
                            done += len(tail)
                            progress_cb(done, total_out, "Test integralności: ZLIB")
                        break
                    data = decomp.decompress(comp_chunk)
                    if data:
                        sink.write(data)
                        h.update(data)
                        done += len(data)
                        progress_cb(done, total_out, "Test integralności: ZLIB")
                    while decomp.unconsumed_tail:
                        data = decomp.decompress(decomp.unconsumed_tail)
                        if not data:
                            break
                        sink.write(data)
                        h.update(data)
                        done += len(data)
                        progress_cb(done, total_out, "Test integralności: ZLIB")
                    if decomp.eof:
                        break

            else:
                raise ValueError(f"Nieobsługiwany algorytm: {algo}")

    finally:
        sink.close()

    actual_hash = h.hexdigest()
    return {
        "ok": actual_hash == expected_hash,
        "expected_hash": expected_hash,
        "actual_hash": actual_hash,
        "header": header,
    }


class Worker(threading.Thread):
    def __init__(self, app, task_name: str, task_fn: Callable, **kwargs):
        super().__init__(daemon=True)
        self.app = app
        self.task_name = task_name
        self.task_fn = task_fn
        self.kwargs = kwargs

    def run(self):
        start = time.time()
        try:
            result = self.task_fn(**self.kwargs)
            self.app.queue.put({"type": "done", "task": self.task_name, "result": result, "elapsed": time.time() - start})
        except CancelledError as e:
            self.app.queue.put({"type": "cancelled", "task": self.task_name, "message": str(e), "elapsed": time.time() - start})
        except Exception as e:
            self.app.queue.put({
                "type": "error",
                "task": self.task_name,
                "message": str(e),
                "traceback": traceback.format_exc(),
                "elapsed": time.time() - start,
            })


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1180x860")
        self.minsize(1080, 760)

        self.queue: "queue.Queue[dict]" = queue.Queue()
        self.cancel_event = threading.Event()
        self.current_worker: Optional[Worker] = None
        self.progress_start_time = 0.0
        self.last_output_file: Optional[Path] = None

        self._build_variables()
        self._build_ui()
        self._load_settings()
        self.after(QUEUE_POLL_MS, self._poll_queue)

    def _build_variables(self):
        self.file_path_var = tk.StringVar()
        self.decode_path_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.text_name_var = tk.StringVar(value="tekst_wejsciowy.txt")

        self.algo_mode_var = tk.StringVar(value="single")
        self.single_algo_var = tk.StringVar(value=AVAILABLE_ALGOS[0] if AVAILABLE_ALGOS else "")
        self.level_var = tk.IntVar(value=6)
        self.chunk_var = tk.StringVar(value="1 MB")

        self.overwrite_var = tk.BooleanVar(value=False)
        self.verify_hash_var = tk.BooleanVar(value=True)
        self.restore_mtime_var = tk.BooleanVar(value=True)
        self.open_folder_var = tk.BooleanVar(value=False)
        self.prefer_original_path_var = tk.BooleanVar(value=True)
        self.load_text_on_decode_var = tk.BooleanVar(value=True)

        self.auto_zlib_var = tk.BooleanVar(value="zlib" in AVAILABLE_ALGOS)
        self.auto_gzip_var = tk.BooleanVar(value="gzip" in AVAILABLE_ALGOS)
        self.auto_bz2_var = tk.BooleanVar(value="bz2" in AVAILABLE_ALGOS)
        self.auto_lzma_var = tk.BooleanVar(value="lzma" in AVAILABLE_ALGOS)

        self.status_var = tk.StringVar(value="Gotowe.")
        self.progress_text_var = tk.StringVar(value="0%")
        self.eta_var = tk.StringVar(value="Pozostały czas: —")
        self.input_size_var = tk.StringVar(value="Wejście: —")
        self.estimate_size_var = tk.StringVar(value="Szacowany wynik: —")
        self.actual_size_var = tk.StringVar(value="Ostatni wynik: —")
        self.header_info_var = tk.StringVar(value="Nagłówek archiwum: —")
        self.file_info_var = tk.StringVar(value="Plik: —")
        self.text_info_var = tk.StringVar(value="Tekst: 0 znaków / 0 B")

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        title = ttk.Label(
            self,
            text=f"{APP_NAME} — bezstratne kodowanie i dekodowanie plików / tekstu",
            font=("Segoe UI", 14, "bold"),
        )
        title.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))

        main = ttk.Panedwindow(self, orient="horizontal")
        main.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        left = ttk.Frame(main, padding=8)
        right = ttk.Frame(main, padding=8)
        main.add(left, weight=3)
        main.add(right, weight=2)

        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(left)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self._build_tab_file()
        self._build_tab_text()
        self._build_tab_decode()

        right.columnconfigure(0, weight=1)
        self._build_settings(right)
        self._build_status(right)
        self._build_log(right)

    def _build_tab_file(self):
        tab = ttk.Frame(self.notebook, padding=10)
        tab.columnconfigure(1, weight=1)
        self.notebook.add(tab, text="Kodowanie pliku")

        ttk.Label(tab, text="Plik wejściowy:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(tab, textvariable=self.file_path_var).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(tab, text="Wybierz…", command=self.choose_file).grid(row=0, column=2, pady=4)

        ttk.Label(tab, textvariable=self.file_info_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 4))
        ttk.Label(
            tab,
            text="Domyślnie wynik zapisze się obok pliku wejściowego, chyba że wskażesz katalog wyjściowy po prawej.",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 10))

        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Button(buttons, text="Oszacuj rozmiar", command=self.start_estimate_from_file).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Koduj plik", command=self.start_encode_file).pack(side="left")

    def _build_tab_text(self):
        tab = ttk.Frame(self.notebook, padding=10)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self.notebook.add(tab, text="Kodowanie tekstu")

        row1 = ttk.Frame(tab)
        row1.grid(row=0, column=0, sticky="ew")
        row1.columnconfigure(1, weight=1)

        ttk.Label(row1, text="Nazwa tekstu / przyszłego pliku:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(row1, textvariable=self.text_name_var).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(row1, text="Wczytaj TXT…", command=self.load_text_from_file).grid(row=0, column=2, pady=4)

        ttk.Label(tab, textvariable=self.text_info_var).grid(row=1, column=0, sticky="w", pady=(4, 4))

        self.text_box = tk.Text(tab, wrap="word", undo=True, font=("Consolas", 11))
        self.text_box.grid(row=2, column=0, sticky="nsew", pady=6)
        self.text_box.bind("<<Modified>>", self.on_text_modified)

        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Button(buttons, text="Wyczyść", command=lambda: self.text_box.delete("1.0", "end")).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Oszacuj rozmiar", command=self.start_estimate_from_text).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Koduj tekst", command=self.start_encode_text).pack(side="left")

    def _build_tab_decode(self):
        tab = ttk.Frame(self.notebook, padding=10)
        tab.columnconfigure(1, weight=1)
        self.notebook.add(tab, text="Dekodowanie")

        ttk.Label(tab, text="Archiwum *.pylc:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(tab, textvariable=self.decode_path_var).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(tab, text="Wybierz…", command=self.choose_archive).grid(row=0, column=2, pady=4)

        ttk.Label(tab, textvariable=self.header_info_var, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 6))
        ttk.Label(
            tab,
            text="Jeśli zaznaczysz ‘Przywracaj do oryginalnej lokalizacji’, program spróbuje użyć ścieżki zapisanej w archiwum; w przeciwnym razie użyje katalogu wyjściowego lub folderu domyślnego.",
            wraplength=760,
            justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 10))

        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Button(buttons, text="Czytaj nagłówek", command=self.load_archive_header).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Test integralności", command=self.start_verify_archive).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Dekoduj", command=self.start_decode).pack(side="left")

    def _build_settings(self, parent):
        frm = ttk.LabelFrame(parent, text="Ustawienia", padding=10)
        frm.grid(row=0, column=0, sticky="ew")
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Katalog wyjściowy:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frm, textvariable=self.output_dir_var).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(frm, text="Wybierz…", command=self.choose_output_dir).grid(row=0, column=2, pady=4)

        ttk.Separator(frm, orient="horizontal").grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)

        ttk.Label(frm, text="Tryb kompresji:").grid(row=2, column=0, sticky="w", pady=4)
        row = ttk.Frame(frm)
        row.grid(row=2, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(row, text="Jeden algorytm", variable=self.algo_mode_var, value="single").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(row, text="Minimum z wybranych", variable=self.algo_mode_var, value="auto").pack(side="left")

        ttk.Label(frm, text="Algorytm:").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(frm, state="readonly", values=AVAILABLE_ALGOS, textvariable=self.single_algo_var).grid(row=3, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frm, text="Poziom:").grid(row=3, column=2, sticky="e", pady=4)
        ttk.Spinbox(frm, from_=0, to=9, textvariable=self.level_var, width=6).grid(row=3, column=2, sticky="w", padx=(54, 0), pady=4)

        ttk.Label(frm, text="Auto-test algorytmów:").grid(row=4, column=0, sticky="nw", pady=4)
        auto_box = ttk.Frame(frm)
        auto_box.grid(row=4, column=1, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(auto_box, text="zlib", variable=self.auto_zlib_var).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(auto_box, text="gzip", variable=self.auto_gzip_var).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(auto_box, text="bz2", variable=self.auto_bz2_var).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(auto_box, text="lzma", variable=self.auto_lzma_var).pack(side="left")

        ttk.Label(frm, text="Rozmiar porcji:").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Combobox(frm, state="readonly", values=["256 KB", "512 KB", "1 MB", "4 MB"], textvariable=self.chunk_var, width=12).grid(row=5, column=1, sticky="w", padx=6, pady=4)

        ttk.Checkbutton(frm, text="Nadpisuj istniejące pliki", variable=self.overwrite_var).grid(row=6, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Checkbutton(frm, text="Weryfikuj SHA-256 przy dekodowaniu", variable=self.verify_hash_var).grid(row=7, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Checkbutton(frm, text="Przywracaj znacznik czasu pliku po dekodowaniu", variable=self.restore_mtime_var).grid(row=8, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Checkbutton(frm, text="Przywracaj do oryginalnej lokalizacji, jeśli istnieje", variable=self.prefer_original_path_var).grid(row=9, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Checkbutton(frm, text="Jeśli źródłem był tekst, po dekodowaniu załaduj go też do pola", variable=self.load_text_on_decode_var).grid(row=10, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Checkbutton(frm, text="Otwórz folder po zakończeniu", variable=self.open_folder_var).grid(row=11, column=0, columnspan=3, sticky="w", pady=2)

        btns = ttk.Frame(frm)
        btns.grid(row=12, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Button(btns, text="Anuluj", command=self.cancel_current_job).pack(side="left")
        ttk.Button(btns, text="Otwórz ostatni folder", command=self.open_last_output_folder).pack(side="left", padx=(8, 0))

    def _build_status(self, parent):
        frm = ttk.LabelFrame(parent, text="Status i rozmiary", padding=10)
        frm.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        frm.columnconfigure(0, weight=1)

        ttk.Label(frm, textvariable=self.status_var, wraplength=380, justify="left").grid(row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        ttk.Label(frm, textvariable=self.progress_text_var).grid(row=2, column=0, sticky="w")
        ttk.Label(frm, textvariable=self.eta_var).grid(row=3, column=0, sticky="w", pady=(2, 6))
        ttk.Label(frm, textvariable=self.input_size_var).grid(row=4, column=0, sticky="w", pady=1)
        ttk.Label(frm, textvariable=self.estimate_size_var).grid(row=5, column=0, sticky="w", pady=1)
        ttk.Label(frm, textvariable=self.actual_size_var).grid(row=6, column=0, sticky="w", pady=1)

    def _build_log(self, parent):
        frm = ttk.LabelFrame(parent, text="Dziennik", padding=10)
        frm.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        parent.rowconfigure(2, weight=1)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)

        self.log_box = tk.Text(frm, height=16, wrap="word", state="disabled", font=("Consolas", 10))
        self.log_box.grid(row=0, column=0, sticky="nsew")

    def log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{timestamp}] {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def get_chunk_size(self) -> int:
        mapping = {
            "256 KB": 256 * 1024,
            "512 KB": 512 * 1024,
            "1 MB": 1024 * 1024,
            "4 MB": 4 * 1024 * 1024,
        }
        return mapping.get(self.chunk_var.get().strip().upper().replace("MB", " MB").replace("KB", " KB"), DEFAULT_CHUNK)

    def get_auto_algos(self) -> list[str]:
        algos = []
        if self.auto_zlib_var.get() and "zlib" in AVAILABLE_ALGOS:
            algos.append("zlib")
        if self.auto_gzip_var.get() and "gzip" in AVAILABLE_ALGOS:
            algos.append("gzip")
        if self.auto_bz2_var.get() and "bz2" in AVAILABLE_ALGOS:
            algos.append("bz2")
        if self.auto_lzma_var.get() and "lzma" in AVAILABLE_ALGOS:
            algos.append("lzma")
        return algos

    def choose_file(self):
        path = filedialog.askopenfilename(title="Wybierz plik do zakodowania")
        if path:
            self.file_path_var.set(path)
            self.update_file_info()

    def choose_archive(self):
        path = filedialog.askopenfilename(
            title="Wybierz archiwum do dekodowania",
            filetypes=[("PyLossless (*.pylc)", f"*{CONTAINER_EXT}"), ("Wszystkie pliki", "*")],
        )
        if path:
            self.decode_path_var.set(path)
            self.load_archive_header()

    def choose_output_dir(self):
        path = filedialog.askdirectory(title="Wybierz katalog wyjściowy")
        if path:
            self.output_dir_var.set(path)

    def load_text_from_file(self):
        path = filedialog.askopenfilename(title="Wybierz plik tekstowy")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = Path(path).read_text(encoding="cp1250")
            except Exception as e:
                messagebox.showerror("Błąd", f"Nie udało się wczytać tekstu z pliku:\n{e}")
                return
        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się wczytać pliku:\n{e}")
            return

        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", text)
        self.text_name_var.set(Path(path).name)
        self.on_text_modified()

    def update_file_info(self):
        path_str = self.file_path_var.get().strip()
        if not path_str:
            self.file_info_var.set("Plik: —")
            self.input_size_var.set("Wejście: —")
            return

        p = Path(path_str)
        if not p.exists():
            self.file_info_var.set("Plik: wskazana ścieżka nie istnieje.")
            self.input_size_var.set("Wejście: —")
            return

        size = p.stat().st_size
        self.file_info_var.set(f"Plik: {p.name} | {human_size(size)} | {p}")
        self.input_size_var.set(f"Wejście: {human_size(size)}")

    def on_text_modified(self, event=None):
        try:
            self.text_box.edit_modified(False)
        except Exception:
            pass
        text = self.text_box.get("1.0", "end-1c")
        char_count = len(text)
        byte_count = len(text.encode("utf-8"))
        self.text_info_var.set(f"Tekst: {char_count} znaków / {human_size(byte_count)}")
        self.input_size_var.set(f"Wejście: {human_size(byte_count)}")

    def load_archive_header(self):
        path_str = self.decode_path_var.get().strip()
        if not path_str:
            return
        try:
            header, _ = read_container_header(Path(path_str))
            self.header_info_var.set("\n".join([
                f"Nazwa oryginalna: {header.get('original_name', '—')}",
                f"Typ źródła: {header.get('source_mode', '—')}",
                f"Algorytm: {header.get('algorithm', '—')} | poziom {header.get('level', '—')}",
                f"Rozmiar oryginału: {human_size(int(header.get('original_size') or 0))}",
                f"Oryginalna lokalizacja: {header.get('original_parent') or '—'}",
            ]))
        except Exception as e:
            self.header_info_var.set(f"Nie udało się odczytać nagłówka: {e}")

    def get_file_source(self) -> SourceSpec:
        path_str = self.file_path_var.get().strip()
        if not path_str:
            raise ValueError("Wybierz plik wejściowy.")
        p = Path(path_str)
        if not p.exists() or not p.is_file():
            raise ValueError("Wskazany plik nie istnieje lub nie jest plikiem.")
        return SourceSpec(mode="file", file_path=p, text_bytes=None, text_name=p.name)

    def get_text_source(self) -> SourceSpec:
        text = self.text_box.get("1.0", "end-1c")
        data = text.encode("utf-8")
        if not data and text == "":
            raise ValueError("Pole tekstowe jest puste.")
        name = self.text_name_var.get().strip() or "tekst_wejsciowy.txt"
        return SourceSpec(mode="text", file_path=None, text_bytes=data, text_name=name, text_encoding="utf-8")

    def reset_progress(self):
        self.progress["value"] = 0
        self.progress_text_var.set("0%")
        self.eta_var.set("Pozostały czas: —")
        self.progress_start_time = time.time()

    def update_progress(self, done: int, total: int, phase: str):
        total = max(total, 1)
        pct = min(100.0, (done / total) * 100.0)
        self.progress["value"] = pct
        self.progress_text_var.set(f"{pct:5.1f}% | {phase}")

        elapsed = max(0.001, time.time() - self.progress_start_time)
        speed = done / elapsed
        remaining = (total - done) / speed if speed > 0 else float("inf")
        self.eta_var.set(f"Pozostały czas: {format_seconds(remaining)} | {human_size(speed)}/s")

    def start_worker(self, task: str, fn: Callable, **kwargs):
        if self.current_worker and self.current_worker.is_alive():
            messagebox.showwarning("Uwaga", "Inne zadanie jest już w toku.")
            return
        self.cancel_event.clear()
        self.reset_progress()
        self.status_var.set("Przetwarzanie…")
        self.current_worker = Worker(self, task, fn, **kwargs)
        self.current_worker.start()

    def start_encode_file(self):
        try:
            source = self.get_file_source()
        except Exception as e:
            messagebox.showerror("Błąd", str(e))
            return

        self.start_worker(
            "encode_file",
            compress_job,
            source=source,
            output_dir=self.output_dir_var.get().strip() or None,
            algo_mode=self.algo_mode_var.get(),
            algo_single=self.single_algo_var.get(),
            auto_enabled=self.get_auto_algos(),
            level=self.level_var.get(),
            chunk_size=self._chunk_value(),
            overwrite=self.overwrite_var.get(),
            cancel_event=self.cancel_event,
            progress_cb=lambda done, total, phase: self.queue.put({"type": "progress", "done": done, "total": total, "phase": phase}),
            log_cb=lambda msg: self.queue.put({"type": "log", "message": msg}),
        )

    def start_encode_text(self):
        try:
            source = self.get_text_source()
        except Exception as e:
            messagebox.showerror("Błąd", str(e))
            return

        self.start_worker(
            "encode_text",
            compress_job,
            source=source,
            output_dir=self.output_dir_var.get().strip() or None,
            algo_mode=self.algo_mode_var.get(),
            algo_single=self.single_algo_var.get(),
            auto_enabled=self.get_auto_algos(),
            level=self.level_var.get(),
            chunk_size=self._chunk_value(),
            overwrite=self.overwrite_var.get(),
            cancel_event=self.cancel_event,
            progress_cb=lambda done, total, phase: self.queue.put({"type": "progress", "done": done, "total": total, "phase": phase}),
            log_cb=lambda msg: self.queue.put({"type": "log", "message": msg}),
        )

    def start_decode(self):
        path_str = self.decode_path_var.get().strip()
        if not path_str:
            messagebox.showerror("Błąd", "Wybierz archiwum do dekodowania.")
            return

        arc = Path(path_str)
        if not arc.exists():
            messagebox.showerror("Błąd", "Archiwum nie istnieje.")
            return

        self.start_worker(
            "decode",
            decompress_job,
            archive_path=arc,
            output_dir=self.output_dir_var.get().strip() or None,
            chunk_size=self._chunk_value(),
            overwrite=self.overwrite_var.get(),
            prefer_original_path=self.prefer_original_path_var.get(),
            verify_hash=self.verify_hash_var.get(),
            restore_mtime=self.restore_mtime_var.get(),
            cancel_event=self.cancel_event,
            progress_cb=lambda done, total, phase: self.queue.put({"type": "progress", "done": done, "total": total, "phase": phase}),
            log_cb=lambda msg: self.queue.put({"type": "log", "message": msg}),
            load_text_to_memory=self.load_text_on_decode_var.get(),
        )

    def start_verify_archive(self):
        path_str = self.decode_path_var.get().strip()
        if not path_str:
            messagebox.showerror("Błąd", "Wybierz archiwum do sprawdzenia.")
            return

        arc = Path(path_str)
        if not arc.exists():
            messagebox.showerror("Błąd", "Archiwum nie istnieje.")
            return

        self.start_worker(
            "verify",
            verify_archive_job,
            archive_path=arc,
            chunk_size=self._chunk_value(),
            cancel_event=self.cancel_event,
            progress_cb=lambda done, total, phase: self.queue.put({"type": "progress", "done": done, "total": total, "phase": phase}),
            log_cb=lambda msg: self.queue.put({"type": "log", "message": msg}),
        )

    def start_estimate_from_file(self):
        try:
            source = self.get_file_source()
        except Exception as e:
            messagebox.showerror("Błąd", str(e))
            return

        self.start_worker(
            "estimate",
            estimate_output,
            source=source,
            chunk_size=self._chunk_value(),
            algo_mode=self.algo_mode_var.get(),
            algo_single=self.single_algo_var.get(),
            auto_enabled=self.get_auto_algos(),
            level=self.level_var.get(),
        )

    def start_estimate_from_text(self):
        try:
            source = self.get_text_source()
        except Exception as e:
            messagebox.showerror("Błąd", str(e))
            return

        self.start_worker(
            "estimate",
            estimate_output,
            source=source,
            chunk_size=self._chunk_value(),
            algo_mode=self.algo_mode_var.get(),
            algo_single=self.single_algo_var.get(),
            auto_enabled=self.get_auto_algos(),
            level=self.level_var.get(),
        )

    def cancel_current_job(self):
        if self.current_worker and self.current_worker.is_alive():
            self.cancel_event.set()
            self.status_var.set("Anulowanie…")
            self.log("Wysłano żądanie anulowania zadania.")

    def open_last_output_folder(self):
        if not self.last_output_file:
            messagebox.showinfo("Informacja", "Brak ostatniego pliku wynikowego.")
            return
        self.open_folder(self.last_output_file.parent)

    def open_folder(self, path: Path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(path)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showwarning("Uwaga", f"Nie udało się otworzyć folderu:\n{e}")

    def _poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                t = item.get("type")

                if t == "progress":
                    self.update_progress(item["done"], item["total"], item["phase"])
                elif t == "log":
                    self.log(item["message"])
                elif t == "done":
                    self.handle_done(item)
                elif t == "error":
                    self.handle_error(item)
                elif t == "cancelled":
                    self.handle_cancelled(item)

        except queue.Empty:
            pass

        self.after(QUEUE_POLL_MS, self._poll_queue)

    def handle_done(self, item: dict):
        task = item["task"]
        result = item["result"]
        elapsed = item.get("elapsed", 0.0)
        self.current_worker = None

        if task == "estimate":
            best_algo = result["best_algo"]
            best_size = result["best_size"]
            kind = result["kind"]
            details = ", ".join(f"{k.upper()}: {human_size(v)}" for k, v in result["results"].items())
            self.estimate_size_var.set(
                f"Szacowany wynik: {human_size(best_size)} | najlepszy: {best_algo.upper()} | tryb: {'dokładny' if kind == 'exact' else 'z próbki'}"
            )
            self.status_var.set(f"Oszacowanie gotowe w {elapsed:.1f}s")
            self.log(f"Oszacowanie ({kind}): {details}")
            return

        if task in {"encode_file", "encode_text"}:
            self.last_output_file = Path(result["dest"])
            self.actual_size_var.set(
                f"Ostatni wynik: {human_size(result['size'])} | algorytm: {result['algorithm'].upper()} | współczynnik: {result['ratio']:.2f}%"
            )
            self.estimate_size_var.set("Szacowany wynik: —")
            self.status_var.set(f"Kodowanie zakończone w {elapsed:.1f}s")
            self.log(
                f"Zapisano: {result['dest']} | wejście {human_size(result['source_size'])} -> wyjście {human_size(result['size'])} | {result['algorithm'].upper()}"
            )
            if self.open_folder_var.get() and self.last_output_file:
                self.open_folder(self.last_output_file.parent)
            return

        if task == "decode":
            self.last_output_file = Path(result["dest"])
            self.actual_size_var.set(
                f"Ostatni wynik: {human_size(result['size'])} | zdekompresowano algorytmem: {result['algorithm'].upper()}"
            )
            self.status_var.set(f"Dekodowanie zakończone w {elapsed:.1f}s")
            self.log(f"Odzyskano plik: {result['dest']}")

            if result.get("source_mode") == "text" and result.get("text") is not None and self.load_text_on_decode_var.get():
                self.text_box.delete("1.0", "end")
                self.text_box.insert("1.0", result["text"])
                self.on_text_modified()
                self.notebook.select(1)
                self.log("Załadowano odzyskany tekst do pola tekstowego.")

            if self.open_folder_var.get() and self.last_output_file:
                self.open_folder(self.last_output_file.parent)
            return

        if task == "verify":
            ok = result["ok"]
            self.status_var.set(f"Test integralności zakończony w {elapsed:.1f}s")
            self.log(
                "Test integralności: "
                + ("OK" if ok else "NIEPOWODZENIE")
                + f" | oczekiwany SHA-256: {result['expected_hash']} | obliczony: {result['actual_hash']}"
            )
            messagebox.showinfo(
                "Test integralności",
                "Integralność potwierdzona." if ok else "Integralność nie została potwierdzona. Sprawdź dziennik.",
            )
            return

    def handle_error(self, item: dict):
        self.current_worker = None
        self.status_var.set(f"Błąd: {item['message']}")
        self.log(item["traceback"])
        messagebox.showerror("Błąd", item["message"])

    def handle_cancelled(self, item: dict):
        self.current_worker = None
        self.status_var.set("Operacja anulowana.")
        self.log(item.get("message", "Operacja anulowana."))

    def _chunk_value(self) -> int:
        value = self.chunk_var.get().strip().upper()
        mapping = {
            "256 KB": 256 * 1024,
            "512 KB": 512 * 1024,
            "1 MB": 1024 * 1024,
            "4 MB": 4 * 1024 * 1024,
        }
        return mapping.get(value, DEFAULT_CHUNK)

    def _load_settings(self):
        if not SETTINGS_FILE.exists():
            self.update_file_info()
            self.on_text_modified()
            return

        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self.output_dir_var.set(data.get("output_dir", ""))
            self.algo_mode_var.set(data.get("algo_mode", "single"))
            if data.get("single_algo") in AVAILABLE_ALGOS:
                self.single_algo_var.set(data.get("single_algo"))
            self.level_var.set(int(data.get("level", 6)))
            self.chunk_var.set(data.get("chunk", "1 MB"))
            self.overwrite_var.set(bool(data.get("overwrite", False)))
            self.verify_hash_var.set(bool(data.get("verify_hash", True)))
            self.restore_mtime_var.set(bool(data.get("restore_mtime", True)))
            self.prefer_original_path_var.set(bool(data.get("prefer_original_path", True)))
            self.load_text_on_decode_var.set(bool(data.get("load_text_on_decode", True)))
            self.open_folder_var.set(bool(data.get("open_folder", False)))
            self.auto_zlib_var.set(bool(data.get("auto_zlib", self.auto_zlib_var.get())))
            self.auto_gzip_var.set(bool(data.get("auto_gzip", self.auto_gzip_var.get())))
            self.auto_bz2_var.set(bool(data.get("auto_bz2", self.auto_bz2_var.get())))
            self.auto_lzma_var.set(bool(data.get("auto_lzma", self.auto_lzma_var.get())))
        except Exception as e:
            self.log(f"Nie udało się wczytać ustawień: {e}")

        self.update_file_info()
        self.on_text_modified()

    def _save_settings(self):
        data = {
            "output_dir": self.output_dir_var.get(),
            "algo_mode": self.algo_mode_var.get(),
            "single_algo": self.single_algo_var.get(),
            "level": self.level_var.get(),
            "chunk": self.chunk_var.get(),
            "overwrite": self.overwrite_var.get(),
            "verify_hash": self.verify_hash_var.get(),
            "restore_mtime": self.restore_mtime_var.get(),
            "prefer_original_path": self.prefer_original_path_var.get(),
            "load_text_on_decode": self.load_text_on_decode_var.get(),
            "open_folder": self.open_folder_var.get(),
            "auto_zlib": self.auto_zlib_var.get(),
            "auto_gzip": self.auto_gzip_var.get(),
            "auto_bz2": self.auto_bz2_var.get(),
            "auto_lzma": self.auto_lzma_var.get(),
        }
        try:
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def destroy(self):
        self._save_settings()
        super().destroy()


def main():
    if not AVAILABLE_ALGOS:
        raise RuntimeError("Ten interpreter Pythona nie ma dostępnego żadnego modułu kompresji z zestawu: zlib/gzip/bz2/lzma.")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
