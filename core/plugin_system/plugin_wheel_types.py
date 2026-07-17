from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packaging.tags import Tag
from packaging.version import Version


class PluginWheelError(ValueError):
    """A static wheel validation failure with a stable error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WheelLimits:
    max_archive_size: int = 512 * 1024 * 1024
    max_entries: int = 8192
    max_uncompressed_size: int = 512 * 1024 * 1024
    max_member_size: int = 256 * 1024 * 1024
    max_metadata_size: int = 2 * 1024 * 1024
    max_record_size: int = 8 * 1024 * 1024

    def __post_init__(self):
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True)
class WheelInstallEntry:
    archive_path: str
    install_path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class WheelArtifact:
    path: Path
    sha256: str
    distribution: str
    version: Version
    build_tag: tuple[int, str] | tuple[()]
    tags: frozenset[Tag]
    root_is_purelib: bool
    requires_python: str | None
    requirements: tuple[str, ...]
    files: tuple[str, ...]
    installed_files: tuple[str, ...]
    top_level_imports: tuple[str, ...]
    native_extensions: tuple[str, ...]
    dlls: tuple[str, ...]
    install_entries: tuple[WheelInstallEntry, ...] = ()
    target_python_abi: str | None = None
    target_platform: str | None = None
