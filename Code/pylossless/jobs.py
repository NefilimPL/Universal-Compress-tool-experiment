from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Callable, Iterable, Optional

from .algorithms import (
    AVAILABLE_ALGOS,
    bz2,
    clamp_level,
    ensure_algorithm_available,
    gzip,
    lzma,
    open_compressed_writer,
    zlib,
)
from .constants import CONTAINER_EXT, DEFAULT_CHUNK
from .container import build_header, read_container_header, write_header
from .models import CancelledError, SourceSpec
from .paths import DEFAULT_DECODE_DIR, DEFAULT_ENCODE_DIR
from .utils import (
    atomic_replace,
    choose_final_dest,
    create_temp_in_dir,
    ensure_dir,
    human_size,
    safe_stem,
)


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
        with source.file_path.open("rb") as file_obj:
            while True:
                data = file_obj.read(chunk_size)
                if not data:
                    break
                yield data
        return

    data = source.text_bytes or b""
    for index in range(0, len(data), chunk_size):
        yield data[index:index + chunk_size]


def compute_sha256(
    source: SourceSpec,
    chunk_size: int,
    cancel_event: threading.Event,
    progress_cb: Callable[[int, int, str], None],
) -> str:
    total = source.total_size
    done = 0
    digest = hashlib.sha256()
    if total == 0:
        progress_cb(0, 0, "Analiza wej?cia (SHA-256)")
        return digest.hexdigest()

    for chunk in iter_source_chunks(source, chunk_size):
        if cancel_event.is_set():
            raise CancelledError("Operacja zosta?a anulowana.")
        digest.update(chunk)
        done += len(chunk)
        progress_cb(done, total, "Analiza wej?cia (SHA-256)")
    return digest.hexdigest()


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
    with dest_path.open("wb") as raw_file:
        write_header(raw_file, header)
        writer = open_compressed_writer(algo, raw_file, level)
        try:
            for chunk in iter_source_chunks(source, chunk_size):
                if cancel_event.is_set():
                    raise CancelledError("Operacja zosta?a anulowana.")
                writer.write(chunk)
                done += len(chunk)
                progress_cb(done, total, f"Kompresja: {algo.upper()}")
        finally:
            writer.close()
    return dest_path.stat().st_size


def estimate_size_bytes(data: bytes, algo: str, level: int) -> int:
    temp_dir = tempfile.mkdtemp(prefix="pylossless_est_")
    try:
        source = SourceSpec(
            mode="text",
            file_path=None,
            text_bytes=data,
            text_name="estimate.bin",
            text_encoding="utf-8",
        )
        sha = hashlib.sha256(data).hexdigest()
        header = build_header(source, algo, level, sha)
        path = Path(temp_dir) / f"estimate_{algo}{CONTAINER_EXT}"
        return compress_to_container(
            source,
            algo,
            level,
            path,
            DEFAULT_CHUNK,
            header,
            threading.Event(),
            lambda _a, _b, _c: None,
        )
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
    _ = chunk_size
    total = source.total_size
    exact_limit = 16 * 1024 * 1024
    sample_limit = 4 * 1024 * 1024

    if source.mode == "file":
        assert source.file_path is not None
        with source.file_path.open("rb") as file_obj:
            sample = file_obj.read(exact_limit if total <= exact_limit else sample_limit)
    else:
        data = source.text_bytes or b""
        sample = data if len(data) <= exact_limit else data[:sample_limit]

    algos = [algo_single] if algo_mode == "single" else [algo for algo in auto_enabled if algo in AVAILABLE_ALGOS]
    if not algos:
        raise ValueError("Brak aktywnych algorytm?w do oszacowania.")

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
        raise ValueError("Nie wskazano pliku wej?ciowego.")
    if source.mode == "text" and source.text_bytes is None:
        raise ValueError("Brak tekstu do zakodowania.")

    base_dir = resolve_encode_output_dir(source, output_dir)
    base_name = f"{safe_stem(source.original_name)}{CONTAINER_EXT}"
    final_dest = choose_final_dest(base_dir, base_name, overwrite)

    candidate_algos = [algo_single] if algo_mode == "single" else [algo for algo in auto_enabled if algo in AVAILABLE_ALGOS]
    if not candidate_algos:
        raise ValueError("Brak wybranych algorytm?w do kompresji.")

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
        for index, algo in enumerate(candidate_algos, start=1):
            if cancel_event.is_set():
                raise CancelledError("Operacja zosta?a anulowana.")

            used_level = clamp_level(algo, level)
            header = build_header(source, algo, used_level, sha)
            temp_path = create_temp_in_dir(base_dir, CONTAINER_EXT)
            log_cb(f"Test {index}/{len(candidate_algos)}: {algo.upper()} (poziom {used_level})")

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
            raise RuntimeError("Nie uda?o si? wygenerowa? pliku wynikowego.")

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


