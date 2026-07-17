from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import uuid
import zipfile
from pathlib import Path

from core.plugin_system.plugin_manifest import PluginManifestError, parse_manifest
from core.plugin_system.plugin_package import (
    PluginPackageError,
    inspect_plugin_package,
)


_BYTECODE_SUFFIXES = frozenset({".pyc", ".pyo"})
_HASH_CHUNK_SIZE = 1024 * 1024


class PluginPackerError(RuntimeError):
    """An author-facing package build failure."""


def build_plugin_package(plugin_dir, output_dir=".") -> Path:
    """Build and validate one root-layout Manifest v2 .atplugin package."""

    plugin_root = _resolve_plugin_root(plugin_dir)
    manifest = _read_source_manifest(plugin_root / "manifest.json")
    if type(manifest.get("manifest_version")) is not int or manifest.get(
        "manifest_version"
    ) != 2:
        raise PluginPackerError("Plugin packages require manifest_version 2.")

    destination_root = _prepare_output_directory(output_dir)
    output_path = destination_root / f"{plugin_root.name}.atplugin"
    files = _collect_files(plugin_root, output_path)
    manifest["files"] = {relative: digest for relative, _, digest in files}
    _synchronize_native_hashes(manifest, files)

    try:
        parse_manifest(manifest)
    except PluginManifestError as error:
        raise PluginPackerError(f"Invalid Manifest v2: {error}") from error

    temporary_path = destination_root / (
        f".{output_path.stem}.{uuid.uuid4().hex}.atplugin"
    )
    try:
        _write_archive(temporary_path, manifest, files)
        inspect_plugin_package(temporary_path)
        os.replace(temporary_path, output_path)
    except PluginPackerError:
        raise
    except PluginPackageError as error:
        raise PluginPackerError(f"Generated package failed self-validation: {error}") from error
    except OSError as error:
        raise PluginPackerError(f"Cannot write plugin package: {error}") from error
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
    return output_path


def _resolve_plugin_root(plugin_dir) -> Path:
    try:
        candidate = Path(plugin_dir).expanduser()
        candidate_stat = os.lstat(candidate)
        if _is_unsafe_directory(candidate_stat):
            raise PluginPackerError("Plugin source must be a regular directory.")
        return candidate.resolve(strict=True)
    except PluginPackerError:
        raise
    except (OSError, RuntimeError, TypeError) as error:
        raise PluginPackerError(f"Cannot open plugin source directory: {error}") from error


def _prepare_output_directory(output_dir) -> Path:
    try:
        destination = Path(output_dir).expanduser()
        destination.mkdir(parents=True, exist_ok=True)
        if not destination.is_dir():
            raise PluginPackerError("Plugin output path must be a directory.")
        return destination.resolve(strict=True)
    except PluginPackerError:
        raise
    except (OSError, RuntimeError, TypeError) as error:
        raise PluginPackerError(f"Cannot prepare plugin output directory: {error}") from error


def _read_source_manifest(path: Path) -> dict:
    try:
        path_stat = os.lstat(path)
        if _is_unsafe_file(path_stat):
            raise PluginPackerError("manifest.json must be a regular file.")
        with path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except PluginPackerError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PluginPackerError(f"Cannot read manifest.json: {error}") from error
    if not isinstance(manifest, dict):
        raise PluginPackerError("manifest.json must contain an object.")
    return manifest


def _collect_files(
    plugin_root: Path, output_path: Path
) -> list[tuple[str, Path, str]]:
    files = []
    try:
        for directory, directory_names, file_names in os.walk(
            plugin_root, topdown=True, followlinks=False
        ):
            directory_path = Path(directory)
            retained_directories = []
            for name in sorted(directory_names):
                if name == "__pycache__":
                    continue
                child_stat = os.lstat(directory_path / name)
                if _is_unsafe_directory(child_stat):
                    raise PluginPackerError(
                        f"Plugin source contains an unsafe directory: {name}"
                    )
                retained_directories.append(name)
            directory_names[:] = retained_directories

            for name in sorted(file_names):
                path = directory_path / name
                relative_path = path.relative_to(plugin_root).as_posix()
                if relative_path == "manifest.json":
                    continue
                if path.suffix.lower() in _BYTECODE_SUFFIXES:
                    continue
                if path == output_path:
                    continue
                path_stat = os.lstat(path)
                if _is_unsafe_file(path_stat):
                    raise PluginPackerError(
                        f"Plugin source contains an unsafe file: {relative_path}"
                    )
                files.append((relative_path, path, _hash_file(path, path_stat)))
    except PluginPackerError:
        raise
    except OSError as error:
        raise PluginPackerError(f"Cannot enumerate plugin source files: {error}") from error
    return sorted(files, key=lambda item: item[0])


def _synchronize_native_hashes(manifest: dict, files) -> None:
    native_modules = manifest.get("native_modules")
    if not isinstance(native_modules, list):
        raise PluginPackerError("native_modules must be an array in Manifest v2.")
    hashes = {relative.casefold(): digest for relative, _, digest in files}
    for index, native_module in enumerate(native_modules):
        if not isinstance(native_module, dict):
            raise PluginPackerError(f"native_modules.{index} must be an object.")
        raw_path = native_module.get("path")
        if not isinstance(raw_path, str):
            raise PluginPackerError(f"native_modules.{index}.path must be a string.")
        normalized_path = raw_path.strip().replace("\\", "/")
        digest = hashes.get(normalized_path.casefold())
        if digest is None:
            raise PluginPackerError(
                f"Native module is not present in the plugin source: {raw_path}"
            )
        native_module["sha256"] = digest


def _write_archive(archive_path: Path, manifest: dict, files) -> None:
    manifest_payload = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    with zipfile.ZipFile(
        archive_path, "x", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr("manifest.json", manifest_payload)
        for relative_path, source_path, _ in files:
            archive.write(source_path, relative_path)


def _hash_file(path: Path, expected_stat) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            if not os.path.samestat(expected_stat, opened_stat) or _is_unsafe_file(
                opened_stat
            ):
                raise PluginPackerError(f"Plugin source file changed: {path.name}")
            for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
                digest.update(chunk)
            final_stat = os.fstat(handle.fileno())
            if (
                not os.path.samestat(opened_stat, final_stat)
                or opened_stat.st_size != final_stat.st_size
                or opened_stat.st_mtime_ns != final_stat.st_mtime_ns
            ):
                raise PluginPackerError(f"Plugin source file changed: {path.name}")
    except PluginPackerError:
        raise
    except OSError as error:
        raise PluginPackerError(f"Cannot hash plugin source file {path.name}: {error}") from error
    return digest.hexdigest()


def _is_unsafe_directory(path_stat) -> bool:
    return (
        not stat.S_ISDIR(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or _is_reparse(path_stat)
    )


def _is_unsafe_file(path_stat) -> bool:
    return (
        not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or _is_reparse(path_stat)
    )


def _is_reparse(path_stat) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build an Agile Tiles .atplugin package")
    parser.add_argument("plugin_dir", help="Manifest v2 plugin source directory")
    parser.add_argument(
        "--out",
        default=".",
        help="Output directory (default: current directory)",
    )
    args = parser.parse_args(argv)

    try:
        package_path = build_plugin_package(args.plugin_dir, args.out)
    except PluginPackerError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(package_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
