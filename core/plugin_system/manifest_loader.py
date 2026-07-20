from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from core.logger import logger
from core.plugin_system.plugin_manifest import (
    PluginManifest,
    PluginManifestError,
    parse_manifest,
)
from core.plugin_system.plugin_integrity import (
    build_plugin_file_hashes,
    validate_plugin_directory,
)


class ManifestLoader:
    """Scans and validates plugin manifest.json files."""

    @classmethod
    def _validate(
        cls,
        manifest: Any,
        plugin_dir: str,
        *,
        allow_unsealed: bool = False,
    ) -> tuple[Dict[str, Any], PluginManifest]:
        if (
            allow_unsealed
            and isinstance(manifest, dict)
            and manifest.get("manifest_version") == 2
            and manifest.get("files") == {}
        ):
            manifest = deepcopy(manifest)
            manifest["files"] = build_plugin_file_hashes(plugin_dir)
            for native_module in manifest.get("native_modules", []):
                if not isinstance(native_module, dict):
                    continue
                path = str(native_module.get("path") or "").replace("\\", "/")
                digest = manifest["files"].get(path)
                if digest:
                    native_module["sha256"] = digest

        normalized = parse_manifest(manifest)
        plugin_root = Path(plugin_dir).resolve()
        # Do not resolve the child independently. Microsoft Store Python can
        # virtualize an AppData child to LocalCache while leaving its existing
        # parent on the logical Roaming path. parse_manifest already guarantees
        # a safe relative entry, and directory integrity rejects links.
        entry_path = plugin_root.joinpath(*normalized.entry.split("/"))

        if not entry_path.is_file():
            raise PluginManifestError(
                "ENTRY_NOT_FOUND",
                "Plugin entry file does not exist.",
                field="entry",
            )

        validate_plugin_directory(plugin_root, normalized)

        return manifest, normalized

    @classmethod
    def load_with_model_or_raise(
        cls,
        plugin_dir: str,
        *,
        allow_unsealed: bool = False,
    ) -> tuple[Dict[str, Any], PluginManifest]:
        manifest_path = os.path.join(plugin_dir, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        return cls._validate(
            manifest,
            plugin_dir,
            allow_unsealed=allow_unsealed,
        )

    @classmethod
    def load_with_model(
        cls,
        plugin_dir: str,
        *,
        log_errors: bool = True,
        allow_unsealed: bool = False,
    ) -> Optional[tuple[Dict[str, Any], PluginManifest]]:
        """Load raw compatibility data and its normalized typed model once."""

        manifest_path = os.path.join(plugin_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            return None

        try:
            return cls.load_with_model_or_raise(
                plugin_dir,
                allow_unsealed=allow_unsealed,
            )
        except PluginManifestError as error:
            if log_errors:
                logger.error(
                    "Invalid manifest at %s [%s]: %s",
                    plugin_dir,
                    error.code,
                    error,
                )
            return None
        except Exception as error:
            if log_errors:
                logger.error(
                    "Failed to parse manifest at %s: %s",
                    plugin_dir,
                    error,
                    exc_info=True,
                )
            return None

    @classmethod
    def load(cls, plugin_dir: str) -> Optional[Dict[str, Any]]:
        loaded = cls.load_with_model(plugin_dir)
        return loaded[0] if loaded else None

    @classmethod
    def load_model(cls, plugin_dir: str) -> Optional[PluginManifest]:
        loaded = cls.load_with_model(plugin_dir)
        return loaded[1] if loaded else None