def _copy_decompressed_stream(
    stream,
    label: str,
    chunk_size: int,
    cancel_event: threading.Event,
    progress_cb: Callable[[int, int, str], None],
    total_out: int,
    out_file,
    digest,
) -> int:
    done_out = 0
    while True:
        if cancel_event.is_set():
            raise CancelledError("Operacja zosta?a anulowana.")
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        if out_file is not None:
            out_file.write(chunk)
        if digest is not None:
            digest.update(chunk)
        done_out += len(chunk)
        progress_cb(done_out, total_out, label)
    return done_out


def _stream_decompress_zlib(
    in_file,
    out_file,
    chunk_size: int,
    cancel_event: threading.Event,
    progress_cb: Callable[[int, int, str], None],
    total_out: int,
    digest,
) -> int:
    ensure_algorithm_available("zlib")
    decomp = zlib.decompressobj()
    done_out = 0

    def handle(data: bytes) -> None:
        nonlocal done_out
        if out_file is not None:
            out_file.write(data)
        if digest is not None:
            digest.update(data)
        done_out += len(data)
        progress_cb(done_out, total_out, "Dekompresja: ZLIB")

    while True:
        if cancel_event.is_set():
            raise CancelledError("Operacja zosta?a anulowana.")

        comp_chunk = in_file.read(chunk_size)
        if not comp_chunk:
            tail = decomp.flush()
            if tail:
                handle(tail)
            if not decomp.eof:
                raise ValueError("Strumie? zlib jest niekompletny lub uszkodzony.")
            break

        data = decomp.decompress(comp_chunk)
        if data:
            handle(data)

        while decomp.unconsumed_tail:
            data = decomp.decompress(decomp.unconsumed_tail)
            if not data:
                break
            handle(data)

        if decomp.eof:
            break

    return done_out


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
        digest = hashlib.sha256() if verify_hash else None
        with archive_path.open("rb") as raw_in, temp_out.open("wb") as out_file:
            raw_in.seek(payload_offset)

            if algo == "gzip":
                ensure_algorithm_available("gzip")
                with gzip.GzipFile(fileobj=raw_in, mode="rb") as gz:
                    done_out = _copy_decompressed_stream(
                        gz,
                        "Dekompresja: GZIP",
                        chunk_size,
                        cancel_event,
                        progress_cb,
                        total_out,
                        out_file,
                        digest,
                    )
            elif algo == "bz2":
                ensure_algorithm_available("bz2")
                with bz2.BZ2File(raw_in, mode="rb") as bz:
                    done_out = _copy_decompressed_stream(
                        bz,
                        "Dekompresja: BZ2",
                        chunk_size,
                        cancel_event,
                        progress_cb,
                        total_out,
                        out_file,
                        digest,
                    )
            elif algo == "lzma":
                ensure_algorithm_available("lzma")
                with lzma.LZMAFile(raw_in, mode="rb") as xz:
                    done_out = _copy_decompressed_stream(
                        xz,
                        "Dekompresja: LZMA",
                        chunk_size,
                        cancel_event,
                        progress_cb,
                        total_out,
                        out_file,
                        digest,
                    )
            elif algo == "zlib":
                done_out = _stream_decompress_zlib(
                    raw_in,
                    out_file,
                    chunk_size,
                    cancel_event,
                    progress_cb,
                    total_out,
                    digest,
                )
            else:
                raise ValueError(f"Nieznany algorytm w archiwum: {algo}")

        actual_size = temp_out.stat().st_size
        if actual_size != total_out:
            raise ValueError(f"Rozmiar po dekodowaniu nie zgadza si? z nag??wkiem: {actual_size} != {total_out}.")
        if done_out != actual_size:
            raise ValueError("Liczba zdekodowanych bajt?w nie zgadza si? z rozmiarem pliku tymczasowego.")

        if verify_hash:
            expected = header.get("original_sha256")
            actual_digest = digest.hexdigest() if digest is not None else None
            if expected and actual_digest != expected:
                raise ValueError("Weryfikacja SHA-256 nie powiod?a si?. Plik lub archiwum mo?e by? uszkodzone.")

        if restore_mtime and header.get("mtime_ns") is not None:
            mtime_ns = int(header["mtime_ns"])
            os.utime(temp_out, ns=(mtime_ns, mtime_ns))

        atomic_replace(temp_out, final_path)

        text_value = None
        if load_text_to_memory and header.get("source_mode") == "text":
            encoding = header.get("text_encoding") or "utf-8"
            try:
                text_value = final_path.read_text(encoding=encoding)
            except Exception as exc:
                log_cb(f"Nie uda?o si? za?adowa? odzyskanego tekstu do pola ({encoding}): {exc}")

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
    digest = hashlib.sha256() if expected_hash else None

    log_cb(f"Test integralno?ci: {algo}")

    with archive_path.open("rb") as raw_in:
        raw_in.seek(payload_offset)

        if algo == "gzip":
            ensure_algorithm_available("gzip")
            with gzip.GzipFile(fileobj=raw_in, mode="rb") as gz:
                done_out = _copy_decompressed_stream(
                    gz,
                    "Test integralno?ci: GZIP",
                    chunk_size,
                    cancel_event,
                    progress_cb,
                    total_out,
                    None,
                    digest,
                )
        elif algo == "bz2":
            ensure_algorithm_available("bz2")
            with bz2.BZ2File(raw_in, mode="rb") as bz:
                done_out = _copy_decompressed_stream(
                    bz,
                    "Test integralno?ci: BZ2",
                    chunk_size,
                    cancel_event,
                    progress_cb,
                    total_out,
                    None,
                    digest,
                )
        elif algo == "lzma":
            ensure_algorithm_available("lzma")
            with lzma.LZMAFile(raw_in, mode="rb") as xz:
                done_out = _copy_decompressed_stream(
                    xz,
                    "Test integralno?ci: LZMA",
                    chunk_size,
                    cancel_event,
                    progress_cb,
                    total_out,
                    None,
                    digest,
                )
        elif algo == "zlib":
            done_out = _stream_decompress_zlib(
                raw_in,
                None,
                chunk_size,
                cancel_event,
                progress_cb,
                total_out,
                digest,
            )
        else:
            raise ValueError(f"Nieobs?ugiwany algorytm: {algo}")

    actual_hash = digest.hexdigest() if digest is not None else None
    size_ok = done_out == total_out
    hash_checked = bool(expected_hash)
    hash_ok = (actual_hash == expected_hash) if hash_checked else True
    return {
        "ok": size_ok and hash_ok,
        "size_ok": size_ok,
        "hash_ok": hash_ok,
        "hash_checked": hash_checked,
        "expected_hash": expected_hash,
        "actual_hash": actual_hash,
        "bytes_verified": done_out,
        "header": header,
    }
