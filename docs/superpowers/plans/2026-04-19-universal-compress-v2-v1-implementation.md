# Universal Compress V2 V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working release of Universal Compress V2 with a new PySide6 shell, native `*.uca` archives, batch job execution, archive inspection, protection modes, media presets, and a standard ZIP export path.

**Architecture:** Keep the legacy `Code/pylossless` package intact while introducing a new `Code/universal_compress` package for the rewrite. Build the archive engine and job model first, then layer the Qt shell, archive workflows, media tooling, and adapters on top so each completed task leaves the repo in a working, testable state.

**Tech Stack:** Python 3.13, PySide6, zstandard, cryptography, FFmpeg/FFprobe, pytest, pytest-qt

---

## File Map

New code should live in a clean package tree:

- `Code/universal_compress/__init__.py`: package marker and version constant
- `Code/universal_compress/main.py`: Qt application bootstrap
- `Code/universal_compress/app.py`: app factory and top-level composition
- `Code/universal_compress/models.py`: shared enums, dataclasses, and validation
- `Code/universal_compress/settings.py`: persisted user settings model
- `Code/universal_compress/costs.py`: cost estimation and explanatory hints
- `Code/universal_compress/archive/manifest.py`: archive manifest and entry models
- `Code/universal_compress/archive/container.py`: low-level UCA header/container primitives
- `Code/universal_compress/archive/security.py`: password gate and full encryption helpers
- `Code/universal_compress/archive/service.py`: create, inspect, verify, and extract workflows
- `Code/universal_compress/jobs/queue.py`: queued background execution and job history
- `Code/universal_compress/media/profiles.py`: audio/video profiles and labels
- `Code/universal_compress/media/ffmpeg.py`: FFmpeg command building and analysis helpers
- `Code/universal_compress/adapters/zip_export.py`: ZIP export adapter
- `Code/universal_compress/ui/main_window.py`: main Qt shell
- `Code/universal_compress/ui/source_list.py`: drag/drop source intake
- `Code/universal_compress/ui/inspector.py`: settings and cost explanation panel
- `Code/universal_compress/ui/task_history.py`: active jobs and recent history panel
- `Code/universal_compress/ui/password_dialog.py`: protected archive password prompt

Tests should be created under `tests/universal_compress/` and kept parallel to the new package layout.

This spec spans several subsystems. The plan keeps them in one document, but each task is a vertical slice that should leave the application running and the tests green before moving on.

### Task 1: Bootstrap the New Qt App

**Files:**
- Create: `Code/universal_compress/__init__.py`
- Create: `Code/universal_compress/main.py`
- Create: `Code/universal_compress/app.py`
- Create: `tests/universal_compress/test_main.py`
- Modify: `requirements.txt`
- Modify: `launcher.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/universal_compress/test_main.py
from PySide6.QtWidgets import QApplication

from universal_compress.app import build_main_window
from universal_compress.main import create_application


def test_create_application_and_main_window(qtbot):
    app = create_application()
    window = build_main_window()
    qtbot.addWidget(window)

    assert isinstance(app, QApplication)
    assert window.windowTitle() == "Universal Compress V2"
    assert window.acceptDrops() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/universal_compress/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'universal_compress'`

- [ ] **Step 3: Write minimal implementation**

```python
# Code/universal_compress/__init__.py
__all__ = ["__version__"]
__version__ = "2.0.0a1"
```

```python
# Code/universal_compress/app.py
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget


def build_main_window() -> QMainWindow:
    window = QMainWindow()
    window.setWindowTitle("Universal Compress V2")
    window.setAcceptDrops(True)
    window.resize(1440, 900)

    body = QWidget()
    layout = QVBoxLayout(body)
    layout.addWidget(QLabel("Universal Compress V2"))
    window.setCentralWidget(body)
    return window
```

```python
# Code/universal_compress/main.py
import sys

from PySide6.QtWidgets import QApplication

from .app import build_main_window


def create_application() -> QApplication:
    app = QApplication.instance()
    return app or QApplication(sys.argv)


def main() -> int:
    app = create_application()
    window = build_main_window()
    window.show()
    return app.exec()
```

```python
# launcher.py
from Code.universal_compress.main import main


if __name__ == "__main__":
    raise SystemExit(main())
```

```text
# requirements.txt
PySide6>=6.9,<7
cryptography>=45,<46
zstandard>=0.23,<0.24
pytest>=8.4,<9
pytest-qt>=4.4,<5
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/universal_compress/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt launcher.py Code/universal_compress/__init__.py Code/universal_compress/main.py Code/universal_compress/app.py tests/universal_compress/test_main.py
git commit -m "feat: bootstrap Qt app shell"
```

### Task 2: Add Shared Models, Settings, and Cost Classification

