from __future__ import annotations

import os
import stat
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from core.plugin_system.host_runtime_lock_codec import (
    dll_to_data,
    package_to_data,
    parse_dll_entry,
    parse_host_runtime_lock,
    parse_host_runtime_lock_json,
    parse_package_entry,
    serialize_host_runtime_lock,
    validate_lock_instance,
)
from core.plugin_system.host_runtime_lock_types import (
    HOST_RUNTIME_LOCK_FILENAME,
    HOST_RUNTIME_LOCK_VERSION,
    MAX_HOST_RUNTIME_LOCK_SIZE,
    SUPPORTED_HOST_PLATFORMS,
    HostRuntimeDll,
    HostRuntimeLock,
    HostRuntimeLockError,
    HostRuntimePackage,
    HostRuntimeTarget,
)


def build_host_runtime_lock(
    *,
    app_version: str,
    python_abi: str,
    platform: str,
    packages: Iterable[HostRuntimePackage | Mapping[str, Any]],
    dlls: Iterable[HostRuntimeDll | Mapping[str, Any]],
) -> HostRuntimeLock:
    """Build a canonical lock exclusively from explicitly supplied facts."""

    parsed_packages = []
    for index, value in enumerate(_bounded_iterable(packages, "packages")):
        try:
            if isinstance(value, HostRuntimePackage):
                raw = package_to_data(value)
            elif isinstance(value, Mapping):
                raw = dict(value)
            else:
                raise TypeError
            imports = raw.get("top_level_imports")
            if isinstance(imports, (tuple, list)):
                raw["top_level_imports"] = list(imports)
        except Exception as error:
            raise HostRuntimeLockError(
                "INVALID_HOST_RUNTIME_PACKAGE",
                "Host runtime package entries must be explicit objects.",
                field=f"packages.{index}",
            ) from error
        parsed_packages.append(
            parse_package_entry(raw, index, require_sorted_imports=False)
        )
    parsed_packages.sort(key=lambda item: item.distribution)

    parsed_dlls = []
    for index, value in enumerate(_bounded_iterable(dlls, "dlls")):
        try:
            if isinstance(value, HostRuntimeDll):
                raw = dll_to_data(value)
            elif isinstance(value, Mapping):
                raw = dict(value)
            else:
                raise TypeError
        except Exception as error:
            raise HostRuntimeLockError(
                "INVALID_HOST_RUNTIME_DLL",
                "Host runtime DLL entries must be explicit objects.",
                field=f"dlls.{index}",
            ) from error
        parsed_dlls.append(parse_dll_entry(raw, index))
    parsed_dlls.sort(key=lambda item: item.path.casefold())

    return parse_host_runtime_lock(
        {
            "lock_version": HOST_RUNTIME_LOCK_VERSION,
            "app_version": app_version,
            "target": {"python_abi": python_abi, "platform": platform},
            "packages": [package_to_data(item) for item in parsed_packages],
            "dlls": [dll_to_data(item) for item in parsed_dlls],
        }
    )


def generate_host_runtime_lock(
    *,
    app_version: str,
    python_abi: str,
    platform: str,
    packages: Iterable[HostRuntimePackage | Mapping[str, Any]],
    dlls: Iterable[HostRuntimeDll | Mapping[str, Any]],
) -> bytes:
    """Build and serialize a lock without inspecting the active environment."""

    return serialize_host_runtime_lock(
        build_host_runtime_lock(
            app_version=app_version,
            python_abi=python_abi,
            platform=platform,
            packages=packages,
            dlls=dlls,
        )
    )


def validate_host_runtime_lock(
    lock: HostRuntimeLock,
    *,
    expected_app_version: str,
    expected_python_abi: str,
    expected_platform: str,
) -> None:
    """Bind immutable lock facts to the exact running application target."""

    normalized = validate_lock_instance(lock)
    expected_version = _exact_version(
        expected_app_version,
        field="expected.app_version",
    )
    if (
        not isinstance(expected_python_abi, str)
        or not expected_python_abi.startswith("cp")
        or not expected_python_abi[2:].isdigit()
        or len(expected_python_abi[2:]) not in {2, 3}
        or not isinstance(expected_platform, str)
        or expected_platform not in SUPPORTED_HOST_PLATFORMS
    ):
        raise HostRuntimeLockError(
            "INVALID_HOST_RUNTIME_TARGET",
            "Expected host runtime target is invalid.",
            field="expected.target",
        )
    checks = (
        (
            normalized.app_version == expected_version,
            "HOST_RUNTIME_LOCK_APP_VERSION_MISMATCH",
            "Lock belongs to a different application version.",
            "app_version",
        ),
        (
            normalized.target.python_abi == expected_python_abi,
            "HOST_RUNTIME_LOCK_PYTHON_ABI_MISMATCH",
            "Lock belongs to a different Python ABI.",
            "target.python_abi",
        ),
        (
            normalized.target.platform == expected_platform,
            "HOST_RUNTIME_LOCK_PLATFORM_MISMATCH",
            "Lock belongs to a different platform.",
            "target.platform",
        ),
    )
    for matches, code, message, field in checks:
        if not matches:
            raise HostRuntimeLockError(code, message, field=field)


