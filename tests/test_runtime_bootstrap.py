from __future__ import annotations

import builtins
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Code"))

import runtime_bootstrap


class RuntimeBootstrapTest(unittest.TestCase):
    def setUp(self):
        test_root = ROOT / ".tmp_test_runs"
        test_root.mkdir(exist_ok=True)
        self.temp_dir = test_root / f"bootstrap_{uuid4().hex}"
        self.temp_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_read_requirements_file_supports_nested_requirement_files(self):
        nested = self.temp_dir / "nested.txt"
        nested.write_text("rich>=13\n", encoding="utf-8")
        requirements = self.temp_dir / "requirements.txt"
        requirements.write_text(
            "# comment\nrequests>=2.0\n-r nested.txt\n--extra-index-url https://example.invalid/simple\n",
            encoding="utf-8",
        )

        result = runtime_bootstrap.read_requirements_file(requirements)

        self.assertEqual([item.spec for item in result], ["requests>=2.0", "rich>=13"])
        self.assertEqual([item.distribution_name for item in result], ["requests", "rich"])

    def test_find_missing_requirements_returns_only_missing_distributions(self):
        requirements = [
            runtime_bootstrap.RequirementSpec("present_pkg>=1", "present_pkg", self.temp_dir / "r.txt", 1),
            runtime_bootstrap.RequirementSpec("missing_pkg>=1", "missing_pkg", self.temp_dir / "r.txt", 2),
        ]

        def fake_version(name: str) -> str:
            if name == "present_pkg":
                return "1.0"
            raise runtime_bootstrap.metadata.PackageNotFoundError

        with patch.object(runtime_bootstrap.metadata, "version", side_effect=fake_version):
            missing = runtime_bootstrap.find_missing_requirements(requirements)

        self.assertEqual([item.distribution_name for item in missing], ["missing_pkg"])

    def test_ask_user_to_install_accepts_console_confirmation(self):
        requirements = [
            runtime_bootstrap.RequirementSpec("missing_pkg>=1", "missing_pkg", self.temp_dir / "r.txt", 1),
        ]

        with patch.object(runtime_bootstrap, "has_interactive_console", return_value=True), patch.object(builtins, "input", return_value="tak"):
            accepted = runtime_bootstrap.ask_user_to_install(requirements, self.temp_dir / "requirements.txt")

        self.assertTrue(accepted)

    def test_ensure_runtime_dependencies_skips_empty_requirements_file(self):
        requirements = self.temp_dir / "requirements.txt"
        requirements.write_text("# brak zewn?trznych pakiet?w\n", encoding="utf-8")

        with patch.object(runtime_bootstrap, "ask_user_to_install") as ask_mock, patch.object(runtime_bootstrap, "install_requirements") as install_mock:
            runtime_bootstrap.ensure_runtime_dependencies(requirements)

        ask_mock.assert_not_called()
        install_mock.assert_not_called()

    def test_ensure_runtime_dependencies_installs_missing_packages_after_consent(self):
        requirements_path = self.temp_dir / "requirements.txt"
        requirements_path.write_text("missing_pkg>=1\n", encoding="utf-8")
        requirements = runtime_bootstrap.read_requirements_file(requirements_path)
        install_result = subprocess.CompletedProcess(args=[sys.executable], returncode=0, stdout="ok", stderr="")

        with patch.object(runtime_bootstrap, "find_missing_requirements", side_effect=[requirements, []]) as find_mock, patch.object(runtime_bootstrap, "ask_user_to_install", return_value=True) as ask_mock, patch.object(runtime_bootstrap, "install_requirements", return_value=install_result) as install_mock:
            runtime_bootstrap.ensure_runtime_dependencies(requirements_path)

        self.assertEqual(find_mock.call_count, 2)
        ask_mock.assert_called_once()
        install_mock.assert_called_once_with(requirements_path)
