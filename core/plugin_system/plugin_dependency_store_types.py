from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packaging.version import Version


class PluginDependencyStoreError(RuntimeError):
    """A dependency object store failure with a stable error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StoredFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class StoredDependency:
    sha256: str
    distribution: str
    version: Version
    tags: tuple[str, ...]
    root_is_purelib: bool
    object_root: Path
    site_root: Path
    files: tuple[StoredFile, ...]
    native_extensions: tuple[Path, ...]
    dlls: tuple[Path, ...]
    dll_directories: tuple[Path, ...]


__all__ = [
    "PluginDependencyStoreError",
    "StoredDependency",
    "StoredFile",
]
