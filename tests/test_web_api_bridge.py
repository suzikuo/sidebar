import json
import unittest

from core.api_gateway import ApiRegistry
from core.web_ui import WebApiBridge


class WebApiBridgeTest(unittest.TestCase):
    def setUp(self):
        self.registry = ApiRegistry()
        self.responses = []

    def _bridge(self, owner_id="settings", capabilities=(), **kwargs):
        bridge = WebApiBridge(
            self.registry,
            owner_id,
            capabilities,
            **kwargs,
        )
        bridge.response_ready.connect(
            lambda request_id, payload: self.responses.append(
                (request_id, json.loads(payload))
            )
        )
        return bridge

    def test_owner_scoped_route_returns_envelope(self):
        self.registry.register_route(
            "settings",
            "plugins/settings/get",
            lambda payload, context: {
                "value": payload["key"],
                "caller": context.caller.caller_id,
            },
        )
        bridge = self._bridge()

        bridge.invoke("plugins/settings/get", '{"key":"theme"}', "request-1")

        request_id, result = self.responses.pop()
        self.assertEqual(request_id, "request-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["caller"], "web:settings")

    def test_bridge_capabilities_are_fixed_by_host(self):
        self.registry.register_route(
            "bookmarks",
            "plugins/bookmarks/list",
            lambda payload, context: ["docs"],
            exported_capability="bookmarks.read",
        )
        denied_bridge = self._bridge(owner_id="toolbox")
        allowed_bridge = self._bridge(
            owner_id="toolbox",
            capabilities={"bookmarks.read"},
        )

        denied_bridge.invoke("plugins/bookmarks/list", "{}", "denied")
        allowed_bridge.invoke("plugins/bookmarks/list", "{}", "allowed")

        self.assertEqual(self.responses[0][1]["code"], "FORBIDDEN")
        self.assertTrue(self.responses[1][1]["ok"])

    def test_invalid_json_and_non_object_payload_are_rejected(self):
        bridge = self._bridge()

        bridge.invoke("plugins/settings/get", "{", "invalid-json")
        bridge.invoke("plugins/settings/get", "[]", "invalid-shape")

        self.assertEqual(self.responses[0][1]["code"], "INVALID_REQUEST")
        self.assertEqual(self.responses[1][1]["code"], "INVALID_REQUEST")

    def test_request_id_and_payload_size_are_bounded(self):
        bridge = self._bridge(max_payload_bytes=4)

        bridge.invoke("plugins/settings/get", "{}", "bad id")
        bridge.invoke("plugins/settings/get", '{"a":1}', "large-payload")

        self.assertEqual(self.responses[0][1]["code"], "INVALID_REQUEST")
        self.assertEqual(self.responses[1][1]["code"], "INVALID_REQUEST")

    def test_host_can_publish_json_event(self):
        bridge = self._bridge()
        events = []
        bridge.event_ready.connect(
            lambda event_name, payload: events.append(
                (event_name, json.loads(payload))
            )
        )

        bridge.publish_event("settings.changed", {"key": "theme"})

        self.assertEqual(events, [("settings.changed", {"key": "theme"})])


if __name__ == "__main__":
    unittest.main()
