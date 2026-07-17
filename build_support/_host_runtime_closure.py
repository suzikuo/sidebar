from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from build_support._host_runtime_imports import extract_top_level_imports
from build_support._inventory_common import BuildInventoryError, inventory_error
from core.plugin_system.host_runtime_lock_types import HostRuntimePackage


DistributionProvider = Callable[[str], Iterable[Any]]
_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


@dataclass(frozen=True)
class _DistributionFacts:
    name: str
    version: Version
    requirements: tuple[Requirement, ...]
    provided_extras: frozenset[str]
    distribution: Any


def build_package_inventory(
    root_requirements: Iterable[str],
    *,
    distribution_provider: DistributionProvider,
    marker_environment: Mapping[str, str] | None = None,
    top_level_overrides: Mapping[str, Iterable[str]] | None = None,
) -> tuple[HostRuntimePackage, ...]:
    environment = default_environment()
    if marker_environment is not None:
        try:
            environment.update(dict(marker_environment))
        except (TypeError, ValueError) as error:
            raise inventory_error(
                "INVALID_MARKER_ENVIRONMENT",
                "Marker environment must be a string mapping.",
            ) from error
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in environment.items()):
        raise inventory_error(
            "INVALID_MARKER_ENVIRONMENT",
            "Marker environment must be a string mapping.",
        )
    overrides = _normalize_overrides(top_level_overrides or {})
    roots = _parse_roots(root_requirements, environment)
    if not roots:
        raise inventory_error(
            "EMPTY_ROOT_REQUIREMENTS",
            "At least one active root requirement is required.",
        )

    cache: dict[str, _DistributionFacts] = {}
    active_extras: dict[str, set[str]] = {}
    processed_extras: dict[str, frozenset[str]] = {}
    queue: deque[str] = deque()

    def get_facts(name: str) -> _DistributionFacts:
        facts = cache.get(name)
        if facts is None:
            facts = _load_distribution(name, distribution_provider)
            cache[name] = facts
        return facts

    for name, (pinned_version, extras) in roots.items():
        facts = get_facts(name)
        if facts.version != pinned_version:
            raise inventory_error(
                "DISTRIBUTION_VERSION_MISMATCH",
                f"Root {name} pins {pinned_version}, but metadata is {facts.version}.",
                distribution=name,
            )
        active_extras.setdefault(name, set()).update(extras)
        queue.append(name)

    while queue:
        name = queue.popleft()
        facts = get_facts(name)
        extras = frozenset(active_extras.get(name, ()))
        if processed_extras.get(name) == extras:
            continue
        unknown = extras - facts.provided_extras
        if unknown:
            raise inventory_error(
                "UNKNOWN_DISTRIBUTION_EXTRA",
                f"{name} does not provide requested extras: {', '.join(sorted(unknown))}.",
                distribution=name,
            )
        processed_extras[name] = extras
        for requirement in facts.requirements:
            if not _marker_applies(requirement, environment, extras):
                continue
            dependency_name = _canonical_name(requirement.name)
            dependency = get_facts(dependency_name)
            if requirement.specifier and dependency.version not in requirement.specifier:
                raise inventory_error(
                    "DISTRIBUTION_VERSION_MISMATCH",
                    f"{name} requires {requirement}, but {dependency.version} is present.",
                    distribution=dependency_name,
                )
            requested = {_canonical_name(extra) for extra in requirement.extras}
            known = dependency_name in active_extras
            current = active_extras.setdefault(dependency_name, set())
            before = len(current)
            current.update(requested)
            if not known or len(current) != before:
                queue.append(dependency_name)

    unknown_overrides = set(overrides) - set(cache)
    if unknown_overrides:
        name = sorted(unknown_overrides)[0]
        raise inventory_error(
            "UNKNOWN_TOP_LEVEL_OVERRIDE",
            f"Top-level override targets a distribution outside the closure: {name}.",
            distribution=name,
        )

    packages = []
    for name in sorted(cache):
        facts = cache[name]
        imports = extract_top_level_imports(
            facts.distribution,
            distribution_name=name,
            additive_override=overrides.get(name, ()),
        )
        packages.append(HostRuntimePackage(name, facts.version, imports))
    return tuple(packages)


