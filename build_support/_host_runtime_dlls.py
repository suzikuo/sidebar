from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable

from build_support._inventory_common import BuildInventoryError, inventory_error
from core.plugin_system.host_runtime_lock_types import (
    HostRuntimeDll,
    HostRuntimeLockError,
)


_HASH_CHUNK_SIZE = 1024 * 1024
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def scan_runtime_dlls(bundle_root: str | os.PathLike[str]) -> tuple[HostRuntimeDll, ...]:
    try:
        root = Path(bundle_root).absolute()
        root_stat = root.lstat()
    except (OSError, TypeError, ValueError) as error:
        raise inventory_error(
            "INVALID_BUNDLE_ROOT",
            f"Cannot inspect bundle root: {error}",
        ) from error
    if not stat.S_ISDIR(root_stat.st_mode) or _is_link_or_reparse(root, root_stat):
        raise inventory_error(
            "INVALID_BUNDLE_ROOT",
            "Bundle root must be an ordinary directory.",
        )

    dlls = []
    seen_paths: set[str] = set()
    for path, entry_stat in _walk_ordinary_files(root):
        if path.suffix.casefold() != ".dll":
            continue
        relative_path = _safe_relative_path(root, path)
        key = relative_path.casefold()
        if key in seen_paths:
            raise inventory_error(
                "DUPLICATE_RUNTIME_DLL_PATH",
                f"Bundle contains case-colliding DLL paths: {relative_path}.",
            )
        seen_paths.add(key)
        size, digest = _hash_stable_file(path, entry_stat, relative_path)
        try:
            dlls.append(HostRuntimeDll(relative_path, digest, size))
        except HostRuntimeLockError as error:
            raise inventory_error(
                "UNSAFE_RUNTIME_DLL",
                f"Runtime DLL has an invalid inventory path: {relative_path}.",
            ) from error
    return tuple(sorted(dlls, key=lambda item: (item.path.casefold(), item.path)))


def _walk_ordinary_files(root: Path) -> Iterable[tuple[Path, os.stat_result]]:
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: (item.name.casefold(), item.name))
        except OSError as error:
            raise inventory_error(
                "BUNDLE_SCAN_FAILED",
                f"Cannot scan bundle directory {directory}: {error}",
            ) from error
        child_directories = []
        for entry in entries:
            path = Path(entry.path)
            try:
                # DirEntry's cached Windows find-data omits stable file identity.
                entry_stat = path.stat(follow_symlinks=False)
            except OSError as error:
                raise inventory_error(
                    "BUNDLE_SCAN_FAILED",
                    f"Cannot inspect bundle entry {path}: {error}",
                ) from error
            if entry.is_symlink() or _has_reparse_attribute(entry_stat):
                raise inventory_error(
                    "UNSAFE_BUNDLE_ENTRY",
                    f"Bundle contains a link or reparse point: {path}.",
                )
            if stat.S_ISDIR(entry_stat.st_mode):
                child_directories.append(path)
            elif stat.S_ISREG(entry_stat.st_mode):
                yield path, entry_stat
            else:
                raise inventory_error(
                    "UNSAFE_BUNDLE_ENTRY",
                    f"Bundle contains a special filesystem entry: {path}.",
                )
        pending.extend(reversed(child_directories))


def _hash_stable_file(
    path: Path,
    expected_stat: os.stat_result,
    relative_path: str,
) -> tuple[int, str]:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or _stat_identity(before) != _stat_identity(expected_stat):
                raise inventory_error(
                    "RUNTIME_DLL_CHANGED",
                    f"Runtime DLL changed while it was opened: {relative_path}.",
                )
            if before.st_nlink > 1:
                raise inventory_error(
                    "UNSAFE_RUNTIME_DLL",
                    f"Runtime DLL must not be hard-linked: {relative_path}.",
                )
            while True:
                chunk = stream.read(_HASH_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            if _stat_snapshot(before) != _stat_snapshot(after):
                raise inventory_error(
                    "RUNTIME_DLL_CHANGED",
                    f"Runtime DLL changed while it was hashed: {relative_path}.",
                )
        final_stat = path.stat(follow_symlinks=False)
        if _stat_snapshot(after) != _stat_snapshot(final_stat):
            raise inventory_error(
                "RUNTIME_DLL_CHANGED",
                f"Runtime DLL changed after it was hashed: {relative_path}.",
            )
    except BuildInventoryError:
        raise
    except OSError as error:
        raise inventory_error(
            "RUNTIME_DLL_READ_FAILED",
            f"Cannot hash runtime DLL {relative_path}: {error}",
        ) from error
    if after.st_size <= 0:
        raise inventory_error(
            "UNSAFE_RUNTIME_DLL",
            f"Runtime DLL is empty: {relative_path}.",
        )
    return after.st_size, digest.hexdigest()


def _safe_relative_path(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise inventory_error(
            "UNSAFE_RUNTIME_DLL",
            "Runtime DLL escaped the bundle root.",
        ) from error
    value = PurePosixPath(*relative.parts).as_posix()
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        not value
        or "\\" in value
        or "\x00" in value
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or any(part in {"", ".", ".."} for part in posix_path.parts)
        or any(part.endswith((" ", ".")) for part in posix_path.parts)
    ):
        raise inventory_error(
            "UNSAFE_RUNTIME_DLL",
            f"Runtime DLL has an unsafe relative path: {value!r}.",
        )
    return value


def _is_link_or_reparse(path: Path, value: os.stat_result) -> bool:
    return path.is_symlink() or _has_reparse_attribute(value)


def _has_reparse_attribute(value: os.stat_result) -> bool:
    return bool(getattr(value, "st_file_attributes", 0) & _REPARSE_POINT)


def _stat_identity(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, value.st_mode


def _stat_snapshot(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_nlink,
        getattr(value, "st_file_attributes", 0),
    )
