import tempfile
import unittest
import json
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWidgets import QApplication

from core.api_gateway import ApiRegistry
from core.settings import SettingsApiService, SettingsManager
from core.settings.settings_web_view import SettingsInterface
from core.state_store import StateStore
from core.ui_kernel.design_tokens import DesignTokens
from core.ui_kernel.theme_engine import ThemeEngine
from core.web_ui.web_plugin_host import (
    WebPluginHost,
    is_web_url_allowed,
    resolve_web_entry,
)


class WebPluginHostSecurityTest(unittest.TestCase):
    def test_entry_must_exist_inside_content_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            outside = root.parent / "outside.html"
            outside.write_text("outside", encoding="utf-8")
            self.addCleanup(outside.unlink, missing_ok=True)

            resolved_root, entry = resolve_web_entry(root)

            self.assertEqual(resolved_root, root.resolve())
            self.assertEqual(entry, (root / "index.html").resolve())
            with self.assertRaises(ValueError):
                resolve_web_entry(root, "../outside.html")

    def test_only_local_root_and_qwebchannel_urls_are_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            local_asset = root / "assets" / "app.js"
            outside = root.parent / "secret.txt"

            self.assertTrue(
                is_web_url_allowed(QUrl.fromLocalFile(str(local_asset)), root)
            )
            self.assertTrue(
                is_web_url_allowed(
                    QUrl("qrc:///qtwebchannel/qwebchannel.js"),
                    root,
                )
            )
            self.assertTrue(is_web_url_allowed(QUrl("about:blank"), root))
            self.assertFalse(is_web_url_allowed(QUrl.fromLocalFile(str(outside)), root))
            self.assertFalse(is_web_url_allowed(QUrl("https://example.com"), root))
            self.assertFalse(is_web_url_allowed(QUrl("data:text/plain,test"), root))


class WebPluginHostIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_local_javascript_can_invoke_scoped_api_route(self):
        registry = ApiRegistry()
        registry.register_route(
            "settings",
            "plugins/settings/ping",
            lambda payload, context: {
                "message": payload["message"],
                "caller": context.caller.caller_id,
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text(
                """<!doctype html>
<html>
  <head>
    <meta http-equiv="Content-Security-Policy"
          content="default-src 'self' qrc:; script-src 'self' 'unsafe-inline' qrc:; connect-src 'none'">
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  </head>
  <body>
    <script>
      new QWebChannel(qt.webChannelTransport, function (channel) {
        channel.objects.agileApi.invoke(
          "plugins/settings/ping",
          JSON.stringify({message: "ready"}),
          "integration-request"
        );
      });
    </script>
  </body>
</html>
""",
                encoding="utf-8",
            )
            host = WebPluginHost(registry, "settings", root)
            responses = []
            loop = QEventLoop()

            def on_response(request_id, payload_json):
                responses.append((request_id, json.loads(payload_json)))
                loop.quit()

            host.bridge.response_ready.connect(on_response)
            QTimer.singleShot(10000, loop.quit)
            loop.exec()
            host.close()
            self.app.processEvents()

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0][0], "integration-request")
        self.assertTrue(responses[0][1]["ok"])
        self.assertEqual(responses[0][1]["data"]["message"], "ready")
        self.assertEqual(responses[0][1]["data"]["caller"], "web:settings")

    def test_dispose_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            host = WebPluginHost(ApiRegistry(), "settings", root, autoload=False)

            host.dispose()
            host.dispose()
            self.app.processEvents()

        self.assertTrue(host._disposed)

    def test_settings_interface_falls_back_when_build_is_missing(self):
        class SettingsManagerStub:
            def __init__(self):
                self.widget = None

            def get_settings_widget(self):
                if self.widget is None:
                    from PySide6.QtWidgets import QWidget

                    self.widget = QWidget()
                return self.widget

        with tempfile.TemporaryDirectory() as temp_dir:
            interface = SettingsInterface(
                ApiRegistry(),
                SettingsManagerStub(),
                temp_dir,
            )

            self.assertFalse(interface.using_web_view)
            self.assertIsNotNone(interface.layout().currentWidget())
            interface.close()

    @unittest.skipUnless(
        (Path(__file__).resolve().parents[1] / "front" / "dist" / "desktop" / "index.html").is_file(),
        "Build the desktop frontend before running the production bridge smoke test.",
    )
    def test_built_settings_frontend_invokes_real_settings_api(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = ApiRegistry()
            manager = SettingsManager(
                ThemeEngine(DesignTokens()),
                StateStore(str(Path(temp_dir) / "state.json")),
            )
            SettingsApiService(registry, manager).register_routes()
            interface = SettingsInterface(
                registry,
                manager,
                project_root / "front" / "dist" / "desktop",
            )
            responses = []
            loop = QEventLoop()

            interface._web_view.bridge.response_ready.connect(
                lambda request_id, payload: (
                    responses.append((request_id, json.loads(payload))),
                    loop.quit(),
                )
            )
            QTimer.singleShot(10000, loop.quit)
            loop.exec()
            interface.close()
            self.app.processEvents()

        self.assertTrue(responses)
        self.assertTrue(responses[0][0].startswith("settings-"))
        self.assertTrue(responses[0][1]["ok"])


if __name__ == "__main__":
    unittest.main()
