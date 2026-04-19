from __future__ import annotations

import json
import struct
import time
from pathlib import Path

from .constants import APP_NAME, APP_VERSION, HEADER_FMT, MAGIC
from .models import SourceSpec


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
    with path.open("rb") as file_obj:
        magic = file_obj.read(len(MAGIC))
        if magic != MAGIC:
            raise ValueError("To nie jest plik w formacie PYLC1.")
        length_raw = file_obj.read(struct.calcsize(HEADER_FMT))
        if len(length_raw) != struct.calcsize(HEADER_FMT):
            raise ValueError("Uszkodzony nagłówek pliku.")
        header_len = struct.unpack(HEADER_FMT, length_raw)[0]
        header_bytes = file_obj.read(header_len)
        if len(header_bytes) != header_len:
            raise ValueError("Nagłówek pliku jest niekompletny.")
        header = json.loads(header_bytes.decode("utf-8"))
        payload_offset = len(MAGIC) + struct.calcsize(HEADER_FMT) + header_len
        return header, payload_offset
