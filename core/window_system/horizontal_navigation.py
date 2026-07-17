"""Horizontal navigation interface for the top sidebar position."""

from typing import Union

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLayout,
    QScrollArea,
    QWidget,
)
from qfluentwidgets import FluentIconBase, NavigationItemPosition, ToolButton


class _HorizontalPluginScrollArea(QScrollArea):
    """A scrollbar-free horizontal viewport for navigation items."""

    def wheelEvent(self, event: QWheelEvent):
        pixel_delta = event.pixelDelta()
        angle_delta = event.angleDelta()

        if pixel_delta.x():
            delta = pixel_delta.x()
            is_pixel_delta = True
        elif pixel_delta.y():
            delta = pixel_delta.y()
            is_pixel_delta = True
        elif angle_delta.x():
            delta = angle_delta.x()
            is_pixel_delta = False
        elif angle_delta.y():
            delta = angle_delta.y()
            is_pixel_delta = False
        else:
            event.ignore()
            return

        bar = self.horizontalScrollBar()
        if is_pixel_delta:
            distance = delta
        else:
            lines = max(QApplication.wheelScrollLines(), 1)
            distance = round(delta / 120 * lines * max(bar.singleStep(), 1))
            if distance == 0:
                distance = 1 if delta > 0 else -1

        previous = bar.value()
        bar.setValue(previous - distance)
        if bar.value() == previous:
            event.ignore()
        else:
            event.accept()


class HorizontalNavigationInterface(QWidget):
    """
    Horizontal Navigation Interface for top sidebar.
    Provides the same API as NavigationInterface but arranges items horizontally.
    """

    def __init__(
        self,
        parent=None,
        showMenuButton=False,
        showReturnButton=False,
        collapsible=True,
    ):
        super().__init__(parent=parent)

        self.items = {}
        self.top_items = {}
        self.scroll_items = {}
        self.bottom_items = {}
        self._currentItem = None

        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout.setContentsMargins(5, 5, 5, 5)
        self.hBoxLayout.setSpacing(2)

        self.topLayout = QHBoxLayout()
        self.topLayout.setContentsMargins(0, 0, 0, 0)
        self.topLayout.setSpacing(2)
        self.topLayout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.scrollArea = _HorizontalPluginScrollArea(self)
        self.scrollArea.setFrameShape(QFrame.NoFrame)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setMinimumWidth(0)
        self.scrollArea.setFixedHeight(40)
        self.scrollArea.setFocusPolicy(Qt.NoFocus)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scrollArea.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.scrollWidget = QWidget()
        self.scrollLayout = QHBoxLayout(self.scrollWidget)
        self.scrollLayout.setContentsMargins(0, 0, 0, 0)
        self.scrollLayout.setSpacing(2)
        self.scrollLayout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.scrollLayout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.scrollArea.setWidget(self.scrollWidget)

        self.bottomLayout = QHBoxLayout()
        self.bottomLayout.setContentsMargins(0, 0, 0, 0)
        self.bottomLayout.setSpacing(2)
        self.bottomLayout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.hBoxLayout.addLayout(self.topLayout)
        self.hBoxLayout.addWidget(self.scrollArea, 1)
        self.hBoxLayout.addLayout(self.bottomLayout)

        # Set transparent background
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumWidth(0)
        self.setStyleSheet(
            "HorizontalNavigationInterface, QScrollArea, "
            "QScrollArea > QWidget > QWidget "
            "{ background: transparent; border: none; }"
        )

    def addItem(
        self,
        routeKey: str,
        icon: Union[str, QIcon, FluentIconBase],
        text: str,
        onClick=None,
        selectable=True,
        position=NavigationItemPosition.TOP,
        tooltip: str = None,
        parentRouteKey: str = None,
    ):
        """
        Add navigation item (horizontal button).

        Parameters
        ----------
        routeKey : str
            Unique identifier for this item
        icon : str | QIcon | FluentIconBase
            Icon for the button
        text : str
            Text label (used for tooltip)
        onClick : callable, optional
            Click handler
        selectable : bool
            Whether item is selectable
        position : NavigationItemPosition
            Fixed TOP, scrollable SCROLL, or fixed BOTTOM position
        tooltip : str, optional
            Tooltip text
        parentRouteKey : str, optional
            Parent route key (not used)

        Returns
        -------
        ToolButton
            The created button widget
        """
        if routeKey in self.items:
            return self.items[routeKey]

        parent = (
            self.scrollWidget
            if position == NavigationItemPosition.SCROLL
            else self
        )
        button = ToolButton(icon, parent)
        button.setFixedSize(40, 40)
        button.setToolTip(tooltip or text)
        button.setProperty("routeKey", routeKey)
        button.setProperty("selectable", selectable)

        # Fix font size warning: explicitly set font size
        font = button.font()
        font.setPointSize(12)
        button.setFont(font)

        if onClick:
            button.clicked.connect(onClick)

        self.items[routeKey] = button
        if position == NavigationItemPosition.TOP:
            self.top_items[routeKey] = button
            self.topLayout.addWidget(button)
        elif position == NavigationItemPosition.SCROLL:
            self.scroll_items[routeKey] = button
            self.scrollLayout.addWidget(button)
            self._refresh_scroll_extent()
        elif position == NavigationItemPosition.BOTTOM:
            self.bottom_items[routeKey] = button
            self.bottomLayout.addWidget(button)

        return button

    def removeWidget(self, routeKey: str):
        """
        Remove widget by route key.

        Parameters
        ----------
        routeKey : str
            Route key of item to remove
        """
        if routeKey not in self.items:
            return

        widget = self.items.pop(routeKey)

        if self._currentItem == widget:
            self._currentItem = None

        if routeKey in self.top_items:
            self.top_items.pop(routeKey)
            self.topLayout.removeWidget(widget)
        elif routeKey in self.scroll_items:
            self.scroll_items.pop(routeKey)
            self.scrollLayout.removeWidget(widget)
            self._refresh_scroll_extent()
        else:
            self.bottom_items.pop(routeKey, None)
            self.bottomLayout.removeWidget(widget)
        widget.deleteLater()

    def setCurrentItem(self, name: str):
        """
        Set current selected item and update visual state.

        Parameters
        ----------
        name : str
            Route key of item to select
        """
        # Deselect old item
        if self._currentItem:
            self._currentItem.setProperty("isSelected", False)
            self._currentItem.style().polish(self._currentItem)

        # Select new item
        self._currentItem = self.items.get(name)
        if self._currentItem and self._currentItem.property("selectable"):
            self._currentItem.setProperty("isSelected", True)
            self._currentItem.style().polish(self._currentItem)
            if name in self.scroll_items:
                self.scrollArea.ensureWidgetVisible(self._currentItem, 4, 0)

    def _refresh_scroll_extent(self):
        self.scrollLayout.invalidate()
        self.scrollLayout.activate()
        self.scrollWidget.adjustSize()
        self.scrollWidget.updateGeometry()

    def widget(self, routeKey: str):
        """
        Get widget by route key.

        Parameters
        ----------
        routeKey : str
            Route key of widget

        Returns
        -------
        QWidget
            The widget, or None if not found
        """
        return self.items.get(routeKey)

    def hide(self):
        """Hide the navigation interface."""
        super().hide()

    def show(self):
        """Show the navigation interface."""
        super().show()
