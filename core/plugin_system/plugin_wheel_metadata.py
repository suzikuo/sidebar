from __future__ import annotations

import re
from email import policy
from email.parser import BytesParser
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.tags import Tag, compatible_tags, cpython_tags, parse_tag
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version

from core.plugin_system.plugin_wheel_types import PluginWheelError


_CPYTHON_ABI_PATTERN = re.compile(r"cp(?P<digits>[0-9]{2,3})\Z")


def parse_filename(filename: str):
    try:
        distribution, version, build_tag, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename as error:
        raise PluginWheelError(
            "INVALID_WHEEL_FILENAME",
            f"Invalid wheel filename: {filename}",
        ) from error
    return canonicalize_name(distribution), version, build_tag, frozenset(tags)


def parse_target_python(python_abi: str) -> Version:
    match = _CPYTHON_ABI_PATTERN.fullmatch(str(python_abi).lower())
    if match is None:
        raise PluginWheelError(
            "INVALID_WHEEL_TARGET",
            f"Unsupported wheel Python target: {python_abi}",
        )
    digits = match.group("digits")
    major = int(digits[0])
    minor = int(digits[1:])
    return Version(f"{major}.{minor}.0")


def supported_tags(
    python_abi: str,
    target_version: Version,
    platform_tag: str,
) -> frozenset[Tag]:
    python_version = (target_version.major, target_version.minor)
    tags = set(cpython_tags(python_version, platforms=[platform_tag]))
    tags.update(
        compatible_tags(
            python_version,
            interpreter=python_abi,
            platforms=[platform_tag],
        )
    )
    return frozenset(tags)


def check_expected_identity(
    distribution: str,
    version: Version,
    expected_name: str | None,
    expected_version: Version | str | None,
):
    if expected_name is not None and canonicalize_name(expected_name) != distribution:
        raise PluginWheelError(
            "WHEEL_NAME_MISMATCH",
            "Wheel distribution name does not match the dependency lock.",
        )
    if expected_version is None:
        return
    try:
        locked_version = (
            expected_version
            if isinstance(expected_version, Version)
            else Version(str(expected_version))
        )
    except InvalidVersion as error:
        raise PluginWheelError(
            "INVALID_WHEEL_VERSION",
            "Expected wheel version is invalid.",
        ) from error
    if locked_version != version:
        raise PluginWheelError(
            "WHEEL_VERSION_MISMATCH",
            "Wheel version does not match the dependency lock.",
        )


def validate_install_path(path: str, distribution: str, version: Version):
    if Path(path).suffix.lower() == ".pth":
        raise PluginWheelError(
            "WHEEL_PTH_NOT_ALLOWED",
            f"Executable .pth files are not allowed: {path}",
        )
    parts = path.split("/")
    if parts[0].endswith(".data"):
        if len(parts) < 3 or parts[1] not in {"purelib", "platlib"}:
            raise PluginWheelError(
                "WHEEL_SCHEME_NOT_ALLOWED",
                f"Wheel install scheme is not allowed: {path}",
            )
        _validate_named_metadata_root(
            parts[0],
            ".data",
            distribution,
            version,
            "WHEEL_DATA_ROOT_MISMATCH",
        )


def installed_files(archive_paths: tuple[str, ...]) -> tuple[str, ...]:
    installed = []
    seen = set()
    for archive_path in archive_paths:
        installed_path = wheel_install_path(archive_path)
        key = installed_path.casefold()
        if key in seen:
            raise PluginWheelError(
                "WHEEL_INSTALL_PATH_COLLISION",
                f"Wheel files map to the same install path: {installed_path}",
            )
        seen.add(key)
        installed.append(installed_path)
    return tuple(sorted(installed))


def top_level_imports(installed_paths: tuple[str, ...]) -> tuple[str, ...]:
    imports = set()
    for member_path in installed_paths:
        parts = member_path.split("/")
        if not parts or parts[0].endswith(".dist-info"):
            continue
        if len(parts) > 1:
            candidate = parts[0]
        else:
            suffix = Path(parts[0]).suffix.lower()
            if suffix == ".py":
                candidate = Path(parts[0]).stem
            elif suffix == ".pyd":
                candidate = parts[0].split(".", 1)[0]
            else:
                continue
        if candidate.isidentifier():
            imports.add(candidate)
    return tuple(sorted(imports))


def wheel_install_path(path: str) -> str:
    """Map one validated wheel archive member to its site install path."""

    parts = path.split("/")
    if parts[0].endswith(".data"):
        return "/".join(parts[2:])
    return path


def validate_dist_info_name(
    dist_info_root: str,
    distribution: str,
    version: Version,
):
    _validate_named_metadata_root(
        dist_info_root,
        ".dist-info",
        distribution,
        version,
        "WHEEL_DIST_INFO_MISMATCH",
    )


