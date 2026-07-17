from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

from core.plugin_system.plugin_dependency_store_types import (
    PluginDependencyStoreError,
    StoredFile,
)
from core.plugin_system.plugin_wheel import inspect_wheel
from core.plugin_system.plugin_wheel_archive import (
    hash_wheel,
    resolve_wheel_path,
    same_file_snapshot,
    validate_member,
)
from core.plugin_system.plugin_wheel_metadata import wheel_install_path
from core.plugin_system.plugin_wheel_types import (
    PluginWheelError,
    WheelArtifact,
    WheelLimits,
)


_BUFFER_SIZE = 1024 * 1024


def materialize_wheel_snapshot(
    artifact: WheelArtifact,
    snapshot_path: Path,
    site_root: Path,
    *,
    target_python_abi: str,
    target_platform: str,
) -> tuple[WheelArtifact, tuple[StoredFile, ...]]:
    """Copy, re-inspect, and extract one wheel from a private snapshot."""

    _copy_source_snapshot(artifact, snapshot_path)
    snapshot_artifact = inspect_wheel(
        snapshot_path,
        target_python_abi=target_python_abi,
        target_platform=target_platform,
        expected_name=artifact.distribution,
        expected_version=artifact.version,
        expected_sha256=artifact.sha256,
    )
    _require_same_artifact(artifact, snapshot_artifact)
    stored_files = _extract_snapshot(
        snapshot_artifact,
        snapshot_path,
        site_root,
    )
    try:
        snapshot_path.unlink()
    except OSError as error:
        raise PluginDependencyStoreError(
            "DEPENDENCY_STORE_IO_ERROR",
            f"Cannot remove private wheel snapshot: {error}",
        ) from error
    return snapshot_artifact, stored_files


def _copy_source_snapshot(
    artifact: WheelArtifact,
    snapshot_path: Path,
):
    source_path, expected_stat = resolve_wheel_path(
        artifact.path,
        WheelLimits(),
    )
    digest = hashlib.sha256()
    try:
        with source_path.open("rb") as source, snapshot_path.open("xb") as target:
            opened_stat = os.fstat(source.fileno())
            if not same_file_snapshot(expected_stat, opened_stat):
                raise PluginDependencyStoreError(
                    "WHEEL_FILE_CHANGED",
                    "Wheel changed before its private snapshot was created.",
                )
            for chunk in iter(lambda: source.read(_BUFFER_SIZE), b""):
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
            final_stat = os.fstat(source.fileno())
            if not same_file_snapshot(opened_stat, final_stat):
                raise PluginDependencyStoreError(
                    "WHEEL_FILE_CHANGED",
                    "Wheel changed while its private snapshot was created.",
                )
    except PluginDependencyStoreError:
        raise
    except OSError as error:
        raise PluginDependencyStoreError(
            "DEPENDENCY_STORE_IO_ERROR",
            f"Cannot create dependency wheel snapshot: {error}",
        ) from error
    if digest.hexdigest() != artifact.sha256:
        raise PluginDependencyStoreError(
            "WHEEL_HASH_MISMATCH",
            "Wheel content changed after it was inspected.",
        )