**Files:**
- Create: `Code/universal_compress/models.py`
- Create: `Code/universal_compress/settings.py`
- Create: `Code/universal_compress/costs.py`
- Create: `tests/universal_compress/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/universal_compress/test_models.py
from pathlib import Path
from pathlib import PurePosixPath

import pytest

from universal_compress.costs import classify_operation_cost
from universal_compress.models import ArchivePlan, ArchiveProtection, CostLevel, SourceItem


def test_source_item_from_path_uses_relative_posix_path(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    sample = root / "docs" / "alpha.txt"
    sample.parent.mkdir()
    sample.write_text("hello", encoding="utf-8")

    item = SourceItem.from_path(sample, root)

    assert item.relative_path == PurePosixPath("docs/alpha.txt")
    assert item.size == 5


def test_protected_archive_plan_requires_password(tmp_path):
    with pytest.raises(ValueError):
        ArchivePlan(
            output_path=tmp_path / "secure.uca",
            protection=ArchiveProtection.FULL_ENCRYPTION,
            password=None,
        )


def test_cost_classifier_marks_large_encrypted_work_as_high():
    cost = classify_operation_cost(total_bytes=8 * 1024**3, encrypted=True, media_mode=False)
    assert cost is CostLevel.HIGH
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/universal_compress/test_models.py -v`
Expected: FAIL with `ImportError` for missing modules

- [ ] **Step 3: Write minimal implementation**

```python
# Code/universal_compress/models.py
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath


class ArchiveProtection(str, Enum):
    NONE = "none"
    PASSWORD_GATE = "password_gate"
    FULL_ENCRYPTION = "full_encryption"


class CostLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidPasswordError(ValueError):
    pass


@dataclass(frozen=True)
class SourceItem:
    source_path: Path
    relative_path: PurePosixPath
    size: int

    @classmethod
    def from_path(cls, source_path: Path, root_path: Path) -> "SourceItem":
        return cls(
            source_path=source_path,
            relative_path=PurePosixPath(source_path.relative_to(root_path).as_posix()),
            size=source_path.stat().st_size,
        )


@dataclass(frozen=True)
class ArchivePlan:
    output_path: Path
    protection: ArchiveProtection = ArchiveProtection.NONE
    password: str | None = None
    compression_method: str = "zstd"

    def __post_init__(self) -> None:
        if self.protection is not ArchiveProtection.NONE and not self.password:
            raise ValueError("Protected archives require a password.")
```

```python
# Code/universal_compress/settings.py
from dataclasses import dataclass


@dataclass
class AppSettings:
    simple_mode: bool = True
    theme: str = "system"
    max_parallel_jobs: int = 1
```

```python
# Code/universal_compress/costs.py
from .models import CostLevel


def classify_operation_cost(total_bytes: int, encrypted: bool, media_mode: bool) -> CostLevel:
    if media_mode:
        return CostLevel.HIGH if total_bytes >= 2 * 1024**3 else CostLevel.MEDIUM
    if encrypted and total_bytes >= 2 * 1024**3:
        return CostLevel.HIGH
    if total_bytes >= 512 * 1024**2:
        return CostLevel.MEDIUM
    return CostLevel.LOW
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/universal_compress/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Code/universal_compress/models.py Code/universal_compress/settings.py Code/universal_compress/costs.py tests/universal_compress/test_models.py
git commit -m "feat: add shared v2 models and cost rules"
```

### Task 3: Define the Native UCA Manifest and Container Header

**Files:**
- Create: `Code/universal_compress/archive/__init__.py`
- Create: `Code/universal_compress/archive/manifest.py`
- Create: `Code/universal_compress/archive/container.py`
- Create: `tests/universal_compress/archive/test_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/universal_compress/archive/test_manifest.py
from pathlib import PurePosixPath

from universal_compress.archive.container import read_container_header, write_container_header
from universal_compress.archive.manifest import ArchiveEntry, ArchiveManifest


def test_manifest_round_trip_preserves_entry_data():
    manifest = ArchiveManifest(
        entries=[
            ArchiveEntry(relative_path=PurePosixPath("docs/alpha.txt"), original_size=5, stored_size=7),
        ],
        protection="none",
        compression_method="zstd",
    )

    loaded = ArchiveManifest.from_bytes(manifest.to_bytes())
    assert loaded.entries[0].relative_path == PurePosixPath("docs/alpha.txt")
    assert loaded.compression_method == "zstd"


def test_container_header_round_trip(tmp_path):
    header_path = tmp_path / "header.bin"
    write_container_header(header_path, manifest_length=128, protection="none")
    header = read_container_header(header_path)

    assert header["magic"] == "UCA1"
    assert header["manifest_length"] == 128
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/universal_compress/archive/test_manifest.py -v`
Expected: FAIL with `ImportError` for missing archive modules

- [ ] **Step 3: Write minimal implementation**

```python
# Code/universal_compress/archive/manifest.py
import json
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class ArchiveEntry:
    relative_path: PurePosixPath
    original_size: int
    stored_size: int

    def to_dict(self) -> dict:
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
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ArchiveManifest":
        payload = json.loads(raw.decode("utf-8"))
        return cls(
            entries=[
                ArchiveEntry(
                    relative_path=PurePosixPath(item["relative_path"]),
                    original_size=item["original_size"],
                    stored_size=item["stored_size"],
                )
                for item in payload["entries"]
            ],
            protection=payload["protection"],
            compression_method=payload["compression_method"],
        )
```

