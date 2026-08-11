import tempfile
import unittest
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWebView import QtWebView
from PySide6.QtWidgets import QApplication

from core.api_gateway import ApiRegistry
from core.settings import SettingsApiService, SettingsManager
from core.settings.settings_web_view import SettingsInterface
from core.state_store import StateStore
from core.ui_kernel.design_tokens import DesignTokens
from core.ui_kernel.theme_engine import ThemeEngine
from core.web_ui.web_plugin_host import (
    WebPluginHost,
    build_web_entry_url,
    is_web_url_allowed,
    prepare_web_entry,
    resolve_web_entry,
)


class WebPluginHostSecurityTest(unittest.TestCase):
    def test_entry_is_loaded_as_a_bounded_in_memory_document(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            entry = Path(temp_dir) / "index.html"
            entry.write_text(
                "<html><body>ready<script>window.ready = true</script></body></html>",
                encoding="utf-8",
            )

            url = build_web_entry_url(entry)

            self.assertEqual(url.scheme(), "data")
            self.assertIn("text/html", url.toString())
            with self.assertRaisesRegex(ValueError, "up to 4 MiB"):
                build_web_entry_url(entry, max_bytes=4)

    def test_entry_extracts_inline_application_script_exactly(self):
        source = "window.value = '$&';\nwindow.ready = true;"
        with tempfile.TemporaryDirectory() as temp_dir:
            entry = Path(temp_dir) / "index.html"
            entry.write_bytes(
                f"<html><body><main>ready</main><script>{source}</script></body></html>".encode(
                    "utf-8"
                )
            )

            url, script = prepare_web_entry(entry)

        self.assertEqual(url.scheme(), "data")
        self.assertEqual(script, source)

    def test_entry_rejects_external_script_and_stylesheet_assets(self):
        entries = (
            '<html><script src="./app.js"></script></html>',
            '<html><link rel="stylesheet" href="./app.css"><script>0</script></html>',
        )
        for content in entries:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temp_dir:
                entry = Path(temp_dir) / "index.html"
                entry.write_text(content, encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "must be inline"):
                    prepare_web_entry(entry)

    def test_store_virtualized_child_keeps_logical_web_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            original_resolve = Path.resolve

            def virtualized_child(path, *args, **kwargs):
                resolved = original_resolve(path, *args, **kwargs)
                if resolved.name == "index.html":
                    return root / "LocalCache" / "index.html"
                return resolved

            with patch.object(Path, "resolve", virtualized_child):
                resolved_root, entry = resolve_web_entry(root)
                allowed = is_web_url_allowed(QUrl.fromLocalFile(str(entry)), resolved_root)

            self.assertEqual(resolved_root, root.resolve())
            self.assertEqual(entry, root.resolve() / "index.html")
            self.assertTrue(allowed)

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

    def test_only_local_root_and_about_blank_urls_are_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            local_asset = root / "assets" / "app.js"
            outside = root.parent / "secret.txt"

            self.assertTrue(
                is_web_url_allowed(QUrl.fromLocalFile(str(local_asset)), root)
            )
            self.assertTrue(is_web_url_allowed(QUrl("about:blank"), root))
            self.assertFalse(is_web_url_allowed(QUrl("qrc:///AgileTiles/WebView.qml"), root))
            self.assertFalse(is_web_url_allowed(QUrl.fromLocalFile(str(outside)), root))
            self.assertFalse(is_web_url_allowed(QUrl("https://example.com"), root))
            self.assertFalse(is_web_url_allowed(QUrl("data:text/plain,test"), root))


class WebPluginHostIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QtWebView.initialize()
        cls.app = QApplication.instance() or QApplication([])

    def test_native_bridge_can_invoke_scoped_api_route_without_listener(self):
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
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            host = WebPluginHost(registry, "settings", root, autoload=False)
            delivered = []
            observed_responses = []
            host._deliver_to_page = delivered.append
            host.bridge.response_ready.connect(
                lambda request_id, payload: observed_responses.append(
                    (request_id, json.loads(payload))
                )
            )
            host._handle_native_request(
                "integration-request",
                json.dumps(
                    {
                        "type": "invoke",
                        "id": "integration-request",
                        "route": "plugins/settings/ping",
                        "payload": {"message": "ready"},
                    }
                ),
            )
            host.dispose()
            self.app.processEvents()

        self.assertFalse(hasattr(host, "_socket_bridge"))
        self.assertEqual(delivered[0]["id"], "integration-request")
        self.assertTrue(delivered[0]["result"]["ok"])
        self.assertEqual(delivered[0]["result"]["data"]["message"], "ready")
        self.assertEqual(delivered[0]["result"]["data"]["caller"], "web:settings")
        self.assertEqual(observed_responses[0][0], "integration-request")
        self.assertTrue(observed_responses[0][1]["ok"])

    def test_native_bridge_delivers_host_events_to_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            host = WebPluginHost(ApiRegistry(), "settings", root, autoload=False)
            delivered = []
            host._deliver_to_page = delivered.append

            host.publish_event("settings.changed", {"key": "theme", "value": "dark"})
            host.dispose()

        self.assertEqual(
            delivered,
            [
                {
                    "type": "event",
                    "event": "settings.changed",
                    "payload": {"key": "theme", "value": "dark"},
                }
            ],
        )

    def test_native_bridge_drains_concurrent_request_batch(self):
        registry = ApiRegistry()
        observed = []
        registry.register_route(
            "settings",
            "plugins/settings/read",
            lambda payload, _context: observed.append(payload["index"]),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            host = WebPluginHost(registry, "settings", root, autoload=False)
            host._deliver_to_page = Mock()
            requests = [
                json.dumps(
                    {
                        "type": "invoke",
                        "id": f"request-{index}",
                        "route": "plugins/settings/read",
                        "payload": {"index": index},
                    }
                )
                for index in range(5)
            ]

            host._handle_native_requests(json.dumps(requests))
            host.dispose()

        self.assertEqual(observed, list(range(5)))
        self.assertEqual(host._deliver_to_page.call_count, 5)

    def test_unknown_webview2_status_uses_ready_document_instead_of_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            host = WebPluginHost(ApiRegistry(), "settings", root, autoload=False)
            failed = []
            host.load_failed.connect(failed.append)

            with patch.object(host, "_run_page_script") as run_page_script:
                host._on_ready_state_after_unknown_failure(
                    "complete",
                    "COREWEBVIEW2_WEB_ERROR_STATUS_UNKNOWN",
                )
            host.dispose()

        run_page_script.assert_called_once_with()
        self.assertEqual(failed, [])

    def test_same_document_application_fragment_does_not_reload_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            host = WebPluginHost(ApiRegistry(), "control-center", root, autoload=False)
            host._entry_url = QUrl("data:text/html;base64,PGh0bWw+PC9odG1sPg==")
            web_view = Mock()
            host._web_view = web_view

            host._on_url_changed(
                QUrl("data:text/html;base64,PGh0bWw+PC9odG1sPg==#settings")
            )
            web_view.setUrl.assert_not_called()
            host.dispose()

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
        (
            Path(__file__).resolve().parents[1]
            / "frontend"
            / "dist"
            / "desktop"
            / "index.html"
        ).is_file()
        and os.environ.get("AGILE_TILES_RUN_WEBVIEW2_TESTS") == "1",
        "Set AGILE_TILES_RUN_WEBVIEW2_TESTS=1 on an interactive Windows desktop to run the WebView2 smoke test.",
    )
    def test_built_settings_frontend_invokes_real_settings_api(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = ApiRegistry()
            state_store = StateStore(str(Path(temp_dir) / "state.json"))
            manager = SettingsManager(
                ThemeEngine(DesignTokens()),
                state_store,
            )
            SettingsApiService(registry, manager).register_routes()
            host = WebPluginHost(
                registry,
                "settings",
                project_root / "frontend" / "dist" / "desktop",
                capabilities={
                    SettingsApiService.READ_CAPABILITY,
                    SettingsApiService.WRITE_CAPABILITY,
                },
                autoload=False,
            )
            host.resize(900, 700)
            host.show()
            responses = []
            diagnostics = []
            failures = []
            loop = QEventLoop()

            host.bridge.response_ready.connect(
                lambda request_id, payload: (
                    responses.append((request_id, json.loads(payload))),
                    loop.quit(),
                )
            )
            host.load_failed.connect(failures.append)
            host.load()

            def collect_diagnostics():
                if host._web_view is None:
                    diagnostics.append("web host unavailable")
                    loop.quit()
                    return
                host._web_view.runJavaScript(
                    "JSON.stringify({ready: document.readyState, "
                    "title: document.title, body: document.body?.innerText?.slice(0, 200), "
                    "bridgeTake: typeof window.__agileTilesBridgeTakeRequests, "
                    "bridgeDeliver: typeof window.__agileTilesBridgeDeliver, "
                    "bundleError: window.__agileTilesBundleError})",
                    lambda result: (diagnostics.append(result), loop.quit()),
                )

            QTimer.singleShot(8000, collect_diagnostics)
            QTimer.singleShot(10000, loop.quit)
            loop.exec()
            host.close()
            state_store.close()
            self.app.processEvents()

        self.assertTrue(
            responses,
            f"No frontend API request; failures={failures!r}, diagnostics={diagnostics!r}",
        )
        self.assertTrue(responses[0][0].startswith("request-"))
        self.assertTrue(responses[0][1]["ok"])

    @unittest.skipUnless(
        (
            Path(__file__).resolve().parents[1]
            / "plugins"
            / "gateway_manager"
            / "web"
            / "index.html"
        ).is_file()
        and os.environ.get("AGILE_TILES_RUN_WEBVIEW2_TESTS") == "1",
        "Set AGILE_TILES_RUN_WEBVIEW2_TESTS=1 on an interactive Windows desktop to run the WebView2 smoke test.",
    )
    def test_built_gateway_frontend_invokes_snapshot_api(self):
        self._exercise_built_frontend(
            Path(__file__).resolve().parents[1]
            / "plugins"
            / "gateway_manager"
            / "web",
            "gateway_manager",
            {
                "plugins/gateway_manager/snapshot": {
                    "running_count": 0,
                    "total_gateways": 0,
                    "gateways": [],
                    "tunnels": [],
                    "services": [],
                    "routes": [],
                    "logs": [],
                }
            },
        )

    @unittest.skipUnless(
        (
            Path(__file__).resolve().parents[1]
            / "resources"
            / "web"
            / "control-center"
            / "index.html"
        ).is_file()
        and os.environ.get("AGILE_TILES_RUN_WEBVIEW2_TESTS") == "1",
        "Set AGILE_TILES_RUN_WEBVIEW2_TESTS=1 on an interactive Windows desktop to run the WebView2 smoke test.",
    )
    def test_built_control_center_frontend_invokes_initial_apis(self):
        self._exercise_built_frontend(
            Path(__file__).resolve().parents[1]
            / "resources"
            / "web"
            / "control-center",
            "control-center",
            {
                "core/control-center/overview": {
                    "version": "1.0.0",
                    "pluginCount": 0,
                    "enabledPluginCount": 0,
                    "loadedPluginCount": 0,
                    "pendingRestartCount": 0,
                    "errorCount": 0,
                    "errors": [],
                },
                "core/control-center/plugins": {"order": [], "plugins": []},
                "core/control-center/catalog": {"entries": [], "errors": []},
                "core/settings/schema": {},
                "core/settings/snapshot": {
                    "appearance": {
                        "ui_scale": "auto",
                        "theme_mode": "system",
                        "accent_color": "#006874",
                    }
                },
            },
            capabilities={"test.web.read"},
        )

    def _exercise_built_frontend(
        self,
        content_root: Path,
        owner_id: str,
        routes: dict[str, object],
        *,
        capabilities=(),
    ):
        registry = ApiRegistry()
        expected_routes = set(routes)
        observed_routes = set()
        loop = QEventLoop()

        for route, response in routes.items():
            route_owner = "core" if route.startswith("core/") else owner_id

            def handler(_payload, context, value=response):
                observed_routes.add(context.route)
                if observed_routes >= expected_routes:
                    QTimer.singleShot(0, loop.quit)
                return value

            registry.register_route(
                route_owner,
                route,
                handler,
                exported_capability=("test.web.read" if route_owner == "core" else None),
            )

        host = WebPluginHost(
            registry,
            owner_id,
            content_root,
            capabilities=capabilities,
            autoload=False,
        )
        failures = []
        host.load_failed.connect(failures.append)
        host.resize(1080, 760)
        host.show()
        host.load()
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        host.close()
        self.app.processEvents()

        self.assertEqual(observed_routes, expected_routes, failures)


if __name__ == "__main__":
    unittest.main()
