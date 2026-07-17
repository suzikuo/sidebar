from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from core.plugin_system.plugin_dependency_receipt import (
    MAX_RECEIPT_SIZE,
    RECEIPT_FILENAME,
    parse_receipt,
)
from core.plugin_system.plugin_dependency_store_types import (
    PluginDependencyStoreError,
    StoredDependency,
    StoredFile,
)
from core.plugin_system.plugin_wheel_archive import same_file_snapshot
from core.plugin_system.plugin_wheel_types import WheelArtifact


_BUFFER_SIZE = 1024 * 1024


def verify_dependency_object(
    object_root: Path,
    *,
    expected_artifact: WheelArtifact,
    require_addressed_path: bool = True,
) -> StoredDependency:
    require_safe_directory(
        object_root,
        "DEPENDENCY_OBJECT_NOT_FOUND",
        "Dependency object is missing or unsafe.",
    )
    try:
        with os.scandir(object_root) as iterator:
            entry_names = {entry.name for entry in iterator}
    except OSError as error:
        raise _corrupt(f"Cannot enumerate dependency object: {error}") from error
    if entry_names != {"site", RECEIPT_FILENAME}:
        raise _corrupt("Dependency object contains unexpected entries.")

    site_root = object_root / "site"
    require_safe_directory(
        site_root,
        "DEPENDENCY_OBJECT_CORRUPT",
        "Dependency site root is missing or unsafe.",
    )
    receipt_path = object_root / RECEIPT_FILENAME
    payload = _read_receipt(receipt_path)
    stored = parse_receipt(
        payload,
        object_root,
        expected_artifact=expected_artifact,
    )
    if require_addressed_path and (
        object_root.name != stored.sha256
        or object_root.parent.name != stored.sha256[:2]
    ):
        raise _corrupt("Dependency object path does not match its wheel SHA-256.")
    _verify_site_tree(site_root, stored.files)
    if not _is_read_only(receipt_path.lstat()):
        raise _corrupt("Dependency receipt is writable.")
    if not _is_read_only(site_root.lstat()) or not _is_read_only(
        object_root.lstat()
    ):
        raise _corrupt("Dependency object directories are writable.")
    return stored