```python
# Code/universal_compress/archive/container.py
import json
import struct
from pathlib import Path

MAGIC = b"UCA1"
HEADER_STRUCT = struct.Struct("<I")


def write_container_header(path: Path, manifest_length: int, protection: str) -> None:
    header_bytes = json.dumps(
        {"magic": "UCA1", "manifest_length": manifest_length, "protection": protection},
        separators=(",", ":"),
    ).encode("utf-8")
    path.write_bytes(MAGIC + HEADER_STRUCT.pack(len(header_bytes)) + header_bytes)


def read_container_header(path: Path) -> dict:
    raw = path.read_bytes()
    header_size = HEADER_STRUCT.unpack(raw[len(MAGIC):len(MAGIC) + HEADER_STRUCT.size])[0]
    payload = raw[len(MAGIC) + HEADER_STRUCT.size:len(MAGIC) + HEADER_STRUCT.size + header_size]
    return json.loads(payload.decode("utf-8"))
```

```python
# Code/universal_compress/archive/__init__.py
from .container import read_container_header, write_container_header
from .manifest import ArchiveEntry, ArchiveManifest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/universal_compress/archive/test_manifest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Code/universal_compress/archive/__init__.py Code/universal_compress/archive/manifest.py Code/universal_compress/archive/container.py tests/universal_compress/archive/test_manifest.py
git commit -m "feat: define native UCA manifest primitives"
```

### Task 4: Implement Archive Create, Inspect, and Extract

**Files:**
- Create: `Code/universal_compress/archive/service.py`
- Create: `tests/universal_compress/archive/test_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/universal_compress/archive/test_service.py
from pathlib import Path

from universal_compress.archive.service import ArchiveService
from universal_compress.models import ArchivePlan, ArchiveProtection, SourceItem


def test_create_and_inspect_archive_without_extraction(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    alpha = root / "alpha.txt"
    nested = root / "nested"
    nested.mkdir()
    beta = nested / "beta.txt"
    alpha.write_text("alpha", encoding="utf-8")
    beta.write_text("beta", encoding="utf-8")

    sources = [SourceItem.from_path(alpha, root), SourceItem.from_path(beta, root)]
    service = ArchiveService()
    archive_path = service.create_archive(
        sources=sources,
        plan=ArchivePlan(output_path=tmp_path / "bundle.uca", protection=ArchiveProtection.NONE),
    )

    manifest = service.inspect_archive(archive_path)
    assert [entry.relative_path.as_posix() for entry in manifest.entries] == ["alpha.txt", "nested/beta.txt"]


def test_extract_selected_entries(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    only_file = source_root / "only.txt"
    only_file.write_text("hello", encoding="utf-8")

    source = [SourceItem.from_path(only_file, source_root)]
    service = ArchiveService()
    archive_path = service.create_archive(
        sources=source,
        plan=ArchivePlan(output_path=tmp_path / "single.uca", protection=ArchiveProtection.NONE),
    )

    output_dir = tmp_path / "out"
    extracted = service.extract_selected(archive_path, output_dir, ["only.txt"])
    assert extracted == [output_dir / "only.txt"]
    assert (output_dir / "only.txt").read_text(encoding="utf-8") == "hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/universal_compress/archive/test_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'ArchiveService'`

- [ ] **Step 3: Write minimal implementation**

```python
# Code/universal_compress/archive/service.py
import json
from pathlib import Path

import zstandard as zstd

from .container import HEADER_STRUCT, MAGIC
from .manifest import ArchiveEntry, ArchiveManifest
from ..models import ArchivePlan, SourceItem


class ArchiveService:
    def create_archive(self, sources: list[SourceItem], plan: ArchivePlan) -> Path:
        compressor = zstd.ZstdCompressor(level=6)
        entries: list[ArchiveEntry] = []
        payload_parts: list[bytes] = []

        for source in sources:
            raw = source.source_path.read_bytes()
            stored = compressor.compress(raw)
            entries.append(
                ArchiveEntry(
                    relative_path=source.relative_path,
                    original_size=len(raw),
                    stored_size=len(stored),
                )
            )
            payload_parts.append(
                json.dumps({"path": source.relative_path.as_posix()}, separators=(",", ":")).encode("utf-8")
                + b"\n"
                + stored
            )

        manifest = ArchiveManifest(entries=entries, protection=plan.protection.value, compression_method=plan.compression_method)
        manifest_bytes = manifest.to_bytes()
        header_bytes = json.dumps(
            {"magic": "UCA1", "manifest_length": len(manifest_bytes), "protection": plan.protection.value},
            separators=(",", ":"),
        ).encode("utf-8")

        with plan.output_path.open("wb") as file_obj:
            file_obj.write(MAGIC)
            file_obj.write(HEADER_STRUCT.pack(len(header_bytes)))
            file_obj.write(header_bytes)
            file_obj.write(manifest_bytes)
            for part in payload_parts:
                file_obj.write(part)

        return plan.output_path

    def inspect_archive(self, archive_path: Path) -> ArchiveManifest:
        raw = archive_path.read_bytes()
        header_length = HEADER_STRUCT.unpack(raw[len(MAGIC):len(MAGIC) + HEADER_STRUCT.size])[0]
        manifest_start = len(MAGIC) + HEADER_STRUCT.size + header_length
        header_payload = raw[len(MAGIC) + HEADER_STRUCT.size:manifest_start]
        manifest_length = json.loads(header_payload.decode("utf-8"))["manifest_length"]
        manifest_bytes = raw[manifest_start:manifest_start + manifest_length]
        return ArchiveManifest.from_bytes(manifest_bytes)

    def extract_selected(self, archive_path: Path, output_dir: Path, relative_paths: list[str]) -> list[Path]:
        manifest = self.inspect_archive(archive_path)
        target_names = set(relative_paths)
        output_dir.mkdir(parents=True, exist_ok=True)
        extracted: list[Path] = []
        data = archive_path.read_bytes()
        cursor = len(MAGIC) + HEADER_STRUCT.size
        header_length = HEADER_STRUCT.unpack(data[len(MAGIC):len(MAGIC) + HEADER_STRUCT.size])[0]
        cursor += header_length
        manifest_length = len(manifest.to_bytes())
        cursor += manifest_length
        decompressor = zstd.ZstdDecompressor()

        for entry in manifest.entries:
            line_end = data.index(b"\n", cursor)
            metadata = json.loads(data[cursor:line_end].decode("utf-8"))
            cursor = line_end + 1
            blob = data[cursor:cursor + entry.stored_size]
            cursor += entry.stored_size

            if metadata["path"] not in target_names:
                continue

            destination = output_dir / metadata["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(decompressor.decompress(blob))
            extracted.append(destination)

        return extracted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/universal_compress/archive/test_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Code/universal_compress/archive/service.py tests/universal_compress/archive/test_service.py
git commit -m "feat: implement basic create inspect and extract flows"
```

### Task 5: Add Password Gate and Full Encryption

**Files:**
- Create: `Code/universal_compress/archive/security.py`
- Modify: `Code/universal_compress/archive/service.py`
- Create: `tests/universal_compress/archive/test_security.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/universal_compress/archive/test_security.py
import pytest

from universal_compress.archive.service import ArchiveService
from universal_compress.models import ArchivePlan, ArchiveProtection, InvalidPasswordError, SourceItem


def test_full_encryption_requires_valid_password(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    secret = root / "secret.txt"
    secret.write_text("classified", encoding="utf-8")

    service = ArchiveService()
    archive_path = service.create_archive(
        [SourceItem.from_path(secret, root)],
        ArchivePlan(
            output_path=tmp_path / "secret.uca",
            protection=ArchiveProtection.FULL_ENCRYPTION,
            password="hunter2",
        ),
    )

    with pytest.raises(InvalidPasswordError):
        service.inspect_archive(archive_path, password="wrong")

    manifest = service.inspect_archive(archive_path, password="hunter2")
    assert manifest.entries[0].relative_path.as_posix() == "secret.txt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/universal_compress/archive/test_security.py -v`
Expected: FAIL because `inspect_archive()` does not accept a password and encrypted archives are not supported

- [ ] **Step 3: Write minimal implementation**

```python
# Code/universal_compress/archive/security.py
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from ..models import InvalidPasswordError


def derive_key(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(password.encode("utf-8"))


def encrypt_blob(raw: bytes, password: str) -> bytes:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = derive_key(password, salt)
    cipher = AESGCM(key)
    return salt + nonce + cipher.encrypt(nonce, raw, None)


def decrypt_blob(raw: bytes, password: str) -> bytes:
    salt, nonce, ciphertext = raw[:16], raw[16:28], raw[28:]
    key = derive_key(password, salt)
    cipher = AESGCM(key)
    try:
        return cipher.decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise InvalidPasswordError("Invalid archive password.") from exc
```

