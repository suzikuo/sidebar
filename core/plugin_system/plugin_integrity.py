from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path

from core.plugin_system.plugin_dependency_lock import (
    MAX_DEPENDENCY_LOCK_SIZE,
    parse_and_validate_dependency_lock,
)
from core.plugin_system.native_binary import (
    NativeBinaryError,
    validate_windows_pyd,
)
from core.plugin_system.plugin_manifest import PluginManifest, PluginManifestError
from core.plugin_system.plugin_wheel import PluginWheelError, inspect_wheel


_HASH_CHUNK_SIZE = 1024 * 1024


def build_plugin_file_hashes(root) -> dict[str, str]:
    """Build an in-memory file declaration for a trusted source plugin."""

    plugin_root = _resolve_plugin_root(root)
    files = {}
    try:
        for directory, directory_names, file_names in os.walk(
            plugin_root, topdown=True, followlinks=False
        ):
            directory_path = Path(directory)
            for name in directory_names:
                if _is_unsafe_path(directory_path / name):
                    raise PluginManifestError(
                        "UNSAFE_PLUGIN_FILE",
                        f"Plugin directory contains a link or reparse point: {name}",
                    )
            for name in file_names:
                path = directory_path / name
                relative_path = path.relative_to(plugin_root).as_posix()
                if relative_path == "manifest.json":
                    continue
                relative_parts = Path(relative_path).parts
                if "__pycache__" in relative_parts and path.suffix.lower() == ".pyc":
                    continue
                path_stat = os.lstat(path)
                if _stat_is_unsafe_file(path_stat):
                    raise PluginManifestError(
                        "UNSAFE_PLUGIN_FILE",
                        f"Plugin file is not a regular independent file: {name}",
                    )
                files[relative_path] = _hash_file(path, path_stat)
    except PluginManifestError:
        raise
    except OSError as error:
        raise PluginManifestError(
            "PLUGIN_DIRECTORY_UNAVAILABLE",
            f"Cannot enumerate plugin files: {error}",
        ) from error
    return dict(sorted(files.items()))


def hash_plugin_directory(root) -> str:
    """Return a deterministic digest binding every regular file and its path."""

    plugin_root = _resolve_plugin_root(root)

    files = []
    try:
        for directory, directory_names, file_names in os.walk(
            plugin_root, topdown=True, followlinks=False
        ):
            directory_path = Path(directory)
            for name in directory_names:
                if _is_unsafe_path(directory_path / name):
                    raise PluginManifestError(
                        "UNSAFE_PLUGIN_FILE",
                        f"Plugin directory contains a link or reparse point: {name}",
                    )
            for name in file_names:
                path = directory_path / name
                path_stat = os.lstat(path)
                if _stat_is_unsafe_file(path_stat):
                    raise PluginManifestError(
                        "UNSAFE_PLUGIN_FILE",
                        f"Plugin file is not a regular independent file: {name}",
                    )
                files.append(
                    (path.relative_to(plugin_root).as_posix(), path, path_stat)
                )
    except PluginManifestError:
        raise
    except OSError as error:
        raise PluginManifestError(
            "PLUGIN_DIRECTORY_UNAVAILABLE",
            f"Cannot enumerate plugin files: {error}",
        ) from error

    digest = hashlib.sha256()
    for relative_path, path, path_stat in sorted(files, key=lambda item: item[0]):
        path_bytes = relative_path.encode("utf-8")
        file_digest = bytes.fromhex(_hash_file(path, path_stat))
        digest.update(len(path_bytes).to_bytes(4, "big"))
        digest.update(path_bytes)
        digest.update(path_stat.st_size.to_bytes(8, "big"))
        digest.update(file_digest)
    return digest.hexdigest()


