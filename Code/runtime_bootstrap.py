from __future__ import annotations

import importlib
import importlib.metadata as metadata
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

APP_NAME = "PyLossless Studio"
_REQUIREMENT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class RequirementSpec:
    spec: str
    distribution_name: str | None
    source: Path
    line_number: int


def configure_console_encoding() -> None:
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
        except Exception:
            pass

    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_requirements_path() -> Path:
    return get_project_root() / "requirements.txt"


def get_user_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / APP_NAME


def get_bootstrap_log_dir() -> Path:
    return get_user_data_dir() / "logs"


def format_install_command(requirements_path: Path) -> str:
    return f'"{sys.executable}" -m pip install -r "{requirements_path}"'


def extract_distribution_name(spec: str) -> str | None:
    stripped = spec.strip()
    if not stripped:
        return None
    if stripped.startswith(("git+", "http://", "https://")) or "://" in stripped:
        return None
    if stripped.startswith(".") or stripped.startswith("/"):
        return None
    match = _REQUIREMENT_NAME_RE.match(stripped)
    if not match:
        return None
    return match.group(0)


def read_requirements_file(path: Path, _seen: set[Path] | None = None) -> list[RequirementSpec]:
    if _seen is None:
        _seen = set()
    path = path.resolve()
    if path in _seen or not path.exists():
        return []
    _seen.add(path)

    requirements: list[RequirementSpec] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-r ", "--requirement ")):
            _, include_path = line.split(maxsplit=1)
            nested_path = Path(include_path)
            if not nested_path.is_absolute():
                nested_path = path.parent / nested_path
            requirements.extend(read_requirements_file(nested_path, _seen))
            continue
        if line.startswith("-"):
            continue
        requirements.append(
            RequirementSpec(
                spec=line,
                distribution_name=extract_distribution_name(line),
                source=path,
                line_number=line_number,
            )
        )
    return requirements


def find_missing_requirements(
    requirements: list[RequirementSpec],
    *,
    assume_present_for_uncheckable: bool = False,
) -> list[RequirementSpec]:
    missing: list[RequirementSpec] = []
    seen: set[str] = set()
    for requirement in requirements:
        key = (requirement.distribution_name or requirement.spec).lower()
        if key in seen:
            continue
        seen.add(key)
        if requirement.distribution_name is None:
            if not assume_present_for_uncheckable:
                missing.append(requirement)
            continue
        try:
            metadata.version(requirement.distribution_name)
        except metadata.PackageNotFoundError:
            missing.append(requirement)
    return missing


def _format_requirement_list(requirements: list[RequirementSpec]) -> str:
    return "\n".join(f"- {requirement.spec}" for requirement in requirements)


def has_interactive_console() -> bool:
    return bool(sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty())


def console_print(message: str = "", *, stream=None) -> None:
    target = stream or sys.stdout
    print(message, file=target)


def ask_user_to_install(missing: list[RequirementSpec], requirements_path: Path) -> bool:
    if os.environ.get("PYLOSSLESS_AUTO_INSTALL") == "1":
        console_print("Automatyczna instalacja zależności została wymuszona przez PYLOSSLESS_AUTO_INSTALL=1.")
        return True

    package_list = _format_requirement_list(missing)
    console_print("Brakuje pakietów wymaganych do uruchomienia aplikacji:")
    console_print(package_list)
    console_print(f"Plik źródłowy: {requirements_path}")
    console_print()

    if not has_interactive_console():
        return False

    while True:
        reply = input("Czy chcesz zainstalować je teraz? [t/N]: ").strip().lower()
        if reply in {"", "n", "nie", "no"}:
            return False
        if reply in {"t", "tak", "y", "yes"}:
            return True
        console_print("Wpisz 't' lub 'n'.")


