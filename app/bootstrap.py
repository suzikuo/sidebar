"""Process and Qt bootstrap for the desktop application."""

import sys
from collections.abc import Sequence

from core.data_layer.path_utils import PathManager
from core.display_scaling import configure_ui_scale
from core.process_control import (
    ProcessControlError,
    extract_wait_for_pid,
    wait_for_process_exit,
)


def _prepare_arguments(argv: Sequence[str]) -> list[str]:
    wait_for_pid, cleaned_argv = extract_wait_for_pid(argv)
    if wait_for_pid is not None and not wait_for_process_exit(wait_for_pid):
        raise ProcessControlError(
            "WAIT_PROCESS_TIMEOUT",
            "The previous Agile Tiles process did not exit within 60 seconds.",
        )
    return cleaned_argv


def main(argv: Sequence[str] | None = None) -> int:
    """Create QApplication before importing the UI composition root."""

    raw_argv = list(sys.argv if argv is None else argv)
    try:
        qt_argv = _prepare_arguments(raw_argv)
    except ProcessControlError as error:
        print(f"Agile Tiles restart error [{error.code}]: {error}", file=sys.stderr)
        return 2

    if argv is None:
        sys.argv[:] = qt_argv

    configure_ui_scale(PathManager.get_config_path("state.json"))

    # Qt WebView must be initialized before QApplication creates its GUI context.
    from PySide6.QtWebView import QtWebView
    from PySide6.QtWidgets import QApplication

    QtWebView.initialize()
    qt_app = QApplication.instance() or QApplication(qt_argv)
    qt_app.setQuitOnLastWindowClosed(False)

    from app.application import AgileTilesApplication

    application = AgileTilesApplication(qt_app)
    return application.run()