```python
# Code/universal_compress/archive/service.py
import json
from pathlib import Path

import zstandard as zstd

from .container import HEADER_STRUCT, MAGIC
from .manifest import ArchiveEntry, ArchiveManifest
from .security import decrypt_blob, encrypt_blob
from ..models import ArchivePlan, ArchiveProtection, SourceItem


class ArchiveService:
    def create_archive(self, sources: list[SourceItem], plan: ArchivePlan) -> Path:
        compressor = zstd.ZstdCompressor(level=6)
        entries: list[ArchiveEntry] = []
        payload_parts: list[bytes] = []

        for source in sources:
            raw = source.source_path.read_bytes()
            stored = compressor.compress(raw)
            entries.append(
                ArchiveEntry(
                    relative_path=source.relative_path,
                    original_size=len(raw),
                    stored_size=len(stored),
                )
            )
            payload_parts.append(
                json.dumps({"path": source.relative_path.as_posix()}, separators=(",", ":")).encode("utf-8")
                + b"\n"
                + stored
            )

        manifest = ArchiveManifest(entries=entries, protection=plan.protection.value, compression_method=plan.compression_method)
        manifest_bytes = manifest.to_bytes()
        payload_bytes = b"".join(payload_parts)

        if plan.protection is ArchiveProtection.FULL_ENCRYPTION:
            manifest_bytes = encrypt_blob(manifest_bytes, plan.password or "")
            payload_bytes = encrypt_blob(payload_bytes, plan.password or "")

        header_bytes = json.dumps(
            {"magic": "UCA1", "manifest_length": len(manifest_bytes), "protection": plan.protection.value},
            separators=(",", ":"),
        ).encode("utf-8")

        with plan.output_path.open("wb") as file_obj:
            file_obj.write(MAGIC)
            file_obj.write(HEADER_STRUCT.pack(len(header_bytes)))
            file_obj.write(header_bytes)
            file_obj.write(manifest_bytes)
            file_obj.write(payload_bytes)

        return plan.output_path

    def _read_layout(self, archive_path: Path, password: str | None = None) -> tuple[dict, ArchiveManifest, bytes]:
        raw = archive_path.read_bytes()
        header_length = HEADER_STRUCT.unpack(raw[len(MAGIC):len(MAGIC) + HEADER_STRUCT.size])[0]
        manifest_start = len(MAGIC) + HEADER_STRUCT.size + header_length
        header_payload = raw[len(MAGIC) + HEADER_STRUCT.size:manifest_start]
        header = json.loads(header_payload.decode("utf-8"))
        manifest_end = manifest_start + header["manifest_length"]
        manifest_bytes = raw[manifest_start:manifest_end]
        payload_bytes = raw[manifest_end:]

        if header["protection"] == ArchiveProtection.FULL_ENCRYPTION.value:
            manifest_bytes = decrypt_blob(manifest_bytes, password or "")
            payload_bytes = decrypt_blob(payload_bytes, password or "")

        manifest = ArchiveManifest.from_bytes(manifest_bytes)
        return header, manifest, payload_bytes

    def inspect_archive(self, archive_path: Path, password: str | None = None) -> ArchiveManifest:
        _, manifest, _ = self._read_layout(archive_path, password=password)
        return manifest

    def extract_selected(self, archive_path: Path, output_dir: Path, relative_paths: list[str], password: str | None = None) -> list[Path]:
        _, manifest, payload_bytes = self._read_layout(archive_path, password=password)
        output_dir.mkdir(parents=True, exist_ok=True)
        target_names = set(relative_paths)
        cursor = 0
        extracted: list[Path] = []
        decompressor = zstd.ZstdDecompressor()

        for entry in manifest.entries:
            line_end = payload_bytes.index(b"\n", cursor)
            metadata = json.loads(payload_bytes[cursor:line_end].decode("utf-8"))
            cursor = line_end + 1
            blob = payload_bytes[cursor:cursor + entry.stored_size]
            cursor += entry.stored_size

            if metadata["path"] not in target_names:
                continue

            destination = output_dir / metadata["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(decompressor.decompress(blob))
            extracted.append(destination)

        return extracted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/universal_compress/archive/test_security.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Code/universal_compress/archive/security.py Code/universal_compress/archive/service.py tests/universal_compress/archive/test_security.py
git commit -m "feat: add archive protection modes"
```

### Task 6: Add Background Jobs, History, and Structured Progress

**Files:**
- Create: `Code/universal_compress/jobs/__init__.py`
- Create: `Code/universal_compress/jobs/queue.py`
- Create: `tests/universal_compress/jobs/test_queue.py`
- Modify: `Code/universal_compress/models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/universal_compress/jobs/test_queue.py
from universal_compress.jobs.queue import JobQueueService
from universal_compress.models import JobStatus


def test_queue_runs_job_and_records_completion():
    queue = JobQueueService(max_workers=1)
    job_id = queue.submit("sample", lambda context: "done")

    record = queue.wait_for(job_id, timeout=2.0)
    assert record.status is JobStatus.COMPLETED
    assert record.result == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/universal_compress/jobs/test_queue.py -v`
Expected: FAIL with missing `JobQueueService`

- [ ] **Step 3: Write minimal implementation**

```python
# Code/universal_compress/models.py
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class JobRecord:
    name: str
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    result: Any = None
    error: str | None = None
    job_id: str = field(default_factory=lambda: uuid4().hex)
```

```python
# Code/universal_compress/jobs/queue.py
from concurrent.futures import ThreadPoolExecutor

from ..models import JobRecord, JobStatus


class JobContext:
    def __init__(self, record: JobRecord) -> None:
        self.record = record


class JobQueueService:
    def __init__(self, max_workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._records: dict[str, JobRecord] = {}
        self._futures = {}

    def submit(self, name: str, runner):
        record = JobRecord(name=name)
        self._records[record.job_id] = record

        def wrapped():
            record.status = JobStatus.RUNNING
            result = runner(JobContext(record))
            record.status = JobStatus.COMPLETED
            record.progress = 1.0
            record.result = result
            return record

        self._futures[record.job_id] = self._executor.submit(wrapped)
        return record.job_id

    def wait_for(self, job_id: str, timeout: float):
        future = self._futures[job_id]
        return future.result(timeout=timeout)
```

```python
# Code/universal_compress/jobs/__init__.py
from .queue import JobQueueService
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/universal_compress/jobs/test_queue.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Code/universal_compress/models.py Code/universal_compress/jobs/__init__.py Code/universal_compress/jobs/queue.py tests/universal_compress/jobs/test_queue.py
git commit -m "feat: add v2 job queue and history records"
```

### Task 7: Build the Main Window, Source Intake, and Cost Inspector

