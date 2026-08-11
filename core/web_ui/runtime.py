"""Small, read-only checks for the Windows WebView2 Evergreen Runtime."""

from __future__ import annotations

import os
import sys
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _runtime_roots() -> tuple[Path, ...]:
    if sys.platform != "win32":
        return ()

    roots = []
    for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value) / "Microsoft" / "EdgeWebView" / "Application")
    return tuple(dict.fromkeys(roots))


def detect_webview2_runtime() -> dict[str, str | bool | None]:
    """Return local runtime availability without starting a process or network request."""
    if sys.platform != "win32":
        return {"available": False, "version": None, "path": None}

    candidates: list[tuple[tuple[int, ...], Path]] = []
    for root in _runtime_roots():
        try:
            children = tuple(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or not (child / "msedgewebview2.exe").is_file():
                continue
            try:
                version = tuple(int(part) for part in child.name.split("."))
            except ValueError:
                version = ()
            candidates.append((version, child))

    if not candidates:
        return {"available": False, "version": None, "path": None}

    _, selected = max(candidates, key=lambda item: item[0])
    return {
        "available": True,
        "version": selected.name,
        "path": str(selected / "msedgewebview2.exe"),
    }


def missing_runtime_message() -> str:
    return (
        "Microsoft Edge WebView2 Runtime is required for this web interface. "
        "Install the Evergreen Runtime and reopen Agile Tiles."
    )


def ensure_native_qwebview_available() -> None:
    """Fail with an actionable message when the source environment is too old."""
    module = import_module("PySide6.QtWebView")
    if hasattr(module, "QWebView") and hasattr(module, "QWebViewSettings"):
        return
    try:
        installed = version("PySide6")
    except PackageNotFoundError:
        installed = "not installed"
    raise RuntimeError(
        "Native QWebView requires PySide6 6.11.1 or newer; "
        f"the current environment provides {installed}. "
        "Run 'python -m pip install -r requirements.txt' and restart Agile Tiles."
    )


__all__ = [
    "detect_webview2_runtime",
    "ensure_native_qwebview_available",
    "missing_runtime_message",
]