def _parse_roots(
    values: Iterable[str], environment: Mapping[str, str]
) -> dict[str, tuple[Version, frozenset[str]]]:
    if isinstance(values, (str, bytes)):
        raise inventory_error(
            "INVALID_ROOT_REQUIREMENT",
            "Root requirements must be an iterable of requirement strings.",
        )
    try:
        raw_values = tuple(values)
    except TypeError as error:
        raise inventory_error(
            "INVALID_ROOT_REQUIREMENT",
            "Root requirements must be iterable.",
        ) from error
    roots: dict[str, tuple[Version, frozenset[str]]] = {}
    for raw in raw_values:
        requirement = _parse_requirement(raw, root=True)
        specifiers = tuple(requirement.specifier)
        if (
            len(specifiers) != 1
            or specifiers[0].operator != "=="
            or "*" in specifiers[0].version
        ):
            raise inventory_error(
                "ROOT_REQUIREMENT_NOT_PINNED",
                f"Root requirement must use one exact == pin: {raw!r}.",
            )
        try:
            version = Version(specifiers[0].version)
        except InvalidVersion as error:
            raise inventory_error(
                "ROOT_REQUIREMENT_NOT_PINNED",
                f"Root requirement has an invalid exact version: {raw!r}.",
            ) from error
        extras = frozenset(_canonical_name(value) for value in requirement.extras)
        if not _marker_applies(requirement, environment, extras):
            continue
        name = _canonical_name(requirement.name)
        previous = roots.get(name)
        if previous is not None and previous[0] != version:
            raise inventory_error(
                "CONFLICTING_ROOT_REQUIREMENT",
                f"Root requirements pin conflicting versions of {name}.",
                distribution=name,
            )
        roots[name] = (
            version,
            frozenset(set(previous[1] if previous else ()) | set(extras)),
        )
    return roots


def _load_distribution(name: str, provider: DistributionProvider) -> _DistributionFacts:
    try:
        provided = provider(name)
        if isinstance(provided, (str, bytes)):
            raise TypeError("provider returned text")
        candidates = tuple(provided)
    except BuildInventoryError:
        raise
    except Exception as error:
        raise inventory_error(
            "DISTRIBUTION_PROVIDER_FAILED",
            f"Cannot query distribution metadata for {name}: {error}",
            distribution=name,
        ) from error
    if not candidates:
        raise inventory_error(
            "DISTRIBUTION_NOT_FOUND",
            f"Distribution metadata is missing for {name}.",
            distribution=name,
        )
    if len(candidates) != 1:
        raise inventory_error(
            "DUPLICATE_DISTRIBUTION_METADATA",
            f"Multiple metadata records were returned for {name}.",
            distribution=name,
        )
    distribution = candidates[0]
    metadata = _read_metadata(distribution, name)
    actual_name = _single_metadata_value(metadata, "Name", name)
    if _canonical_name(actual_name) != name:
        raise inventory_error(
            "DISTRIBUTION_PROVIDER_MISMATCH",
            f"Provider returned {actual_name!r} while querying {name}.",
            distribution=name,
        )
    raw_version = _single_metadata_value(metadata, "Version", name)
    try:
        version = Version(raw_version)
    except InvalidVersion as error:
        raise inventory_error(
            "INVALID_DISTRIBUTION_METADATA",
            f"Distribution {name} has an invalid version.",
            distribution=name,
        ) from error
    _reject_direct_url(distribution, name)
    requirements = _metadata_requirements(metadata, name)
    extras = _metadata_extras(metadata, name)
    return _DistributionFacts(name, version, requirements, extras, distribution)


def _read_metadata(distribution: Any, name: str) -> Any:
    try:
        metadata = distribution.metadata
    except Exception as error:
        raise inventory_error(
            "INVALID_DISTRIBUTION_METADATA",
            f"Cannot read metadata for {name}: {error}",
            distribution=name,
        ) from error
    if metadata is None or not hasattr(metadata, "get"):
        raise inventory_error(
            "INVALID_DISTRIBUTION_METADATA",
            f"Distribution {name} has no readable metadata.",
            distribution=name,
        )
    return metadata


def _single_metadata_value(metadata: Any, field: str, name: str) -> str:
    values = _metadata_values(metadata, field, name)
    if len(values) != 1 or not isinstance(values[0], str) or not values[0].strip():
        raise inventory_error(
            "INVALID_DISTRIBUTION_METADATA",
            f"Distribution {name} must contain exactly one {field} field.",
            distribution=name,
        )
    return values[0].strip()


def _metadata_requirements(metadata: Any, name: str) -> tuple[Requirement, ...]:
    raw_values = _metadata_values(metadata, "Requires-Dist", name)
    if len(raw_values) != len(set(raw_values)):
        raise inventory_error(
            "DUPLICATE_REQUIREMENT_METADATA",
            f"Distribution {name} contains duplicate dependency metadata.",
            distribution=name,
        )
    return tuple(_parse_requirement(value, root=False, owner=name) for value in raw_values)


