from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path

from packaging.tags import Tag
from packaging.version import Version

from core.plugin_system.native_binary import (
    NativeBinaryError,
    validate_windows_pe_machine,
    validate_windows_pyd,
)
from core.plugin_system.plugin_wheel_archive import (
    hash_wheel,
    read_member,
    resolve_wheel_path,
    same_file_snapshot,
    validate_member,
    validate_path_collisions,
    validate_record,
)
from core.plugin_system.plugin_wheel_metadata import (
    check_expected_identity,
    installed_files,
    parse_core_metadata,
    parse_filename,
    parse_target_python,
    parse_wheel_metadata,
    supported_tags,
    top_level_imports,
    validate_dist_info_name,
    validate_install_path,
    wheel_install_path,
)
from core.plugin_system.plugin_wheel_types import (
    PluginWheelError,
    WheelArtifact,
    WheelInstallEntry,
    WheelLimits,
)


__all__ = (
    "PluginWheelError",
    "WheelArtifact",
    "WheelInstallEntry",
    "WheelLimits",
    "inspect_wheel",
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def inspect_wheel(
    wheel_path,
    *,
    target_python_abi: str,
    target_platform: str,
    expected_name: str | None = None,
    expected_version: Version | str | None = None,
    expected_sha256: str | None = None,
    limits: WheelLimits | None = None,
) -> WheelArtifact:
    """Validate one wheel without extracting or importing its contents."""

    limits = limits or WheelLimits()
    path, expected_stat = resolve_wheel_path(wheel_path, limits)
    distribution, version, build_tag, filename_tags = parse_filename(path.name)
    target_version = parse_target_python(target_python_abi)
    target_tags = supported_tags(
        target_python_abi,
        target_version,
        target_platform,
    )
    if not filename_tags.intersection(target_tags):
        raise PluginWheelError(
            "WHEEL_TAG_INCOMPATIBLE",
            f"Wheel tags are incompatible with {target_python_abi}-{target_platform}.",
        )

    check_expected_identity(
        distribution,
        version,
        expected_name,
        expected_version,
    )
    try:
        wheel_file = path.open("rb")
    except OSError as error:
        raise PluginWheelError(
            "WHEEL_FILE_CHANGED",
            f"Wheel became unavailable before inspection: {error}",
        ) from error

    try:
        with wheel_file:
            digest, hashed_stat = hash_wheel(wheel_file, expected_stat)
            if expected_sha256 is not None:
                normalized_digest = str(expected_sha256).lower()
                if not _SHA256_PATTERN.fullmatch(normalized_digest):
                    raise PluginWheelError(
                        "INVALID_WHEEL_HASH",
                        "Expected wheel SHA-256 is invalid.",
                    )
                if digest != normalized_digest:
                    raise PluginWheelError(
                        "WHEEL_HASH_MISMATCH",
                        "Wheel SHA-256 does not match the dependency lock.",
                    )

            with zipfile.ZipFile(wheel_file, "r") as archive:
                opened_stat = os.fstat(wheel_file.fileno())
                if not same_file_snapshot(hashed_stat, opened_stat):
                    raise PluginWheelError(
                        "WHEEL_FILE_CHANGED",
                        "Wheel changed before being inspected.",
                    )
                artifact = _inspect_archive(
                    archive,
                    path,
                    digest,
                    distribution,
                    version,
                    build_tag,
                filename_tags,
                target_tags,
                target_python_abi,
                target_version,
                    target_platform,
                    limits,
                )
                inspected_stat = os.fstat(wheel_file.fileno())
                if not same_file_snapshot(opened_stat, inspected_stat):
                    raise PluginWheelError(
                        "WHEEL_FILE_CHANGED",
                        "Wheel changed while being inspected.",
                    )

            verified_digest, final_stat = hash_wheel(wheel_file, inspected_stat)
            if verified_digest != digest or not same_file_snapshot(
                inspected_stat,
                final_stat,
            ):
                raise PluginWheelError(
                    "WHEEL_FILE_CHANGED",
                    "Wheel content changed while being inspected.",
                )
            return artifact
    except PluginWheelError:
        raise
    except (
        NotImplementedError,
        OSError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as error:
        raise PluginWheelError(
            "INVALID_WHEEL_ARCHIVE",
            f"Cannot read wheel archive: {error}",
        ) from error


def _inspect_archive(
    archive: zipfile.ZipFile,
    path: Path,
    digest: str,
    distribution: str,
    version: Version,
    build_tag,
    filename_tags: frozenset[Tag],
    target_tags: frozenset[Tag],
    target_python_abi: str,
    target_version: Version,
    target_platform: str,
    limits: WheelLimits,
) -> WheelArtifact:
    infos = archive.infolist()
    if not infos or len(infos) > limits.max_entries:
        raise PluginWheelError(
            "WHEEL_ENTRY_LIMIT",
            "Wheel has no entries or exceeds the entry limit.",
        )

    files: dict[str, zipfile.ZipInfo] = {}
    path_records: dict[str, tuple[str, bool]] = {}
    dist_info_roots = set()
    total_size = 0
    native_extensions = []
    dlls = []

    for info in infos:
        normalized, is_directory = validate_member(info)
        path_key = normalized.casefold()
        if path_key in path_records:
            raise PluginWheelError(
                "DUPLICATE_WHEEL_PATH",
                f"Wheel contains a duplicate path: {normalized}",
            )
        path_records[path_key] = (normalized, is_directory)
        parts = normalized.split("/")
        if parts[0].endswith(".dist-info"):
            dist_info_roots.add(parts[0])
        if is_directory:
            continue

        if info.file_size < 0 or info.file_size > limits.max_member_size:
            raise PluginWheelError(
                "WHEEL_MEMBER_SIZE_LIMIT",
                f"Wheel member exceeds the size limit: {normalized}",
            )
        total_size += info.file_size
        if total_size > limits.max_uncompressed_size:
            raise PluginWheelError(
                "WHEEL_SIZE_LIMIT",
                "Wheel exceeds the total uncompressed size limit.",
            )

        validate_install_path(normalized, distribution, version)
        suffix = Path(normalized).suffix.lower()
        if suffix == ".pyd":
            native_extensions.append(normalized)
        elif suffix == ".dll":
            dlls.append(normalized)
        files[normalized] = info

    validate_path_collisions(path_records)
    if len(dist_info_roots) != 1:
        raise PluginWheelError(
            "INVALID_WHEEL_DIST_INFO",
            "Wheel must contain exactly one top-level dist-info directory.",
        )

    dist_info_root = next(iter(dist_info_roots))
    validate_dist_info_name(dist_info_root, distribution, version)
    metadata_path = f"{dist_info_root}/METADATA"
    wheel_metadata_path = f"{dist_info_root}/WHEEL"
    record_path = f"{dist_info_root}/RECORD"
    for required_path in (metadata_path, wheel_metadata_path, record_path):
        if required_path not in files:
            raise PluginWheelError(
                "WHEEL_METADATA_MISSING",
                f"Wheel is missing required metadata: {required_path}",
            )

    metadata = parse_core_metadata(
        read_member(archive, files[metadata_path], limits.max_metadata_size),
        distribution,
        version,
        target_version,
    )
    root_is_purelib, wheel_tags = parse_wheel_metadata(
        read_member(
            archive,
            files[wheel_metadata_path],
            limits.max_metadata_size,
        )
    )
    if wheel_tags != filename_tags:
        raise PluginWheelError(
            "WHEEL_TAG_METADATA_MISMATCH",
            "WHEEL Tag headers do not match the wheel filename.",
        )
    if not wheel_tags.intersection(target_tags):
        raise PluginWheelError(
            "WHEEL_TAG_INCOMPATIBLE",
            "WHEEL metadata tags are incompatible with the target host.",
        )
    if (native_extensions or dlls) and root_is_purelib:
        raise PluginWheelError(
            "WHEEL_NATIVE_LAYOUT_MISMATCH",
            "A wheel with native binaries cannot be Root-Is-Purelib.",
        )
    if native_extensions and not any(tag.platform != "any" for tag in wheel_tags):
        raise PluginWheelError(
            "WHEEL_NATIVE_TAG_MISMATCH",
            "A wheel with native extensions must use a platform tag.",
        )
    if dlls and not any(tag.platform != "any" for tag in wheel_tags):
        raise PluginWheelError(
            "WHEEL_NATIVE_TAG_MISMATCH",
            "A wheel with DLLs must use a platform tag.",
        )

    record_payload = read_member(
        archive,
        files[record_path],
        limits.max_record_size,
    )
    verified_files = validate_record(archive, files, record_path, record_payload)
    for native_path in native_extensions:
        _validate_native_extension(
            archive,
            files[native_path],
            native_path,
            target_platform,
        )
    for dll_path in dlls:
        _validate_native_library(
            archive,
            files[dll_path],
            dll_path,
            target_platform,
        )

    materialized_files = installed_files(tuple(files))
    install_entries = tuple(
        sorted(
            (
                WheelInstallEntry(
                    archive_path=archive_path,
                    install_path=wheel_install_path(archive_path),
                    size=verified_files[archive_path][0],
                    sha256=verified_files[archive_path][1],
                )
                for archive_path in files
            ),
            key=lambda item: item.install_path,
        )
    )
    return WheelArtifact(
        path=path,
        sha256=digest,
        distribution=distribution,
        version=version,
        build_tag=build_tag,
        tags=filename_tags,
        root_is_purelib=root_is_purelib,
        requires_python=metadata[0],
        requirements=metadata[1],
        files=tuple(sorted(files)),
        installed_files=materialized_files,
        top_level_imports=top_level_imports(materialized_files),
        native_extensions=tuple(sorted(native_extensions)),
        dlls=tuple(sorted(dlls)),
        install_entries=install_entries,
        target_python_abi=target_python_abi,
        target_platform=target_platform,
    )


def _validate_native_extension(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    member_path: str,
    target_platform: str,
):
    parts = member_path.split("/")
    if parts[0].endswith(".data"):
        parts = parts[2:]
    filename = parts[-1]
    module_leaf = filename.split(".", 1)[0]
    module_parts = [*parts[:-1], module_leaf]
    if not module_parts or any(not part.isidentifier() for part in module_parts):
        raise PluginWheelError(
            "INVALID_WHEEL_NATIVE_MODULE",
            f"Cannot derive native module name from wheel path: {member_path}",
        )
    try:
        with archive.open(info, "r") as source:
            validate_windows_pyd(
                source,
                file_size=info.file_size,
                module_name=".".join(module_parts),
                platform_tag=target_platform,
            )
    except NativeBinaryError as error:
        raise PluginWheelError(
            error.code,
            f"Invalid wheel native extension {member_path}: {error}",
        ) from error
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise PluginWheelError(
            "WHEEL_MEMBER_READ_FAILED",
            f"Cannot inspect wheel native extension {member_path}: {error}",
        ) from error


def _validate_native_library(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    member_path: str,
    target_platform: str,
):
    try:
        with archive.open(info, "r") as source:
            validate_windows_pe_machine(
                source,
                file_size=info.file_size,
                platform_tag=target_platform,
            )
    except NativeBinaryError as error:
        raise PluginWheelError(
            error.code,
            f"Invalid wheel DLL {member_path}: {error}",
        ) from error
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise PluginWheelError(
            "WHEEL_MEMBER_READ_FAILED",
            f"Cannot inspect wheel DLL {member_path}: {error}",
        ) from error
