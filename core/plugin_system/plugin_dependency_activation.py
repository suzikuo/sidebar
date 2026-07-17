from __future__ import annotations

import importlib
import os
import re
import stat
import sys
import threading
from collections.abc import Iterable
from pathlib import Path

from packaging.utils import canonicalize_name
from packaging.version import Version

from core.plugin_system.plugin_dependency_store_types import StoredDependency


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_ACTIVATION_LOCK = threading.Lock()
_ACTIVE_LEASE = None
_ACTIVATION_CONSUMED = False
_ACTIVATION_POISONED = False


class PluginDependencyActivationError(RuntimeError):
    """A process-level dependency path activation failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DependencyActivationLease:
    """Own process-wide dependency paths and Windows DLL directory handles."""

    def __init__(
        self,
        dependencies: tuple[StoredDependency, ...],
        path_list: list,
        add_dll_directory,
    ):
        self.dependencies = dependencies
        self.site_roots = tuple(item.site_root for item in dependencies)
        self.dll_directories = tuple(
            sorted(
                {
                    directory
                    for item in dependencies
                    for directory in item.dll_directories
                },
                key=lambda path: os.path.normcase(str(path)),
            )
        )
        self._path_list = path_list
        self._add_dll_directory = add_dll_directory
        self._inserted_paths: list[str] = []
        self._dll_handles = []
        self._previous_dont_write_bytecode = None
        self._bytecode_overridden = False
        self._cache_invalidation_pending = False
        self._unrecoverable_side_effect = False
        self._active = False

    @classmethod
    def activate(
        cls,
        dependencies: Iterable[StoredDependency],
        *,
        path_list: list | None = None,
        add_dll_directory=None,
    ) -> "DependencyActivationLease":
        values = _normalize_dependencies(dependencies)
        target_path_list = sys.path if path_list is None else path_list
        if not isinstance(target_path_list, list):
            raise PluginDependencyActivationError(
                "INVALID_DEPENDENCY_PATH_LIST",
                "Dependency activation requires a mutable path list.",
            )
        adder = (
            getattr(os, "add_dll_directory", None)
            if add_dll_directory is None
            else add_dll_directory
        )
        if adder is not None and not callable(adder):
            raise PluginDependencyActivationError(
                "INVALID_DLL_DIRECTORY_ADAPTER",
                "DLL directory adapter must be callable.",
            )

        global _ACTIVE_LEASE, _ACTIVATION_CONSUMED, _ACTIVATION_POISONED
        with _ACTIVATION_LOCK:
            if _ACTIVE_LEASE is not None:
                code = (
                    "DEPENDENCY_RUNTIME_CLEANUP_PENDING"
                    if _ACTIVE_LEASE._has_pending_cleanup()
                    and not _ACTIVE_LEASE.active
                    else "DEPENDENCY_LEASE_ALREADY_ACTIVE"
                )
                raise PluginDependencyActivationError(
                    code,
                    "The process dependency runtime is already owned by a lease.",
                )
            if _ACTIVATION_POISONED:
                raise PluginDependencyActivationError(
                    "DEPENDENCY_ACTIVATION_POISONED",
                    "Dependency activation previously failed with incomplete cleanup; "
                    "restart before loading plugin code.",
                )
            if _ACTIVATION_CONSUMED:
                raise PluginDependencyActivationError(
                    "DEPENDENCY_ACTIVATION_ALREADY_CONSUMED",
                    "Process dependencies were already activated; restart before "
                    "using a different dependency set.",
                )
            lease = cls(values, target_path_list, adder)
            _ACTIVE_LEASE = lease
            try:
                lease._activate()
            except BaseException as error:
                if not lease._has_pending_cleanup():
                    _ACTIVE_LEASE = None
                else:
                    _ACTIVATION_POISONED = True
                    if isinstance(error, Exception):
                        raise PluginDependencyActivationError(
                            "DEPENDENCY_ACTIVATION_CLEANUP_FAILED",
                            "Dependency activation failed and process cleanup is still "
                            "pending; clean up for shutdown and restart before loading "
                            "code.",
                        ) from error
                raise
            _ACTIVATION_CONSUMED = True
            return lease

    @classmethod
    def retry_pending_cleanup(cls) -> bool:
        """Retry cleanup after a failed activation without exposing its lease."""

        global _ACTIVE_LEASE
        with _ACTIVATION_LOCK:
            lease = _ACTIVE_LEASE
            if lease is None:
                return False
            if lease.active or not lease._has_pending_cleanup():
                raise PluginDependencyActivationError(
                    "DEPENDENCY_CLEANUP_NOT_PENDING",
                    "The process dependency runtime has no failed cleanup to retry.",
                )
            cleanup_error = lease._rollback()
            if cleanup_error is not None or lease._has_pending_cleanup():
                raise PluginDependencyActivationError(
                    "DEPENDENCY_RUNTIME_CLEANUP_PENDING",
                    f"Dependency runtime cleanup is still pending: {cleanup_error}",
                ) from cleanup_error
            _ACTIVE_LEASE = None
            return True

    @property
    def active(self) -> bool:
        return self._active

    def _activate(self):
        existing_paths = _normalized_existing_paths(self._path_list)
        for site_root in self.site_roots:
            key = os.path.normcase(str(site_root))
            if key in existing_paths:
                raise PluginDependencyActivationError(
                    "DEPENDENCY_PATH_ALREADY_ACTIVE",
                    f"Dependency site path is already active: {site_root}",
                )

        try:
            if self.dll_directories and self._add_dll_directory is None:
                raise PluginDependencyActivationError(
                    "DLL_DIRECTORY_API_UNAVAILABLE",
                    "This Python runtime cannot register dependency DLL directories.",
                )
            for directory in self.dll_directories:
                try:
                    handle = self._add_dll_directory(str(directory))
                except Exception as error:
                    raise PluginDependencyActivationError(
                        "DEPENDENCY_DLL_DIRECTORY_FAILED",
                        f"Cannot activate dependency DLL directory {directory}: {error}",
                    ) from error
                try:
                    close_handle = getattr(handle, "close", None)
                except Exception as error:
                    self._unrecoverable_side_effect = True
                    raise PluginDependencyActivationError(
                        "INVALID_DLL_DIRECTORY_HANDLE",
                        f"Cannot inspect the DLL directory handle: {error}",
                    ) from error
                if handle is None or not callable(close_handle):
                    self._unrecoverable_side_effect = True
                    raise PluginDependencyActivationError(
                        "INVALID_DLL_DIRECTORY_HANDLE",
                        "DLL directory adapter returned an invalid handle.",
                    )
                self._dll_handles.append(handle)

            if self.dependencies:
                self._previous_dont_write_bytecode = sys.dont_write_bytecode
                self._bytecode_overridden = True
                sys.dont_write_bytecode = True
            for site_root in self.site_roots:
                value = str(site_root)
                self._inserted_paths.append(value)
                try:
                    self._path_list.append(value)
                except Exception as error:
                    raise PluginDependencyActivationError(
                        "DEPENDENCY_PATH_ACTIVATION_FAILED",
                        f"Cannot activate dependency site path {site_root}: {error}",
                    ) from error
            if self._inserted_paths:
                self._cache_invalidation_pending = True
                try:
                    importlib.invalidate_caches()
                except Exception as error:
                    raise PluginDependencyActivationError(
                        "DEPENDENCY_IMPORT_CACHE_FAILED",
                        f"Cannot refresh import caches after dependency activation: {error}",
                    ) from error
                self._cache_invalidation_pending = False
            self._active = True
        except BaseException as error:
            cleanup_error = self._rollback()
            if cleanup_error is not None:
                error.add_note(f"Dependency activation rollback also failed: {cleanup_error}")
            raise

    def close(self):
        global _ACTIVE_LEASE, _ACTIVATION_POISONED
        with _ACTIVATION_LOCK:
            if not self._active and not self._has_pending_cleanup():
                if _ACTIVE_LEASE is self:
                    _ACTIVE_LEASE = None
                return
            cleanup_error = self._rollback()
            self._active = False
            cleanup_pending = self._has_pending_cleanup()
            if cleanup_error is not None or cleanup_pending:
                _ACTIVATION_POISONED = True
            if not cleanup_pending and _ACTIVE_LEASE is self:
                _ACTIVE_LEASE = None
        if cleanup_error is not None or cleanup_pending:
            raise PluginDependencyActivationError(
                "DEPENDENCY_LEASE_CLOSE_FAILED",
                f"Cannot completely close dependency activation: {cleanup_error}",
            ) from cleanup_error

    def _rollback(self) -> BaseException | None:
        first_error = None
        paths_changed = bool(self._inserted_paths)
        failed_paths = []
        for value in reversed(self._inserted_paths):
            try:
                _remove_inserted_value(self._path_list, value)
            except BaseException as error:
                failed_paths.append(value)
                if first_error is None:
                    first_error = error
        self._inserted_paths = list(reversed(failed_paths))
        if paths_changed:
            self._cache_invalidation_pending = True

        if not self._inserted_paths and self._bytecode_overridden:
            sys.dont_write_bytecode = self._previous_dont_write_bytecode
            self._previous_dont_write_bytecode = None
            self._bytecode_overridden = False

        failed_handles = []
        for handle in reversed(self._dll_handles):
            try:
                handle.close()
            except BaseException as error:
                failed_handles.append(handle)
                if first_error is None:
                    first_error = error
        self._dll_handles = list(reversed(failed_handles))
        if self._cache_invalidation_pending:
            try:
                importlib.invalidate_caches()
            except BaseException as error:
                if first_error is None:
                    first_error = error
            else:
                self._cache_invalidation_pending = False
        self._active = False
        return first_error

    def _has_pending_cleanup(self) -> bool:
        return bool(
            self._inserted_paths
            or self._dll_handles
            or self._bytecode_overridden
            or self._cache_invalidation_pending
            or self._unrecoverable_side_effect
        )

    def __enter__(self):
        if not self._active:
            raise PluginDependencyActivationError(
                "DEPENDENCY_LEASE_NOT_ACTIVE",
                "Dependency activation lease is not active.",
            )
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


def _normalize_dependencies(
    dependencies: Iterable[StoredDependency],
) -> tuple[StoredDependency, ...]:
    if isinstance(dependencies, (str, bytes)) or not isinstance(
        dependencies, Iterable
    ):
        raise PluginDependencyActivationError(
            "INVALID_STORED_DEPENDENCIES",
            "Stored dependencies must be an iterable.",
        )
    try:
        values = tuple(dependencies)
    except Exception as error:
        raise PluginDependencyActivationError(
            "INVALID_STORED_DEPENDENCIES",
            f"Cannot enumerate stored dependencies: {error}",
        ) from error
    for item in values:
        if not isinstance(item, StoredDependency):
            raise PluginDependencyActivationError(
                "INVALID_STORED_DEPENDENCY",
                "Dependency activation requires StoredDependency values.",
            )
        _validate_stored_dependency(item)
    ordered = tuple(
        sorted(
            values,
            key=lambda item: (
                item.distribution,
                str(item.version),
                item.sha256,
            ),
        )
    )
    digests = [item.sha256 for item in ordered]
    if len(digests) != len(set(digests)):
        raise PluginDependencyActivationError(
            "DUPLICATE_DEPENDENCY_OBJECT",
            "Dependency activation contains a duplicate content object.",
        )
    site_keys = [os.path.normcase(str(item.site_root)) for item in ordered]
    if len(site_keys) != len(set(site_keys)):
        raise PluginDependencyActivationError(
            "DUPLICATE_DEPENDENCY_PATH",
            "Dependency activation contains a duplicate site path.",
        )
    return ordered


def _validate_stored_dependency(item: StoredDependency):
    if (
        not isinstance(item.sha256, str)
        or not _SHA256_PATTERN.fullmatch(item.sha256)
        or not isinstance(item.distribution, str)
        or canonicalize_name(item.distribution) != item.distribution
        or not isinstance(item.version, Version)
        or not isinstance(item.native_extensions, tuple)
        or not isinstance(item.dlls, tuple)
        or not isinstance(item.dll_directories, tuple)
    ):
        raise PluginDependencyActivationError(
            "INVALID_STORED_DEPENDENCY",
            "Stored dependency identity or native path collections are invalid.",
        )
    object_root = _safe_directory(item.object_root, "dependency object")
    site_root = _safe_directory(item.site_root, "dependency site")
    if (
        object_root.name != item.sha256
        or object_root.parent.name != item.sha256[:2]
        or object_root.parent.parent.name != "sha256"
        or object_root.parent.parent.parent.name != "objects"
        or site_root != object_root / "site"
    ):
        raise PluginDependencyActivationError(
            "INVALID_STORED_DEPENDENCY",
            "Stored dependency paths do not match its content address.",
        )

    native_paths = tuple(
        _safe_file(path, site_root, "native extension")
        for path in item.native_extensions
    )
    dll_paths = tuple(_safe_file(path, site_root, "DLL") for path in item.dlls)
    if len(native_paths) != len(set(native_paths)) or len(dll_paths) != len(
        set(dll_paths)
    ):
        raise PluginDependencyActivationError(
            "INVALID_STORED_DEPENDENCY",
            "Stored dependency contains duplicate native paths.",
        )
    dll_directories = tuple(
        _safe_directory(path, "DLL directory") for path in item.dll_directories
    )
    expected_directories = tuple(sorted({path.parent for path in dll_paths}, key=str))
    if dll_directories != expected_directories:
        raise PluginDependencyActivationError(
            "INVALID_STORED_DEPENDENCY",
            "Stored dependency DLL directories do not match its DLL files.",
        )


def _safe_directory(path, label: str) -> Path:
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            raise ValueError("path is not absolute")
        path_stat = candidate.lstat()
        if not stat.S_ISDIR(path_stat.st_mode) or _is_link_or_reparse(path_stat):
            raise ValueError("path is not a regular directory")
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise PluginDependencyActivationError(
            "UNSAFE_DEPENDENCY_RUNTIME_PATH",
            f"Stored {label} path is unsafe: {error}",
        ) from error
    if resolved != candidate:
        raise PluginDependencyActivationError(
            "UNSAFE_DEPENDENCY_RUNTIME_PATH",
            f"Stored {label} path is not canonical.",
        )
    return resolved


def _safe_file(path, site_root: Path, label: str) -> Path:
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            raise ValueError("path is not absolute")
        path_stat = candidate.lstat()
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or _is_link_or_reparse(path_stat)
            or getattr(path_stat, "st_nlink", 1) > 1
        ):
            raise ValueError("path is not a safe regular file")
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise PluginDependencyActivationError(
            "UNSAFE_DEPENDENCY_RUNTIME_PATH",
            f"Stored {label} path is unsafe: {error}",
        ) from error
    if resolved != candidate or not resolved.is_relative_to(site_root):
        raise PluginDependencyActivationError(
            "UNSAFE_DEPENDENCY_RUNTIME_PATH",
            f"Stored {label} path escapes its site root.",
        )
    return resolved


def _normalized_existing_paths(path_list: list) -> set[str]:
    try:
        values = tuple(path_list)
    except Exception as error:
        raise PluginDependencyActivationError(
            "INVALID_DEPENDENCY_PATH_LIST",
            f"Cannot enumerate the dependency path list: {error}",
        ) from error
    normalized = set()
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        try:
            candidate = Path(value).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        normalized.add(os.path.normcase(str(candidate)))
    return normalized


def _remove_inserted_value(values: list, expected: str):
    for index, value in enumerate(values):
        if value is expected:
            del values[index]
            return


def _is_link_or_reparse(path_stat) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


__all__ = ["DependencyActivationLease", "PluginDependencyActivationError"]
