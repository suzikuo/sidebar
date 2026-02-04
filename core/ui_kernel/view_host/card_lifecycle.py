from abc import ABC, abstractmethod
from typing import Any, Dict


class CardLifecycle(ABC):
    """
    Interface for plugin cards to handle lifecycle events and state management.
    """

    @abstractmethod
    def on_show(self):
        """Called when the card is about to be displayed."""
        pass

    @abstractmethod
    def on_hide(self):
        """Called when the card is hidden or another card is being shown."""
        pass

    @abstractmethod
    def save_state(self) -> Dict[str, Any]:
        """Return a dictionary representing the current UI state (scroll, input, etc.)."""
        return {}

    @abstractmethod
    def restore_state(self, state: Dict[str, Any]):
        """Restore the UI state from the provided dictionary."""
        pass