def install_requirements(requirements_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def write_install_failure_log(requirements_path: Path, result: subprocess.CompletedProcess[str]) -> Path:
    log_dir = get_bootstrap_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"dependency_install_{stamp}_{time.time_ns() % 1_000_000_000:09d}.txt"
    report = [
        "Nieudana instalacja zależności",
        "============================",
        "",
        f"Data: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Plik requirements: {requirements_path}",
        f"Polecenie: {format_install_command(requirements_path)}",
        f"Kod wyjścia: {result.returncode}",
        "",
        "STDOUT:",
        result.stdout.rstrip(),
        "",
        "STDERR:",
        result.stderr.rstrip(),
        "",
    ]
    path.write_text("\n".join(report), encoding="utf-8")
    return path


def print_bootstrap_error(message: str, title: str = "Błąd startu") -> None:
    console_print(f"{title}: {message}", stream=sys.stderr)


def _load_exception_report_writer():
    for module_name in ("Code.pylossless.error_logging", "pylossless.error_logging"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        writer = getattr(module, "write_exception_report", None)
        if callable(writer):
            return writer
    return None


def log_startup_exception(exc: BaseException, context: str) -> Path | None:
    writer = _load_exception_report_writer()
    if writer is None:
        return None
    try:
        return writer(type(exc), exc, exc.__traceback__, context=context)
    except Exception:
        return None


def ensure_runtime_dependencies(requirements_path: Path | None = None) -> None:
    if os.environ.get("PYLOSSLESS_SKIP_DEP_CHECK") == "1":
        console_print("Pomijam sprawdzanie zależności, bo ustawiono PYLOSSLESS_SKIP_DEP_CHECK=1.")
        return

    requirements_path = requirements_path or default_requirements_path()
    if not requirements_path.exists():
        console_print(f"Nie znaleziono pliku zależności: {requirements_path}")
        return

    requirements = read_requirements_file(requirements_path)
    if not requirements:
        console_print("Brak zewnętrznych pakietów w requirements.txt. Uruchamiam GUI.")
        return

    missing = find_missing_requirements(requirements)
    if not missing:
        console_print("Wszystkie pakiety z requirements.txt są już dostępne.")
        return

    if not ask_user_to_install(missing, requirements_path):
        raise RuntimeError(
            "Instalacja brakujących pakietów została anulowana.\n\n"
            f"Pakiety:\n{_format_requirement_list(missing)}\n\n"
            f"Możesz zainstalować je ręcznie poleceniem:\n{format_install_command(requirements_path)}"
        )

    console_print("Rozpoczynam instalację brakujących pakietów...")
    console_print(f"Polecenie: {format_install_command(requirements_path)}")
    result = install_requirements(requirements_path)
    if result.stdout.strip():
        console_print()
        console_print("STDOUT instalacji:")
        console_print(result.stdout.rstrip())
    if result.stderr.strip():
        console_print()
        console_print("STDERR instalacji:", stream=sys.stderr)
        console_print(result.stderr.rstrip(), stream=sys.stderr)

    if result.returncode != 0:
        log_path = write_install_failure_log(requirements_path, result)
        raise RuntimeError(
            "Nie udało się zainstalować wymaganych pakietów.\n\n"
            f"Szczegóły zapisano do:\n{log_path}\n\n"
            f"Spróbuj ponownie poleceniem:\n{format_install_command(requirements_path)}"
        )

    remaining = find_missing_requirements(requirements, assume_present_for_uncheckable=True)
    if remaining:
        raise RuntimeError(
            "Instalacja zakończyła się bez błędu, ale nadal brakuje części pakietów:\n\n"
            f"{_format_requirement_list(remaining)}\n\n"
            f"Spróbuj ponownie poleceniem:\n{format_install_command(requirements_path)}"
        )

    console_print("Instalacja zakończona powodzeniem. Uruchamiam GUI.")


def bootstrap_and_run(start_gui: Callable[[], None]) -> None:
    configure_console_encoding()
    console_print(f"{APP_NAME} launcher")
    console_print(f"Folder logów błędów: {get_bootstrap_log_dir()}")
    console_print("Sprawdzanie zależności...")
    try:
        ensure_runtime_dependencies()
    except RuntimeError as exc:
        print_bootstrap_error(str(exc))
        raise SystemExit(1) from exc

    console_print("Start interfejsu graficznego...")
    try:
        start_gui()
    except Exception as exc:
        log_path = log_startup_exception(exc, "Błąd uruchamiania GUI z launchera.")
        if log_path is not None:
            print_bootstrap_error(f"Nie udało się uruchomić GUI. Raport zapisano do: {log_path}")
        else:
            print_bootstrap_error(f"Nie udało się uruchomić GUI: {exc}")
        raise SystemExit(1) from exc
