from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
)
from PySide6.QtWidgets import QWidget


class ViewTransitionController(QObject):
    """
    Manages transition effects between two views.
    Supports Slide, Fade, and Zoom (future).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration = 300
        self.easing = QEasingCurve.OutCubic

    def slide_transition(
        self, old_widget: QWidget, new_widget: QWidget, direction: str = "right"
    ):
        """
        Slides the new widget in and the old widget out.
        """
        if not old_widget or not new_widget:
            if new_widget:
                new_widget.show()
                new_widget.raise_()
            return None

        # Ensure they are visible for animation
        new_widget.show()
        new_widget.raise_()

        container_rect = new_widget.parent().rect()
        width = container_rect.width()

        # Start and End points
        offset = width if direction == "right" else -width

        new_start = QPoint(offset, 0)
        new_end = QPoint(0, 0)
        old_end = QPoint(-offset, 0)

        # Animations
        anim_new = QPropertyAnimation(new_widget, b"pos")
        anim_new.setDuration(self.duration)
        anim_new.setEasingCurve(self.easing)
        anim_new.setStartValue(new_start)
        anim_new.setEndValue(new_end)

        anim_old = QPropertyAnimation(old_widget, b"pos")
        anim_old.setDuration(self.duration)
        anim_old.setEasingCurve(self.easing)
        anim_old.setEndValue(old_end)

        group = QParallelAnimationGroup(self)
        group.addAnimation(anim_new)
        group.addAnimation(anim_old)

        group.finished.connect(lambda: old_widget.hide())
        group.start()
        return group

    def fade_transition(self, old_widget: QWidget, new_widget: QWidget):
        """
        Fades in the new widget and fades out the old one.
        """
        # Requires GraphicsOpacityEffect on both widgets
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        def get_opacity_effect(w):
            eff = w.graphicsEffect()
            if not isinstance(eff, QGraphicsOpacityEffect):
                eff = QGraphicsOpacityEffect(w)
                w.setGraphicsEffect(eff)
            return eff

        eff_new = get_opacity_effect(new_widget)
        eff_old = get_opacity_effect(old_widget) if old_widget else None

        new_widget.show()
        new_widget.raise_()

        anim_new = QPropertyAnimation(eff_new, b"opacity")
        anim_new.setDuration(self.duration)
        anim_new.setStartValue(0.0)
        anim_new.setEndValue(1.0)

        group = QParallelAnimationGroup(self)
        group.addAnimation(anim_new)

        if old_widget:
            anim_old = QPropertyAnimation(eff_old, b"opacity")
            anim_old.setDuration(self.duration)
            anim_old.setStartValue(1.0)
            anim_old.setEndValue(0.0)
            group.addAnimation(anim_old)
            group.finished.connect(lambda: old_widget.hide())

        group.start()
        return group
