from __future__ import annotations

import importlib.metadata as metadata
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

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


def find_missing_requirements(requirements: list[RequirementSpec]) -> list[RequirementSpec]:
    missing: list[RequirementSpec] = []
    seen: set[str] = set()
    for requirement in requirements:
        key = (requirement.distribution_name or requirement.spec).lower()
        if key in seen:
            continue
        seen.add(key)
        if requirement.distribution_name is None:
            missing.append(requirement)
            continue
        try:
            metadata.version(requirement.distribution_name)
        except metadata.PackageNotFoundError:
            missing.append(requirement)
    return missing


def _format_requirement_list(requirements: list[RequirementSpec]) -> str:
    return "\n".join(f"- {requirement.spec}" for requirement in requirements)


def ask_user_to_install(missing: list[RequirementSpec], requirements_path: Path) -> bool:
    if os.environ.get("PYLOSSLESS_AUTO_INSTALL") == "1":
        return True

    package_list = _format_requirement_list(missing)
    message = (
        "Brakuje pakiet?w wymaganych do uruchomienia aplikacji:\n\n"
        f"{package_list}\n\n"
        f"Plik ?r?d?owy: {requirements_path}\n\n"
        "Czy chcesz zainstalowa? je teraz?"
    )

    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        try:
            return bool(messagebox.askyesno("Brakuj?ce pakiety", message, parent=root))
        finally:
            root.destroy()
    except Exception:
        if sys.stdin and sys.stdin.isatty():
            reply = input(f"{message}\n\nZainstalowa? teraz? [t/N]: ").strip().lower()
            return reply in {"t", "tak", "y", "yes"}
        return False


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


def show_bootstrap_error(message: str, title: str = "Brakuj?ce pakiety") -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        try:
            messagebox.showerror(title, message, parent=root)
        finally:
            root.destroy()
    except Exception:
        print(f"{title}: {message}", file=sys.stderr)


def ensure_runtime_dependencies(requirements_path: Path | None = None) -> None:
    if os.environ.get("PYLOSSLESS_SKIP_DEP_CHECK") == "1":
        return

    requirements_path = requirements_path or default_requirements_path()
    if not requirements_path.exists():
        return

    requirements = read_requirements_file(requirements_path)
    if not requirements:
        return

    missing = find_missing_requirements(requirements)
    if not missing:
        return

    if not ask_user_to_install(missing, requirements_path):
        raise RuntimeError(
            "Brakuje pakiet?w wymaganych do uruchomienia aplikacji:\n\n"
            f"{_format_requirement_list(missing)}\n\n"
            "Instalacja zosta?a anulowana przez u?ytkownika.\n\n"
            f"Mo?esz zainstalowa? je r?cznie poleceniem:\n{format_install_command(requirements_path)}"
        )

    result = install_requirements(requirements_path)
    if result.returncode != 0:
        log_path = write_install_failure_log(requirements_path, result)
        raise RuntimeError(
            "Nie uda?o si? zainstalowa? wymaganych pakiet?w.\n\n"
            f"Szczeg??y zapisano do:\n{log_path}\n\n"
            f"Spr?buj ponownie poleceniem:\n{format_install_command(requirements_path)}"
        )

    remaining = find_missing_requirements(requirements)
    if remaining:
        raise RuntimeError(
            "Instalacja zako?czy?a si? bez b??du, ale nadal brakuje cz??ci pakiet?w:\n\n"
            f"{_format_requirement_list(remaining)}\n\n"
            f"Spr?buj ponownie poleceniem:\n{format_install_command(requirements_path)}"
        )
