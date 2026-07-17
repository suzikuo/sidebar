from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Mapping

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from core.plugin_system.plugin_manifest import PluginManifest, PluginManifestError


MAX_DEPENDENCY_LOCK_SIZE = 1024 * 1024

_ROOT_FIELDS = frozenset({"lock_version", "target", "packages"})
_TARGET_FIELDS = frozenset({"python_abi", "platform"})
_PACKAGE_FIELDS = frozenset({"name", "version", "wheel", "sha256"})
_DISTRIBUTION_NAME_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z"
)
_PYTHON_ABI_PATTERN = re.compile(r"cp[0-9]{2,3}\Z")
_PLATFORM_TAG_PATTERN = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)+\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class DependencyLockTarget:
    python_abi: str
    platform_tag: str


@dataclass(frozen=True)
class LockedDependencyPackage:
    name: str
    version: Version
    wheel: str
    sha256: str


@dataclass(frozen=True)
class DependencyLock:
    lock_version: int
    target: DependencyLockTarget
    packages: tuple[LockedDependencyPackage, ...]
    raw: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({}),
        repr=False,
        compare=False,
    )


def parse_dependency_lock(data: Mapping[str, Any]) -> DependencyLock:
    """Parse an immutable dependency lock without filesystem side effects."""

    if not isinstance(data, Mapping):
        raise PluginManifestError(
            "INVALID_DEPENDENCY_LOCK",
            "Dependency lock root must be a JSON object.",
            field="dependencies.lock",
        )
    _require_exact_fields(data, _ROOT_FIELDS, "dependency lock")

    lock_version = data.get("lock_version")
    if isinstance(lock_version, bool) or lock_version != 1:
        raise PluginManifestError(
            "UNSUPPORTED_DEPENDENCY_LOCK_VERSION",
            "Dependency lock_version must be 1.",
            field="lock_version",
        )

    target = _parse_target(data.get("target"))
    packages = _parse_packages(data.get("packages"))
    return DependencyLock(
        lock_version=lock_version,
        target=target,
        packages=packages,
        raw=_deep_freeze(dict(data)),
    )


def parse_dependency_lock_json(payload: bytes | str) -> DependencyLock:
    """Parse bounded UTF-8 JSON and reject duplicate object keys."""

    if isinstance(payload, bytes):
        size = len(payload)
        try:
            source = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PluginManifestError(
                "INVALID_DEPENDENCY_LOCK_JSON",
                "Dependency lock must be UTF-8 JSON.",
                field="dependencies.lock",
            ) from error
    elif isinstance(payload, str):
        source = payload
        size = len(source.encode("utf-8"))
    else:
        raise PluginManifestError(
            "INVALID_DEPENDENCY_LOCK_JSON",
            "Dependency lock must be UTF-8 JSON.",
            field="dependencies.lock",
        )
    if size > MAX_DEPENDENCY_LOCK_SIZE:
        raise PluginManifestError(
            "DEPENDENCY_LOCK_TOO_LARGE",
            "Dependency lock exceeds the size limit.",
            field="dependencies.lock",
        )

    try:
        data = json.loads(source, object_pairs_hook=_unique_json_object)
    except PluginManifestError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise PluginManifestError(
            "INVALID_DEPENDENCY_LOCK_JSON",
            f"Cannot parse dependency lock JSON: {error}",
            field="dependencies.lock",
        ) from error
    return parse_dependency_lock(data)


