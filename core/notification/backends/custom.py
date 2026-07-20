"""Application-owned floating notification cards."""

from __future__ import annotations

from collections import OrderedDict, deque

from PySide6.QtCore import (
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    Signal,
    QObject,
)
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import FluentIcon

from core.notification.backends.base import NotificationCapabilities
from core.notification.models import (
    NotificationLevel,
    NotificationPresentation,
    NotificationRequest,
)


class CustomToastBackend(QObject):
    name = "custom"
    capabilities = NotificationCapabilities(actions=True, progress=True, sensitive=True)
    activated = Signal(str)
    action_triggered = Signal(str, str)
    dismissed = Signal(str)

    def __init__(self, *, screen_provider=None, max_visible=3):
        super().__init__()
        self._screen_provider = screen_provider
        self._max_visible = max(1, min(int(max_visible), 5))
        self._visible = OrderedDict()
        self._pending = deque()
        self._closed = False

    def is_available(self):
        return not self._closed and QGuiApplication.instance() is not None

    def show(self, request: NotificationRequest):
        if request.notification_id in self._visible:
            self.update(request)
            return
        if len(self._visible) >= self._max_visible:
            self._pending.append(request)
            return
        card = _ToastCard(request)
        card.dismissed.connect(self._dismiss_card)
        card.activated.connect(self.activated)
        card.action_triggered.connect(self.action_triggered)
        self._visible[request.notification_id] = card
        card.show()
        self._layout_cards(animate_new=card)

    def update(self, request: NotificationRequest):
        card = self._visible.get(request.notification_id)
        if card is not None:
            card.apply_request(request)
            return True
        for index, pending in enumerate(self._pending):
            if pending.notification_id == request.notification_id:
                self._pending[index] = request
                return True
        return False

    def dismiss(self, notification_id: str):
        card = self._visible.get(notification_id)
        if card is not None:
            card.dismiss(animated=False)
            return True
        for pending in tuple(self._pending):
            if pending.notification_id == notification_id:
                self._pending.remove(pending)
                return True
        return False

    def shutdown(self):
        self._closed = True
        self._pending.clear()
        for card in tuple(self._visible.values()):
            card.dismiss(animated=False)
        self._visible.clear()

    def _dismiss_card(self, notification_id):
        card = self._visible.pop(notification_id, None)
        if card is not None:
            card.deleteLater()
            self.dismissed.emit(notification_id)
        self._promote_pending()
        self._layout_cards()

    def _promote_pending(self):
        while self._pending and len(self._visible) < self._max_visible and not self._closed:
            self.show(self._pending.popleft())

    def _layout_cards(self, *, animate_new=None):
        screen = self._screen_provider() if self._screen_provider else QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        bottom = available.bottom() - 18
        for card in reversed(tuple(self._visible.values())):
            card.adjustSize()
            target = QRect(available.right() - card.width() - 18, bottom - card.height() + 1, card.width(), card.height())
            bottom = target.top() - 10
            card.move_to(target, animate=card is animate_new)


class _ToastCard(QFrame):
    dismissed = Signal(str)
    activated = Signal(str)
    action_triggered = Signal(str, str)

    _COLORS = {
        NotificationLevel.INFO: "#4A90E2",
        NotificationLevel.SUCCESS: "#3DAA72",
        NotificationLevel.WARNING: "#D9912B",
        NotificationLevel.ERROR: "#D45454",
    }

    def __init__(self, request):
        super().__init__(None)
        self._request = request
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._animation = None
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        # The default is opaque.  ``apply_request`` enables native window
        # translucency only when a caller explicitly requests it.
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(368)
        self.setObjectName("CustomToastCard")
        self._build_ui()
        self.apply_request(request)

    def _build_ui(self):
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 135))
        self.setGraphicsEffect(shadow)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 14, 10, 14)
        outer.setSpacing(12)
        self.icon = QLabel(self)
        self.icon.setFixedSize(24, 24)
        outer.addWidget(self.icon, 0, Qt.AlignTop)
        content = QVBoxLayout()
        content.setSpacing(5)
        self.title = QLabel(self)
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 14px; font-weight: 600; letter-spacing: 0.2px;")
        self.message = QLabel(self)
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #B9C1CC; font-size: 13px;")
        self.progress = QProgressBar(self)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.hide()
        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 2, 0, 0)
        content.addWidget(self.title)
        content.addWidget(self.message)
        content.addWidget(self.progress)
        content.addLayout(self.actions)
        outer.addLayout(content, 1)
        self.close_button = QPushButton("×", self)
        self.close_button.setFixedSize(26, 26)
        self.close_button.setText("\N{MULTIPLICATION SIGN}")
        self.close_button.setToolTip("Dismiss notification")
        self.close_button.clicked.connect(self.dismiss)
        outer.addWidget(self.close_button, 0, Qt.AlignTop)

    def apply_request(self, request):
        self._request = request
        is_compact = request.presentation is NotificationPresentation.COMPACT
        self.setFixedWidth(
            320
            if is_compact
            else 392
            if request.presentation is NotificationPresentation.DETAILED
            else 368
        )
        # Opaque by default; callers may opt into a translucent card through
        # NotificationRequest.transparent_background.
        self.setAttribute(Qt.WA_TranslucentBackground, request.transparent_background)
        background_alpha = 190 if request.transparent_background else 255
        border_alpha = 104 if request.transparent_background else 190
        self.setStyleSheet(
            f"#CustomToastCard {{ background: rgba(24, 27, 34, {background_alpha}); "
            f"border: 1px solid rgba(255, 255, 255, {border_alpha}); border-radius: 14px; }}"
            "QLabel { color: #F5F7FA; } "
            "QPushButton { color: #D7E3FF; border: 0; border-radius: 6px; padding: 3px 6px; } "
            "QPushButton:hover { background: rgba(255,255,255,22); }"
        )
        self.title.setText(request.title)
        self.message.setText(request.message)
        self.message.setVisible(not is_compact and bool(request.message))
        color = self._COLORS[request.level]
        self.icon.setPixmap(_icon_for(request.level).icon().pixmap(22, 22))
        self.progress.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}")
        if request.progress is None:
            self.progress.hide()
        else:
            self.progress.setValue(request.progress.value)
            self.progress.setVisible(not is_compact)
        while self.actions.count():
            item = self.actions.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for action in request.actions:
            button = QPushButton(action.text, self)
            button.setProperty("notification_action_id", action.action_id)
            button.clicked.connect(
                lambda _=False, action_id=action.action_id: self._emit_action(action_id)
            )
            self.actions.addWidget(button)
        self.actions.addStretch()
        if request.duration_ms is None:
            self._timer.stop()
        else:
            self._timer.start(request.duration_ms)

    def move_to(self, target, *, animate=False):
        if not animate:
            self.setGeometry(target)
            return
        start = QRect(target)
        start.moveLeft(target.left() + 28)
        self.setGeometry(start)
        self.setWindowOpacity(0.0)
        self._animation = QParallelAnimationGroup(self)
        geometry = QPropertyAnimation(self, b"geometry", self._animation)
        geometry.setDuration(180)
        geometry.setStartValue(start)
        geometry.setEndValue(target)
        opacity = QPropertyAnimation(self, b"windowOpacity", self._animation)
        opacity.setDuration(180)
        opacity.setStartValue(0.0)
        opacity.setEndValue(1.0)
        self._animation.addAnimation(geometry)
        self._animation.addAnimation(opacity)
        self._animation.start()

    def enterEvent(self, event):
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._request.duration_ms is not None:
            self._timer.start(self._request.duration_ms)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        target = self.childAt(event.position().toPoint())
        if event.button() == Qt.LeftButton and not isinstance(target, QPushButton):
            self.activated.emit(self._request.notification_id)
        super().mouseReleaseEvent(event)

    def dismiss(self, animated=True):
        self._timer.stop()
        self.hide()
        self.dismissed.emit(self._request.notification_id)

    def _emit_action(self, action_id):
        self.action_triggered.emit(self._request.notification_id, action_id)


def _icon_for(level):
    return {
        NotificationLevel.INFO: FluentIcon.INFO,
        NotificationLevel.SUCCESS: FluentIcon.ACCEPT,
        NotificationLevel.WARNING: FluentIcon.INFO,
        NotificationLevel.ERROR: FluentIcon.CLOSE,
    }[level]
