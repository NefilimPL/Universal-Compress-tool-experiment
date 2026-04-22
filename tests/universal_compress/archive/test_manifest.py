from pathlib import Path, PurePosixPath

from universal_compress.archive.container import read_container_header, write_container_header
from universal_compress.archive.manifest import ArchiveEntry, ArchiveManifest


def test_manifest_round_trip_preserves_entry_relative_path_and_compression_method():
    manifest = ArchiveManifest(
        entries=[
            ArchiveEntry(
                relative_path=PurePosixPath("docs/alpha.txt"),
                original_size=5,
                stored_size=7,
            )
        ],
        protection="none",
        compression_method="zstd",
    )

    loaded = ArchiveManifest.from_bytes(manifest.to_bytes())

    assert loaded.entries[0].relative_path == PurePosixPath("docs/alpha.txt")
    assert loaded.compression_method == "zstd"


def test_container_header_round_trip_returns_magic_and_manifest_length(tmp_path):
    header_path = tmp_path / "archive" / "header.bin"
    header_path.parent.mkdir(parents=True, exist_ok=True)

    write_container_header(header_path, manifest_length=128, protection="none")
    header = read_container_header(header_path)

    assert header["magic"] == "UCA1"
    assert header["manifest_length"] == 128