def _metadata_extras(metadata: Any, name: str) -> frozenset[str]:
    normalized = [_canonical_name(value) for value in _metadata_values(metadata, "Provides-Extra", name)]
    if len(normalized) != len(set(normalized)):
        raise inventory_error(
            "DUPLICATE_EXTRA_METADATA",
            f"Distribution {name} contains duplicate extra metadata.",
            distribution=name,
        )
    return frozenset(normalized)


def _metadata_values(metadata: Any, field: str, name: str) -> tuple[str, ...]:
    try:
        getter = getattr(metadata, "get_all", None)
        if getter is not None:
            values = getter(field) or ()
        else:
            value = metadata.get(field)
            values = () if value is None else (value,)
        result = tuple(values)
    except Exception as error:
        raise inventory_error(
            "INVALID_DISTRIBUTION_METADATA",
            f"Cannot read {field} metadata for {name}: {error}",
            distribution=name,
        ) from error
    if any(not isinstance(value, str) for value in result):
        raise inventory_error(
            "INVALID_DISTRIBUTION_METADATA",
            f"Distribution {name} has a non-text {field} field.",
            distribution=name,
        )
    return result


def _parse_requirement(raw: Any, *, root: bool, owner: str | None = None) -> Requirement:
    code = "INVALID_ROOT_REQUIREMENT" if root else "INVALID_REQUIREMENT_METADATA"
    if not isinstance(raw, str) or not raw.strip():
        raise inventory_error(code, "Requirement metadata must be non-empty text.", distribution=owner)
    try:
        requirement = Requirement(raw.strip())
    except InvalidRequirement as error:
        raise inventory_error(code, f"Invalid requirement: {raw!r}.", distribution=owner) from error
    if requirement.url is not None:
        raise inventory_error(
            "DIRECT_URL_REQUIREMENT_UNSUPPORTED",
            f"Direct URL requirements are not supported: {raw!r}.",
            distribution=owner,
        )
    _canonical_name(requirement.name)
    return requirement


def _marker_applies(
    requirement: Requirement,
    environment: Mapping[str, str],
    extras: frozenset[str],
) -> bool:
    if requirement.marker is None:
        return True
    contexts = ("", *sorted(extras))
    try:
        return any(requirement.marker.evaluate({**environment, "extra": extra}) for extra in contexts)
    except Exception as error:
        raise inventory_error(
            "INVALID_REQUIREMENT_MARKER",
            f"Cannot evaluate requirement marker for {requirement}.",
        ) from error


def _reject_direct_url(distribution: Any, name: str) -> None:
    reader = getattr(distribution, "read_text", None)
    if reader is None:
        return
    try:
        payload = reader("direct_url.json")
    except Exception as error:
        raise inventory_error(
            "INVALID_DIRECT_URL_METADATA",
            f"Cannot read direct URL metadata for {name}: {error}",
            distribution=name,
        ) from error
    if payload is None:
        return
    try:
        data = json.loads(payload)
    except (TypeError, ValueError) as error:
        raise inventory_error(
            "INVALID_DIRECT_URL_METADATA",
            f"Distribution {name} has invalid direct URL metadata.",
            distribution=name,
        ) from error
    editable = isinstance(data, dict) and isinstance(data.get("dir_info"), dict) and data["dir_info"].get("editable") is True
    code = "EDITABLE_DISTRIBUTION_UNSUPPORTED" if editable else "DIRECT_URL_DISTRIBUTION_UNSUPPORTED"
    raise inventory_error(code, f"Direct URL distribution {name} is not supported.", distribution=name)


def _normalize_overrides(values: Mapping[str, Iterable[str]]) -> dict[str, tuple[str, ...]]:
    try:
        items = tuple(values.items())
    except (AttributeError, TypeError) as error:
        raise inventory_error("INVALID_TOP_LEVEL_OVERRIDE", "Top-level overrides must be a mapping.") from error
    normalized = {}
    for name, imports in items:
        if not isinstance(name, str) or _canonical_name(name) != name or isinstance(imports, (str, bytes)):
            raise inventory_error("INVALID_TOP_LEVEL_OVERRIDE", "Override keys must be canonical distribution names.")
        try:
            normalized[name] = tuple(imports)
        except TypeError as error:
            raise inventory_error("INVALID_TOP_LEVEL_OVERRIDE", f"Override for {name} must be iterable.", distribution=name) from error
    return normalized


def _canonical_name(value: Any) -> str:
    if not isinstance(value, str):
        raise inventory_error("INVALID_DISTRIBUTION_NAME", "Distribution name must be text.")
    normalized = canonicalize_name(value.strip())
    if not _NAME_PATTERN.fullmatch(normalized):
        raise inventory_error("INVALID_DISTRIBUTION_NAME", f"Invalid distribution name: {value!r}.")
    return normalized
