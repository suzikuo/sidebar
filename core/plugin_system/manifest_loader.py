import json
import os
from typing import Any, Dict, Optional


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
                    print(
                        f"Manifest at {plugin_dir} is missing required field: {field}"
                    )
                    return None

            return manifest
        except Exception as e:
            print(f"Failed to parse manifest at {plugin_dir}: {e}")
            return None
