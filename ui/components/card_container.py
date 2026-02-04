from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QVBoxLayout, QWidget

from core.ui_kernel.theme_engine import ThemeEngine
from ui.components.base_widget import BaseWidget


class CardContainer(BaseWidget):
    """
    Unified envelope for plugin cards.
    Handles borders, shadows, and spacing.
    """

    def __init__(self, content_widget: QWidget, theme_engine: ThemeEngine, parent=None):
        super().__init__(theme_engine, parent)
        self.setObjectName("CardContainer")
        self.content_widget = content_widget

        # Main Layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)  # Space for shadow

        # The actual card frame
        self.frame = QFrame()
        self.frame.setObjectName("CardEnvelope")
        self.frame_layout = QVBoxLayout(self.frame)
        self.frame_layout.setContentsMargins(0, 0, 0, 0)
        self.frame_layout.addWidget(content_widget)

        self.main_layout.addWidget(self.frame)

        # Apply Shadow
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(20)
        self.shadow.setXOffset(0)
        self.shadow.setYOffset(4)
        self.shadow.setColor(Qt.black)  # Theme engine will update this
        self.frame.setGraphicsEffect(self.shadow)

        self.apply_style()

    def get_content(self) -> QWidget:
        return self.content_widget

    def apply_style(self):
        # Use theme engine tokens with correct path-based keys
        qss = f"""
        #CardEnvelope {{
            background-color: {self.theme_engine.tokens.get("colors.surface", "#FFFFFF")};
            border: 1px solid {self.theme_engine.tokens.get("colors.border", "#E0E0E0")};
            border-radius: 12px;
        }}
        """
        self.setStyleSheet(qss)

        # Update shadow color from theme if available
        if hasattr(self, "shadow"):
            # Note: DesignTokens doesn't have a shadow_color by default, using fallback
            shadow_hex = self.theme_engine.tokens.get("colors.border", "#000000")
            from PySide6.QtGui import QColor

            self.shadow.setColor(QColor(shadow_hex))
