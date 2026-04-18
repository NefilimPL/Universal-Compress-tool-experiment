from __future__ import annotations

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
        console_print("Automatyczna instalacja zale?no?ci zosta?a wymuszona przez PYLOSSLESS_AUTO_INSTALL=1.")
        return True

    package_list = _format_requirement_list(missing)
    console_print("Brakuje pakiet?w wymaganych do uruchomienia aplikacji:")
    console_print(package_list)
    console_print(f"Plik ?r?d?owy: {requirements_path}")
    console_print()

    if not has_interactive_console():
        return False

    while True:
        reply = input("Czy chcesz zainstalowa? je teraz? [t/N]: ").strip().lower()
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
        "Nieudana instalacja zale?no?ci",
        "============================",
        "",
        f"Data: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Plik requirements: {requirements_path}",
        f"Polecenie: {format_install_command(requirements_path)}",
        f"Kod wyj?cia: {result.returncode}",
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


def print_bootstrap_error(message: str, title: str = "B??d startu") -> None:
    console_print(f"{title}: {message}", stream=sys.stderr)


def ensure_runtime_dependencies(requirements_path: Path | None = None) -> None:
    if os.environ.get("PYLOSSLESS_SKIP_DEP_CHECK") == "1":
        console_print("Pomijam sprawdzanie zale?no?ci, bo ustawiono PYLOSSLESS_SKIP_DEP_CHECK=1.")
        return

    requirements_path = requirements_path or default_requirements_path()
    if not requirements_path.exists():
        console_print(f"Nie znaleziono pliku zale?no?ci: {requirements_path}")
        return

    requirements = read_requirements_file(requirements_path)
    if not requirements:
        console_print("Brak zewn?trznych pakiet?w w requirements.txt. Uruchamiam GUI.")
        return

    missing = find_missing_requirements(requirements)
    if not missing:
        console_print("Wszystkie pakiety z requirements.txt s? ju? dost?pne.")
        return

    if not ask_user_to_install(missing, requirements_path):
        raise RuntimeError(
            "Instalacja brakuj?cych pakiet?w zosta?a anulowana.\n\n"
            f"Pakiety:\n{_format_requirement_list(missing)}\n\n"
            f"Mo?esz zainstalowa? je r?cznie poleceniem:\n{format_install_command(requirements_path)}"
        )

    console_print("Rozpoczynam instalacj? brakuj?cych pakiet?w...")
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
            "Nie uda?o si? zainstalowa? wymaganych pakiet?w.\n\n"
            f"Szczeg??y zapisano do:\n{log_path}\n\n"
            f"Spr?buj ponownie poleceniem:\n{format_install_command(requirements_path)}"
        )

    remaining = find_missing_requirements(requirements, assume_present_for_uncheckable=True)
    if remaining:
        raise RuntimeError(
            "Instalacja zako?czy?a si? bez b??du, ale nadal brakuje cz??ci pakiet?w:\n\n"
            f"{_format_requirement_list(remaining)}\n\n"
            f"Spr?buj ponownie poleceniem:\n{format_install_command(requirements_path)}"
        )

    console_print("Instalacja zako?czona powodzeniem. Uruchamiam GUI.")


def bootstrap_and_run(start_gui: Callable[[], None]) -> None:
    console_print(f"{APP_NAME} launcher")
    console_print("Sprawdzanie zale?no?ci...")
    try:
        ensure_runtime_dependencies()
    except RuntimeError as exc:
        print_bootstrap_error(str(exc))
        raise SystemExit(1) from exc

    console_print("Start interfejsu graficznego...")
    start_gui()
