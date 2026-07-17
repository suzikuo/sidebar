from __future__ import annotations

import json
import re
from pathlib import Path

from packaging.tags import parse_tag
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from core.plugin_system.plugin_wheel_archive import normalize_path
from core.plugin_system.plugin_wheel_metadata import wheel_install_path
from core.plugin_system.plugin_wheel_types import PluginWheelError, WheelArtifact
from core.plugin_system.plugin_dependency_store_types import (
    PluginDependencyStoreError,
    StoredDependency,
    StoredFile,
)


RECEIPT_FILENAME = "receipt.json"
RECEIPT_VERSION = 1
MAX_RECEIPT_SIZE = 8 * 1024 * 1024

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_ROOT_FIELDS = frozenset(
    {
        "receipt_version",
        "wheel_sha256",
        "distribution",
        "version",
        "tags",
        "root_is_purelib",
        "files",
        "native_extensions",
        "dlls",
    }
)
_FILE_FIELDS = frozenset({"path", "size", "sha256"})


def build_receipt(artifact: WheelArtifact, files: tuple[StoredFile, ...]) -> dict:
    native_extensions = _mapped_paths(artifact.native_extensions)
    dlls = _mapped_paths(artifact.dlls)
    return {
        "receipt_version": RECEIPT_VERSION,
        "wheel_sha256": artifact.sha256,
        "distribution": artifact.distribution,
        "version": str(artifact.version),
        "tags": sorted(str(tag) for tag in artifact.tags),
        "root_is_purelib": artifact.root_is_purelib,
        "files": [
            {"path": item.path, "size": item.size, "sha256": item.sha256}
            for item in files
        ],
        "native_extensions": list(native_extensions),
        "dlls": list(dlls),
    }