def validate_plugin_directory(root, manifest: PluginManifest):
    """Validate v2 declared files without following links or reparse points."""

    if manifest.manifest_version != 2:
        return

    plugin_root = _resolve_plugin_root(root)

    actual_files = {}
    try:
        for directory, directory_names, file_names in os.walk(
            plugin_root, topdown=True, followlinks=False
        ):
            directory_path = Path(directory)
            for name in list(directory_names):
                child = directory_path / name
                if _is_unsafe_path(child):
                    raise PluginManifestError(
                        "UNSAFE_PLUGIN_FILE",
                        f"Plugin directory contains a link or reparse point: {name}",
                    )
            for name in file_names:
                path = directory_path / name
                path_stat = os.lstat(path)
                if _stat_is_unsafe_file(path_stat):
                    raise PluginManifestError(
                        "UNSAFE_PLUGIN_FILE",
                        f"Plugin file is not a regular independent file: {name}",
                    )
                relative_path = path.relative_to(plugin_root).as_posix()
                if relative_path == "manifest.json":
                    continue
                relative_parts = Path(relative_path).parts
                if "__pycache__" in relative_parts and path.suffix.lower() == ".pyc":
                    continue
                actual_files[relative_path] = (path, path_stat)
    except PluginManifestError:
        raise
    except OSError as error:
        raise PluginManifestError(
            "PLUGIN_DIRECTORY_UNAVAILABLE",
            f"Cannot enumerate plugin files: {error}",
        ) from error

    declared_paths = set(manifest.file_hashes)
    actual_paths = set(actual_files)
    missing = sorted(declared_paths - actual_paths)
    if missing:
        raise PluginManifestError(
            "DECLARED_FILE_MISSING",
            f"Manifest declares a missing plugin file: {missing[0]}",
            field="files",
        )
    undeclared = sorted(actual_paths - declared_paths)
    if undeclared:
        raise PluginManifestError(
            "UNDECLARED_PACKAGE_FILE",
            f"Plugin directory contains an undeclared file: {undeclared[0]}",
            field="files",
        )

    for relative_path, expected_hash in manifest.file_hashes.items():
        path, expected_stat = actual_files[relative_path]
        if _hash_file(path, expected_stat) != expected_hash:
            raise PluginManifestError(
                "FILE_HASH_MISMATCH",
                f"Plugin file hash does not match manifest: {relative_path}",
                field=f"files.{relative_path}",
            )

    if manifest.dependencies.lock:
        lock_path, lock_stat = actual_files[manifest.dependencies.lock]
        lock_payload = _read_bounded_file(
            lock_path,
            lock_stat,
            MAX_DEPENDENCY_LOCK_SIZE,
        )
        dependency_lock = parse_and_validate_dependency_lock(lock_payload, manifest)
        for package in dependency_lock.packages:
            wheel_path = plugin_root.joinpath(*package.wheel.split("/"))
            try:
                inspect_wheel(
                    wheel_path,
                    target_python_abi=dependency_lock.target.python_abi,
                    target_platform=dependency_lock.target.platform_tag,
                    expected_name=package.name,
                    expected_version=package.version,
                    expected_sha256=package.sha256,
                )
            except PluginWheelError as error:
                raise PluginManifestError(
                    error.code,
                    f"Invalid locked wheel {package.wheel}: {error}",
                    field="dependencies.lock",
                ) from error

    for module in manifest.native_modules:
        path, expected_stat = actual_files[module.path]
        _validate_native_module_file(
            path,
            expected_stat,
            module.module,
            manifest.compatibility.platform_tag,
        )


def purge_plugin_bytecode_caches(root):
    """Remove ignored Python bytecode caches before plugin code can import them."""

    try:
        plugin_root = _resolve_plugin_root(root)
        cache_directories = []
        for directory, directory_names, _ in os.walk(
            plugin_root, topdown=True, followlinks=False
        ):
            directory_path = Path(directory)
            for name in list(directory_names):
                child = directory_path / name
                if _is_unsafe_path(child):
                    raise PluginManifestError(
                        "UNSAFE_PLUGIN_FILE",
                        f"Plugin directory contains a link or reparse point: {name}",
                    )
                if name == "__pycache__":
                    cache_directories.append(child)
                    directory_names.remove(name)
    except PluginManifestError:
        raise
    except (OSError, RuntimeError) as error:
        raise PluginManifestError(
            "PLUGIN_DIRECTORY_UNAVAILABLE",
            f"Cannot inspect plugin bytecode caches: {error}",
        ) from error

    for cache_directory in cache_directories:
        if _is_unsafe_path(cache_directory):
            raise PluginManifestError(
                "UNSAFE_PLUGIN_FILE",
                "Plugin bytecode cache cannot be a link or reparse point.",
            )
        try:
            shutil.rmtree(cache_directory)
        except OSError as error:
            raise PluginManifestError(
                "PLUGIN_CACHE_CLEANUP_FAILED",
                f"Cannot remove plugin bytecode cache: {error}",
            ) from error


def _hash_file(path: Path, expected_stat) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            if not _same_file(expected_stat, opened_stat) or _stat_is_unsafe_file(
                opened_stat
            ):
                raise PluginManifestError(
                    "UNSAFE_PLUGIN_FILE",
                    f"Plugin file changed while being opened: {path.name}",
                )
            for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
                digest.update(chunk)
            final_stat = os.fstat(handle.fileno())
            if (
                not _same_file(opened_stat, final_stat)
                or opened_stat.st_size != final_stat.st_size
                or opened_stat.st_mtime_ns != final_stat.st_mtime_ns
            ):
                raise PluginManifestError(
                    "PLUGIN_FILE_CHANGED",
                    f"Plugin file changed while being hashed: {path.name}",
                )
    except PluginManifestError:
        raise
    except OSError as error:
        raise PluginManifestError(
            "PLUGIN_FILE_UNAVAILABLE",
            f"Cannot hash plugin file {path.name}: {error}",
        ) from error
    return digest.hexdigest()


