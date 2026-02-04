from abc import ABC, abstractmethod

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIconBase


class ToolboxFeature(ABC):
    """
    Abstract base class for all Toolbox features (tools).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the tool displayed on the card."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Description displayed on the card."""
        pass

    @property
    @abstractmethod
    def icon(self) -> FluentIconBase:
        """Icon displayed on the card."""
        pass

    @abstractmethod
    def create_widget(self) -> QWidget:
        """Creates and returns the main widget for the tool."""
        pass
