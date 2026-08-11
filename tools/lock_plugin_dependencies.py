"""Create a deterministic dependency lock from wheels already in a plugin source tree."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from core.plugin_system.plugin_dependency_lock import (
    DependencyLock,
    DependencyLockTarget,
    LockedDependencyPackage,
)
from core.plugin_system.plugin_dependency_resolver import (
    PluginDependencyInput,
    resolve_dependency_set,
)
from core.plugin_system.plugin_manifest import PluginManifestError, parse_manifest
from core.plugin_system.plugin_wheel import PluginWheelError, inspect_wheel


class PluginDependencyLockError(RuntimeError):
    """An author-facing dependency lock failure."""


def build_dependency_lock(plugin_dir, wheel_dir="wheels", output="dependencies.lock.json"):
    root = Path(plugin_dir).resolve(strict=True)
    manifest = _load_manifest(root)
    if not manifest.dependencies.python:
        raise PluginDependencyLockError("Plugin does not declare Python dependencies.")

    wheels_root = _resolve_child(root, wheel_dir, "wheel directory")
    output_path = _resolve_child(root, output, "lock output")
    artifacts = _inspect_wheels(root, wheels_root, manifest)
    lock = _build_lock(manifest, artifacts, root)
    _validate_direct_requirements(manifest, lock)
    resolved = resolve_dependency_set(
        {
            manifest.plugin_id: PluginDependencyInput(
                lock=lock,
                wheels=artifacts,
            )
        },
        host_packages=_exact_host_versions(manifest),
    )
    payload = {
        "lock_version": 1,
        "target": {
            "python_abi": resolved.python_abi,
            "platform": resolved.platform_tag,
        },
        "packages": [
            {
                "name": item.name,
                "version": str(item.version),
                "wheel": _relative(root, item.artifact.path),
                "sha256": item.sha256,
            }
            for item in resolved.packages
        ],
    }
    _write_json_atomically(output_path, payload)
    return output_path


def _load_manifest(root):
    try:
        payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        # Source manifests deliberately keep files empty until plugin_packer hashes them.
        # Build a parse-only declaration map without modifying the source manifest.
        declared_files = {
            path.relative_to(root).as_posix(): "0" * 64
            for path in root.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        }
        entry = payload.get("entry")
        if isinstance(entry, str) and entry:
            declared_files.setdefault(entry.replace("\\", "/"), "0" * 64)
        dependencies = payload.get("dependencies")
        if isinstance(dependencies, dict) and isinstance(dependencies.get("lock"), str):
            declared_files.setdefault(dependencies["lock"], "0" * 64)
        payload["files"] = declared_files
        return parse_manifest(payload)
    except (OSError, json.JSONDecodeError, PluginManifestError) as error:
        raise PluginDependencyLockError(f"Cannot load plugin manifest: {error}") from error


def _inspect_wheels(root, wheels_root, manifest):
    if not wheels_root.is_dir():
        raise PluginDependencyLockError("Plugin wheel directory does not exist.")
    wheels = sorted(wheels_root.glob("*.whl"), key=lambda path: path.name.casefold())
    if not wheels:
        raise PluginDependencyLockError("Plugin wheel directory contains no .whl files.")
    artifacts = []
    names = set()
    for wheel in wheels:
        try:
            artifact = inspect_wheel(
                wheel,
                target_python_abi=manifest.compatibility.python_abi,
                target_platform=manifest.compatibility.platform_tag,
            )
        except PluginWheelError as error:
            raise PluginDependencyLockError(f"Invalid wheel {wheel.name}: {error}") from error
        name = canonicalize_name(artifact.distribution)
        if name in names:
            raise PluginDependencyLockError(f"Duplicate wheel distribution: {name}")
        names.add(name)
        artifacts.append(artifact)
    return tuple(artifacts)


def _build_lock(manifest, artifacts, root):
    packages = tuple(
        LockedDependencyPackage(
            name=canonicalize_name(artifact.distribution),
            version=artifact.version,
            wheel=_relative(root, artifact.path),
            sha256=artifact.sha256,
        )
        for artifact in sorted(artifacts, key=lambda item: canonicalize_name(item.distribution))
    )
    return DependencyLock(
        lock_version=1,
        target=DependencyLockTarget(
            python_abi=manifest.compatibility.python_abi,
            platform_tag=manifest.compatibility.platform_tag,
        ),
        packages=packages,
    )


def _validate_direct_requirements(manifest, lock):
    packages = {package.name: package for package in lock.packages}
    for requirement in manifest.dependencies.python:
        package = packages.get(requirement.name)
        if package is None or not requirement.accepts(package.version):
            raise PluginDependencyLockError(
                f"No compatible locked wheel for {requirement.requirement}."
            )


def _exact_host_versions(manifest):
    versions = {}
    for dependency in manifest.dependencies.host:
        pins = [
            specifier.version
            for specifier in SpecifierSet(dependency.specifier)
            if specifier.operator == "==" and "*" not in specifier.version
        ]
        if len(pins) == 1:
            versions[dependency.name] = pins[0]
    return versions


def _resolve_child(root, relative, label):
    candidate = (root / Path(relative)).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise PluginDependencyLockError(f"{label} must stay inside the plugin directory.") from error
    return candidate


def _relative(root, path):
    return path.resolve(strict=True).relative_to(root).as_posix()


def _write_json_atomically(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate dependencies.lock from a plugin's vendored wheels."
    )
    parser.add_argument("plugin_dir", type=Path)
    parser.add_argument("--wheel-dir", default="wheels")
    parser.add_argument("--output", default="dependencies.lock.json")
    args = parser.parse_args(argv)
    try:
        path = build_dependency_lock(args.plugin_dir, args.wheel_dir, args.output)
    except PluginDependencyLockError as error:
        parser.exit(1, f"Error: {error}\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
