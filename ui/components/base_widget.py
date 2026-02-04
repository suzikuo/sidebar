from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QWidget

from core.ui_kernel.theme_engine import ThemeEngine


class BaseWidget(QWidget):
    """
    Base class for all custom widgets to ensure theme consistency.
    """

    def __init__(self, theme_engine: ThemeEngine, parent=None):
        super().__init__(parent)
        self.theme_engine = theme_engine
        self.apply_style()

    def apply_style(self):
        # Default implementation, subclasses will override/extend
        pass


class BScrollArea(QScrollArea):
    def __init__(self, /, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.viewport().setAttribute(Qt.WA_TranslucentBackground)
        self.viewport().setAttribute(Qt.WA_NoSystemBackground)
        self.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #888;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #666;
            }
            QScrollBar::handle:vertical:pressed {
                background: #444;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
