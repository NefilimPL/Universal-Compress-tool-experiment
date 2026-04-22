from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath


class CancelledError(Exception):
    pass


class ArchiveProtection(str, Enum):
    NONE = "none"
    PASSWORD_GATE = "password_gate"
    FULL_ENCRYPTION = "full_encryption"


class CostLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidPasswordError(ValueError):
    pass


@dataclass(frozen=True)
class SourceItem:
    source_path: Path
    relative_path: PurePosixPath
    size: int

    @classmethod
    def from_path(cls, source_path: Path, root_path: Path) -> "SourceItem":
        source_path = Path(source_path)
        root_path = Path(root_path)
        relative_path = PurePosixPath(source_path.relative_to(root_path).as_posix())
        return cls(
            source_path=source_path,
            relative_path=relative_path,
            size=source_path.stat().st_size,
        )


@dataclass(frozen=True)
class ArchivePlan:
    output_path: Path
    protection: ArchiveProtection = ArchiveProtection.NONE
    password: str | None = None
    compression_method: str = "zstd"

    def __post_init__(self) -> None:
        if self.protection is not ArchiveProtection.NONE and not self.password:
            raise ValueError("Protected archives require a password.")
