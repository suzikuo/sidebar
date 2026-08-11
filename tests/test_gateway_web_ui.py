import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GatewayWebUiAssetsTest(unittest.TestCase):
    def test_production_build_is_local_and_complete(self):
        root = PROJECT_ROOT / "plugins" / "gateway_manager" / "web"
        html = (root / "index.html").read_text(encoding="utf-8")
        references = re.findall(r'(?:src|href)="([^"]+)"', html)

        self.assertNotIn("qrc:///qtwebchannel/qwebchannel.js", references)
        self.assertIn("connect-src 'none'", html)
        self.assertEqual(references, [])
        self.assertIn("script-src 'self' 'unsafe-inline'", html)
        self.assertIn("style-src 'self' 'unsafe-inline'", html)
        self.assertIn("<script>", html)
        self.assertIn("<style>", html)
        self.assertNotIn('type="module"', html)

    def test_gateway_plugin_is_web_only_without_native_fallback(self):
        plugin = (
            PROJECT_ROOT / "plugins" / "gateway_manager" / "plugin.py"
        ).read_text(encoding="utf-8")
        web_view = (
            PROJECT_ROOT / "plugins" / "gateway_manager" / "web_view.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("gateway_manager.views", plugin)
        self.assertNotIn("GatewayManagerWidget", plugin)
        self.assertNotIn("native_factory", web_view)
        self.assertNotIn("_show_native", web_view)
        self.assertFalse(
            (PROJECT_ROOT / "plugins" / "gateway_manager" / "views.py").exists()
        )

    def test_components_use_one_typed_api_boundary(self):
        source = PROJECT_ROOT / "frontend" / "apps" / "gateway" / "src"
        api = (source / "gatewayApi.ts").read_text(encoding="utf-8")
        app = (source / "GatewayApp.vue").read_text(encoding="utf-8")
        editor = (source / "GatewayEditor.vue").read_text(encoding="utf-8")

        for action in ("snapshot", "action", "save", "delete"):
            self.assertIn(f"plugins/gateway_manager/{action}", api)
        self.assertNotIn("plugins/gateway_manager/", app)
        self.assertNotIn("plugins/gateway_manager/", editor)
        self.assertNotIn("sqlite", (api + app + editor).lower())

    def test_source_layout_has_bounded_responsive_overflow(self):
        css = (
            PROJECT_ROOT / "frontend" / "apps" / "gateway" / "src" / "gateway.css"
        ).read_text(encoding="utf-8")

        self.assertIn("overflow-x: auto", css)
        self.assertIn(".path-flow", css)
        self.assertIn(".resource-row", css)
        self.assertIn(".editor-drawer", css)
        self.assertIn(".resource-toolbar { position: sticky", css)
        self.assertIn(".row-menu { position: absolute; z-index: 12; right: 0; bottom: 38px", css)
        self.assertIn("@media (max-width: 560px)", css)
        self.assertIn("@media (max-width: 480px)", css)
        self.assertIn("min-width: 0", css)


if __name__ == "__main__":
    unittest.main()
