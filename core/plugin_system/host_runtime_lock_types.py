from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Mapping

from packaging.utils import canonicalize_name
from packaging.version import Version


HOST_RUNTIME_LOCK_VERSION = 1
HOST_RUNTIME_LOCK_FILENAME = "HOST_RUNTIME_LOCK.json"
MAX_HOST_RUNTIME_LOCK_SIZE = 1024 * 1024
SUPPORTED_HOST_PLATFORMS = frozenset({"win32", "win_amd64", "win_arm64"})

_DISTRIBUTION_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_PYTHON_ABI_PATTERN = re.compile(r"cp[0-9]{2,3}\Z")
_IMPORT_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class HostRuntimeLockError(ValueError):
    """A host runtime lock failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, *, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.field = field


@dataclass(frozen=True)
class HostRuntimeTarget:
    python_abi: str
    platform: str

    def __post_init__(self):
        if (
            not isinstance(self.python_abi, str)
            or not _PYTHON_ABI_PATTERN.fullmatch(self.python_abi)
            or not isinstance(self.platform, str)
            or self.platform not in SUPPORTED_HOST_PLATFORMS
        ):
            raise _invalid_dto("Host runtime target is invalid.")


@dataclass(frozen=True)
class HostRuntimePackage:
    distribution: str
    version: Version
    top_level_imports: tuple[str, ...]

    def __post_init__(self):
        if (
            not isinstance(self.distribution, str)
            or not _DISTRIBUTION_PATTERN.fullmatch(self.distribution)
            or canonicalize_name(self.distribution) != self.distribution
            or not isinstance(self.version, Version)
            or not isinstance(self.top_level_imports, tuple)
        ):
            raise _invalid_dto("Host runtime package identity is invalid.")
        normalized = []
        seen = set()
        for name in self.top_level_imports:
            if (
                not isinstance(name, str)
                or not _IMPORT_PATTERN.fullmatch(name)
                or keyword.iskeyword(name)
                or name.casefold() in seen
            ):
                raise _invalid_dto("Host runtime package imports are invalid.")
            normalized.append(name)
            seen.add(name.casefold())
        if normalized != sorted(normalized, key=_casefold_sort_key):
            raise _invalid_dto("Host runtime package imports are not canonical.")


@dataclass(frozen=True)
class HostRuntimeDll:
    path: str
    sha256: str
    size: int

    def __post_init__(self):
        if not _is_safe_dll_path(self.path):
            raise _invalid_dto("Host runtime DLL path is invalid.")
        if not isinstance(self.sha256, str) or not _SHA256_PATTERN.fullmatch(
            self.sha256
        ):
            raise _invalid_dto("Host runtime DLL SHA-256 is invalid.")
        if type(self.size) is not int or self.size <= 0:
            raise _invalid_dto("Host runtime DLL size is invalid.")

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name.casefold()


@dataclass(frozen=True)
class HostRuntimeLock:
    lock_version: int
    app_version: Version
    target: HostRuntimeTarget
    packages: tuple[HostRuntimePackage, ...]
    dlls: tuple[HostRuntimeDll, ...]

    def __post_init__(self):
        if type(self.lock_version) is not int or self.lock_version != 1:
            raise _invalid_dto("Host runtime lock version is invalid.")
        if not isinstance(self.app_version, Version) or not isinstance(
            self.target, HostRuntimeTarget
        ):
            raise _invalid_dto("Host runtime lock identity is invalid.")
        if (
            not isinstance(self.packages, tuple)
            or not self.packages
            or not all(isinstance(item, HostRuntimePackage) for item in self.packages)
        ):
            raise _invalid_dto("Host runtime package closure is invalid.")
        if (
            not isinstance(self.dlls, tuple)
            or not self.dlls
            or not all(isinstance(item, HostRuntimeDll) for item in self.dlls)
        ):
            raise _invalid_dto("Host runtime DLL inventory is invalid.")

        distributions = [item.distribution for item in self.packages]
        if distributions != sorted(distributions) or len(distributions) != len(
            set(distributions)
        ):
            raise _invalid_dto("Host runtime packages are not canonical and unique.")
        dll_paths = [item.path for item in self.dlls]
        dll_keys = [path.casefold() for path in dll_paths]
        if dll_paths != sorted(dll_paths, key=str.casefold) or len(dll_keys) != len(
            set(dll_keys)
        ):
            raise _invalid_dto("Host runtime DLL paths are not canonical and unique.")
        if not any(item.top_level_imports for item in self.packages):
            raise _invalid_dto("Host runtime import ownership is empty.")

    @property
    def package_versions(self) -> Mapping[str, Version]:
        return MappingProxyType(
            {item.distribution: item.version for item in self.packages}
        )

    @property
    def import_owners(self) -> Mapping[str, tuple[str, ...]]:
        owners: dict[str, list[str]] = {}
        for package in self.packages:
            for name in package.top_level_imports:
                owners.setdefault(name.casefold(), []).append(package.distribution)
        return MappingProxyType(
            {name: tuple(sorted(values)) for name, values in owners.items()}
        )

    @property
    def protected_imports(self) -> frozenset[str]:
        return frozenset(self.import_owners)

    @property
    def protected_dll_basenames(self) -> frozenset[str]:
        return frozenset(item.name for item in self.dlls)


def _is_safe_dll_path(value) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or "\\" in value
    ):
        return False
    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(value)
    if (
        windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.is_absolute()
        or any(part in {"", ".", ".."} for part in posix_path.parts)
        or posix_path.as_posix() != value
    ):
        return False
    for part in posix_path.parts:
        if (
            part.endswith((" ", "."))
            or any(ord(character) < 32 for character in part)
            or any(character in '<>:"|?*' for character in part)
        ):
            return False
    return posix_path.suffix.casefold() == ".dll"


def _casefold_sort_key(value: str) -> tuple[str, str]:
    return value.casefold(), value


def _invalid_dto(message: str) -> HostRuntimeLockError:
    return HostRuntimeLockError(
        "INVALID_HOST_RUNTIME_LOCK",
        message,
        field="lock",
    )


__all__ = [
    "HOST_RUNTIME_LOCK_FILENAME",
    "HOST_RUNTIME_LOCK_VERSION",
    "MAX_HOST_RUNTIME_LOCK_SIZE",
    "SUPPORTED_HOST_PLATFORMS",
    "HostRuntimeDll",
    "HostRuntimeLock",
    "HostRuntimeLockError",
    "HostRuntimePackage",
    "HostRuntimeTarget",
]