def _read_bounded_file(path: Path, expected_stat, max_size: int) -> bytes:
    if expected_stat.st_size > max_size:
        raise PluginManifestError(
            "DEPENDENCY_LOCK_TOO_LARGE",
            f"Dependency lock exceeds the size limit: {path.name}",
        )
    try:
        with path.open("rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            if not _same_file(expected_stat, opened_stat) or _stat_is_unsafe_file(
                opened_stat
            ):
                raise PluginManifestError(
                    "UNSAFE_PLUGIN_FILE",
                    f"Plugin file changed while being opened: {path.name}",
                )
            payload = handle.read(max_size + 1)
            final_stat = os.fstat(handle.fileno())
            if (
                len(payload) != opened_stat.st_size
                or not _same_file(opened_stat, final_stat)
                or opened_stat.st_size != final_stat.st_size
                or opened_stat.st_mtime_ns != final_stat.st_mtime_ns
            ):
                raise PluginManifestError(
                    "PLUGIN_FILE_CHANGED",
                    f"Plugin file changed while being read: {path.name}",
                )
    except PluginManifestError:
        raise
    except OSError as error:
        raise PluginManifestError(
            "PLUGIN_FILE_UNAVAILABLE",
            f"Cannot read plugin file {path.name}: {error}",
        ) from error
    return payload


def _resolve_plugin_root(root) -> Path:
    try:
        candidate = Path(root)
        candidate_stat = os.lstat(candidate)
    except (OSError, TypeError) as error:
        raise PluginManifestError(
            "PLUGIN_DIRECTORY_UNAVAILABLE",
            f"Cannot inspect plugin directory: {error}",
        ) from error

    attributes = getattr(candidate_stat, "st_file_attributes", 0)
    if (
        not stat.S_ISDIR(candidate_stat.st_mode)
        or stat.S_ISLNK(candidate_stat.st_mode)
        or bool(
            attributes
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
    ):
        raise PluginManifestError(
            "UNSAFE_PLUGIN_FILE",
            "Plugin directory must be a regular non-reparse directory.",
        )

    try:
        plugin_root = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise PluginManifestError(
            "PLUGIN_DIRECTORY_UNAVAILABLE",
            f"Cannot resolve plugin directory: {error}",
        ) from error
    if not plugin_root.is_dir() or _is_unsafe_path(plugin_root):
        raise PluginManifestError(
            "UNSAFE_PLUGIN_FILE",
            "Plugin directory must be a regular non-reparse directory.",
        )
    return plugin_root


def _validate_native_module_file(
    path: Path,
    expected_stat,
    module_name: str,
    platform_tag: str,
):
    try:
        with path.open("rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            if (
                not _same_file(expected_stat, opened_stat)
                or expected_stat.st_size != opened_stat.st_size
                or expected_stat.st_mtime_ns != opened_stat.st_mtime_ns
                or _stat_is_unsafe_file(opened_stat)
            ):
                raise PluginManifestError(
                    "PLUGIN_FILE_CHANGED",
                    f"Native module changed while being opened: {path.name}",
                )
            validate_windows_pyd(
                handle,
                file_size=opened_stat.st_size,
                module_name=module_name,
                platform_tag=platform_tag,
            )
            final_stat = os.fstat(handle.fileno())
            if (
                not _same_file(opened_stat, final_stat)
                or opened_stat.st_size != final_stat.st_size
                or opened_stat.st_mtime_ns != final_stat.st_mtime_ns
            ):
                raise PluginManifestError(
                    "PLUGIN_FILE_CHANGED",
                    f"Native module changed while being inspected: {path.name}",
                )
    except NativeBinaryError as error:
        raise PluginManifestError(
            error.code,
            f"Invalid native module {path.name}: {error}",
            field=f"native_modules.{module_name}",
        ) from error
    except PluginManifestError:
        raise
    except OSError as error:
        raise PluginManifestError(
            "PLUGIN_FILE_UNAVAILABLE",
            f"Cannot inspect native module {path.name}: {error}",
            field=f"native_modules.{module_name}",
        ) from error


def _is_unsafe_path(path: Path) -> bool:
    try:
        path_stat = os.lstat(path)
    except OSError:
        return True
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _stat_is_unsafe_file(path_stat) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return (
        not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        or getattr(path_stat, "st_nlink", 1) > 1
    )


def _same_file(first, second) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino
