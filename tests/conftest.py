from __future__ import annotations

import shutil

import pytest

from tests._paths import make_temp_dir


@pytest.fixture
def tmp_path():
    path = make_temp_dir("pytest")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
