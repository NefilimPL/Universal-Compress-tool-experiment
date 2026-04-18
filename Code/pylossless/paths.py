from __future__ import annotations

import os
import sys
from pathlib import Path

from .constants import APP_NAME


def get_script_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent.parent
    return Path.cwd()


def get_user_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / APP_NAME


SCRIPT_DIR = get_script_dir()
APP_DATA_DIR = get_user_data_dir()
DEFAULT_ENCODE_DIR = APP_DATA_DIR / "wynik_zakodowany"
DEFAULT_DECODE_DIR = APP_DATA_DIR / "wynik_odkodowany"
SETTINGS_FILE = APP_DATA_DIR / "pylossless_settings.json"
LOGS_DIR = APP_DATA_DIR / "logs"
