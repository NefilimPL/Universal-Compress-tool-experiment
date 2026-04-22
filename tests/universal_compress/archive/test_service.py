import threading
from pathlib import PurePosixPath

import pytest

from universal_compress.archive.service import ArchiveService
from universal_compress.models import ArchivePlan, ArchiveProtection, CancelledError, SourceItem


def test_create_and_inspect_archive_without_extraction(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    alpha = root / "alpha.txt"
    nested = root / "nested"
    nested.mkdir()
    beta = nested / "beta.txt"
    alpha.write_text("alpha", encoding="utf-8")
    beta.write_text("beta", encoding="utf-8")

    sources = [SourceItem.from_path(alpha, root), SourceItem.from_path(beta, root)]
    service = ArchiveService()
    archive_path = service.create_archive(
        sources=sources,
        plan=ArchivePlan(output_path=tmp_path / "bundle.uca", protection=ArchiveProtection.NONE),
    )

    manifest = service.inspect_archive(archive_path)

    assert archive_path.exists() is True
    assert [entry.relative_path for entry in manifest.entries] == [
        PurePosixPath("alpha.txt"),
        PurePosixPath("nested/beta.txt"),
    ]


def test_create_archive_reports_progress_for_each_source(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    alpha = root / "alpha.txt"
    beta = root / "beta.txt"
    alpha.write_text("alpha", encoding="utf-8")
    beta.write_text("beta", encoding="utf-8")

    sources = [SourceItem.from_path(alpha, root), SourceItem.from_path(beta, root)]
    service = ArchiveService()
    progress_events = []

    service.create_archive(
        sources=sources,
        plan=ArchivePlan(output_path=tmp_path / "bundle.uca", protection=ArchiveProtection.NONE),
        progress_callback=lambda current, total, source: progress_events.append(
            (current, total, source.relative_path.as_posix())
        ),
    )

    assert progress_events == [
        (1, 2, "alpha.txt"),
        (2, 2, "beta.txt"),
    ]


def test_create_archive_honors_cancel_event_and_does_not_leave_partial_output(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    alpha = root / "alpha.txt"
    beta = root / "beta.txt"
    alpha.write_text("alpha", encoding="utf-8")
    beta.write_text("beta", encoding="utf-8")

    sources = [SourceItem.from_path(alpha, root), SourceItem.from_path(beta, root)]
    service = ArchiveService()
    cancel_event = threading.Event()
    output_path = tmp_path / "bundle.uca"
    progress_events = []

    def on_progress(current, total, source):
        progress_events.append((current, total, source.relative_path.as_posix()))
        cancel_event.set()

    with pytest.raises(CancelledError, match="anulowana"):
        service.create_archive(
            sources=sources,
            plan=ArchivePlan(output_path=output_path, protection=ArchiveProtection.NONE),
            progress_callback=on_progress,
            cancel_event=cancel_event,
        )

    assert progress_events == [(1, 2, "alpha.txt")]
    assert output_path.exists() is False
