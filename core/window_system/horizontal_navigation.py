"""
Horizontal Navigation Interface for Top Sidebar Position
Mimics the NavigationInterface API but uses horizontal layout
"""

from typing import Union

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import FluentIconBase, NavigationItemPosition, ToolButton


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

        # Main horizontal layout
        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout.setContentsMargins(5, 5, 5, 5)
        self.hBoxLayout.setSpacing(2)
        self.hBoxLayout.setAlignment(Qt.AlignCenter)  # Center the plugin icons

        # Store items by position
        self.items = {}
        self.top_items = {}
        self.bottom_items = {}
        self._currentItem = None

        # Set transparent background
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("HorizontalNavigationInterface { background: transparent; }")

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
            Position (TOP or BOTTOM)
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

        # Create icon button
        button = ToolButton(icon, self)
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

        # Add to layout
        self.hBoxLayout.addWidget(button)

        # Store in all relevant dictionaries
        self.items[routeKey] = button

        # Track by position for compatibility with NavigationInterface API
        if position == NavigationItemPosition.TOP:
            self.top_items[routeKey] = button
        elif position == NavigationItemPosition.BOTTOM:
            self.bottom_items[routeKey] = button

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

        # Also remove from position-specific dictionaries
        self.top_items.pop(routeKey, None)
        self.bottom_items.pop(routeKey, None)

        self.hBoxLayout.removeWidget(widget)
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