def _validate_named_metadata_root(
    root_name: str,
    suffix: str,
    distribution: str,
    version: Version,
    mismatch_code: str,
):
    stem = root_name[: -len(suffix)]
    if "-" not in stem:
        raise PluginWheelError(
            mismatch_code,
            f"Wheel {suffix} directory does not contain a version.",
        )
    raw_name, raw_version = stem.rsplit("-", 1)
    try:
        parsed_version = Version(raw_version)
    except InvalidVersion as error:
        raise PluginWheelError(
            mismatch_code,
            f"Wheel {suffix} directory contains an invalid version.",
        ) from error
    if canonicalize_name(raw_name) != distribution or parsed_version != version:
        raise PluginWheelError(
            mismatch_code,
            f"Wheel {suffix} directory does not match its filename.",
        )


def parse_core_metadata(
    payload: bytes,
    distribution: str,
    version: Version,
    target_version: Version,
) -> tuple[str | None, tuple[str, ...]]:
    try:
        message = BytesParser(policy=policy.default).parsebytes(payload)
        metadata_standard = _single_header(
            message,
            "Metadata-Version",
            "INVALID_WHEEL_METADATA",
        )
        metadata_name = canonicalize_name(
            _single_header(message, "Name", "INVALID_WHEEL_METADATA")
        )
        metadata_version = Version(
            _single_header(message, "Version", "INVALID_WHEEL_METADATA")
        )
    except PluginWheelError:
        raise
    except (InvalidVersion, UnicodeError, ValueError) as error:
        raise PluginWheelError(
            "INVALID_WHEEL_METADATA",
            f"Cannot parse wheel METADATA: {error}",
        ) from error
    if not re.fullmatch(r"[12]\.[0-9]+", metadata_standard):
        raise PluginWheelError(
            "INVALID_WHEEL_METADATA",
            f"Unsupported Metadata-Version: {metadata_standard}",
        )
    if metadata_name != distribution or metadata_version != version:
        raise PluginWheelError(
            "WHEEL_METADATA_IDENTITY_MISMATCH",
            "Wheel METADATA name/version does not match its filename.",
        )

    requires_python_values = message.get_all("Requires-Python", [])
    if len(requires_python_values) > 1:
        raise PluginWheelError(
            "INVALID_REQUIRES_PYTHON",
            "Wheel METADATA contains duplicate Requires-Python headers.",
        )
    requires_python = None
    if requires_python_values:
        requires_python = requires_python_values[0].strip()
        if not requires_python:
            raise PluginWheelError(
                "INVALID_REQUIRES_PYTHON",
                "Wheel Requires-Python cannot be empty.",
            )
        try:
            specifier = SpecifierSet(requires_python)
        except InvalidSpecifier as error:
            raise PluginWheelError(
                "INVALID_REQUIRES_PYTHON",
                "Wheel Requires-Python is invalid.",
            ) from error
        if target_version not in specifier:
            raise PluginWheelError(
                "WHEEL_REQUIRES_PYTHON_MISMATCH",
                f"Wheel does not support Python {target_version.major}.{target_version.minor}.",
            )

    requirements = []
    for raw_requirement in message.get_all("Requires-Dist", []):
        try:
            requirement = Requirement(raw_requirement)
        except InvalidRequirement as error:
            raise PluginWheelError(
                "INVALID_WHEEL_REQUIREMENT",
                f"Wheel Requires-Dist is invalid: {raw_requirement}",
            ) from error
        if requirement.url is not None:
            raise PluginWheelError(
                "WHEEL_DEPENDENCY_URL_NOT_ALLOWED",
                "Wheel dependencies cannot use direct URLs.",
            )
        requirements.append(str(requirement))
    return requires_python, tuple(requirements)


def parse_wheel_metadata(payload: bytes) -> tuple[bool, frozenset[Tag]]:
    try:
        message = BytesParser(policy=policy.default).parsebytes(payload)
    except (UnicodeError, ValueError) as error:
        raise PluginWheelError(
            "INVALID_WHEEL_METADATA",
            f"Cannot parse WHEEL metadata: {error}",
        ) from error
    wheel_version = _single_header(
        message,
        "Wheel-Version",
        "INVALID_WHEEL_METADATA",
    )
    if not re.fullmatch(r"1\.[0-9]+", wheel_version):
        raise PluginWheelError(
            "UNSUPPORTED_WHEEL_VERSION",
            f"Unsupported Wheel-Version: {wheel_version}",
        )
    purelib_value = _single_header(
        message,
        "Root-Is-Purelib",
        "INVALID_WHEEL_METADATA",
    ).lower()
    if purelib_value not in {"true", "false"}:
        raise PluginWheelError(
            "INVALID_WHEEL_METADATA",
            "Root-Is-Purelib must be true or false.",
        )
    tag_values = message.get_all("Tag", [])
    if not tag_values:
        raise PluginWheelError(
            "INVALID_WHEEL_METADATA",
            "WHEEL metadata must declare at least one Tag.",
        )
    tags = set()
    try:
        for tag_value in tag_values:
            tags.update(parse_tag(tag_value.strip()))
    except ValueError as error:
        raise PluginWheelError(
            "INVALID_WHEEL_METADATA",
            f"WHEEL metadata contains an invalid Tag: {error}",
        ) from error
    return purelib_value == "true", frozenset(tags)


def _single_header(message, name: str, code: str) -> str:
    values = message.get_all(name, [])
    if len(values) != 1 or not values[0].strip():
        raise PluginWheelError(code, f"Wheel metadata requires one {name} header.")
    return values[0].strip()
