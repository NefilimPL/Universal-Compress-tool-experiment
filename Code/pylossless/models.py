from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class CancelledError(Exception):
    pass


@dataclass
class SourceSpec:
    mode: str
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