def validate_dependency_lock(
    manifest: PluginManifest,
    dependency_lock: DependencyLock,
) -> None:
    """Bind a parsed lock to its v2 manifest without activating dependencies."""

    if manifest.manifest_version != 2 or manifest.dependencies.lock is None:
        raise PluginManifestError(
            "DEPENDENCY_LOCK_NOT_DECLARED",
            "Manifest does not declare a dependency lock.",
            field="dependencies.lock",
        )
    if not isinstance(dependency_lock, DependencyLock):
        raise PluginManifestError(
            "INVALID_DEPENDENCY_LOCK",
            "Dependency lock validation requires a parsed DependencyLock.",
            field="dependencies.lock",
        )

    target = dependency_lock.target
    compatibility = manifest.compatibility
    if (
        target.python_abi != compatibility.python_abi
        or target.platform_tag != compatibility.platform_tag
    ):
        raise PluginManifestError(
            "DEPENDENCY_LOCK_TARGET_MISMATCH",
            "Dependency lock target does not match manifest compatibility.",
            field="target",
        )

    packages_by_name = {package.name: package for package in dependency_lock.packages}
    for requirement in manifest.dependencies.python:
        package = packages_by_name.get(requirement.name)
        if package is None:
            raise PluginManifestError(
                "LOCKED_DEPENDENCY_MISSING",
                f"Dependency lock is missing direct requirement: {requirement.name}",
                field="packages",
            )
        if not requirement.accepts(package.version):
            raise PluginManifestError(
                "LOCKED_DEPENDENCY_INCOMPATIBLE",
                f"Locked {package.name} {package.version} does not satisfy "
                f"{requirement.specifier}.",
                field="packages",
            )

    for package in dependency_lock.packages:
        declared_hash = manifest.file_hashes.get(package.wheel)
        if declared_hash is None:
            raise PluginManifestError(
                "LOCKED_WHEEL_NOT_DECLARED",
                f"Locked wheel is not declared in manifest files: {package.wheel}",
                field=f"packages.{package.name}.wheel",
            )
        if declared_hash != package.sha256:
            raise PluginManifestError(
                "LOCKED_WHEEL_HASH_MISMATCH",
                f"Locked wheel hash differs from manifest files: {package.wheel}",
                field=f"packages.{package.name}.sha256",
            )


def parse_and_validate_dependency_lock(
    payload: bytes | str,
    manifest: PluginManifest,
) -> DependencyLock:
    dependency_lock = parse_dependency_lock_json(payload)
    validate_dependency_lock(manifest, dependency_lock)
    return dependency_lock


def _parse_target(value: Any) -> DependencyLockTarget:
    if not isinstance(value, Mapping):
        raise PluginManifestError(
            "INVALID_DEPENDENCY_LOCK_TARGET",
            "Dependency lock target must be an object.",
            field="target",
        )
    _require_exact_fields(value, _TARGET_FIELDS, "target")
    python_abi = _normalized_tag(
        value.get("python_abi"),
        _PYTHON_ABI_PATTERN,
        "python_abi",
    )
    platform_tag = _normalized_tag(
        value.get("platform"),
        _PLATFORM_TAG_PATTERN,
        "platform",
    )
    return DependencyLockTarget(
        python_abi=python_abi,
        platform_tag=platform_tag,
    )