def make_dependency_object_read_only(
    object_root: Path,
    files: tuple[StoredFile, ...],
):
    site_root = object_root / "site"
    receipt_path = object_root / RECEIPT_FILENAME
    try:
        directories = set()
        for item in files:
            parts = item.path.split("/")
            site_root.joinpath(*parts).chmod(stat.S_IREAD)
            for index in range(1, len(parts)):
                directories.add(site_root.joinpath(*parts[:index]))
        receipt_path.chmod(stat.S_IREAD)
        for directory in sorted(
            directories,
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory.chmod(stat.S_IREAD | stat.S_IEXEC)
        site_root.chmod(stat.S_IREAD | stat.S_IEXEC)
        object_root.chmod(stat.S_IREAD | stat.S_IEXEC)
    except OSError as error:
        raise PluginDependencyStoreError(
            "DEPENDENCY_STORE_IO_ERROR",
            f"Cannot make dependency object read-only: {error}",
        ) from error


def prepare_safe_directory(path, code: str) -> Path:
    try:
        candidate = Path(path).expanduser()
        candidate.mkdir(parents=True, exist_ok=True)
        _require_no_link_ancestors(candidate)
        path_stat = candidate.lstat()
        if not stat.S_ISDIR(path_stat.st_mode) or is_link_or_reparse_stat(path_stat):
            raise PluginDependencyStoreError(code, "Dependency store path is unsafe.")
        return candidate.resolve(strict=True)
    except PluginDependencyStoreError:
        raise
    except (OSError, RuntimeError, TypeError) as error:
        raise PluginDependencyStoreError(
            code,
            f"Cannot prepare dependency store path: {error}",
        ) from error


def require_safe_directory(path: Path, code: str, message: str):
    try:
        path_stat = path.lstat()
    except FileNotFoundError as error:
        raise PluginDependencyStoreError(code, message) from error
    except OSError as error:
        raise PluginDependencyStoreError(
            "DEPENDENCY_STORE_IO_ERROR",
            f"Cannot inspect dependency directory: {error}",
        ) from error
    if not stat.S_ISDIR(path_stat.st_mode) or is_link_or_reparse_stat(path_stat):
        raise PluginDependencyStoreError(code, message)


def remove_staging_tree(root: Path):
    try:
        root_stat = root.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise PluginDependencyStoreError(
            "DEPENDENCY_STORE_IO_ERROR",
            f"Cannot inspect dependency staging cleanup target: {error}",
        ) from error
    if not stat.S_ISDIR(root_stat.st_mode) or is_link_or_reparse_stat(root_stat):
        raise PluginDependencyStoreError(
            "UNSAFE_DEPENDENCY_STAGING",
            "Dependency staging cleanup target is unsafe.",
        )
    _remove_directory_contents(root)
    try:
        root.chmod(stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
        root.rmdir()
    except OSError as error:
        raise PluginDependencyStoreError(
            "DEPENDENCY_STORE_IO_ERROR",
            f"Cannot clean dependency staging: {error}",
        ) from error


def path_exists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError as error:
        raise PluginDependencyStoreError(
            "DEPENDENCY_STORE_IO_ERROR",
            f"Cannot inspect dependency store path: {error}",
        ) from error


def is_link_or_reparse_stat(path_stat) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _read_receipt(path: Path) -> bytes:
    try:
        expected_stat = path.lstat()
        if _unsafe_file_stat(expected_stat):
            raise _corrupt("Dependency receipt is not a safe regular file.")
        if expected_stat.st_size > MAX_RECEIPT_SIZE:
            raise _corrupt("Dependency receipt exceeds its size limit.")
        with path.open("rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            if not same_file_snapshot(expected_stat, opened_stat):
                raise _corrupt("Dependency receipt changed while being opened.")
            payload = handle.read(MAX_RECEIPT_SIZE + 1)
            final_stat = os.fstat(handle.fileno())
            if not same_file_snapshot(opened_stat, final_stat):
                raise _corrupt("Dependency receipt changed while being read.")
    except PluginDependencyStoreError:
        raise
    except OSError as error:
        raise _corrupt(f"Cannot read dependency receipt: {error}") from error
    if len(payload) != expected_stat.st_size:
        raise _corrupt("Dependency receipt size changed while being read.")
    return payload


def _verify_site_tree(
    site_root: Path,
    expected_files: tuple[StoredFile, ...],
):
    expected_by_key = {item.path.casefold(): item for item in expected_files}
    expected_dirs = set()
    for item in expected_files:
        parts = item.path.split("/")[:-1]
        for index in range(1, len(parts) + 1):
            expected_dirs.add("/".join(parts[:index]).casefold())

    actual_files = {}
    actual_dirs = set()
    pending = [(site_root, "")]
    while pending:
        directory, relative_root = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except OSError as error:
            raise _corrupt(f"Cannot enumerate dependency object: {error}") from error
        for entry in entries:
            relative = f"{relative_root}/{entry.name}" if relative_root else entry.name
            relative = relative.replace("\\", "/")
            entry_path = Path(entry.path)
            try:
                entry_stat = entry_path.lstat()
            except OSError as error:
                raise _corrupt(f"Cannot inspect dependency path: {relative}") from error
            if is_link_or_reparse_stat(entry_stat):
                raise _corrupt(f"Dependency object contains a link: {relative}")
            if stat.S_ISDIR(entry_stat.st_mode):
                actual_dirs.add(relative.casefold())
                pending.append((entry_path, relative))
                continue
            if _unsafe_file_stat(entry_stat):
                raise _corrupt(f"Dependency object contains an unsafe file: {relative}")
            key = relative.casefold()
            if key in actual_files:
                raise _corrupt(f"Dependency object repeats a file path: {relative}")
            actual_files[key] = (relative, entry_path, entry_stat)

    if set(actual_files) != set(expected_by_key) or actual_dirs != expected_dirs:
        raise _corrupt("Dependency object file tree does not match its receipt.")
    for key, expected in expected_by_key.items():
        relative, path, expected_stat = actual_files[key]
        if relative != expected.path:
            raise _corrupt("Dependency object path casing does not match its receipt.")
        size, digest = _hash_stored_file(path, expected_stat)
        if size != expected.size or digest != expected.sha256:
            raise _corrupt(f"Dependency object file is corrupted: {relative}")
        if not _is_read_only(expected_stat):
            raise _corrupt(f"Dependency object file is writable: {relative}")


def _hash_stored_file(path: Path, expected_stat) -> tuple[int, str]:
    digest = hashlib.sha256()
    bytes_read = 0
    try:
        with path.open("rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            if not same_file_snapshot(expected_stat, opened_stat):
                raise _corrupt("Dependency file changed while being opened.")
            for chunk in iter(lambda: handle.read(_BUFFER_SIZE), b""):
                bytes_read += len(chunk)
                digest.update(chunk)
            final_stat = os.fstat(handle.fileno())
            if not same_file_snapshot(opened_stat, final_stat):
                raise _corrupt("Dependency file changed while being verified.")
    except PluginDependencyStoreError:
        raise
    except OSError as error:
        raise _corrupt(f"Cannot hash dependency object file: {error}") from error
    return bytes_read, digest.hexdigest()


def _remove_directory_contents(root: Path):
    try:
        with os.scandir(root) as iterator:
            entries = list(iterator)
    except OSError as error:
        raise PluginDependencyStoreError(
            "DEPENDENCY_STORE_IO_ERROR",
            f"Cannot enumerate dependency staging cleanup target: {error}",
        ) from error
    for entry in entries:
        child = Path(entry.path)
        try:
            child_stat = child.lstat()
        except OSError as error:
            raise PluginDependencyStoreError(
                "DEPENDENCY_STORE_IO_ERROR",
                f"Cannot inspect dependency staging entry: {error}",
            ) from error
        if is_link_or_reparse_stat(child_stat):
            raise PluginDependencyStoreError(
                "UNSAFE_DEPENDENCY_STAGING",
                f"Dependency staging contains a link: {entry.name}",
            )
        if stat.S_ISDIR(child_stat.st_mode):
            _remove_directory_contents(child)
            child.chmod(stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
            child.rmdir()
        elif stat.S_ISREG(child_stat.st_mode):
            if getattr(child_stat, "st_nlink", 1) > 1:
                raise PluginDependencyStoreError(
                    "UNSAFE_DEPENDENCY_STAGING",
                    f"Dependency staging contains a hard-linked file: {entry.name}",
                )
            child.chmod(stat.S_IREAD | stat.S_IWRITE)
            child.unlink()
        else:
            raise PluginDependencyStoreError(
                "UNSAFE_DEPENDENCY_STAGING",
                f"Dependency staging contains a special file: {entry.name}",
            )


def _unsafe_file_stat(path_stat) -> bool:
    return (
        not stat.S_ISREG(path_stat.st_mode)
        or is_link_or_reparse_stat(path_stat)
        or getattr(path_stat, "st_nlink", 1) > 1
    )


def _require_no_link_ancestors(path: Path):
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            current_stat = current.lstat()
        except OSError as error:
            raise PluginDependencyStoreError(
                "INVALID_DEPENDENCY_STORE_ROOT",
                f"Cannot inspect dependency store ancestor: {error}",
            ) from error
        if is_link_or_reparse_stat(current_stat):
            raise PluginDependencyStoreError(
                "INVALID_DEPENDENCY_STORE_ROOT",
                f"Dependency store ancestor cannot be a link: {current}",
            )


def _is_read_only(path_stat) -> bool:
    if os.name == "nt":
        attributes = getattr(path_stat, "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_READONLY", 0x1))
    return not bool(path_stat.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _corrupt(message: str) -> PluginDependencyStoreError:
    return PluginDependencyStoreError("DEPENDENCY_OBJECT_CORRUPT", message)


__all__ = [
    "is_link_or_reparse_stat",
    "make_dependency_object_read_only",
    "path_exists",
    "prepare_safe_directory",
    "remove_staging_tree",
    "require_safe_directory",
]
