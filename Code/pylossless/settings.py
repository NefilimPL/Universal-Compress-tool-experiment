from __future__ import annotations

import json
from collections.abc import Mapping

from .paths import SETTINGS_FILE
from .utils import ensure_dir


def load_settings_file() -> dict:
    if not SETTINGS_FILE.exists():
        return {}
    return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))


def save_settings_file(data: Mapping[str, object]) -> None:
    ensure_dir(SETTINGS_FILE.parent)
    SETTINGS_FILE.write_text(json.dumps(dict(data), ensure_ascii=False, indent=2), encoding="utf-8")
