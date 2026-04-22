from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Code"))

from pylossless import error_logging
from tests._paths import make_temp_dir


class ErrorLoggingTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = make_temp_dir("pylossless_logs")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_write_error_report_creates_txt_file(self):
        with patch.object(error_logging, "LOGS_DIR", self.temp_dir):
            path = error_logging.write_error_report(
                title="Test błędu",
                message="Coś poszło nie tak",
                traceback_text="Traceback sample",
                context="Test jednostkowy",
                extra_lines=["linia 1", "linia 2"],
            )

        self.assertEqual(path.suffix, ".txt")
        self.assertTrue(path.exists())
        content = path.read_text(encoding="utf-8")
        self.assertIn("Test błędu", content)
        self.assertIn("Coś poszło nie tak", content)
        self.assertIn("Traceback sample", content)
        self.assertIn("Test jednostkowy", content)
        self.assertIn("linia 1", content)