**Files:**
- Create: `Code/universal_compress/ui/__init__.py`
- Create: `Code/universal_compress/ui/source_list.py`
- Create: `Code/universal_compress/ui/inspector.py`
- Create: `Code/universal_compress/ui/task_history.py`
- Create: `Code/universal_compress/ui/main_window.py`
- Modify: `Code/universal_compress/app.py`
- Create: `tests/universal_compress/ui/test_main_window.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/universal_compress/ui/test_main_window.py
from universal_compress.ui.main_window import MainWindow


def test_main_window_adds_source_paths_and_updates_cost(qtbot, tmp_path):
    source = tmp_path / "demo.txt"
    source.write_text("hello", encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    window.add_source_paths([source])

    assert window.source_list.count() == 1
    assert "Low" in window.inspector.cost_label.text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/universal_compress/ui/test_main_window.py -v`
Expected: FAIL with missing `MainWindow`

- [ ] **Step 3: Write minimal implementation**

```python
# Code/universal_compress/ui/source_list.py
from pathlib import Path

from PySide6.QtWidgets import QListWidget


class SourceListWidget(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def add_paths(self, paths: list[Path]) -> None:
        for path in paths:
            self.addItem(str(path))
```

```python
# Code/universal_compress/ui/inspector.py
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class InspectorPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.cost_label = QLabel("Cost: Low")
        layout.addWidget(self.cost_label)

    def set_cost_label(self, text: str) -> None:
        self.cost_label.setText(text)
```

```python
# Code/universal_compress/ui/task_history.py
from PySide6.QtWidgets import QListWidget


class TaskHistoryWidget(QListWidget):
    pass
```

```python
# Code/universal_compress/ui/main_window.py
from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QWidget

from ..costs import classify_operation_cost
from .inspector import InspectorPanel
from .source_list import SourceListWidget
from .task_history import TaskHistoryWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Universal Compress V2")
        self.setAcceptDrops(True)
        self.resize(1440, 900)

        self.source_list = SourceListWidget()
        self.inspector = InspectorPanel()
        self.task_history = TaskHistoryWidget()

        body = QWidget()
        layout = QHBoxLayout(body)
        layout.addWidget(self.source_list, 2)
        layout.addWidget(self.inspector, 1)
        layout.addWidget(self.task_history, 1)
        self.setCentralWidget(body)

    def add_source_paths(self, paths: list[Path]) -> None:
        self.source_list.add_paths(paths)
        total_bytes = sum(path.stat().st_size for path in paths)
        cost = classify_operation_cost(total_bytes=total_bytes, encrypted=False, media_mode=False)
        self.inspector.set_cost_label(f"Cost: {cost.value}")
```

```python
# Code/universal_compress/app.py
from .ui.main_window import MainWindow


def build_main_window() -> MainWindow:
    return MainWindow()
```

```python
# Code/universal_compress/ui/__init__.py
from .main_window import MainWindow
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/universal_compress/ui/test_main_window.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Code/universal_compress/ui/__init__.py Code/universal_compress/ui/source_list.py Code/universal_compress/ui/inspector.py Code/universal_compress/ui/task_history.py Code/universal_compress/ui/main_window.py Code/universal_compress/app.py tests/universal_compress/ui/test_main_window.py
git commit -m "feat: add source intake and inspector shell"
```

### Task 8: Wire Protected Archive Inspection into the UI

**Files:**
- Create: `Code/universal_compress/ui/password_dialog.py`
- Modify: `Code/universal_compress/ui/inspector.py`
- Modify: `Code/universal_compress/ui/main_window.py`
- Create: `tests/universal_compress/ui/test_archive_open.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/universal_compress/ui/test_archive_open.py
from pathlib import PurePosixPath

from universal_compress.archive.manifest import ArchiveEntry, ArchiveManifest
from universal_compress.ui.main_window import MainWindow


class FakeArchiveService:
    def inspect_archive(self, archive_path, password=None):
        return ArchiveManifest(
            entries=[ArchiveEntry(relative_path=PurePosixPath("docs/a.txt"), original_size=5, stored_size=7)],
            protection="full_encryption",
            compression_method="zstd",
        )


def test_open_archive_path_populates_preview_tree(qtbot, tmp_path):
    archive = tmp_path / "sample.uca"
    archive.write_bytes(b"demo")

    window = MainWindow(archive_service=FakeArchiveService())
    qtbot.addWidget(window)
    window.open_archive_path(archive, password="hunter2")

    assert window.inspector.preview_tree.topLevelItemCount() == 1
    assert window.inspector.preview_tree.topLevelItem(0).text(0) == "docs/a.txt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/universal_compress/ui/test_archive_open.py -v`
Expected: FAIL because the inspector has no preview tree and the main window cannot open archives

- [ ] **Step 3: Write minimal implementation**

```python
# Code/universal_compress/ui/password_dialog.py
from PySide6.QtWidgets import QDialog, QLineEdit, QPushButton, QVBoxLayout


class PasswordDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Unlock archive")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        button = QPushButton("OK")
        button.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(self.password_edit)
        layout.addWidget(button)

    @staticmethod
    def ask_password(parent) -> str | None:
        dialog = PasswordDialog()
        dialog.setParent(parent)
        if dialog.exec():
            return dialog.password_edit.text()
        return None
```

