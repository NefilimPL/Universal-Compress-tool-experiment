from __future__ import annotations

import struct
import threading
from collections.abc import Callable
from pathlib import Path

import zstandard as zstd

from .container import HEADER_STRUCT, MAGIC
from .manifest import ArchiveEntry, ArchiveManifest
from ..models import ArchivePlan, CancelledError, SourceItem

RECORD_HEADER = struct.Struct("<II")


class ArchiveService:
    def create_archive(
        self,
        sources: list[SourceItem],
        plan: ArchivePlan,
        progress_callback: Callable[[int, int, SourceItem], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        compressor = zstd.ZstdCompressor(level=6)
        entries: list[ArchiveEntry] = []
        payload_parts: list[tuple[bytes, bytes]] = []

        try:
            total = len(sources)
            for index, source in enumerate(sources, start=1):
                self._ensure_not_cancelled(cancel_event)
                raw = source.source_path.read_bytes()
                stored = compressor.compress(raw)
                path_bytes = source.relative_path.as_posix().encode("utf-8")
                payload_parts.append((path_bytes, stored))
                entries.append(
                    ArchiveEntry(
                        relative_path=source.relative_path,
                        original_size=len(raw),
                        stored_size=len(stored),
                    )
                )
                if progress_callback is not None:
                    progress_callback(index, total, source)

            self._ensure_not_cancelled(cancel_event)
            manifest = ArchiveManifest(
                entries=entries,
                protection=plan.protection.value,
                compression_method=plan.compression_method,
            )
            manifest_bytes = manifest.to_bytes()
            protection_bytes = plan.protection.value.encode("utf-8") + b"\n"

            plan.output_path.parent.mkdir(parents=True, exist_ok=True)
            with plan.output_path.open("wb") as handle:
                handle.write(MAGIC)
                handle.write(HEADER_STRUCT.pack(len(manifest_bytes)))
                handle.write(protection_bytes)
                handle.write(manifest_bytes)
                for path_bytes, stored in payload_parts:
                    self._ensure_not_cancelled(cancel_event)
                    handle.write(RECORD_HEADER.pack(len(path_bytes), len(stored)))
                    handle.write(path_bytes)
                    handle.write(stored)
        except Exception:
            plan.output_path.unlink(missing_ok=True)
            raise

        return plan.output_path

    def inspect_archive(self, archive_path: Path) -> ArchiveManifest:
        raw = archive_path.read_bytes()
        if raw[: len(MAGIC)] != MAGIC:
            raise ValueError("Invalid UCA container magic.")

        manifest_length = HEADER_STRUCT.unpack(raw[len(MAGIC) : len(MAGIC) + HEADER_STRUCT.size])[0]
        cursor = len(MAGIC) + HEADER_STRUCT.size
        protection_end = raw.index(b"\n", cursor)
        manifest_start = protection_end + 1
        manifest_end = manifest_start + manifest_length
        return ArchiveManifest.from_bytes(raw[manifest_start:manifest_end])

    def _ensure_not_cancelled(self, cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("Operacja zostala anulowana.")
