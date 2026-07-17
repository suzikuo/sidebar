import itertools
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal, Slot

from core.logger import logger


@dataclass(frozen=True)
class _Subscription:
    token: str
    callback: Callable[[Dict[str, Any]], None]
    owner: Optional[str]


class EventBus(QObject):
    """
    Centralized event bus for inter-plugin and core communications.
    Supports throttling for high-frequency events.
    """

    event_triggered = Signal(str, dict)

    def __init__(self):
        super().__init__()
        self._subscribers: Dict[str, List[_Subscription]] = {}
        self._subscription_sequence = itertools.count(1)
        self._lock = threading.RLock()
        self.event_triggered.connect(self._dispatch)

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[Dict[str, Any]], None],
        *,
        owner: str = None,
    ) -> str:
        """Subscribe and return a token that can release this exact registration."""
        if not callable(callback):
            raise TypeError("EventBus callback must be callable.")

        with self._lock:
            token = f"event-subscription-{next(self._subscription_sequence)}"
            subscription = _Subscription(token=token, callback=callback, owner=owner)
            self._subscribers.setdefault(event_type, []).append(subscription)
        return token

    def unsubscribe(self, event_type: str, callback: Callable) -> bool:
        """Remove the first matching callback, preserving the original API."""
        with self._lock:
            subscriptions = self._subscribers.get(event_type, [])
            for subscription in subscriptions:
                if subscription.callback == callback:
                    subscriptions.remove(subscription)
                    self._remove_empty_event(event_type)
                    return True
        return False

    def unsubscribe_token(self, token: str) -> bool:
        """Remove one subscription by the token returned from ``subscribe``."""
        with self._lock:
            for event_type, subscriptions in list(self._subscribers.items()):
                for subscription in subscriptions:
                    if subscription.token == token:
                        subscriptions.remove(subscription)
                        self._remove_empty_event(event_type)
                        return True
        return False

    def unsubscribe_owner(self, owner: str) -> int:
        """Remove every subscription registered for an owner."""
        removed = 0
        with self._lock:
            for event_type, subscriptions in list(self._subscribers.items()):
                retained = [item for item in subscriptions if item.owner != owner]
                removed += len(subscriptions) - len(retained)
                if retained:
                    self._subscribers[event_type] = retained
                else:
                    self._subscribers.pop(event_type, None)
        return removed

    def publish(self, event_type: str, data: Dict[str, Any] = None):
        if data is None:
            data = {}
        self.event_triggered.emit(event_type, data)

    @Slot(str, dict)
    def _dispatch(self, event_type: str, data: Dict[str, Any]):
        with self._lock:
            subscriptions = list(self._subscribers.get(event_type, []))

        for subscription in subscriptions:
            try:
                subscription.callback(data)
            except Exception as e:
                logger.error(f"Error in EventBus subscriber: {e}", exc_info=True)

    def _remove_empty_event(self, event_type: str):
        if not self._subscribers.get(event_type):
            self._subscribers.pop(event_type, None)