```python
# Code/universal_compress/ui/inspector.py
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget


class InspectorPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.cost_label = QLabel("Cost: Low")
        self.preview_tree = QTreeWidget()
        self.preview_tree.setHeaderLabels(["Archive contents"])
        layout.addWidget(self.cost_label)
        layout.addWidget(self.preview_tree)

    def show_manifest(self, manifest) -> None:
        self.preview_tree.clear()
        for entry in manifest.entries:
            self.preview_tree.addTopLevelItem(QTreeWidgetItem([entry.relative_path.as_posix()]))
```

```python
# Code/universal_compress/ui/main_window.py
from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QWidget

from ..archive.service import ArchiveService
from ..costs import classify_operation_cost
from .inspector import InspectorPanel
from .source_list import SourceListWidget
from .task_history import TaskHistoryWidget


class MainWindow(QMainWindow):
    def __init__(self, archive_service: ArchiveService | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Universal Compress V2")
        self.setAcceptDrops(True)
        self.resize(1440, 900)

        self.archive_service = archive_service or ArchiveService()
        self.source_list = SourceListWidget()
        self.inspector = InspectorPanel()
        self.task_history = TaskHistoryWidget()

        body = QWidget()
        layout = QHBoxLayout(body)
        layout.addWidget(self.source_list, 2)
        layout.addWidget(self.inspector, 1)
        layout.addWidget(self.task_history, 1)
        self.setCentralWidget(body)

    def add_source_paths(self, paths: list[Path]) -> None:
        self.source_list.add_paths(paths)
        total_bytes = sum(path.stat().st_size for path in paths)
        cost = classify_operation_cost(total_bytes=total_bytes, encrypted=False, media_mode=False)
        self.inspector.set_cost_label(f"Cost: {cost.value}")

    def open_archive_path(self, archive_path: Path, password: str | None = None) -> None:
        manifest = self.archive_service.inspect_archive(archive_path, password=password)
        self.inspector.show_manifest(manifest)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/universal_compress/ui/test_archive_open.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Code/universal_compress/ui/password_dialog.py Code/universal_compress/ui/inspector.py Code/universal_compress/ui/main_window.py tests/universal_compress/ui/test_archive_open.py
git commit -m "feat: add protected archive inspection flow"
```

### Task 9: Add Media Profiles and FFmpeg Command Builders

**Files:**
- Create: `Code/universal_compress/media/__init__.py`
- Create: `Code/universal_compress/media/profiles.py`
- Create: `Code/universal_compress/media/ffmpeg.py`
- Create: `tests/universal_compress/media/test_ffmpeg.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/universal_compress/media/test_ffmpeg.py
from pathlib import Path

from universal_compress.media.ffmpeg import build_audio_command, build_video_command


def test_build_video_command_uses_balanced_profile():
    command = build_video_command(
        ffmpeg_path=Path("ffmpeg"),
        source_path=Path("input.mp4"),
        output_path=Path("output.mp4"),
        profile_name="balanced",
    )

    assert "libx265" in command
    assert "aac" in command
    assert "output.mp4" in command


def test_build_audio_command_uses_speech_profile():
    command = build_audio_command(
        ffmpeg_path=Path("ffmpeg"),
        source_path=Path("speech.wav"),
        output_path=Path("speech.m4a"),
        profile_name="speech",
    )

    assert "96k" in command
    assert "aac" in command
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/universal_compress/media/test_ffmpeg.py -v`
Expected: FAIL with missing media modules

- [ ] **Step 3: Write minimal implementation**

```python
# Code/universal_compress/media/profiles.py
VIDEO_PROFILES = {
    "balanced": {"video_codec": "libx265", "crf": "28", "audio_bitrate": "128k"},
    "small": {"video_codec": "libx265", "crf": "32", "audio_bitrate": "96k"},
}

AUDIO_PROFILES = {
    "speech": {"audio_codec": "aac", "audio_bitrate": "96k"},
    "music": {"audio_codec": "aac", "audio_bitrate": "192k"},
}
```

```python
# Code/universal_compress/media/ffmpeg.py
from pathlib import Path

from .profiles import AUDIO_PROFILES, VIDEO_PROFILES


def build_video_command(ffmpeg_path: Path, source_path: Path, output_path: Path, profile_name: str) -> list[str]:
    profile = VIDEO_PROFILES[profile_name]
    return [
        str(ffmpeg_path),
        "-i",
        str(source_path),
        "-c:v",
        profile["video_codec"],
        "-crf",
        profile["crf"],
        "-c:a",
        "aac",
        "-b:a",
        profile["audio_bitrate"],
        str(output_path),
    ]


def build_audio_command(ffmpeg_path: Path, source_path: Path, output_path: Path, profile_name: str) -> list[str]:
    profile = AUDIO_PROFILES[profile_name]
    return [
        str(ffmpeg_path),
        "-i",
        str(source_path),
        "-c:a",
        profile["audio_codec"],
        "-b:a",
        profile["audio_bitrate"],
        str(output_path),
    ]
```

