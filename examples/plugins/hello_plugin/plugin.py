from qfluentwidgets import BodyLabel, FluentIcon

from core.plugin_system.plugin_base import PluginBase


class HelloPlugin(PluginBase):
    def __init__(self, context):
        super().__init__(context)
        self._widget = None

    def on_load(self):
        pass

    def on_unload(self):
        if self._widget is not None:
            self._widget.close()
            self._widget = None

    def get_icon(self):
        return FluentIcon.APPLICATION

    def get_thumbnail_widget(self):
        return None

    def get_card_widget(self):
        if self._widget is None:
            self._widget = BodyLabel("Hello from Agile Tiles")
        return self._widget