def load_host_runtime_lock(
    path: Path,
    *,
    expected_app_version: str,
    expected_python_abi: str,
    expected_platform: str,
) -> HostRuntimeLock:
    """Load the shipped lock once, without environment metadata fallback."""

    payload = _read_lock_file(path)
    lock = parse_host_runtime_lock_json(payload)
    validate_host_runtime_lock(
        lock,
        expected_app_version=expected_app_version,
        expected_python_abi=expected_python_abi,
        expected_platform=expected_platform,
    )
    return lock


def _bounded_iterable(values, field: str) -> tuple:
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise HostRuntimeLockError(
            f"INVALID_HOST_RUNTIME_{field.upper()}",
            f"Host runtime {field} must be an iterable of explicit facts.",
            field=field,
        )
    try:
        return tuple(values)
    except Exception as error:
        raise HostRuntimeLockError(
            f"INVALID_HOST_RUNTIME_{field.upper()}",
            f"Cannot enumerate host runtime {field}: {error}",
            field=field,
        ) from error


def _read_lock_file(path) -> bytes:
    try:
        candidate = Path(path)
        initial = candidate.lstat()
    except (OSError, TypeError, ValueError) as error:
        raise _read_error(error) from error
    if _unsafe_file_stat(initial):
        raise HostRuntimeLockError(
            "UNSAFE_HOST_RUNTIME_LOCK",
            "Host runtime lock must be a regular independent non-reparse file.",
            field="lock",
        )
    if initial.st_size > MAX_HOST_RUNTIME_LOCK_SIZE:
        raise HostRuntimeLockError(
            "HOST_RUNTIME_LOCK_TOO_LARGE",
            "Host runtime lock exceeds its size limit.",
            field="lock",
        )
    try:
        with candidate.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if _unsafe_file_stat(opened) or not _same_file(initial, opened):
                raise HostRuntimeLockError(
                    "HOST_RUNTIME_LOCK_CHANGED",
                    "Host runtime lock changed while being opened.",
                    field="lock",
                )
            payload = stream.read(MAX_HOST_RUNTIME_LOCK_SIZE + 1)
            final = os.fstat(stream.fileno())
    except HostRuntimeLockError:
        raise
    except OSError as error:
        raise _read_error(error) from error
    if (
        len(payload) != opened.st_size
        or not _same_file(opened, final)
        or opened.st_size != final.st_size
        or opened.st_mtime_ns != final.st_mtime_ns
    ):
        raise HostRuntimeLockError(
            "HOST_RUNTIME_LOCK_CHANGED",
            "Host runtime lock changed while being read.",
            field="lock",
        )
    return payload


def _unsafe_file_stat(file_stat) -> bool:
    attributes = getattr(file_stat, "st_file_attributes", 0)
    return (
        not stat.S_ISREG(file_stat.st_mode)
        or stat.S_ISLNK(file_stat.st_mode)
        or bool(
            attributes
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
        or getattr(file_stat, "st_nlink", 1) > 1
    )


def _same_file(first, second) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _exact_version(value, *, field: str) -> Version:
    if not isinstance(value, str) or not value:
        raise _version_error(field)
    try:
        version = Version(value)
    except InvalidVersion as error:
        raise _version_error(field) from error
    if str(version) != value:
        raise _version_error(field)
    return version


def _version_error(field: str) -> HostRuntimeLockError:
    return HostRuntimeLockError(
        "INVALID_HOST_RUNTIME_VERSION",
        "Versions must be exact canonical version strings.",
        field=field,
    )


def _read_error(error) -> HostRuntimeLockError:
    return HostRuntimeLockError(
        "HOST_RUNTIME_LOCK_READ_FAILED",
        f"Cannot read host runtime lock: {error}",
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
    "build_host_runtime_lock",
    "generate_host_runtime_lock",
    "load_host_runtime_lock",
    "parse_host_runtime_lock",
    "parse_host_runtime_lock_json",
    "serialize_host_runtime_lock",
    "validate_host_runtime_lock",
]