def serialize_receipt(receipt: dict) -> bytes:
    return (
        json.dumps(
            receipt,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def parse_receipt(
    payload: bytes,
    object_root: Path,
    *,
    expected_artifact: WheelArtifact,
) -> StoredDependency:
    if not isinstance(payload, bytes) or len(payload) > MAX_RECEIPT_SIZE:
        raise _corrupt("Dependency receipt is missing or exceeds its size limit.")
    try:
        raw = json.loads(payload.decode("utf-8"), object_pairs_hook=_strict_object)
    except PluginDependencyStoreError:
        raise
    except (
        RecursionError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise _corrupt(f"Cannot parse dependency receipt: {error}") from error
    if not isinstance(raw, dict) or frozenset(raw) != _ROOT_FIELDS:
        raise _corrupt("Dependency receipt fields are invalid.")
    if (
        type(raw["receipt_version"]) is not int
        or raw["receipt_version"] != RECEIPT_VERSION
    ):
        raise _corrupt("Dependency receipt version is unsupported.")

    wheel_sha256 = _strict_digest(raw["wheel_sha256"], "wheel")
    distribution = raw["distribution"]
    if (
        not isinstance(distribution, str)
        or not distribution
        or canonicalize_name(distribution) != distribution
    ):
        raise _corrupt("Dependency distribution name is not canonical.")
    version = _strict_version(raw["version"])
    tags = _strict_tags(raw["tags"])
    root_is_purelib = raw["root_is_purelib"]
    if not isinstance(root_is_purelib, bool):
        raise _corrupt("Dependency purelib flag is invalid.")
    files = _strict_files(raw["files"])
    native_paths = _strict_path_list(raw["native_extensions"], ".pyd")
    dll_paths = _strict_path_list(raw["dlls"], ".dll")
    file_paths = {item.path for item in files}
    if not set(native_paths).issubset(file_paths) or not set(dll_paths).issubset(
        file_paths
    ):
        raise _corrupt("Dependency native paths are not present in its file list.")

    _match_artifact(
        expected_artifact,
        wheel_sha256,
        distribution,
        version,
        tags,
        root_is_purelib,
        files,
        native_paths,
        dll_paths,
    )

    site_root = object_root / "site"
    native_extensions = tuple(_site_path(site_root, value) for value in native_paths)
    dlls = tuple(_site_path(site_root, value) for value in dll_paths)
    dll_directories = tuple(sorted({path.parent for path in dlls}, key=str))
    return StoredDependency(
        sha256=wheel_sha256,
        distribution=distribution,
        version=version,
        tags=tags,
        root_is_purelib=root_is_purelib,
        object_root=object_root,
        site_root=site_root,
        files=files,
        native_extensions=native_extensions,
        dlls=dlls,
        dll_directories=dll_directories,
    )


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _corrupt(f"Dependency receipt contains a duplicate key: {key}")
        result[key] = value
    return result


def _strict_digest(value, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise _corrupt(f"Dependency {label} SHA-256 is invalid.")
    return value


def _strict_version(value) -> Version:
    if not isinstance(value, str) or not value:
        raise _corrupt("Dependency version is invalid.")
    try:
        version = Version(value)
    except InvalidVersion as error:
        raise _corrupt("Dependency version is invalid.") from error
    if str(version) != value:
        raise _corrupt("Dependency version must use its normalized form.")
    return version


def _strict_tags(value) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _corrupt("Dependency wheel tags are invalid.")
    tags = []
    for raw_tag in value:
        if not isinstance(raw_tag, str) or not raw_tag:
            raise _corrupt("Dependency wheel tag is invalid.")
        try:
            parsed = parse_tag(raw_tag)
        except ValueError as error:
            raise _corrupt("Dependency wheel tag is invalid.") from error
        if len(parsed) != 1 or str(next(iter(parsed))) != raw_tag:
            raise _corrupt("Dependency wheel tag must be an expanded normalized tag.")
        tags.append(raw_tag)
    if tags != sorted(set(tags)):
        raise _corrupt("Dependency wheel tags must be unique and sorted.")
    return tuple(tags)


def _strict_files(value) -> tuple[StoredFile, ...]:
    if not isinstance(value, list) or not value or len(value) > 8192:
        raise _corrupt("Dependency receipt file list is invalid.")
    files = []
    seen = set()
    for raw_file in value:
        if not isinstance(raw_file, dict) or frozenset(raw_file) != _FILE_FIELDS:
            raise _corrupt("Dependency receipt file entry is invalid.")
        path = _strict_path(raw_file["path"])
        key = path.casefold()
        if key in seen:
            raise _corrupt(f"Dependency receipt contains a duplicate path: {path}")
        seen.add(key)
        size = raw_file["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise _corrupt(f"Dependency file size is invalid: {path}")
        files.append(
            StoredFile(
                path=path,
                size=size,
                sha256=_strict_digest(raw_file["sha256"], "file"),
            )
        )
    if [item.path for item in files] != sorted(item.path for item in files):
        raise _corrupt("Dependency receipt files must be sorted by path.")
    return tuple(files)


def _strict_path_list(value, suffix: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _corrupt("Dependency native path list is invalid.")
    paths = tuple(_strict_path(path) for path in value)
    if list(paths) != sorted(set(paths)):
        raise _corrupt("Dependency native paths must be unique and sorted.")
    if any(Path(path).suffix.lower() != suffix for path in paths):
        raise _corrupt(f"Dependency native path must end with {suffix}.")
    return paths


def _strict_path(value) -> str:
    if not isinstance(value, str):
        raise _corrupt("Dependency file path is invalid.")
    try:
        normalized = normalize_path(value)
    except PluginWheelError as error:
        raise _corrupt(f"Dependency file path is unsafe: {value}") from error
    if normalized != value:
        raise _corrupt("Dependency file path is not normalized.")
    return normalized


def _match_artifact(
    artifact: WheelArtifact,
    wheel_sha256: str,
    distribution: str,
    version: Version,
    tags: tuple[str, ...],
    root_is_purelib: bool,
    files: tuple[StoredFile, ...],
    native_paths: tuple[str, ...],
    dll_paths: tuple[str, ...],
):
    expected_paths = tuple(sorted(artifact.installed_files))
    actual_paths = tuple(item.path for item in files)
    expected_files = tuple(
        StoredFile(
            path=entry.install_path,
            size=entry.size,
            sha256=entry.sha256,
        )
        for entry in artifact.install_entries
    )
    if (
        artifact.sha256 != wheel_sha256
        or artifact.distribution != distribution
        or artifact.version != version
        or tuple(sorted(str(tag) for tag in artifact.tags)) != tags
        or artifact.root_is_purelib != root_is_purelib
        or expected_paths != actual_paths
        or not expected_files
        or expected_files != files
        or _mapped_paths(artifact.native_extensions) != native_paths
        or _mapped_paths(artifact.dlls) != dll_paths
    ):
        raise _corrupt("Dependency receipt does not match the inspected wheel.")


def _mapped_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(wheel_install_path(path) for path in paths))


def _site_path(site_root: Path, relative_path: str) -> Path:
    return site_root.joinpath(*relative_path.split("/"))


def _corrupt(message: str) -> PluginDependencyStoreError:
    return PluginDependencyStoreError("DEPENDENCY_OBJECT_CORRUPT", message)


__all__ = [
    "MAX_RECEIPT_SIZE",
    "RECEIPT_FILENAME",
    "build_receipt",
    "parse_receipt",
    "serialize_receipt",
]
