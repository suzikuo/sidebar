import json
import os
from typing import Any, Dict, Optional

from core.logger import logger


class ManifestLoader:
    """Scans and validates plugin manifest.json files."""

    REQUIRED_FIELDS = ["id", "name", "version", "entry", "class"]

    @staticmethod
    def load(plugin_dir: str) -> Optional[Dict[str, Any]]:
        manifest_path = os.path.join(plugin_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            return None

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # Basic validation
            for field in ManifestLoader.REQUIRED_FIELDS:
                if field not in manifest:
                    logger.error(
                        f"Manifest at {plugin_dir} is missing required field: {field}"
                    )
                    return None

            return manifest
        except Exception as e:
            logger.error(
                f"Failed to parse manifest at {plugin_dir}: {e}", exc_info=True
            )
            return None
