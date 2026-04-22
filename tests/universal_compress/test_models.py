from pathlib import Path, PurePosixPath

import pytest

from universal_compress.costs import classify_operation_cost
from universal_compress.models import ArchivePlan, ArchiveProtection, CostLevel, SourceItem


def test_source_item_from_path_uses_relative_posix_path(tmp_path):
    root_path = tmp_path / "root"
    sample = root_path / "docs" / "alpha.txt"
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_text("hello", encoding="utf-8")

    item = SourceItem.from_path(sample, root_path)

    assert item.relative_path == PurePosixPath("docs/alpha.txt")
    assert item.size == 5


def test_protected_archive_plan_requires_password():
    with pytest.raises(ValueError):
        ArchivePlan(
            output_path=Path("secure.uca"),
            protection=ArchiveProtection.FULL_ENCRYPTION,
            password=None,
        )


def test_cost_classifier_marks_large_encrypted_work_as_high():
    cost = classify_operation_cost(total_bytes=8 * 1024**3, encrypted=True, media_mode=False)
    assert cost is CostLevel.HIGH
