"""Explicit access to host services needed by legacy UI and plugins."""

import sys
from typing import Any


_application: Any | None = None
_MISSING = object()
_legacy_main_module: Any | None = None
_legacy_main_previous: Any = _MISSING


def _publish_legacy_main_application(application: Any) -> None:
    global _legacy_main_module, _legacy_main_previous

    main_module = sys.modules.get("__main__")
    if main_module is None:
        return
    if _legacy_main_module is None:
        _legacy_main_module = main_module
        _legacy_main_previous = getattr(main_module, "app_instance", _MISSING)
    setattr(main_module, "app_instance", application)


def _clear_legacy_main_application(application: Any) -> None:
    global _legacy_main_module, _legacy_main_previous

    main_module = _legacy_main_module
    previous = _legacy_main_previous
    _legacy_main_module = None
    _legacy_main_previous = _MISSING
    if (
        main_module is None
        or getattr(main_module, "app_instance", _MISSING) is not application
    ):
        return
    if previous is _MISSING or previous is application:
        delattr(main_module, "app_instance")
    else:
        setattr(main_module, "app_instance", previous)


def register_application(application: Any) -> None:
    global _application
    if _application is not None and _application is not application:
        raise RuntimeError("An Agile Tiles application is already registered")
    _application = application
    _publish_legacy_main_application(application)


def get_application() -> Any:
    if _application is None:
        raise RuntimeError("The Agile Tiles application is not available")
    return _application


def clear_application(application: Any) -> None:
    global _application
    if _application is application:
        _application = None
        _clear_legacy_main_application(application)