def _extract_snapshot(
    artifact: WheelArtifact,
    snapshot_path: Path,
    site_root: Path,
) -> tuple[StoredFile, ...]:
    expected_stat = snapshot_path.lstat()
    files = []
    archive_files = []
    seen_archive_paths = set()
    seen_install_paths = set()
    try:
        with snapshot_path.open("rb") as wheel_file:
            first_digest, inspected_stat = hash_wheel(wheel_file, expected_stat)
            if first_digest != artifact.sha256:
                raise PluginDependencyStoreError(
                    "WHEEL_HASH_MISMATCH",
                    "Private wheel snapshot does not match its inspected artifact.",
                )
            with zipfile.ZipFile(wheel_file, "r") as archive:
                for info in archive.infolist():
                    archive_path, is_directory = validate_member(info)
                    archive_key = archive_path.casefold()
                    if archive_key in seen_archive_paths:
                        raise PluginDependencyStoreError(
                            "DEPENDENCY_SNAPSHOT_INVALID",
                            f"Private wheel snapshot repeats a path: {archive_path}",
                        )
                    seen_archive_paths.add(archive_key)
                    if is_directory:
                        continue
                    archive_files.append(archive_path)
                    install_path = wheel_install_path(archive_path)
                    install_key = install_path.casefold()
                    if install_key in seen_install_paths:
                        raise PluginDependencyStoreError(
                            "DEPENDENCY_SNAPSHOT_INVALID",
                            f"Wheel files collide after installation: {install_path}",
                        )
                    seen_install_paths.add(install_key)
                    files.append(
                        _extract_member(
                            archive,
                            info,
                            install_path,
                            site_root,
                        )
                    )
            second_digest, final_stat = hash_wheel(wheel_file, inspected_stat)
            if second_digest != first_digest or not same_file_snapshot(
                inspected_stat,
                final_stat,
            ):
                raise PluginDependencyStoreError(
                    "WHEEL_FILE_CHANGED",
                    "Private wheel snapshot changed while being materialized.",
                )
    except PluginDependencyStoreError:
        raise
    except PluginWheelError as error:
        raise PluginDependencyStoreError(error.code, str(error)) from error
    except (NotImplementedError, OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise PluginDependencyStoreError(
            "DEPENDENCY_SNAPSHOT_INVALID",
            f"Cannot extract private wheel snapshot: {error}",
        ) from error

    if tuple(sorted(archive_files)) != tuple(sorted(artifact.files)):
        raise PluginDependencyStoreError(
            "DEPENDENCY_SNAPSHOT_INVALID",
            "Private wheel snapshot file set changed after inspection.",
        )
    stored_files = tuple(sorted(files, key=lambda item: item.path))
    if tuple(item.path for item in stored_files) != tuple(
        sorted(artifact.installed_files)
    ):
        raise PluginDependencyStoreError(
            "DEPENDENCY_SNAPSHOT_INVALID",
            "Private wheel snapshot install paths changed after inspection.",
        )
    expected_files = tuple(
        StoredFile(
            path=entry.install_path,
            size=entry.size,
            sha256=entry.sha256,
        )
        for entry in artifact.install_entries
    )
    if not expected_files or stored_files != expected_files:
        raise PluginDependencyStoreError(
            "DEPENDENCY_SNAPSHOT_INVALID",
            "Materialized dependency files do not match the wheel RECORD.",
        )
    return stored_files


def _extract_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    install_path: str,
    site_root: Path,
) -> StoredFile:
    target = site_root.joinpath(*install_path.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    bytes_read = 0
    try:
        with archive.open(info, "r") as source, target.open("xb") as output:
            for chunk in iter(lambda: source.read(_BUFFER_SIZE), b""):
                bytes_read += len(chunk)
                if bytes_read > info.file_size:
                    raise PluginDependencyStoreError(
                        "DEPENDENCY_SNAPSHOT_INVALID",
                        f"Wheel member exceeds its declared size: {install_path}",
                    )
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except PluginDependencyStoreError:
        raise
    except (NotImplementedError, OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise PluginDependencyStoreError(
            "DEPENDENCY_STORE_IO_ERROR",
            f"Cannot materialize wheel member {install_path}: {error}",
        ) from error
    if bytes_read != info.file_size:
        raise PluginDependencyStoreError(
            "DEPENDENCY_SNAPSHOT_INVALID",
            f"Wheel member size changed while extracting: {install_path}",
        )
    return StoredFile(
        path=install_path,
        size=bytes_read,
        sha256=digest.hexdigest(),
    )


def _require_same_artifact(expected: WheelArtifact, actual: WheelArtifact):
    if (
        expected.sha256 != actual.sha256
        or expected.distribution != actual.distribution
        or expected.version != actual.version
        or expected.build_tag != actual.build_tag
        or expected.tags != actual.tags
        or expected.root_is_purelib != actual.root_is_purelib
        or expected.requires_python != actual.requires_python
        or expected.requirements != actual.requirements
        or expected.files != actual.files
        or expected.installed_files != actual.installed_files
        or expected.top_level_imports != actual.top_level_imports
        or expected.native_extensions != actual.native_extensions
        or expected.dlls != actual.dlls
        or expected.install_entries != actual.install_entries
        or expected.target_python_abi != actual.target_python_abi
        or expected.target_platform != actual.target_platform
    ):
        raise PluginDependencyStoreError(
            "DEPENDENCY_ARTIFACT_CHANGED",
            "Private wheel snapshot differs from the inspected dependency artifact.",
        )


__all__ = ["materialize_wheel_snapshot"]
