import json
import os
from typing import Any


class DesignTokens:
    """Standardized tokens (colors, sizes, etc.) for UI consistency."""

    DEFAULT_TOKENS = {
        "colors": {
            "primary": "#0078D4",
            "background": "#F3F3F3",
            "surface": "#FFFFFF",
            "text": "#323130",
            "border": "#EDEBE9",
            "danger": "#D83B01",
            "glass_background": "rgba(243, 243, 243, 200)",
            "glass_border": "rgba(255, 255, 255, 100)",
            # Dark theme for sidebar (matching reference)
            "sidebar_bg": "#2B2B2B",
            "sidebar_icon": "#FFFFFF",
            "sidebar_icon_hover": "#E0E0E0",
            "sidebar_active_bg": "rgba(255, 192, 203, 0.25)",  # Pink highlight
            "card_bg_dark": "rgba(30, 30, 30, 0.95)",
        },
        "sizing": {"radius": "8px", "padding": "12px", "card_min_height": "100px"},
    }

    def __init__(self, token_file: str = None):
        self.tokens = self.DEFAULT_TOKENS
        if token_file and os.path.exists(token_file):
            self._load(token_file)

    def _load(self, path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.tokens.update(json.load(f))
        except Exception as e:
            print(f"Error loading tokens: {e}")

    def get(self, path: str, default: Any = None) -> Any:
        # Simple path resolver (e.g. "colors.primary")
        keys = path.split(".")
        val = self.tokens
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val
