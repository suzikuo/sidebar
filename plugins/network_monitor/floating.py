"""One configurable always-on-top widget for system and V2Ray traffic."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
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
        self._latest_snapshot = None
        self._display_mode = "proxy_direct"
        self._show_v2ray_metadata = False
        self._layout_mode = "single"
        self._scale = 100
        self._font_size = 11
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.setFixedSize(300, 34)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 3, 8, 3)
        root.setSpacing(1)
        line = QWidget(self)
        self._rate_layout = QGridLayout(line)
        self._rate_layout.setContentsMargins(0, 0, 0, 0)
        self._rate_layout.setHorizontalSpacing(3)
        self._rate_layout.setVerticalSpacing(0)

        self.system_title_label = self._title_label("系统", "#D7DEE8")
        self.system_upload_label = self._rate_label()
        self.system_download_label = self._rate_label()
        self.system_separator = self._separator()

        self.proxy_title_label = self._title_label("代理", "#5DB8FF")
        self.proxy_upload_label = self._rate_label()
        self.proxy_download_label = self._rate_label()
        self.proxy_separator = self._separator()
        self.direct_title_label = self._title_label("直连", "#FFB454")
        self.direct_upload_label = self._rate_label()
        self.direct_download_label = self._rate_label()

        root.addWidget(line)
        self.v2ray_metadata_label = QLabel("", self)
        self.v2ray_metadata_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.v2ray_metadata_label.setStyleSheet(
            "color: #AEB8C5; font-size: 9px; font-weight: 500;"
        )
        self.v2ray_metadata_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.v2ray_metadata_label.hide()
        root.addWidget(self.v2ray_metadata_label)

        self._groups = {
            "system": (
                self.system_title_label,
                self.system_upload_label,
                self.system_download_label,
            ),
            "proxy": (
                self.proxy_title_label,
                self.proxy_upload_label,
                self.proxy_download_label,
            ),
            "direct": (
                self.direct_title_label,
                self.direct_upload_label,
                self.direct_download_label,
            ),
        }
        self._layout_widgets = (
            (
                self.system_title_label,
                self.system_upload_label,
                self.system_download_label,
                self.system_separator,
            ),
            (
                self.proxy_title_label,
                self.proxy_upload_label,
                self.proxy_download_label,
                self.proxy_separator,
            ),
            (
                self.direct_title_label,
                self.direct_upload_label,
                self.direct_download_label,
                None,
            ),
        )
        self._apply_layout_mode()
        self._apply_group_visibility()

        self._render_rates()

    def _title_label(self, title, color):
        title_label = QLabel(title, self)
        title_label.setFixedWidth(30)
        title_label.setProperty("trafficColor", color)
        title_label.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: 700;"
        )
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._add_text_shadow(title_label)
        self._text_labels.append(title_label)
        return title_label

    def _rate_label(self):
        label = QLabel("--", self)
        label.setFixedWidth(50)
        label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setStyleSheet("font-size: 11px; font-weight: 600;")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._add_text_shadow(label)
        self._text_labels.append(label)
        return label

    def _separator(self):
        separator = QFrame(self)
        separator.setFixedSize(1, 18)
        separator.setStyleSheet("background: rgba(255, 255, 255, 70);")
        separator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return separator

    @staticmethod
    def _add_text_shadow(widget):
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(5)
        shadow.setOffset(0, 1)
        shadow.setColor(QColor(0, 0, 0, 220))
        widget.setGraphicsEffect(shadow)

    def set_snapshot(self, snapshot):
        self._latest_snapshot = snapshot
        self._render_rates()

    def _render_rates(self):
        system = None if self._latest_snapshot is None else self._latest_snapshot.system
        proxy = None if self._latest_snapshot is None else self._latest_snapshot.proxy
        direct = None if self._latest_snapshot is None else self._latest_snapshot.direct
        self._set_rate_label(
            self.system_upload_label,
            "↑",
            "#29A8FF",
            None if system is None else system.upload_bytes_per_second,
        )
        self._set_rate_label(
            self.system_download_label,
            "↓",
            "#5CD46A",
            None if system is None else system.download_bytes_per_second,
        )
        self._set_rate_label(
            self.proxy_upload_label,
            "↑",
            "#29A8FF",
            None if proxy is None else proxy.upload_bytes_per_second,
        )
        self._set_rate_label(
            self.proxy_download_label,
            "↓",
            "#5CD46A",
            None if proxy is None else proxy.download_bytes_per_second,
        )
        self._set_rate_label(
            self.direct_upload_label,
            "↑",
            "#29A8FF",
            None if direct is None else direct.upload_bytes_per_second,
        )
        self._set_rate_label(
            self.direct_download_label,
            "↓",
            "#5CD46A",
            None if direct is None else direct.download_bytes_per_second,
        )
        self._render_v2ray_metadata()

    def _set_rate_label(self, label, arrow, arrow_color, value):
        label.setText(
            f'<span style="color:{arrow_color};">{arrow}</span>'
            f'<span style="color:{self._font_color};">{_format_rate(value)}</span>'
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
        self._display_mode = config.get("floating_display_mode", "proxy_direct")
        self._layout_mode = (
            "double" if config.get("floating_layout_mode") == "double" else "single"
        )
        self._scale = min(140, max(70, int(config.get("floating_scale", 100))))
        self._font_size = min(18, max(8, int(config.get("floating_font_size", 11))))
        self._show_v2ray_metadata = bool(
            config.get("floating_show_v2ray_metadata", False)
        )
        self._apply_text_metrics()
        self._apply_group_visibility()
        self._render_rates()
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

    def _apply_group_visibility(self):
        visible = {
            "proxy_direct": ("proxy", "direct"),
            "system_direct": ("system", "direct"),
            "system_proxy": ("system", "proxy"),
            "system_proxy_direct": ("system", "proxy", "direct"),
        }.get(self._display_mode, ("proxy", "direct"))
        for name, widgets in self._groups.items():
            for widget in widgets:
                widget.setVisible(name in visible)
        self.system_separator.setVisible("system" in visible and len(visible) > 1)
        self.proxy_separator.setVisible(
            "proxy" in visible and visible[-1] != "proxy"
        )
        metadata_visible = self._show_v2ray_metadata and "proxy" in visible
        self.v2ray_metadata_label.setVisible(metadata_visible)
        self._apply_layout_mode()
        if self._layout_mode == "double":
            base_width = 300 if len(visible) == 3 else 210
        else:
            base_width = 438 if len(visible) == 3 else 300
        base_height = 52 if self._layout_mode == "double" else 34
        if metadata_visible:
            base_width = max(300, base_width)
            base_height += 16
        factor = self._layout_factor()
        self.setFixedSize(
            max(210, round(base_width * factor)),
            max(24, round(base_height * factor)),
        )

    def _apply_layout_mode(self):
        while self._rate_layout.count():
            self._rate_layout.takeAt(0)
        column = 0
        for title, upload, download, separator in self._layout_widgets:
            if self._layout_mode == "double":
                self._rate_layout.addWidget(
                    title,
                    0,
                    column,
                    2,
                    1,
                    Qt.AlignmentFlag.AlignVCenter,
                )
                self._rate_layout.addWidget(upload, 0, column + 1)
                self._rate_layout.addWidget(download, 1, column + 1)
                column += 2
                if separator is not None:
                    self._rate_layout.addWidget(separator, 0, column, 2, 1)
                    column += 1
            else:
                self._rate_layout.addWidget(title, 0, column)
                self._rate_layout.addWidget(upload, 0, column + 1)
                self._rate_layout.addWidget(download, 0, column + 2)
                column += 3
                if separator is not None:
                    self._rate_layout.addWidget(separator, 0, column)
                    column += 1

    def _apply_text_metrics(self):
        factor = self._layout_factor()
        for title in (
            self.system_title_label,
            self.proxy_title_label,
            self.direct_title_label,
        ):
            title.setFixedWidth(max(24, round(30 * factor)))
            title.setStyleSheet(
                f"color: {title.property('trafficColor')}; "
                f"font-size: {self._font_size}px; font-weight: 700;"
            )
        for label in (
            self.system_upload_label,
            self.system_download_label,
            self.proxy_upload_label,
            self.proxy_download_label,
            self.direct_upload_label,
            self.direct_download_label,
        ):
            label.setFixedWidth(max(38, round(50 * factor)))
            label.setStyleSheet(
                f"font-size: {self._font_size}px; font-weight: 600;"
            )
        separator_height = max(14, round(18 * factor))
        self.system_separator.setFixedHeight(separator_height)
        self.proxy_separator.setFixedHeight(separator_height)
        self.v2ray_metadata_label.setStyleSheet(
            f"color: #AEB8C5; font-size: {max(8, self._font_size - 2)}px; "
            "font-weight: 500;"
        )

    def _render_v2ray_metadata(self):
        snapshot = self._latest_snapshot
        node = getattr(snapshot, "v2ray_node", None) if snapshot is not None else None
        latency = (
            getattr(snapshot, "v2ray_latency_ms", None)
            if snapshot is not None
            else None
        )
        route = getattr(snapshot, "v2ray_route", None) if snapshot is not None else None
        latency_text = "--" if latency is None else f"{latency:.0f} ms"
        self.v2ray_metadata_label.setText(
            f"节点 {node or '--'}  ·  延迟 {latency_text}  ·  路由 {route or '--'}"
        )
        self.v2ray_metadata_label.setToolTip(self.v2ray_metadata_label.text())

    def _layout_factor(self):
        return max(self._scale / 100.0, self._font_size / 11.0)

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
    for unit in ("B", "K", "M", "G"):
        if value < 1024.0 or unit == "G":
            precision = 0 if unit == "B" else 1
            return f"{value:.{precision}f}{unit}"
        value /= 1024.0
    return "0B"


__all__ = ["FloatingNetworkWidget"]
