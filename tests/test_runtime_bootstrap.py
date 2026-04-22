from __future__ import annotations

import builtins
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Code"))

import runtime_bootstrap
from tests._paths import make_temp_dir


class RuntimeBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = make_temp_dir("bootstrap")

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

    def test_find_missing_requirements_treats_version_mismatch_as_missing(self):
        requirements = [
            runtime_bootstrap.RequirementSpec("sample_pkg>=2", "sample_pkg", self.temp_dir / "r.txt", 1),
        ]

        with patch.object(runtime_bootstrap.metadata, "version", return_value="1.0"):
            missing = runtime_bootstrap.find_missing_requirements(requirements)

        self.assertEqual([item.distribution_name for item in missing], ["sample_pkg"])

    def test_ask_user_to_install_accepts_console_confirmation(self):
        requirements = [
            runtime_bootstrap.RequirementSpec("missing_pkg>=1", "missing_pkg", self.temp_dir / "r.txt", 1),
        ]

        with patch.object(runtime_bootstrap, "has_interactive_console", return_value=True), patch.object(builtins, "input", return_value="tak"):
            accepted = runtime_bootstrap.ask_user_to_install(requirements, self.temp_dir / "requirements.txt")

        self.assertTrue(accepted)

    def test_ensure_runtime_dependencies_skips_empty_requirements_file(self):
        requirements = self.temp_dir / "requirements.txt"
        requirements.write_text("# brak zewnętrznych pakietów\n", encoding="utf-8")

        with patch.object(runtime_bootstrap, "ask_user_to_install") as ask_mock, patch.object(runtime_bootstrap, "install_requirements") as install_mock:
            runtime_bootstrap.ensure_runtime_dependencies(requirements)

        ask_mock.assert_not_called()
        install_mock.assert_not_called()

    def test_ensure_runtime_dependencies_uses_runtime_requirements_by_default(self):
        requirements = self.temp_dir / "requirements-runtime.txt"
        requirements.write_text("# runtime only\n", encoding="utf-8")

        with patch.object(runtime_bootstrap, "default_runtime_requirements_path", return_value=requirements), patch.object(runtime_bootstrap, "read_requirements_file", return_value=[]) as read_mock, patch.object(runtime_bootstrap, "ask_user_to_install") as ask_mock, patch.object(runtime_bootstrap, "install_requirements") as install_mock:
            runtime_bootstrap.ensure_runtime_dependencies()

        read_mock.assert_called_once_with(requirements)
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

    def test_install_requirements_retries_with_user_after_permission_denied(self):
        requirements_path = self.temp_dir / "requirements-runtime.txt"
        requirements_path.write_text("PySide6>=6.9,<7\n", encoding="utf-8")
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if "--user" in command:
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="installed", stderr="")
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr="ERROR: Could not install packages due to an OSError: [WinError 5] Access is denied",
            )

        with patch.object(runtime_bootstrap.subprocess, "run", side_effect=fake_run):
            result = runtime_bootstrap.install_requirements(requirements_path)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            calls,
            [
                [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)],
                [sys.executable, "-m", "pip", "install", "-r", str(requirements_path), "--user"],
            ],
        )

    def test_install_requirements_does_not_retry_with_user_for_generic_failure(self):
        requirements_path = self.temp_dir / "requirements-runtime.txt"
        requirements_path.write_text("PySide6>=6.9,<7\n", encoding="utf-8")
        failure = subprocess.CompletedProcess(
            args=[sys.executable],
            returncode=1,
            stdout="",
            stderr="ERROR: No matching distribution found for imaginary-pkg",
        )

        with patch.object(runtime_bootstrap.subprocess, "run", return_value=failure) as run_mock:
            result = runtime_bootstrap.install_requirements(requirements_path)

        self.assertIs(result, failure)
        run_mock.assert_called_once_with(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_bootstrap_and_run_logs_gui_startup_exception(self):
        start_gui = Mock(side_effect=RuntimeError("boom"))
        fake_log_path = self.temp_dir / "startup_error.txt"

        with patch.object(runtime_bootstrap, "ensure_runtime_dependencies"), patch.object(runtime_bootstrap, "log_startup_exception", return_value=fake_log_path) as log_mock, patch.object(runtime_bootstrap, "print_bootstrap_error") as error_mock:
            with self.assertRaises(SystemExit) as cm:
                runtime_bootstrap.bootstrap_and_run(start_gui)

        self.assertEqual(cm.exception.code, 1)
        log_mock.assert_called_once()
        error_mock.assert_called_once_with(f"Nie udało się uruchomić GUI. Raport zapisano do: {fake_log_path}")
    def test_bootstrap_and_run_uses_supplied_requirements_path(self):
        start_gui = Mock()
        requirements_path = self.temp_dir / "requirements-runtime.txt"
        requirements_path.write_text("PySide6>=6.9,<7\n", encoding="utf-8")

        with patch.object(runtime_bootstrap, "ensure_runtime_dependencies") as ensure_mock:
            runtime_bootstrap.bootstrap_and_run(start_gui, requirements_path=requirements_path)

        ensure_mock.assert_called_once_with(requirements_path)

    def test_launcher_run_uses_bootstrap_and_runtime_requirements(self):
        import importlib

        launcher = importlib.import_module("launcher")
        runtime_requirements = self.temp_dir / "requirements-runtime.txt"

        with patch.object(launcher, "default_runtime_requirements_path", return_value=runtime_requirements), patch.object(launcher, "bootstrap_and_run") as bootstrap_mock:
            launcher.run()

        bootstrap_mock.assert_called_once()
        self.assertEqual(bootstrap_mock.call_args.kwargs["requirements_path"], runtime_requirements)

        start_gui = bootstrap_mock.call_args.args[0]
        with patch("Code.universal_compress.main.main") as main_mock:
            start_gui()

        main_mock.assert_called_once()

    def test_code_main_run_uses_universal_compress_main(self):
        import importlib

        code_main = importlib.import_module("Code.__main__")
        runtime_requirements = self.temp_dir / "requirements-runtime.txt"

        with patch.object(code_main, "default_runtime_requirements_path", return_value=runtime_requirements), patch.object(code_main, "bootstrap_and_run") as bootstrap_mock, patch("Code.universal_compress.main.main") as new_main:
            code_main.run()
            bootstrap_mock.assert_called_once()
            self.assertEqual(bootstrap_mock.call_args.kwargs["requirements_path"], runtime_requirements)
            bootstrap_mock.call_args.args[0]()
            new_main.assert_called_once()

    def test_ensure_runtime_dependencies_honors_universal_compress_skip_alias(self):
        requirements = self.temp_dir / "requirements-runtime.txt"
        requirements.write_text("PySide6>=6.9,<7\n", encoding="utf-8")

        with patch.dict(runtime_bootstrap.os.environ, {"UNIVERSAL_COMPRESS_SKIP_DEP_CHECK": "1"}, clear=False), patch.object(runtime_bootstrap, "read_requirements_file") as read_mock, patch.object(runtime_bootstrap, "ask_user_to_install") as ask_mock, patch.object(runtime_bootstrap, "install_requirements") as install_mock:
            runtime_bootstrap.ensure_runtime_dependencies(requirements)

        read_mock.assert_not_called()
        ask_mock.assert_not_called()
        install_mock.assert_not_called()

    def test_ask_user_to_install_honors_universal_compress_auto_install_alias(self):
        requirements = [
            runtime_bootstrap.RequirementSpec("missing_pkg>=1", "missing_pkg", self.temp_dir / "r.txt", 1),
        ]

        with patch.dict(runtime_bootstrap.os.environ, {"UNIVERSAL_COMPRESS_AUTO_INSTALL": "1"}, clear=False):
            accepted = runtime_bootstrap.ask_user_to_install(requirements, self.temp_dir / "requirements-runtime.txt")

        self.assertTrue(accepted)

    def test_load_exception_report_writer_prefers_universal_compress_module(self):
        def universal_writer(*args, **kwargs):
            return self.temp_dir / "universal.txt"

        def legacy_writer(*args, **kwargs):
            return self.temp_dir / "legacy.txt"

        import types

        universal_module = types.SimpleNamespace(write_exception_report=universal_writer)
        legacy_module = types.SimpleNamespace(write_exception_report=legacy_writer)

        def fake_import(name: str):
            if name in {"Code.universal_compress.error_logging", "universal_compress.error_logging"}:
                return universal_module
            if name in {"Code.pylossless.error_logging", "pylossless.error_logging"}:
                return legacy_module
            raise ImportError(name)

        with patch.object(runtime_bootstrap.importlib, "import_module", side_effect=fake_import) as import_mock:
            writer = runtime_bootstrap._load_exception_report_writer()

        self.assertIs(writer, universal_writer)
        self.assertEqual(
            [call.args[0] for call in import_mock.call_args_list],
            ["Code.universal_compress.error_logging"],
        )
