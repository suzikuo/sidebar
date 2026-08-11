"""Compatibility aliases for UI plugins installed before the UI kernel move."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType


LEGACY_UI_MODULE_ALIASES = {
    "ui": "core.ui_kernel",
    "ui.components": "core.ui_kernel.components",
    "ui.components.base_widget": "core.ui_kernel.components.base_widget",
}


def install_legacy_ui_module_aliases() -> dict[str, ModuleType]:
    """Expose the former UI namespace without loading duplicate implementations."""
    installed = {
        legacy_name: importlib.import_module(current_name)
        for legacy_name, current_name in LEGACY_UI_MODULE_ALIASES.items()
    }
    for legacy_name, current_module in installed.items():
        existing_module = sys.modules.get(legacy_name)
        if existing_module is not None and existing_module is not current_module:
            raise ImportError(
                f"Legacy UI module namespace is already occupied: {legacy_name}"
            )

    for legacy_name, current_module in installed.items():
        sys.modules[legacy_name] = current_module
    return installed
