"""Transparent always-on-top proxy and direct traffic widget."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGridLayout,
    QLabel,
    QWidget,
)


class FloatingNetworkWidget(QWidget):
    position_changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_offset = None
        self._is_locked = False
        self._position_initialized = False
        self._background_color = QColor(0, 0, 0, 0)
        self._font_color = "#FFFFFF"
        self._text_labels = []
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.setFixedSize(246, 54)

        layout = QGridLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setHorizontalSpacing(4)
        layout.setVerticalSpacing(2)

        self.proxy_upload_label, self.proxy_download_label = self._add_rate_row(
            layout,
            row=0,
            title="代理",
            title_color="#5DB8FF",
        )
        self.direct_upload_label, self.direct_download_label = self._add_rate_row(
            layout,
            row=1,
            title="直连",
            title_color="#F2F5F8",
        )

    def _add_rate_row(self, layout, *, row, title, title_color):
        title_label = QLabel(title, self)
        title_label.setFixedWidth(30)
        title_label.setStyleSheet(
            f"color: {title_color}; font-size: 12px; font-weight: 700;"
        )

        upload_arrow = QLabel("↑", self)
        upload_arrow.setStyleSheet(
            "color: #29A8FF; font-size: 13px; font-weight: 700;"
        )
        upload_arrow.setFixedWidth(12)
        upload_value = self._value_label()

        download_arrow = QLabel("↓", self)
        download_arrow.setStyleSheet(
            "color: #5CD46A; font-size: 13px; font-weight: 700;"
        )
        download_arrow.setFixedWidth(12)
        download_value = self._value_label()

        widgets = (
            title_label,
            upload_arrow,
            upload_value,
            download_arrow,
            download_value,
        )
        for column, widget in enumerate(widgets):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._add_text_shadow(widget)
            layout.addWidget(widget, row, column)
        self._text_labels.extend((title_label, upload_value, download_value))
        return upload_value, download_value

    def _value_label(self):
        label = QLabel("--", self)
        label.setFixedWidth(78)
        label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        label.setStyleSheet(
            "color: #FFFFFF; font-size: 12px; font-weight: 600;"
        )
        return label

    @staticmethod
    def _add_text_shadow(widget):
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(5)
        shadow.setOffset(0, 1)
        shadow.setColor(QColor(0, 0, 0, 220))
        widget.setGraphicsEffect(shadow)

    def set_snapshot(self, snapshot):
        self._set_rates(
            self.proxy_upload_label,
            self.proxy_download_label,
            snapshot.proxy,
        )
        self._set_rates(
            self.direct_upload_label,
            self.direct_download_label,
            snapshot.direct,
        )

    @staticmethod
    def _set_rates(upload_label, download_label, rates):
        upload_label.setText(
            _format_rate(None if rates is None else rates.upload_bytes_per_second)
        )
        download_label.setText(
            _format_rate(None if rates is None else rates.download_bytes_per_second)
        )

    def apply_config(self, config):
        locked = bool(config.get("floating_locked", False))
        if self._is_locked != locked:
            self._is_locked = locked
            self._drag_offset = None
            flags = self.windowFlags()
            if locked:
                flags |= Qt.WindowType.WindowTransparentForInput
            else:
                flags &= ~Qt.WindowType.WindowTransparentForInput
            self.setWindowFlags(flags)

        background = QColor(config.get("floating_background_color", "#202327"))
        background.setAlphaF(
            min(
                1.0,
                max(0.0, float(config.get("floating_background_opacity", 0)) / 100.0),
            )
        )
        self._background_color = background
        self._font_color = config.get("floating_font_color", "#FFFFFF")
        for label in self._text_labels:
            label.setStyleSheet(
                f"color: {self._font_color}; font-size: 12px; font-weight: 600;"
            )
        self.update()

        x = config.get("floating_x")
        y = config.get("floating_y")
        if isinstance(x, int) and isinstance(y, int):
            self._move_onto_screen(x, y)
            self._position_initialized = True
        elif not self._position_initialized:
            self._move_to_default_position()
            self._position_initialized = True

        if config.get("floating_enabled", False):
            self.show()
            self.raise_()
        else:
            self.hide()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._background_color.alpha() > 0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._background_color)
            painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 6, 6)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and not self._is_locked:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if (
            self._drag_offset is not None
            and not self._is_locked
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._drag_offset is not None:
            self.position_changed.emit(self.x(), self.y())
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _move_to_default_position(self):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.move(40, 40)
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 48)

    def _move_onto_screen(self, x, y):
        screens = QGuiApplication.screens()
        if not screens:
            self.move(x, y)
            return
        target = next(
            (
                screen.availableGeometry()
                for screen in screens
                if screen.availableGeometry().contains(QPoint(x, y))
            ),
            screens[0].availableGeometry(),
        )
        maximum_x = max(target.left(), target.right() - self.width() + 1)
        maximum_y = max(target.top(), target.bottom() - self.height() + 1)
        self.move(
            min(maximum_x, max(target.left(), x)),
            min(maximum_y, max(target.top(), y)),
        )


def _format_rate(value):
    if value is None:
        return "--"
    value = max(0.0, float(value))
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if value < 1024.0 or unit == "GB/s":
            precision = 0 if unit == "B/s" else 1
            return f"{value:.{precision}f}{unit}"
        value /= 1024.0
    return "0 B/s"


__all__ = ["FloatingNetworkWidget"]
