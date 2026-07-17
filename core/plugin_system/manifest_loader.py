import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from core.logger import logger
from core.plugin_system.plugin_manifest import (
    PluginManifest,
    PluginManifestError,
    parse_manifest,
)
from core.plugin_system.plugin_integrity import validate_plugin_directory


class ManifestLoader:
    """Scans and validates plugin manifest.json files."""

    @classmethod
    def _validate(cls, manifest: Any, plugin_dir: str) -> PluginManifest:
        normalized = parse_manifest(manifest)
        plugin_root = Path(plugin_dir).resolve()
        entry_path = plugin_root.joinpath(*normalized.entry.split("/")).resolve()
        try:
            entry_path.relative_to(plugin_root)
        except ValueError as error:
            raise PluginManifestError(
                "INVALID_ENTRY",
                "Plugin entry resolves outside the plugin directory.",
                field="entry",
            ) from error

        if not entry_path.is_file():
            raise PluginManifestError(
                "ENTRY_NOT_FOUND",
                "Plugin entry file does not exist.",
                field="entry",
            )

        validate_plugin_directory(plugin_root, normalized)

        return normalized

    @classmethod
    def load_with_model_or_raise(
        cls, plugin_dir: str
    ) -> tuple[Dict[str, Any], PluginManifest]:
        manifest_path = os.path.join(plugin_dir, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        normalized = cls._validate(manifest, plugin_dir)
        return manifest, normalized

    @classmethod
    def load_with_model(
        cls,
        plugin_dir: str,
        *,
        log_errors: bool = True,
    ) -> Optional[tuple[Dict[str, Any], PluginManifest]]:
        """Load raw compatibility data and its normalized typed model once."""

        manifest_path = os.path.join(plugin_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            return None

        try:
            return cls.load_with_model_or_raise(plugin_dir)
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
