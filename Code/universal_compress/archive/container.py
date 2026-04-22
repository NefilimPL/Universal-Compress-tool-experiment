from __future__ import annotations

import struct
from pathlib import Path

MAGIC = b"UCA1"
HEADER_STRUCT = struct.Struct("<I")


def write_container_header(path: Path, manifest_length: int, protection: str) -> None:
    path.write_bytes(MAGIC + HEADER_STRUCT.pack(manifest_length) + protection.encode("utf-8"))


def read_container_header(path: Path) -> dict[str, int | str]:
    raw = path.read_bytes()
    if raw[: len(MAGIC)] != MAGIC:
        raise ValueError("Invalid UCA container magic.")

    manifest_length = HEADER_STRUCT.unpack(raw[len(MAGIC) : len(MAGIC) + HEADER_STRUCT.size])[0]
    protection = raw[len(MAGIC) + HEADER_STRUCT.size :].decode("utf-8")
    return {
        "magic": MAGIC.decode("ascii"),
        "manifest_length": manifest_length,
        "protection": protection,
    }
