from __future__ import annotations

import json
import keyword
import re
from typing import Any, Mapping

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from core.plugin_system.host_runtime_lock_types import (
    HOST_RUNTIME_LOCK_VERSION,
    MAX_HOST_RUNTIME_LOCK_SIZE,
    SUPPORTED_HOST_PLATFORMS,
    HostRuntimeDll,
    HostRuntimeLock,
    HostRuntimeLockError,
    HostRuntimePackage,
    HostRuntimeTarget,
    _is_safe_dll_path,
)


_ROOT_FIELDS = frozenset(
    {"lock_version", "app_version", "target", "packages", "dlls"}
)
_TARGET_FIELDS = frozenset({"python_abi", "platform"})
_PACKAGE_FIELDS = frozenset({"distribution", "version", "top_level_imports"})
_DLL_FIELDS = frozenset({"path", "sha256", "size"})
_DISTRIBUTION_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_PYTHON_ABI_PATTERN = re.compile(r"cp[0-9]{2,3}\Z")
_IMPORT_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def parse_host_runtime_lock(data: Mapping[str, Any]) -> HostRuntimeLock:
    """Parse canonical lock data into immutable runtime facts."""

    if not isinstance(data, Mapping):
        raise _error(
            "INVALID_HOST_RUNTIME_LOCK",
            "Lock root must be an object.",
            "lock",
        )
    _require_fields(data, _ROOT_FIELDS, "lock")
    lock_version = data["lock_version"]
    if type(lock_version) is not int or lock_version != HOST_RUNTIME_LOCK_VERSION:
        raise _error(
            "UNSUPPORTED_HOST_RUNTIME_LOCK_VERSION",
            "Host runtime lock_version must be the integer 1.",
            "lock_version",
        )

    packages = _parse_packages(data["packages"])
    dlls = _parse_dlls(data["dlls"])
    return HostRuntimeLock(
        lock_version=lock_version,
        app_version=_parse_version(data["app_version"], "app_version"),
        target=_parse_target(data["target"]),
        packages=packages,
        dlls=dlls,
    )


def parse_host_runtime_lock_json(payload: bytes | str) -> HostRuntimeLock:
    """Parse bounded UTF-8 JSON while rejecting duplicate object keys."""

    if isinstance(payload, bytes):
        if len(payload) > MAX_HOST_RUNTIME_LOCK_SIZE:
            raise _too_large()
        try:
            source = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _json_error("Host runtime lock must be UTF-8 JSON.") from error
    elif isinstance(payload, str):
        if len(payload) > MAX_HOST_RUNTIME_LOCK_SIZE:
            raise _too_large()
        source = payload
        try:
            encoded_size = len(source.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise _json_error("Host runtime lock must be UTF-8 JSON.") from error
        if encoded_size > MAX_HOST_RUNTIME_LOCK_SIZE:
            raise _too_large()
    else:
        raise _json_error("Host runtime lock must be UTF-8 JSON.")

    try:
        data = json.loads(source, object_pairs_hook=_unique_object)
    except HostRuntimeLockError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ) as error:
        raise _json_error(f"Cannot parse host runtime lock JSON: {error}") from error
    return parse_host_runtime_lock(data)


