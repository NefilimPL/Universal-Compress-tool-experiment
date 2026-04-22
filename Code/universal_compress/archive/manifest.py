from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class ArchiveEntry:
    relative_path: PurePosixPath
    original_size: int
    stored_size: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "relative_path": self.relative_path.as_posix(),
            "original_size": self.original_size,
            "stored_size": self.stored_size,
        }


@dataclass(frozen=True)
class ArchiveManifest:
    entries: list[ArchiveEntry]
    protection: str
    compression_method: str

    def to_bytes(self) -> bytes:
        payload = {
            "entries": [entry.to_dict() for entry in self.entries],
            "protection": self.protection,
            "compression_method": self.compression_method,
        }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ArchiveManifest":
        payload = json.loads(raw.decode("utf-8"))
        return cls(
            entries=[
                ArchiveEntry(
                    relative_path=PurePosixPath(entry["relative_path"]),
                    original_size=entry["original_size"],
                    stored_size=entry["stored_size"],
                )
                for entry in payload["entries"]
            ],
            protection=payload["protection"],
            compression_method=payload["compression_method"],
        )