```python
# Code/universal_compress/media/__init__.py
from .ffmpeg import build_audio_command, build_video_command
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/universal_compress/media/test_ffmpeg.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Code/universal_compress/media/__init__.py Code/universal_compress/media/profiles.py Code/universal_compress/media/ffmpeg.py tests/universal_compress/media/test_ffmpeg.py
git commit -m "feat: add media preset command builders"
```

### Task 10: Add ZIP Export and Finish the V1 Integration Pass

**Files:**
- Create: `Code/universal_compress/adapters/__init__.py`
- Create: `Code/universal_compress/adapters/zip_export.py`
- Create: `tests/universal_compress/adapters/test_zip_export.py`
- Modify: `Code/universal_compress/ui/main_window.py`
- Modify: `README.md`

- [ ] **Step 1: Write the failing test**

```python
# tests/universal_compress/adapters/test_zip_export.py
from zipfile import ZipFile

from universal_compress.adapters.zip_export import ZipExportAdapter
from universal_compress.models import SourceItem


def test_zip_export_adapter_writes_selected_sources(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    alpha = root / "alpha.txt"
    beta = root / "beta.txt"
    alpha.write_text("alpha", encoding="utf-8")
    beta.write_text("beta", encoding="utf-8")

    output = tmp_path / "bundle.zip"
    adapter = ZipExportAdapter()
    adapter.export(
        [SourceItem.from_path(alpha, root), SourceItem.from_path(beta, root)],
        output,
    )

    with ZipFile(output) as zip_file:
        assert sorted(zip_file.namelist()) == ["alpha.txt", "beta.txt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/universal_compress/adapters/test_zip_export.py -v`
Expected: FAIL with missing ZIP adapter

- [ ] **Step 3: Write minimal implementation**

```python
# Code/universal_compress/adapters/zip_export.py
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from ..models import SourceItem


class ZipExportAdapter:
    def export(self, sources: list[SourceItem], output_path: Path) -> Path:
        with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as zip_file:
            for source in sources:
                zip_file.write(source.source_path, arcname=source.relative_path.as_posix())
        return output_path
```

```python
# Code/universal_compress/adapters/__init__.py
from .zip_export import ZipExportAdapter
```

```python
# Code/universal_compress/ui/main_window.py
from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QWidget

from ..archive.service import ArchiveService
from ..adapters.zip_export import ZipExportAdapter
from ..costs import classify_operation_cost
from .inspector import InspectorPanel
from .source_list import SourceListWidget
from .task_history import TaskHistoryWidget


class MainWindow(QMainWindow):
    def __init__(self, archive_service: ArchiveService | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Universal Compress V2")
        self.setAcceptDrops(True)
        self.resize(1440, 900)

        self.archive_service = archive_service or ArchiveService()
        self.zip_export = ZipExportAdapter()
        self.source_list = SourceListWidget()
        self.inspector = InspectorPanel()
        self.task_history = TaskHistoryWidget()

        body = QWidget()
        layout = QHBoxLayout(body)
        layout.addWidget(self.source_list, 2)
        layout.addWidget(self.inspector, 1)
        layout.addWidget(self.task_history, 1)
        self.setCentralWidget(body)

    def add_source_paths(self, paths: list[Path]) -> None:
        self.source_list.add_paths(paths)
        total_bytes = sum(path.stat().st_size for path in paths)
        cost = classify_operation_cost(total_bytes=total_bytes, encrypted=False, media_mode=False)
        self.inspector.set_cost_label(f"Cost: {cost.value}")

    def open_archive_path(self, archive_path: Path, password: str | None = None) -> None:
        manifest = self.archive_service.inspect_archive(archive_path, password=password)
        self.inspector.show_manifest(manifest)
```

```markdown
# README.md
## Universal Compress V2

Current rewrite status:

- PySide6 shell bootstrapped
- Native `*.uca` archive flow available in the new package
- Protected archive inspection path added
- Media preset command builders added
- ZIP export adapter added as the first standard-format helper

Run the V2 test suite with `python -m pytest tests/universal_compress -v`.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/universal_compress/adapters/test_zip_export.py -v`
Expected: PASS

Then run: `python -m pytest tests/universal_compress -v`
Expected: PASS with the full V2 suite green

- [ ] **Step 5: Commit**

```bash
git add Code/universal_compress/adapters/__init__.py Code/universal_compress/adapters/zip_export.py Code/universal_compress/ui/main_window.py README.md tests/universal_compress/adapters/test_zip_export.py
git commit -m "feat: add ZIP export and finalize v1 integration slice"
```

## Self-Review Notes

- Spec coverage: tasks 1-10 cover the V1 scope items from the design spec, including Qt GUI, drag/drop shell, native archive format, archive inspection, protection modes, queue/history, media module foundations, standard export, and user-facing cost hints.
- Intentional omissions: legacy `*.pylc` import, deeper file previews, richer preset comparison, and extra Windows integrations remain out of scope for this V1 plan, matching the design spec.
- Placeholder scan: the plan contains no unresolved placeholder markers.
- Type consistency: `ArchivePlan`, `ArchiveProtection`, `SourceItem`, `CostLevel`, `InvalidPasswordError`, `JobStatus`, and `JobRecord` are introduced before later tasks reuse them.
