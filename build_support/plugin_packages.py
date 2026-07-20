"""Build the repository's plugin sources into standalone package artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from plugin_packer import build_plugin_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_PLUGIN_SOURCE_ROOT = PROJECT_ROOT / "plugins1"


@dataclass(frozen=True)
class PluginPackageSource:
    plugin_id: str
    source_dir: Path


def discover_plugin_package_sources(source_root: Path) -> tuple[PluginPackageSource, ...]:
    """Return deterministic manifest-bearing plugin directories."""
    source_root = Path(source_root).resolve(strict=True)
    sources = []
    seen_ids = set()

    for source_dir in sorted(source_root.iterdir(), key=lambda path: path.name.casefold()):
        manifest_path = source_dir / "manifest.json"
        if not source_dir.is_dir() or not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        plugin_id = str(manifest.get("id") or "").strip()
        if not plugin_id:
            raise ValueError(f"Plugin manifest has no id: {manifest_path}")
        if plugin_id in seen_ids:
            raise ValueError(f"Duplicate plugin id in package sources: {plugin_id}")
        seen_ids.add(plugin_id)
        sources.append(PluginPackageSource(plugin_id, source_dir.resolve(strict=True)))

    return tuple(sources)


def build_plugin_packages(source_root: Path, output_dir: Path) -> tuple[Path, ...]:
    """Build every source before replacing the published package set."""
    sources = discover_plugin_package_sources(source_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        dir=str(output_dir.parent), prefix=f".{output_dir.name}-build-"
    ) as temporary_dir:
        staging_dir = Path(temporary_dir)
        staged_packages = [
            build_plugin_package(source.source_dir, staging_dir) for source in sources
        ]
        if len(staged_packages) != len(sources):
            raise RuntimeError("Not every plugin source produced a package.")

        for stale_package in output_dir.glob("*.atplugin"):
            stale_package.unlink()

        packages = []
        for staged_package in staged_packages:
            destination = output_dir / staged_package.name
            os.replace(staged_package, destination)
            packages.append(destination)

    return tuple(packages)