def serialize_host_runtime_lock(lock: HostRuntimeLock) -> bytes:
    """Serialize a validated lock to reproducible UTF-8 JSON bytes."""

    normalized = validate_lock_instance(lock)
    source = json.dumps(
        lock_to_data(normalized),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (source + "\n").encode("utf-8")


def parse_package_entry(
    value: Any,
    index: int,
    *,
    require_sorted_imports: bool = True,
) -> HostRuntimePackage:
    field = f"packages.{index}"
    if not isinstance(value, Mapping):
        raise _error(
            "INVALID_HOST_RUNTIME_PACKAGE",
            "Package entry must be an object.",
            field,
        )
    _require_fields(value, _PACKAGE_FIELDS, field)
    distribution = value["distribution"]
    if (
        not isinstance(distribution, str)
        or not _DISTRIBUTION_PATTERN.fullmatch(distribution)
        or canonicalize_name(distribution) != distribution
    ):
        raise _error(
            "INVALID_HOST_RUNTIME_DISTRIBUTION",
            "Distribution must use its canonical name.",
            f"{field}.distribution",
        )
    imports = _parse_imports(
        value["top_level_imports"],
        field,
        require_sorted=require_sorted_imports,
    )
    return HostRuntimePackage(
        distribution=distribution,
        version=_parse_version(value["version"], f"{field}.version"),
        top_level_imports=imports,
    )


def parse_dll_entry(value: Any, index: int) -> HostRuntimeDll:
    field = f"dlls.{index}"
    if not isinstance(value, Mapping):
        raise _error(
            "INVALID_HOST_RUNTIME_DLL",
            "Host runtime DLL must be an object.",
            field,
        )
    _require_fields(value, _DLL_FIELDS, field)
    path = value["path"]
    if not _is_safe_dll_path(path):
        raise _error(
            "INVALID_HOST_RUNTIME_DLL_PATH",
            "Host DLL path must be a safe canonical bundle-relative .dll path.",
            f"{field}.path",
        )
    digest = value["sha256"]
    if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
        raise _error(
            "INVALID_HOST_RUNTIME_DLL_DIGEST",
            "Host DLL SHA-256 must be 64 lowercase hexadecimal characters.",
            f"{field}.sha256",
        )
    size = value["size"]
    if type(size) is not int or size <= 0:
        raise _error(
            "INVALID_HOST_RUNTIME_DLL_SIZE",
            "Host DLL size must be a positive integer.",
            f"{field}.size",
        )
    return HostRuntimeDll(path=path, sha256=digest, size=size)


def validate_lock_instance(lock: HostRuntimeLock) -> HostRuntimeLock:
    if not isinstance(lock, HostRuntimeLock):
        raise _error(
            "INVALID_HOST_RUNTIME_LOCK",
            "A HostRuntimeLock is required.",
            "lock",
        )
    try:
        return parse_host_runtime_lock(lock_to_data(lock))
    except HostRuntimeLockError:
        raise
    except Exception as error:
        raise _error(
            "INVALID_HOST_RUNTIME_LOCK",
            "Host runtime lock DTO structure is invalid.",
            "lock",
        ) from error


def lock_to_data(lock: HostRuntimeLock) -> dict[str, Any]:
    return {
        "lock_version": lock.lock_version,
        "app_version": str(lock.app_version),
        "target": {
            "python_abi": lock.target.python_abi,
            "platform": lock.target.platform,
        },
        "packages": [package_to_data(item) for item in lock.packages],
        "dlls": [dll_to_data(item) for item in lock.dlls],
    }


def package_to_data(package: HostRuntimePackage) -> dict[str, Any]:
    return {
        "distribution": package.distribution,
        "version": str(package.version),
        "top_level_imports": list(package.top_level_imports),
    }


def dll_to_data(dll: HostRuntimeDll) -> dict[str, Any]:
    return {"path": dll.path, "sha256": dll.sha256, "size": dll.size}


def _parse_packages(value: Any) -> tuple[HostRuntimePackage, ...]:
    if not isinstance(value, list):
        raise _error(
            "INVALID_HOST_RUNTIME_PACKAGES",
            "Host runtime packages must be an array.",
            "packages",
        )
    if not value:
        raise _error(
            "EMPTY_HOST_RUNTIME_PACKAGES",
            "Host runtime lock must contain the production package closure.",
            "packages",
        )
    packages = tuple(parse_package_entry(item, i) for i, item in enumerate(value))
    names = [item.distribution for item in packages]
    if names != sorted(names):
        raise _error(
            "NONCANONICAL_HOST_RUNTIME_PACKAGES",
            "Packages must be sorted by canonical distribution.",
            "packages",
        )
    if len(names) != len(set(names)):
        raise _error(
            "DUPLICATE_HOST_RUNTIME_PACKAGE",
            "Host distributions must be unique.",
            "packages",
        )
    if not any(item.top_level_imports for item in packages):
        raise _error(
            "EMPTY_HOST_RUNTIME_IMPORT_OWNERS",
            "Host runtime lock must identify at least one protected import.",
            "packages",
        )
    return packages


def _parse_dlls(value: Any) -> tuple[HostRuntimeDll, ...]:
    if not isinstance(value, list):
        raise _error(
            "INVALID_HOST_RUNTIME_DLLS",
            "Host runtime DLL inventory must be an array.",
            "dlls",
        )
    if not value:
        raise _error(
            "EMPTY_HOST_RUNTIME_DLLS",
            "Host runtime lock must contain the protected DLL inventory.",
            "dlls",
        )
    dlls = tuple(parse_dll_entry(item, i) for i, item in enumerate(value))
    paths = [item.path for item in dlls]
    keys = [path.casefold() for path in paths]
    if paths != sorted(paths, key=str.casefold):
        raise _error(
            "NONCANONICAL_HOST_RUNTIME_DLLS",
            "Host runtime DLLs must be sorted by relative path.",
            "dlls",
        )
    if len(keys) != len(set(keys)):
        raise _error(
            "DUPLICATE_HOST_RUNTIME_DLL",
            "Host runtime DLL paths must be unique.",
            "dlls",
        )
    return dlls


def _parse_target(value: Any) -> HostRuntimeTarget:
    if not isinstance(value, Mapping):
        raise _error(
            "INVALID_HOST_RUNTIME_TARGET",
            "Target must be an object.",
            "target",
        )
    _require_fields(value, _TARGET_FIELDS, "target")
    python_abi = value["python_abi"]
    platform = value["platform"]
    if (
        not isinstance(python_abi, str)
        or not _PYTHON_ABI_PATTERN.fullmatch(python_abi)
        or not isinstance(platform, str)
        or platform not in SUPPORTED_HOST_PLATFORMS
    ):
        raise _error(
            "INVALID_HOST_RUNTIME_TARGET",
            "Target must use a supported CPython ABI and Windows platform.",
            "target",
        )
    return HostRuntimeTarget(python_abi=python_abi, platform=platform)


def _parse_imports(value: Any, package_field: str, *, require_sorted: bool):
    field = f"{package_field}.top_level_imports"
    if not isinstance(value, list):
        raise _error(
            "INVALID_HOST_RUNTIME_IMPORTS",
            "Import owners must be an array.",
            field,
        )
    imports = []
    seen = set()
    for index, name in enumerate(value):
        item_field = f"{field}.{index}"
        if (
            not isinstance(name, str)
            or not _IMPORT_PATTERN.fullmatch(name)
            or keyword.iskeyword(name)
        ):
            raise _error(
                "INVALID_HOST_RUNTIME_IMPORT",
                "Import owners must be top-level Python identifiers.",
                item_field,
            )
        key = name.casefold()
        if key in seen:
            raise _error(
                "DUPLICATE_HOST_RUNTIME_IMPORT",
                f"Duplicate import owner: {name}",
                item_field,
            )
        seen.add(key)
        imports.append(name)
    ordered = sorted(imports, key=lambda name: (name.casefold(), name))
    if require_sorted and imports != ordered:
        raise _error(
            "NONCANONICAL_HOST_RUNTIME_IMPORTS",
            "Import owners must be sorted.",
            field,
        )
    return tuple(ordered)


def _parse_version(value: Any, field: str) -> Version:
    if not isinstance(value, str) or not value:
        raise _version_error(field)
    try:
        version = Version(value)
    except InvalidVersion as error:
        raise _version_error(field) from error
    if str(version) != value:
        raise _version_error(field)
    return version


def _require_fields(value: Mapping[str, Any], expected: frozenset[str], field: str):
    if not all(isinstance(key, str) for key in value):
        raise _error(
            "INVALID_HOST_RUNTIME_LOCK",
            f"{field} keys must be strings.",
            field,
        )
    actual = set(value)
    for difference, code, label in (
        (expected - actual, "MISSING_HOST_RUNTIME_LOCK_FIELD", "Missing"),
        (actual - expected, "UNKNOWN_HOST_RUNTIME_LOCK_FIELD", "Unknown"),
    ):
        if difference:
            key = sorted(difference)[0]
            name = f"{field}.{key}" if field != "lock" else key
            raise _error(code, f"{label} host runtime lock field: {name}", name)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _error(
                "DUPLICATE_HOST_RUNTIME_LOCK_KEY",
                f"Host runtime lock JSON has duplicate key: {key}",
                "lock",
            )
        result[key] = value
    return result


def _too_large() -> HostRuntimeLockError:
    return _error(
        "HOST_RUNTIME_LOCK_TOO_LARGE",
        "Host runtime lock exceeds its size limit.",
        "lock",
    )


def _version_error(field: str) -> HostRuntimeLockError:
    return _error(
        "INVALID_HOST_RUNTIME_VERSION",
        "Versions must be exact canonical version strings.",
        field,
    )


def _json_error(message: str) -> HostRuntimeLockError:
    return _error("INVALID_HOST_RUNTIME_LOCK_JSON", message, "lock")


def _error(code: str, message: str, field: str) -> HostRuntimeLockError:
    return HostRuntimeLockError(code, message, field=field)


__all__ = [
    "dll_to_data",
    "lock_to_data",
    "package_to_data",
    "parse_dll_entry",
    "parse_host_runtime_lock",
    "parse_host_runtime_lock_json",
    "parse_package_entry",
    "serialize_host_runtime_lock",
    "validate_lock_instance",
]
