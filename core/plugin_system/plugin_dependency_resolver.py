from __future__ import annotations

import keyword
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Mapping

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
from packaging.version import InvalidVersion

from core.plugin_system.plugin_dependency_lock import DependencyLock
from core.plugin_system.plugin_wheel import WheelArtifact


_CPYTHON_ABI_PATTERN = re.compile(r"cp(?P<digits>[0-9]{2,3})\Z")
_TOP_LEVEL_IMPORT_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class PluginDependencyResolutionError(ValueError):
    """A deterministic process-level dependency conflict."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PluginDependencyInput:
    lock: DependencyLock
    wheels: tuple[WheelArtifact, ...]


@dataclass(frozen=True)
class ResolvedDependency:
    name: str
    version: Version
    sha256: str
    artifact: WheelArtifact
    owners: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedDependencySet:
    python_abi: str | None
    platform_tag: str | None
    packages: tuple[ResolvedDependency, ...]
    plugin_packages: Mapping[str, tuple[str, ...]]


def resolve_dependency_set(
    plugin_inputs: Mapping[str, PluginDependencyInput],
    *,
    host_packages: Mapping[str, Version | str] | None = None,
    host_imports: Iterable[str] | None = None,
    host_dll_basenames: Iterable[str] | None = None,
    stdlib_modules: frozenset[str] | set[str] | None = None,
) -> ResolvedDependencySet:
    """Resolve one immutable dependency set for the shared Python process."""

    if not isinstance(plugin_inputs, Mapping):
        raise PluginDependencyResolutionError(
            "INVALID_DEPENDENCY_INPUT",
            "Plugin dependency inputs must be a mapping.",
        )
    if host_packages is not None and not isinstance(host_packages, Mapping):
        raise PluginDependencyResolutionError(
            "INVALID_HOST_DEPENDENCY",
            "Host dependencies must be a package-to-version mapping.",
        )
    host_versions = {}
    for name, raw_version in (host_packages or {}).items():
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise PluginDependencyResolutionError(
                "INVALID_HOST_DEPENDENCY",
                "Host dependency name is invalid.",
            )
        normalized_name = canonicalize_name(name)
        if normalized_name in host_versions:
            raise PluginDependencyResolutionError(
                "INVALID_HOST_DEPENDENCY",
                f"Host dependency is duplicated after normalization: {name}",
            )
        try:
            host_versions[normalized_name] = (
                raw_version
                if isinstance(raw_version, Version)
                else Version(str(raw_version))
            )
        except InvalidVersion as error:
            raise PluginDependencyResolutionError(
                "INVALID_HOST_DEPENDENCY",
                f"Host dependency version is invalid: {name}",
            ) from error
    stdlib_names = {
        name.casefold()
        for name in (
            stdlib_modules
            if stdlib_modules is not None
            else sys.stdlib_module_names
        )
    }
    protected_host_imports = _normalize_host_imports(host_imports)
    protected_host_dlls = _normalize_host_dll_basenames(host_dll_basenames)

    target = None
    selected = {}
    owners: dict[str, set[str]] = {}
    plugin_packages = {}

    for plugin_id in sorted(plugin_inputs):
        if not isinstance(plugin_id, str) or not plugin_id:
            raise PluginDependencyResolutionError(
                "INVALID_DEPENDENCY_INPUT",
                "Plugin dependency input has an invalid plugin id.",
            )
        plugin_input = plugin_inputs[plugin_id]
        if not isinstance(plugin_input, PluginDependencyInput):
            raise PluginDependencyResolutionError(
                "INVALID_DEPENDENCY_INPUT",
                f"Plugin dependency input is invalid: {plugin_id}",
            )
        lock = plugin_input.lock
        current_target = (lock.target.python_abi, lock.target.platform_tag)
        if target is None:
            target = current_target
        elif target != current_target:
            raise PluginDependencyResolutionError(
                "DEPENDENCY_TARGET_CONFLICT",
                "Selected plugins use different dependency targets.",
            )

        artifacts = {}
        for artifact in plugin_input.wheels:
            if not isinstance(artifact, WheelArtifact):
                raise PluginDependencyResolutionError(
                    "INVALID_DEPENDENCY_INPUT",
                    f"Plugin has an invalid wheel artifact: {plugin_id}",
                )
            if (
                artifact.target_python_abi,
                artifact.target_platform,
            ) != current_target:
                raise PluginDependencyResolutionError(
                    "LOCKED_WHEEL_TARGET_MISMATCH",
                    f"Wheel artifact target differs for {artifact.distribution}.",
                )
            name = canonicalize_name(artifact.distribution)
            if name in artifacts:
                raise PluginDependencyResolutionError(
                    "DUPLICATE_DEPENDENCY_ARTIFACT",
                    f"Plugin provides duplicate wheel artifacts: {name}",
                )
            artifacts[name] = artifact

        locked_names = {package.name for package in lock.packages}
        extra_artifacts = sorted(set(artifacts) - locked_names)
        if extra_artifacts:
            raise PluginDependencyResolutionError(
                "UNLOCKED_DEPENDENCY_ARTIFACT",
                f"Plugin provides an unlocked wheel: {extra_artifacts[0]}",
            )

        current_names = []
        for package in lock.packages:
            artifact = artifacts.get(package.name)
            if artifact is None:
                raise PluginDependencyResolutionError(
                    "LOCKED_WHEEL_MISSING",
                    f"Plugin is missing a locked wheel: {package.name}",
                )
            if artifact.version != package.version:
                raise PluginDependencyResolutionError(
                    "LOCKED_WHEEL_VERSION_MISMATCH",
                    f"Locked wheel version differs for {package.name}.",
                )
            if artifact.sha256 != package.sha256:
                raise PluginDependencyResolutionError(
                    "LOCKED_WHEEL_HASH_MISMATCH",
                    f"Locked wheel hash differs for {package.name}.",
                )
            if package.name in host_versions:
                raise PluginDependencyResolutionError(
                    "DEPENDENCY_SHADOWS_HOST",
                    f"Plugin-managed dependency shadows a host package: {package.name}",
                )

            existing = selected.get(package.name)
            if existing is not None:
                if existing.version != package.version:
                    raise PluginDependencyResolutionError(
                        "DEPENDENCY_VERSION_CONFLICT",
                        f"Plugins require different versions of {package.name}.",
                    )
                if existing.sha256 != package.sha256:
                    raise PluginDependencyResolutionError(
                        "DEPENDENCY_ARTIFACT_CONFLICT",
                        f"Plugins lock different wheel content for {package.name}.",
                    )
            else:
                selected[package.name] = artifact
            owners.setdefault(package.name, set()).add(plugin_id)
            current_names.append(package.name)
        plugin_packages[plugin_id] = tuple(sorted(current_names))

    if target is not None:
        _validate_dependency_closure(selected, target, host_versions)
    _validate_runtime_conflicts(
        selected,
        stdlib_names,
        protected_host_imports,
        protected_host_dlls,
    )

    packages = tuple(
        ResolvedDependency(
            name=name,
            version=artifact.version,
            sha256=artifact.sha256,
            artifact=artifact,
            owners=tuple(sorted(owners[name])),
        )
        for name, artifact in sorted(selected.items())
    )
    return ResolvedDependencySet(
        python_abi=target[0] if target else None,
        platform_tag=target[1] if target else None,
        packages=packages,
        plugin_packages=MappingProxyType(dict(plugin_packages)),
    )


def _validate_dependency_closure(selected, target, host_versions):
    marker_environment = _target_marker_environment(*target)
    for owner_name, artifact in sorted(selected.items()):
        for raw_requirement in artifact.requirements:
            try:
                requirement = Requirement(raw_requirement)
            except InvalidRequirement as error:
                raise PluginDependencyResolutionError(
                    "INVALID_WHEEL_REQUIREMENT",
                    f"Invalid dependency metadata in {owner_name}: {raw_requirement}",
                ) from error
            if requirement.marker is not None and not requirement.marker.evaluate(
                marker_environment
            ):
                continue
            dependency_name = canonicalize_name(requirement.name)
            dependency = selected.get(dependency_name)
            if dependency is None:
                host_version = host_versions.get(dependency_name)
                if host_version is not None:
                    if host_version in requirement.specifier:
                        continue
                    raise PluginDependencyResolutionError(
                        "HOST_DEPENDENCY_VERSION_MISMATCH",
                        f"Host package does not satisfy {owner_name}: {requirement}",
                    )
                raise PluginDependencyResolutionError(
                    "DEPENDENCY_CLOSURE_INCOMPLETE",
                    f"{owner_name} requires a missing package: {dependency_name}",
                )
            if dependency.version not in requirement.specifier:
                raise PluginDependencyResolutionError(
                    "DEPENDENCY_CLOSURE_VERSION_MISMATCH",
                    f"{owner_name} requirement is not satisfied: {requirement}",
                )


def _target_marker_environment(python_abi: str, platform_tag: str):
    match = _CPYTHON_ABI_PATTERN.fullmatch(python_abi)
    if match is None:
        raise PluginDependencyResolutionError(
            "INVALID_DEPENDENCY_TARGET",
            f"Unsupported Python dependency target: {python_abi}",
        )
    digits = match.group("digits")
    major = int(digits[0])
    minor = int(digits[1:])
    python_version = f"{major}.{minor}"
    machine_by_platform = {
        "win32": "x86",
        "win_amd64": "AMD64",
        "win_arm64": "ARM64",
    }
    machine = machine_by_platform.get(platform_tag)
    if machine is None:
        raise PluginDependencyResolutionError(
            "INVALID_DEPENDENCY_TARGET",
            f"Unsupported dependency platform: {platform_tag}",
        )
    environment = default_environment()
    environment.update(
        {
            "implementation_name": "cpython",
            "implementation_version": f"{python_version}.0",
            "os_name": "nt",
            "platform_machine": machine,
            "platform_python_implementation": "CPython",
            "platform_system": "Windows",
            "python_full_version": f"{python_version}.0",
            "python_version": python_version,
            "sys_platform": "win32",
            "extra": "",
        }
    )
    return environment


def _normalize_host_imports(values) -> frozenset[str]:
    items = _host_inventory_items(
        values,
        code="INVALID_HOST_IMPORT",
        description="Host imports",
    )
    normalized = set()
    for name in items:
        if (
            not isinstance(name, str)
            or not _TOP_LEVEL_IMPORT_PATTERN.fullmatch(name)
            or keyword.iskeyword(name)
        ):
            raise PluginDependencyResolutionError(
                "INVALID_HOST_IMPORT",
                "Host import names must be top-level Python identifiers.",
            )
        normalized.add(name.casefold())
    return frozenset(normalized)


def _normalize_host_dll_basenames(values) -> frozenset[str]:
    items = _host_inventory_items(
        values,
        code="INVALID_HOST_DLL",
        description="Host DLL basenames",
    )
    normalized = set()
    for name in items:
        if not _is_valid_host_dll_basename(name):
            raise PluginDependencyResolutionError(
                "INVALID_HOST_DLL",
                "Host DLL names must be safe .dll basenames.",
            )
        normalized.add(name.casefold())
    return frozenset(normalized)


def _host_inventory_items(values, *, code: str, description: str) -> tuple:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise PluginDependencyResolutionError(
            code,
            f"{description} must be an iterable of strings.",
        )
    try:
        return tuple(values)
    except Exception as error:
        raise PluginDependencyResolutionError(
            code,
            f"Cannot enumerate {description.lower()}.",
        ) from error


def _is_valid_host_dll_basename(value) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and "\x00" not in value
        and "/" not in value
        and "\\" not in value
        and value not in {".", ".."}
        and not value.endswith((" ", "."))
        and not any(ord(character) < 32 for character in value)
        and not any(character in '<>:"|?*' for character in value)
        and value.casefold().endswith(".dll")
    )


def _validate_runtime_conflicts(
    selected,
    stdlib_names,
    protected_host_imports,
    protected_host_dlls,
):
    installed_files = {}
    top_level_imports = {}
    dll_names = {}
    for package_name, artifact in sorted(selected.items()):
        for installed_path in artifact.installed_files:
            _claim_unique(
                installed_files,
                installed_path.casefold(),
                package_name,
                "DEPENDENCY_FILE_CONFLICT",
                f"Installed dependency file conflicts: {installed_path}",
            )
        for import_name in artifact.top_level_imports:
            key = import_name.casefold()
            if key in protected_host_imports:
                raise PluginDependencyResolutionError(
                    "DEPENDENCY_SHADOWS_HOST_IMPORT",
                    f"Dependency shadows a host top-level import: {import_name}",
                )
            if key in stdlib_names:
                raise PluginDependencyResolutionError(
                    "DEPENDENCY_SHADOWS_STDLIB",
                    f"Dependency shadows a standard-library module: {import_name}",
                )
            _claim_unique(
                top_level_imports,
                key,
                package_name,
                "DEPENDENCY_IMPORT_CONFLICT",
                f"Dependencies provide the same top-level import: {import_name}",
            )
        for dll_path in artifact.dlls:
            dll_name = PurePosixPath(dll_path).name
            if dll_name.casefold() in protected_host_dlls:
                raise PluginDependencyResolutionError(
                    "DEPENDENCY_SHADOWS_HOST_DLL",
                    f"Dependency shadows a host DLL basename: {dll_name}",
                )
            _claim_unique(
                dll_names,
                dll_name.casefold(),
                f"{package_name}:{dll_path.casefold()}",
                "DEPENDENCY_DLL_CONFLICT",
                f"Dependencies provide the same DLL basename: {dll_name}",
            )


def _claim_unique(mapping, key, owner, code, message):
    existing = mapping.get(key)
    if existing is not None and existing != owner:
        raise PluginDependencyResolutionError(code, message)
    mapping[key] = owner
