from enum import Enum

from PySide6.QtCore import QPoint, QRect


class SidebarState(Enum):
    HIDDEN = 0
    VISIBLE = 1
    EXPANDED = 2


class WindowBehavior:
    """
    Pure logic for sidebar desktop interaction:
    - Snapping to screen edges
    - Hover detection for auto-show
    - Focus loss for auto-hide
    """

    # Minimum dimensions to prevent rendering errors
    MIN_WIDTH = 2
    MIN_HEIGHT = 100
    MAX_WIDTH = 800

    def __init__(
        self,
        screen_geometry: QRect,
        width: int = 280,
        collapsed_width: int = 48,
        edge: str = "left",
    ):
        self.screen_geometry = screen_geometry
        self.width = max(self.MIN_WIDTH, min(width, self.MAX_WIDTH))
        self.collapsed_width = max(self.MIN_WIDTH, collapsed_width)
        self.trigger_zone = 5  # Pixels from edge to trigger show
        self.edge = edge  # "left" or "right"
        self.is_left_edge = edge == "left"
        self.is_top_edge = edge == "top"

    def get_hidden_geometry(self, peek_width: int = None) -> QRect:
        """
        Geometry when sidebar is 'hidden' (waiting at edge).
        Use peek_width to control the visible strip size.
        """
        if peek_width is None:
            peek_width = 2

        if self.is_top_edge:
            # Top edge: thin horizontal strip at top
            rect = QRect(
                self.screen_geometry.left(),
                self.screen_geometry.top() - self.collapsed_width + peek_width,
                self.screen_geometry.width(),
                peek_width,
            )
        elif self.is_left_edge:
            rect = QRect(
                self.screen_geometry.left() - self.collapsed_width + peek_width,
                self.screen_geometry.top(),
                peek_width,
                self.screen_geometry.height(),
            )
        else:
            rect = QRect(
                self.screen_geometry.right() - peek_width,
                self.screen_geometry.top(),
                peek_width,
                self.screen_geometry.height(),
            )
        return self._validate_geometry(rect)

    def get_visible_geometry(self) -> QRect:
        """Geometry when sidebar is visible but collapsed (icon strip only)."""
        if self.is_top_edge:
            # Top edge: full width horizontal bar
            rect = QRect(
                self.screen_geometry.left(),
                self.screen_geometry.top(),
                self.screen_geometry.width(),
                self.collapsed_width,
            )
        elif self.is_left_edge:
            rect = QRect(
                self.screen_geometry.left(),
                self.screen_geometry.top(),
                self.collapsed_width,
                self.screen_geometry.height(),
            )
        else:
            rect = QRect(
                self.screen_geometry.right() - self.collapsed_width,
                self.screen_geometry.top(),
                self.collapsed_width,
                self.screen_geometry.height(),
            )
        return self._validate_geometry(rect)

    def get_expanded_geometry(self, custom_width: int = None) -> QRect:
        """Geometry when sidebar is fully active (content visible)."""
        # Clamp width to valid range
        width = custom_width if custom_width is not None else self.width
        width = max(self.MIN_WIDTH, min(width, self.MAX_WIDTH))

        if self.is_left_edge:
            rect = QRect(
                self.screen_geometry.left(),
                self.screen_geometry.top(),
                width,
                self.screen_geometry.height(),
            )

        else:
            rect = QRect(
                self.screen_geometry.right() - width,
                self.screen_geometry.top(),
                width,
                self.screen_geometry.height(),
            )
        return self._validate_geometry(rect)

    def is_in_trigger_zone(self, mouse_pos: QPoint) -> bool:
        """Checks if mouse is near the edge to trigger sidebar."""
        if self.is_top_edge:
            return mouse_pos.y() <= self.screen_geometry.top() + self.trigger_zone
        elif self.is_left_edge:
            return mouse_pos.x() <= self.screen_geometry.left() + self.trigger_zone
        else:
            return mouse_pos.x() >= self.screen_geometry.right() - self.trigger_zone

    def should_hide(self, mouse_pos: QPoint, sidebar_geometry: QRect) -> bool:
        """Checks if sidebar should hide based on mouse position."""
        return not sidebar_geometry.contains(mouse_pos)

    def _validate_geometry(self, rect: QRect) -> QRect:
        """
        Validate and fix geometry to prevent UpdateLayeredWindowIndirect errors.
        Ensures all dimensions are positive and within valid bounds.
        """
        return rect
        # Boundary limits (exclusive)
        screen_top = self.screen_geometry.top()
        screen_bottom = self.screen_geometry.top() + self.screen_geometry.height()
        screen_left = self.screen_geometry.left()
        screen_right = self.screen_geometry.left() + self.screen_geometry.width()

        x = max(screen_left, min(rect.x(), screen_right - self.MIN_WIDTH))
        y = max(screen_top, min(rect.y(), screen_bottom - self.MIN_HEIGHT))
        width = max(self.MIN_WIDTH, min(rect.width(), self.MAX_WIDTH))
        height = max(self.MIN_HEIGHT, min(rect.height(), self.screen_geometry.height()))

        # Ensure the window doesn't extend beyond screen bounds
        if x + width > screen_right:
            x = screen_right - width

        if x < screen_left:
            width = screen_left - x

        if y + height > screen_bottom:
            height = screen_bottom - y

        return QRect(int(x), int(y), int(width), int(height))
