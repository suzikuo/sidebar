from abc import ABC, abstractmethod

from core.plugin_system.plugin_context import PluginContext


class PluginBase(ABC):
    """
    All plugins must inherit from this class.
    Provides standard lifecycle hooks.
    """

    def __init__(self, context: PluginContext):
        self.context = context
        self.description = ""

    @abstractmethod
    def on_load(self):
        """Called when the plugin is loaded."""
        pass

    @abstractmethod
    def on_unload(self):
        """Called when the plugin is unloaded."""
        pass

    @abstractmethod
    def get_icon(self):
        """Returns the icon for the sidebar (FluentIcon or QIcon or str path)."""
        pass

    @abstractmethod
    def get_thumbnail_widget(self):
        """Returns a small QWidget (e.g., 40x40) to be shown in the sidebar's icon bar."""
        pass

    @abstractmethod
    def get_card_widget(self):
        """Returns the main QWidget for the plugin card."""
        pass

    def get_sidebar_widget(self):
        """Optional: Returns a small QWidget to embed directly in the sidebar layout.
        Return None (default) if the plugin has no sidebar widget."""
        return None

    def get_widget(self):
        """Deprecated: use get_card_widget instead."""
        return self.get_card_widget()

    def run(self):
        """
        Optional: Called when the plugin icon is left-clicked in the sidebar.
        If implemented, the plugin can perform a quick action instead of or before opening the card.
        Returns:
            bool: True if the action was handled and detail view should NOT be shown.
                  False if the detail view should still be shown.
        """
        return False

    def on_migrate(self, from_version: int, to_version: int):
        """Optional hook for database migrations."""
        pass

    @property
    def db(self):
        """Shortcut to access the plugin's scoped database. Can be overridden."""
        return getattr(self, "_db", None) or self.context.db

    @db.setter
    def db(self, value):
        self._db = value

    @property
    def state(self):
        """Shortcut to access the plugin's scoped state store. Can be overridden."""
        return getattr(self, "_state", None) or self.context.state

    @state.setter
    def state(self, value):
        self._state = value

    def get_context_menu_items(self):
        """
        Optional: Returns a list of QAction (or compatible objects - e.g. Action from qfluentwidgets)
        to be added to the sidebar context menu.
        """
        return []
