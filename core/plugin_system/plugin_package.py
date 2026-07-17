import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.plugin_system.plugin_dependency_lock import (
    MAX_DEPENDENCY_LOCK_SIZE,
    parse_and_validate_dependency_lock,
)
from core.plugin_system.native_binary import (
    NativeBinaryError,
    validate_windows_pyd,
)
from core.plugin_system.plugin_manifest import (
    PluginManifest,
    PluginManifestError,
    parse_manifest,
)
from core.plugin_system.plugin_integrity import validate_plugin_directory


_PLUGIN_ID_PATTERN = re.compile(
    r"(?=.{1,64}\Z)[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*"
)
_WINDOWS_DRIVE_PATTERN = re.compile(r"^[a-zA-Z]:")
_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*')
_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
_COPY_CHUNK_SIZE = 1024 * 1024


class PluginPackageError(ValueError):
    """A package validation or staging failure with a stable error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PackageLimits:
    max_entries: int = 4096
    max_uncompressed_size: int = 512 * 1024 * 1024
    max_manifest_size: int = 1024 * 1024

    def __post_init__(self):
        for name in ("max_entries", "max_uncompressed_size", "max_manifest_size"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")


@dataclass(frozen=True)
class PluginPackageMember:
    archive_name: str
    relative_path: str
    is_directory: bool
    uncompressed_size: int


@dataclass(frozen=True)
class PluginPackageInfo:
    package_path: Path
    plugin_id: str
    manifest: dict[str, Any]
    normalized_manifest: PluginManifest
    content_prefix: str
    members: tuple[PluginPackageMember, ...]
    total_uncompressed_size: int
    legacy_zip: bool


@dataclass(frozen=True)
class StagedPluginPackage:
    info: PluginPackageInfo
    staging_path: Path


def is_safe_plugin_id(plugin_id: object) -> bool:
    return isinstance(plugin_id, str) and bool(_PLUGIN_ID_PATTERN.fullmatch(plugin_id))


def validate_plugin_id(plugin_id: object) -> str:
    if not is_safe_plugin_id(plugin_id):
        raise PluginPackageError(
            "INVALID_PLUGIN_ID",
            "Plugin id must be 1-64 lowercase characters, start with a letter, "
            "and use alphanumeric segments separated by '.', '_' or '-'.",
        )
    return plugin_id


def inspect_plugin_package(
    package_path,
    *,
    allow_legacy_zip: bool = False,
    limits: PackageLimits | None = None,
) -> PluginPackageInfo:
    """Validate an .atplugin archive without writing any archive content."""

    path, legacy_zip = _validate_package_path(package_path, allow_legacy_zip)
    limits = limits or PackageLimits()
    try:
        with zipfile.ZipFile(path, "r") as archive:
            return _inspect_archive(archive, path, legacy_zip, limits)
    except PluginPackageError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise PluginPackageError(
            "INVALID_ARCHIVE", f"Cannot read plugin package: {error}"
        ) from error


def stage_plugin_package(
    package_path,
    staging_root,
    *,
    allow_legacy_zip: bool = False,
    limits: PackageLimits | None = None,
) -> StagedPluginPackage:
    """Validate and extract a package into a newly-created staging directory."""

    path, legacy_zip = _validate_package_path(package_path, allow_legacy_zip)
    limits = limits or PackageLimits()
    root = _prepare_staging_root(staging_root)
    staging_path = None

    try:
        with zipfile.ZipFile(path, "r") as archive:
            info = _inspect_archive(archive, path, legacy_zip, limits)
            staging_path = Path(
                tempfile.mkdtemp(prefix=f"{info.plugin_id}-", dir=str(root))
            ).resolve(strict=True)
            _extract_checked_members(archive, info, staging_path, limits)
            try:
                validate_plugin_directory(
                    staging_path,
                    info.normalized_manifest,
                )
            except PluginManifestError as error:
                raise PluginPackageError(error.code, str(error)) from error
            return StagedPluginPackage(info=info, staging_path=staging_path)
    except PluginPackageError:
        if staging_path is not None:
            shutil.rmtree(staging_path, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError) as error:
        if staging_path is not None:
            shutil.rmtree(staging_path, ignore_errors=True)
        raise PluginPackageError(
            "STAGING_FAILED", f"Cannot stage plugin package: {error}"
        ) from error


def _validate_package_path(package_path, allow_legacy_zip: bool) -> tuple[Path, bool]:
    try:
        path = Path(package_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError) as error:
        raise PluginPackageError(
            "PACKAGE_NOT_FOUND", f"Plugin package does not exist: {package_path}"
        ) from error

    if not path.is_file():
        raise PluginPackageError("INVALID_PACKAGE", "Plugin package must be a file.")

    suffix = path.suffix.lower()
    if suffix == ".atplugin":
        return path, False
    if suffix == ".zip" and allow_legacy_zip:
        return path, True

    expected = ".atplugin or explicitly-enabled legacy .zip"
    raise PluginPackageError(
        "UNSUPPORTED_PACKAGE_TYPE", f"Plugin package must be {expected}."
    )


def _inspect_archive(
    archive: zipfile.ZipFile,
    package_path: Path,
    legacy_zip: bool,
    limits: PackageLimits,
) -> PluginPackageInfo:
    raw_infos = archive.infolist()
    if not raw_infos:
        raise PluginPackageError("EMPTY_PACKAGE", "Plugin package is empty.")
    if len(raw_infos) > limits.max_entries:
        raise PluginPackageError(
            "TOO_MANY_ENTRIES",
            f"Plugin package exceeds the {limits.max_entries} entry limit.",
        )

    records: list[tuple[zipfile.ZipInfo, str, bool]] = []
    normalized_paths: dict[str, tuple[str, bool]] = {}
    total_uncompressed_size = 0

    for zip_info in raw_infos:
        normalized_name = _normalize_archive_name(zip_info.filename)
        is_directory = _validate_member_type(zip_info)
        path_key = normalized_name.casefold()
        if path_key in normalized_paths:
            raise PluginPackageError(
                "DUPLICATE_PATH",
                f"Plugin package contains duplicate path: {normalized_name}",
            )

        normalized_paths[path_key] = (normalized_name, is_directory)
        records.append((zip_info, normalized_name, is_directory))
        if not is_directory:
            if zip_info.file_size < 0:
                raise PluginPackageError(
                    "INVALID_SIZE", f"Invalid file size for {normalized_name}."
                )
            total_uncompressed_size += zip_info.file_size
            if total_uncompressed_size > limits.max_uncompressed_size:
                raise PluginPackageError(
                    "PACKAGE_TOO_LARGE",
                    "Plugin package exceeds the uncompressed size limit.",
                )

    _validate_path_collisions(normalized_paths)
    content_prefix, manifest_record = _find_manifest(records, legacy_zip)
    manifest = _read_manifest(archive, manifest_record[0], limits)
    raw_manifest_version = manifest.get("manifest_version", 1)
    if (
        not legacy_zip
        and type(raw_manifest_version) is int
        and raw_manifest_version == 1
    ):
        raise PluginPackageError(
            "MANIFEST_V2_REQUIRED",
            ".atplugin packages require manifest_version 2. "
            "Legacy manifest v1 is only accepted from an explicitly-enabled .zip.",
        )
    normalized_manifest = _validate_manifest(manifest)
    plugin_id = normalized_manifest.plugin_id
    entry_path = normalized_manifest.entry
    entry_archive_path = f"{content_prefix}{entry_path}"
    entry_record = normalized_paths.get(entry_archive_path.casefold())
    if entry_record is None or entry_record[1]:
        raise PluginPackageError(
            "ENTRY_NOT_FOUND",
            f"Manifest entry is not a package file: {manifest['entry']}",
        )
    if entry_record[0] != entry_archive_path:
        raise PluginPackageError(
            "ENTRY_CASE_MISMATCH",
            "Manifest entry path casing must match the package member exactly.",
        )

    members = []
    for zip_info, normalized_name, is_directory in records:
        if content_prefix:
            wrapper_dir = content_prefix[:-1]
            if normalized_name == wrapper_dir and is_directory:
                continue
            if not normalized_name.startswith(content_prefix):
                raise PluginPackageError(
                    "INVALID_LAYOUT",
                    "Legacy ZIP content must stay inside its single wrapper directory.",
                )
            relative_path = normalized_name[len(content_prefix) :]
        else:
            relative_path = normalized_name

        if not relative_path:
            continue
        members.append(
            PluginPackageMember(
                archive_name=zip_info.filename,
                relative_path=relative_path,
                is_directory=is_directory,
                uncompressed_size=0 if is_directory else zip_info.file_size,
            )
        )

    if normalized_manifest.manifest_version == 2:
        _validate_v2_archive_contents(archive, normalized_manifest, members)

    return PluginPackageInfo(
        package_path=package_path,
        plugin_id=plugin_id,
        manifest=manifest,
        normalized_manifest=normalized_manifest,
        content_prefix=content_prefix,
        members=tuple(members),
        total_uncompressed_size=total_uncompressed_size,
        legacy_zip=legacy_zip,
    )


def _normalize_archive_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise PluginPackageError("INVALID_PATH", "Archive member path is empty.")

    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or _WINDOWS_DRIVE_PATTERN.match(normalized):
        raise PluginPackageError(
            "UNSAFE_PATH", f"Archive member uses an absolute path: {name}"
        )

    raw_parts = normalized.split("/")
    if raw_parts[-1] == "":
        raw_parts = raw_parts[:-1]
    if not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
        raise PluginPackageError(
            "UNSAFE_PATH", f"Archive member path is not normalized: {name}"
        )

    for part in raw_parts:
        _validate_windows_path_component(part, name)
    return "/".join(raw_parts)


def _validate_windows_path_component(component: str, original_name: str):
    if any(
        character in _WINDOWS_INVALID_CHARS or ord(character) < 32
        for character in component
    ):
        raise PluginPackageError(
            "UNSAFE_PATH", f"Archive member has an invalid Windows path: {original_name}"
        )
    if component.endswith((" ", ".")):
        raise PluginPackageError(
            "UNSAFE_PATH", f"Archive member has an ambiguous Windows path: {original_name}"
        )

    device_base = component.split(".", 1)[0].upper()
    if device_base in _WINDOWS_DEVICE_NAMES:
        raise PluginPackageError(
            "UNSAFE_PATH", f"Archive member uses a Windows device name: {original_name}"
        )


def _validate_member_type(zip_info: zipfile.ZipInfo) -> bool:
    if zip_info.flag_bits & 0x1:
        raise PluginPackageError(
            "ENCRYPTED_MEMBER",
            f"Encrypted archive members are not supported: {zip_info.filename}",
        )

    unix_mode = zip_info.external_attr >> 16
    file_type = stat.S_IFMT(unix_mode)
    if file_type == stat.S_IFLNK:
        raise PluginPackageError(
            "LINK_NOT_ALLOWED",
            f"Symbolic links are not allowed: {zip_info.filename}",
        )
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise PluginPackageError(
            "SPECIAL_FILE_NOT_ALLOWED",
            f"Special archive members are not allowed: {zip_info.filename}",
        )

    windows_attributes = zip_info.external_attr & 0xFFFF
    if windows_attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise PluginPackageError(
            "LINK_NOT_ALLOWED",
            f"Reparse points are not allowed: {zip_info.filename}",
        )

    is_directory = zip_info.is_dir() or file_type == stat.S_IFDIR
    if is_directory and zip_info.file_size:
        raise PluginPackageError(
            "INVALID_SIZE", f"Directory member has content: {zip_info.filename}"
        )
    return is_directory


def _validate_path_collisions(paths: dict[str, tuple[str, bool]]):
    for normalized_name, _ in paths.values():
        parts = normalized_name.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            parent_record = paths.get(parent.casefold())
            if parent_record is not None and not parent_record[1]:
                raise PluginPackageError(
                    "PATH_COLLISION",
                    f"Archive file is also used as a directory: {parent_record[0]}",
                )


def _find_manifest(
    records: list[tuple[zipfile.ZipInfo, str, bool]], legacy_zip: bool
) -> tuple[str, tuple[zipfile.ZipInfo, str, bool]]:
    files = {record[1]: record for record in records if not record[2]}
    root_manifest = files.get("manifest.json")
    if root_manifest is not None:
        return "", root_manifest

    if not legacy_zip:
        raise PluginPackageError(
            "MANIFEST_NOT_FOUND", ".atplugin requires manifest.json at archive root."
        )

    candidates = [
        record
        for record in records
        if not record[2]
        and len(record[1].split("/")) == 2
        and record[1].endswith("/manifest.json")
    ]
    if len(candidates) != 1:
        raise PluginPackageError(
            "MANIFEST_NOT_FOUND",
            "Legacy ZIP requires manifest.json at root or in one wrapper directory.",
        )
    wrapper = candidates[0][1].split("/", 1)[0]
    prefix = f"{wrapper}/"
    for _, normalized_name, is_directory in records:
        if normalized_name == wrapper and is_directory:
            continue
        if not normalized_name.startswith(prefix):
            raise PluginPackageError(
                "INVALID_LAYOUT",
                "Legacy ZIP content must stay inside its single wrapper directory.",
            )
    return prefix, candidates[0]


def _read_manifest(
    archive: zipfile.ZipFile, manifest_info: zipfile.ZipInfo, limits: PackageLimits
) -> dict[str, Any]:
    if manifest_info.file_size > limits.max_manifest_size:
        raise PluginPackageError(
            "MANIFEST_TOO_LARGE",
            f"manifest.json exceeds the {limits.max_manifest_size} byte limit.",
        )

    try:
        with archive.open(manifest_info, "r") as manifest_file:
            raw_manifest = manifest_file.read(limits.max_manifest_size + 1)
        if len(raw_manifest) > limits.max_manifest_size:
            raise PluginPackageError(
                "MANIFEST_TOO_LARGE",
                f"manifest.json exceeds the {limits.max_manifest_size} byte limit.",
            )
        manifest = json.loads(
            raw_manifest.decode("utf-8"), object_pairs_hook=_unique_json_object
        )
    except PluginPackageError:
        raise
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as error:
        raise PluginPackageError(
            "INVALID_MANIFEST", f"Cannot parse manifest.json: {error}"
        ) from error

    if not isinstance(manifest, dict):
        raise PluginPackageError(
            "INVALID_MANIFEST", "manifest.json must contain a JSON object."
        )
    return manifest


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PluginPackageError(
                "INVALID_MANIFEST", f"manifest.json has duplicate key: {key}"
            )
        result[key] = value
    return result


def _validate_manifest(manifest: dict[str, Any]) -> PluginManifest:
    try:
        return parse_manifest(manifest)
    except PluginManifestError as error:
        raise PluginPackageError(error.code, str(error)) from error


def _validate_v2_archive_contents(
    archive: zipfile.ZipFile,
    manifest: PluginManifest,
    members: list[PluginPackageMember],
):
    packaged_files = {
        member.relative_path: member
        for member in members
        if not member.is_directory and member.relative_path != "manifest.json"
    }
    declared_files = dict(manifest.file_hashes)
    packaged_paths = set(packaged_files)
    declared_paths = set(declared_files)

    missing = sorted(declared_paths - packaged_paths)
    if missing:
        raise PluginPackageError(
            "DECLARED_FILE_MISSING",
            f"Manifest declares a missing package file: {missing[0]}",
        )
    undeclared = sorted(packaged_paths - declared_paths)
    if undeclared:
        raise PluginPackageError(
            "UNDECLARED_PACKAGE_FILE",
            f"Plugin package contains an undeclared file: {undeclared[0]}",
        )

    native_paths = {module.path for module in manifest.native_modules}
    packaged_native_paths = {
        path for path in packaged_paths if Path(path).suffix.lower() == ".pyd"
    }
    undeclared_native = sorted(packaged_native_paths - native_paths)
    if undeclared_native:
        raise PluginPackageError(
            "UNDECLARED_NATIVE_MODULE",
            f"Native module is not declared in manifest: {undeclared_native[0]}",
        )
    missing_native = sorted(native_paths - packaged_native_paths)
    if missing_native:
        raise PluginPackageError(
            "NATIVE_MODULE_MISSING",
            f"Declared native module is missing: {missing_native[0]}",
        )

    expected_native_suffix = (
        f".{manifest.compatibility.python_abi}-"
        f"{manifest.compatibility.platform_tag}.pyd"
    )
    for module in manifest.native_modules:
        if not module.path.lower().endswith(expected_native_suffix):
            raise PluginPackageError(
                "NATIVE_MODULE_TAG_MISMATCH",
                f"Native module filename does not match host tags: {module.path}",
            )

    for path, member in packaged_files.items():
        actual_hash = _hash_archive_member(archive, member)
        if actual_hash != declared_files[path]:
            raise PluginPackageError(
                "FILE_HASH_MISMATCH",
                f"Plugin package file hash does not match manifest: {path}",
            )

    if manifest.dependencies.lock:
        _validate_archive_dependency_lock(
            archive,
            packaged_files[manifest.dependencies.lock],
            manifest,
        )

    for module in manifest.native_modules:
        member = packaged_files[module.path]
        try:
            zip_info = archive.getinfo(member.archive_name)
            with archive.open(zip_info, "r") as source:
                validate_windows_pyd(
                    source,
                    file_size=member.uncompressed_size,
                    module_name=module.module,
                    platform_tag=manifest.compatibility.platform_tag,
                )
        except NativeBinaryError as error:
            raise PluginPackageError(
                error.code,
                f"Invalid native module {module.path}: {error}",
            ) from error
        except (KeyError, OSError, RuntimeError, zipfile.BadZipFile) as error:
            raise PluginPackageError(
                "PACKAGE_READ_FAILED",
                f"Cannot inspect native module {module.path}: {error}",
            ) from error


def _hash_archive_member(
    archive: zipfile.ZipFile, member: PluginPackageMember
) -> str:
    digest = hashlib.sha256()
    bytes_read = 0
    try:
        zip_info = archive.getinfo(member.archive_name)
        with archive.open(zip_info, "r") as source:
            while True:
                chunk = source.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > member.uncompressed_size:
                    raise PluginPackageError(
                        "INVALID_SIZE",
                        f"Package member exceeded its declared size: {member.relative_path}",
                    )
                digest.update(chunk)
    except PluginPackageError:
        raise
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise PluginPackageError(
            "PACKAGE_READ_FAILED",
            f"Cannot hash package member {member.relative_path}: {error}",
        ) from error
    if bytes_read != member.uncompressed_size:
        raise PluginPackageError(
            "INVALID_SIZE",
            f"Package member size changed while hashing: {member.relative_path}",
        )
    return digest.hexdigest()


def _validate_archive_dependency_lock(
    archive: zipfile.ZipFile,
    member: PluginPackageMember,
    manifest: PluginManifest,
):
    if member.uncompressed_size > MAX_DEPENDENCY_LOCK_SIZE:
        raise PluginPackageError(
            "DEPENDENCY_LOCK_TOO_LARGE",
            "Dependency lock exceeds the size limit.",
        )
    try:
        zip_info = archive.getinfo(member.archive_name)
        with archive.open(zip_info, "r") as source:
            payload = source.read(MAX_DEPENDENCY_LOCK_SIZE + 1)
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise PluginPackageError(
            "PACKAGE_READ_FAILED",
            f"Cannot read dependency lock {member.relative_path}: {error}",
        ) from error
    if len(payload) != member.uncompressed_size:
        raise PluginPackageError(
            "INVALID_SIZE",
            f"Dependency lock size changed while reading: {member.relative_path}",
        )
    try:
        parse_and_validate_dependency_lock(payload, manifest)
    except PluginManifestError as error:
        raise PluginPackageError(
            error.code,
            f"Invalid dependency lock {member.relative_path}: {error}",
        ) from error


def _prepare_staging_root(staging_root) -> Path:
    root = Path(staging_root).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
        if _is_reparse_point(root):
            raise PluginPackageError(
                "UNSAFE_STAGING_ROOT", "Staging root cannot be a link or reparse point."
            )
        resolved = root.resolve(strict=True)
    except PluginPackageError:
        raise
    except (OSError, RuntimeError, TypeError) as error:
        raise PluginPackageError(
            "INVALID_STAGING_ROOT", f"Cannot prepare staging root: {error}"
        ) from error

    if not resolved.is_dir():
        raise PluginPackageError(
            "INVALID_STAGING_ROOT", "Staging root must be a directory."
        )
    return resolved


def _is_reparse_point(path: Path) -> bool:
    try:
        file_stat = os.lstat(path)
    except OSError:
        return False
    attributes = getattr(file_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(file_stat.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _extract_checked_members(
    archive: zipfile.ZipFile,
    info: PluginPackageInfo,
    staging_path: Path,
    limits: PackageLimits,
):
    written_size = 0
    for member in info.members:
        target = (staging_path / Path(*member.relative_path.split("/"))).resolve()
        if not target.is_relative_to(staging_path):
            raise PluginPackageError(
                "UNSAFE_PATH", f"Archive member escapes staging: {member.relative_path}"
            )

        if member.is_directory:
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            zip_info = archive.getinfo(member.archive_name)
            file_written = 0
            with archive.open(zip_info, "r") as source, target.open("xb") as destination:
                while True:
                    chunk = source.read(_COPY_CHUNK_SIZE)
                    if not chunk:
                        break
                    file_written += len(chunk)
                    written_size += len(chunk)
                    if (
                        file_written > member.uncompressed_size
                        or written_size > limits.max_uncompressed_size
                    ):
                        raise PluginPackageError(
                            "PACKAGE_TOO_LARGE",
                            "Extracted package exceeded its declared or configured size.",
                        )
                    destination.write(chunk)
        except PluginPackageError:
            raise
        except (KeyError, OSError, RuntimeError, zipfile.BadZipFile) as error:
            raise PluginPackageError(
                "EXTRACTION_FAILED",
                f"Cannot extract package member {member.relative_path}: {error}",
            ) from error

        if file_written != member.uncompressed_size:
            raise PluginPackageError(
                "INVALID_SIZE",
                f"Extracted size does not match package metadata: {member.relative_path}",
            )
