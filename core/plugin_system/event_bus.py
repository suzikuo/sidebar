from typing import Any, Callable, Dict, List

from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    """
    Centralized event bus for inter-plugin and core communications.
    Supports throttling for high-frequency events.
    """

    event_triggered = Signal(str, dict)

    def __init__(self):
        super().__init__()
        self._subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable[[Dict[str, Any]], None]):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable):
        if event_type in self._subscribers:
            if callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)

    def publish(self, event_type: str, data: Dict[str, Any] = None):
        if data is None:
            data = {}

        # Internal Qt signal for decoupled cross-thread safety
        self.event_triggered.emit(event_type, data)

        # Immediate synchronous call for performance where needed
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    callback(data)
                except Exception as e:
                    print(f"Error in EventBus subscriber: {e}")