def _parse_packages(value: Any) -> tuple[LockedDependencyPackage, ...]:
    if not isinstance(value, list):
        raise PluginManifestError(
            "INVALID_LOCKED_PACKAGES",
            "Dependency lock packages must be an array.",
            field="packages",
        )

    packages = []
    names = set()
    wheel_paths = set()
    for index, raw_package in enumerate(value):
        field_name = f"packages.{index}"
        if not isinstance(raw_package, Mapping):
            raise PluginManifestError(
                "INVALID_LOCKED_PACKAGE",
                "Locked package entries must be objects.",
                field=field_name,
            )
        _require_exact_fields(raw_package, _PACKAGE_FIELDS, field_name)

        raw_name = raw_package.get("name")
        if (
            not isinstance(raw_name, str)
            or not _DISTRIBUTION_NAME_PATTERN.fullmatch(raw_name.strip())
        ):
            raise PluginManifestError(
                "INVALID_LOCKED_PACKAGE",
                "Locked package name must be a valid distribution name.",
                field=f"{field_name}.name",
            )
        name = canonicalize_name(raw_name.strip())
        if name in names:
            raise PluginManifestError(
                "DUPLICATE_LOCKED_PACKAGE",
                f"Duplicate normalized locked package: {name}",
                field=f"{field_name}.name",
            )

        raw_version = raw_package.get("version")
        if not isinstance(raw_version, str) or not raw_version.strip():
            raise PluginManifestError(
                "INVALID_LOCKED_PACKAGE_VERSION",
                "Locked package version must be an exact version string.",
                field=f"{field_name}.version",
            )
        try:
            version = Version(raw_version.strip())
        except InvalidVersion as error:
            raise PluginManifestError(
                "INVALID_LOCKED_PACKAGE_VERSION",
                "Locked package version must be an exact version string.",
                field=f"{field_name}.version",
            ) from error

        wheel = _parse_relative_path(
            raw_package.get("wheel"),
            f"{field_name}.wheel",
        )
        if Path(wheel).suffix.lower() != ".whl":
            raise PluginManifestError(
                "INVALID_LOCKED_WHEEL",
                "Locked package wheel must reference a .whl file.",
                field=f"{field_name}.wheel",
            )
        wheel_key = wheel.casefold()
        if wheel_key in wheel_paths:
            raise PluginManifestError(
                "DUPLICATE_LOCKED_WHEEL",
                f"Duplicate locked wheel path: {wheel}",
                field=f"{field_name}.wheel",
            )

        digest = _parse_sha256(
            raw_package.get("sha256"),
            f"{field_name}.sha256",
        )
        packages.append(
            LockedDependencyPackage(
                name=name,
                version=version,
                wheel=wheel,
                sha256=digest,
            )
        )
        names.add(name)
        wheel_paths.add(wheel_key)
    return tuple(packages)


def _require_exact_fields(
    value: Mapping[str, Any],
    fields: frozenset[str],
    field_name: str,
) -> None:
    if not all(isinstance(key, str) for key in value):
        raise PluginManifestError(
            "INVALID_DEPENDENCY_LOCK",
            f"{field_name} keys must be strings.",
            field=field_name,
        )
    missing = sorted(fields - set(value))
    if missing:
        nested = f"{field_name}.{missing[0]}"
        raise PluginManifestError(
            "MISSING_DEPENDENCY_LOCK_FIELD",
            f"Missing dependency lock field: {nested}",
            field=nested,
        )
    unknown = sorted(set(value) - fields)
    if unknown:
        nested = f"{field_name}.{unknown[0]}"
        raise PluginManifestError(
            "UNKNOWN_DEPENDENCY_LOCK_FIELD",
            f"Unknown dependency lock field: {nested}",
            field=nested,
        )


def _normalized_tag(value: Any, pattern: re.Pattern[str], field_name: str) -> str:
    if not isinstance(value, str):
        raise PluginManifestError(
            "INVALID_DEPENDENCY_LOCK_TARGET",
            f"Dependency lock {field_name} is invalid.",
            field=f"target.{field_name}",
        )
    normalized = value.strip().lower()
    if not pattern.fullmatch(normalized):
        raise PluginManifestError(
            "INVALID_DEPENDENCY_LOCK_TARGET",
            f"Dependency lock {field_name} is invalid.",
            field=f"target.{field_name}",
        )
    return normalized


def _parse_relative_path(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PluginManifestError(
            "INVALID_LOCKED_WHEEL",
            f"{field_name} must be a safe relative file path.",
            field=field_name,
        )
    normalized = value.strip().replace("\\", "/")
    windows_path = PureWindowsPath(normalized)
    posix_path = PurePosixPath(normalized)
    if (
        windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.is_absolute()
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise PluginManifestError(
            "INVALID_LOCKED_WHEEL",
            f"{field_name} must be a safe relative file path.",
            field=field_name,
        )
    return "/".join(posix_path.parts)


def _parse_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value.lower()):
        raise PluginManifestError(
            "INVALID_LOCKED_WHEEL_HASH",
            f"{field_name} must be a 64-character SHA-256 hex digest.",
            field=field_name,
        )
    return value.lower()


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PluginManifestError(
                "DUPLICATE_DEPENDENCY_LOCK_KEY",
                f"Dependency lock JSON has duplicate key: {key}",
                field="dependencies.lock",
            )
        result[key] = value
    return result


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value
