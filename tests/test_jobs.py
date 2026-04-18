from __future__ import annotations

import json
import shutil
import struct
import sys
from uuid import uuid4
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Code"))

from pylossless.algorithms import AVAILABLE_ALGOS
from pylossless.constants import HEADER_FMT, MAGIC
from pylossless.container import read_container_header
from pylossless.jobs import compress_job, decompress_job, verify_archive_job
from pylossless.models import SourceSpec


def rewrite_header(archive_path: Path, transform):
    header, payload_offset = read_container_header(archive_path)
    payload = archive_path.read_bytes()[payload_offset:]
    new_header = transform(dict(header))
    header_bytes = json.dumps(new_header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    archive_path.write_bytes(MAGIC + struct.pack(HEADER_FMT, len(header_bytes)) + header_bytes + payload)


class JobsTest(unittest.TestCase):
    def setUp(self):
        test_root = ROOT / '.tmp_test_runs'
        test_root.mkdir(exist_ok=True)
        self.temp_dir = test_root / f"pylossless_tests_{uuid4().hex}"
        self.temp_dir.mkdir()
        self.algo = "zlib" if "zlib" in AVAILABLE_ALGOS else AVAILABLE_ALGOS[0]

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def make_text_source(self, text: str) -> SourceSpec:
        return SourceSpec(
            mode="text",
            file_path=None,
            text_bytes=text.encode("utf-8"),
            text_name="fraza.txt",
            text_encoding="utf-8",
        )

    def test_text_roundtrip(self):
        source = self.make_text_source("p?ki w twoim posiadaniu nie uronisz kropli krwi")
        result = compress_job(
            source=source,
            output_dir=str(self.temp_dir / "encoded"),
            algo_mode="single",
            algo_single=self.algo,
            auto_enabled=[self.algo],
            level=6,
            chunk_size=32,
            overwrite=True,
            cancel_event=threading.Event(),
            progress_cb=lambda *_: None,
            log_cb=lambda *_: None,
        )

        decoded = decompress_job(
            archive_path=Path(result["dest"]),
            output_dir=str(self.temp_dir / "decoded"),
            chunk_size=32,
            overwrite=True,
            prefer_original_path=False,
            verify_hash=True,
            restore_mtime=True,
            cancel_event=threading.Event(),
            progress_cb=lambda *_: None,
            log_cb=lambda *_: None,
            load_text_to_memory=True,
        )

        self.assertEqual(decoded["text"], "p?ki w twoim posiadaniu nie uronisz kropli krwi")
        self.assertTrue(Path(decoded["dest"]).exists())

    def test_decode_keeps_file_when_text_encoding_is_invalid(self):
        source = self.make_text_source("za???? g??l? ja??")
        result = compress_job(
            source=source,
            output_dir=str(self.temp_dir / "encoded"),
            algo_mode="single",
            algo_single=self.algo,
            auto_enabled=[self.algo],
            level=6,
            chunk_size=16,
            overwrite=True,
            cancel_event=threading.Event(),
            progress_cb=lambda *_: None,
            log_cb=lambda *_: None,
        )

        rewrite_header(Path(result["dest"]), lambda header: {**header, "text_encoding": "totally-invalid-encoding"})
        logs: list[str] = []

        decoded = decompress_job(
            archive_path=Path(result["dest"]),
            output_dir=str(self.temp_dir / "decoded"),
            chunk_size=16,
            overwrite=True,
            prefer_original_path=False,
            verify_hash=True,
            restore_mtime=True,
            cancel_event=threading.Event(),
            progress_cb=lambda *_: None,
            log_cb=logs.append,
            load_text_to_memory=True,
        )

        decoded_path = Path(decoded["dest"])
        self.assertTrue(decoded_path.exists())
        self.assertEqual(decoded_path.read_text(encoding="utf-8"), "za???? g??l? ja??")
        self.assertIsNone(decoded["text"])
        self.assertTrue(any("Nie uda?o si? za?adowa? odzyskanego tekstu" in line for line in logs))

    def test_verify_detects_size_mismatch(self):
        source = self.make_text_source("kr?tka polska fraza")
        result = compress_job(
            source=source,
            output_dir=str(self.temp_dir / "encoded"),
            algo_mode="single",
            algo_single=self.algo,
            auto_enabled=[self.algo],
            level=6,
            chunk_size=16,
            overwrite=True,
            cancel_event=threading.Event(),
            progress_cb=lambda *_: None,
            log_cb=lambda *_: None,
        )

        rewrite_header(Path(result["dest"]), lambda header: {**header, "original_size": int(header["original_size"]) + 1})
        verify = verify_archive_job(
            archive_path=Path(result["dest"]),
            chunk_size=16,
            cancel_event=threading.Event(),
            progress_cb=lambda *_: None,
            log_cb=lambda *_: None,
        )

        self.assertFalse(verify["ok"])
        self.assertFalse(verify["size_ok"])
        self.assertTrue(verify["hash_ok"])
