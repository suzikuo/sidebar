"""High-DPI display scaling configured before Qt is imported."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import MutableMapping


AUTO_UI_SCALE = "auto"
UI_SCALE_VALUES = (AUTO_UI_SCALE, "100", "125", "150", "175", "200")
UI_SCALE_FACTORS = {
    "100": "1",
    "125": "1.25",
    "150": "1.5",
    "175": "1.75",
    "200": "2",
}

_MANAGED_SCALE_ENV = "AGILE_TILES_MANAGED_QT_SCALE"
_QT_SCALE_ENV = "QT_SCALE_FACTOR"
_QT_ROUNDING_POLICY_ENV = "QT_SCALE_FACTOR_ROUNDING_POLICY"


def normalize_ui_scale(value: object) -> str:
    """Return a supported scale value, defaulting to system-managed scaling."""
    normalized = str(value).strip().lower() if value is not None else AUTO_UI_SCALE
    return normalized if normalized in UI_SCALE_VALUES else AUTO_UI_SCALE


def _read_ui_scale_from_file(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    settings = payload.get("settings")
    if not isinstance(settings, dict):
        return None
    appearance = settings.get("appearance")
    if not isinstance(appearance, dict) or "ui_scale" not in appearance:
        return None
    return normalize_ui_scale(appearance["ui_scale"])


def read_ui_scale_setting(state_path: str | Path) -> str:
    """Read the saved scale without constructing the Qt-dependent settings stack."""
    path = Path(state_path)
    for candidate in (path, Path(f"{path}.bak")):
        scale = _read_ui_scale_from_file(candidate)
        if scale is not None:
            return scale
    return AUTO_UI_SCALE


def apply_ui_scale(
    scale: object,
    environ: MutableMapping[str, str] | None = None,
) -> str:
    """Apply the selected scale to the environment inherited by Qt."""
    env = os.environ if environ is None else environ
    normalized = normalize_ui_scale(scale)

    if normalized == AUTO_UI_SCALE:
        if env.get(_MANAGED_SCALE_ENV):
            env.pop(_QT_SCALE_ENV, None)
            env.pop(_QT_ROUNDING_POLICY_ENV, None)
        env.pop(_MANAGED_SCALE_ENV, None)
        return normalized

    env[_QT_SCALE_ENV] = UI_SCALE_FACTORS[normalized]
    env[_QT_ROUNDING_POLICY_ENV] = "PassThrough"
    env[_MANAGED_SCALE_ENV] = normalized
    return normalized


def configure_ui_scale(
    state_path: str | Path,
    environ: MutableMapping[str, str] | None = None,
) -> str:
    """Load and apply the display scale before QApplication is created."""
    return apply_ui_scale(read_ui_scale_setting(state_path), environ)
