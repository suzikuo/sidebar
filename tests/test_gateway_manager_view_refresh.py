import importlib.util
import unittest


UI_DEPS_AVAILABLE = all(
    importlib.util.find_spec(module) is not None
    for module in ("PySide6", "qfluentwidgets")
)


class _EmptyDatabase:
    def list_cloudflare_tunnels(self):
        return []

    def list_routes(self):
        return []

    def list_gateways(self):
        return []


class _EmptyPlugin:
    def get_cloudflare_statuses(self):
        return {}

    def get_status(self):
        return {}


class _CountingLayout:
    def __init__(self):
        self.clear_count = 0

    def takeAllWidgets(self):
        self.clear_count += 1


class _CountingTable:
    def __init__(self):
        self.clear_count = 0

    def setRowCount(self, count):
        if count == 0:
            self.clear_count += 1


class _Label:
    def setText(self, text):
        pass


@unittest.skipUnless(UI_DEPS_AVAILABLE, "gateway view tests require Qt UI dependencies")
class GatewayCardRefreshTest(unittest.TestCase):
    def setUp(self):
        from plugins.gateway_manager.views import GatewayManagerWidget

        self.view_type = GatewayManagerWidget
        self.widget = type("FakeGatewayManagerWidget", (), {})()
        self.widget.db = _EmptyDatabase()
        self.widget.plugin = _EmptyPlugin()
        self.widget.overviewLayout = _CountingLayout()
        self.widget.tunnelOverviewLayout = _CountingLayout()
        self.widget.overviewContainer = None
        self.widget.tunnelOverviewContainer = None
        self.widget._gateway_cards_signature = None
        self.widget._tunnel_cards_signature = None
        self.widget._status_table_signature = None

    def test_unchanged_gateway_cards_are_not_rebuilt(self):
        self.view_type.refresh_gateway_cards(self.widget)
        self.view_type.refresh_gateway_cards(self.widget)

        self.assertEqual(self.widget.overviewLayout.clear_count, 1)

    def test_unchanged_tunnel_cards_are_not_rebuilt(self):
        self.view_type.refresh_tunnel_cards(self.widget)
        self.view_type.refresh_tunnel_cards(self.widget)

        self.assertEqual(self.widget.tunnelOverviewLayout.clear_count, 1)

    def test_unchanged_status_table_is_not_rebuilt(self):
        self.widget.statusTable = _CountingTable()
        self.widget.statusLabel = _Label()
        self.widget.refresh_gateway_cards = lambda: None
        self.widget.refresh_cloudflare_status = lambda: None

        self.view_type.refresh_status(self.widget)
        self.view_type.refresh_status(self.widget)

        self.assertEqual(self.widget.statusTable.clear_count, 1)


if __name__ == "__main__":
    unittest.main()
