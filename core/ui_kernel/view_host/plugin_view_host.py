from typing import Any, Dict, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel

from core.state_store import StateStore
from core.ui_kernel.view_host.card_lifecycle import CardLifecycle
from core.ui_kernel.view_host.view_transition import ViewTransitionController


class PluginViewHost(QWidget):
    """
    The View Scheduler. Manages the lifecycle and display of plugin cards.
    """

    view_closed = Signal()

    def __init__(self, state_store: StateStore, theme_engine, parent=None):
        super().__init__(parent)
        self.state_store = state_store
        self.theme_engine = theme_engine

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # We use a QWidget as a container for animations,
        # but we manage the widgets manually for better transition control.
        self.container = QWidget()
        self.layout.addWidget(self.container)

        self.transition_controller = ViewTransitionController(self)
        self.active_plugin_id: Optional[str] = None
        self.cache: Dict[str, QWidget] = {}

        self.hide()  # Hidden by default

    def open(self, plugin_id: str, plugin_instance: Any):
        """
        Opens a plugin card with caching and lifecycle management.
        """
        if self.active_plugin_id == plugin_id:
            return

        # 1. Save state of current plugin
        self._deactivate_current()

        # 2. Get or Create Card
        card_widget = self.cache.get(plugin_id)
        if not card_widget:
            # Create a new CardContainer/Widget
            from ui.components.card_container import CardContainer

            if hasattr(plugin_instance, "get_card_widget"):
                content_widget = plugin_instance.get_card_widget()
            elif hasattr(plugin_instance, "get_widget"):
                content_widget = plugin_instance.get_widget()
            else:
                content_widget = BodyLabel(f"Plugin {plugin_id} has no view content.")

            card_widget = CardContainer(
                content_widget, self.theme_engine, self.container
            )
            self.cache[plugin_id] = card_widget

            # Initial state restore
            if isinstance(content_widget, CardLifecycle):
                state = self.state_store.get_plugin_state(plugin_id, "view_context", {})
                content_widget.restore_state(state)

        # 3. Transition to new card
        old_card = (
            self.cache.get(self.active_plugin_id) if self.active_plugin_id else None
        )

        # Prepare new card (ensure it's in the container)
        card_widget.setParent(self.container)
        card_widget.resize(self.container.size())

        self.transition_controller.slide_transition(old_card, card_widget)

        # 4. Lifecycle Hook
        content_widget = card_widget.get_content()
        if isinstance(content_widget, CardLifecycle):
            content_widget.on_show()

        self.active_plugin_id = plugin_id
        self.show()

    def close(self):
        """
        Closes the host layer, saving state and triggering lifecycle hooks.
        """
        if not self.active_plugin_id:
            return

        self._deactivate_current()
        self.active_plugin_id = None
        self.hide()
        self.view_closed.emit()

    def preload(self, plugin_id: str, plugin_instance: Any):
        """Builds the card in the background without showing."""
        if plugin_id in self.cache:
            return

        from ui.components.card_container import CardContainer

        if hasattr(plugin_instance, "get_card_widget"):
            content_widget = plugin_instance.get_card_widget()
        elif hasattr(plugin_instance, "get_widget"):
            content_widget = plugin_instance.get_widget()
        else:
            return  # Skip if no widget

        card_widget = CardContainer(content_widget, self.theme_engine)
        self.cache[plugin_id] = card_widget

        if isinstance(content_widget, CardLifecycle):
            state = self.state_store.get_plugin_state(plugin_id, "view_context", {})
            content_widget.restore_state(state)

        card_widget.hide()

    def _deactivate_current(self):
        if not self.active_plugin_id:
            return

        card_widget = self.cache.get(self.active_plugin_id)
        if card_widget:
            content_widget = card_widget.get_content()
            if isinstance(content_widget, CardLifecycle):
                # 1. Lifecycle Hook
                content_widget.on_hide()
                # 2. Save State
                state = content_widget.save_state()
                self.state_store.set_plugin_state(
                    self.active_plugin_id, "view_context", state
                )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Ensure active card matches container size
        if self.active_plugin_id and self.active_plugin_id in self.cache:
            self.cache[self.active_plugin_id].resize(self.container.size())
