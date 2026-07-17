import unittest

from core.api_gateway import ApiCaller, ApiError, ApiRegistry


class ApiRegistryTest(unittest.TestCase):
    def setUp(self):
        self.registry = ApiRegistry()

    def _register_bookmarks(self, exported_capability=None):
        return self.registry.register_route(
            "bookmarks.card",
            "plugins/bookmarks.card/list",
            lambda payload, context: {
                "query": payload.get("query", ""),
                "caller": context.caller.caller_id,
            },
            exported_capability=exported_capability,
        )

    def test_owner_and_owner_web_ui_can_call_route(self):
        self._register_bookmarks()

        plugin_result = self.registry.call(
            ApiCaller.plugin("bookmarks.card"),
            "plugins/bookmarks.card/list",
            {"query": "docs"},
        )
        web_result = self.registry.call(
            ApiCaller.web("bookmarks.card"),
            "plugins/bookmarks.card/list",
            {},
        )

        self.assertEqual(plugin_result["query"], "docs")
        self.assertEqual(web_result["caller"], "web:bookmarks.card")

    def test_cross_plugin_call_requires_exported_capability(self):
        self._register_bookmarks(exported_capability="bookmarks.read")
        route = "plugins/bookmarks.card/list"

        denied = self.registry.invoke(ApiCaller.plugin("toolbox"), route, {})
        allowed = self.registry.invoke(
            ApiCaller.plugin("toolbox", {"bookmarks.read"}), route, {}
        )

        self.assertEqual(denied["code"], "FORBIDDEN")
        self.assertTrue(allowed["ok"])

    def test_route_without_export_is_private(self):
        self._register_bookmarks()

        with self.assertRaises(ApiError) as error:
            self.registry.call(
                ApiCaller.plugin("toolbox", {"bookmarks.read"}),
                "plugins/bookmarks.card/list",
                {},
            )

        self.assertEqual(error.exception.code, "FORBIDDEN")

    def test_unregister_owner_marks_routes_unavailable(self):
        route = self._register_bookmarks()
        self.registry.unregister_owner("bookmarks.card")

        result = self.registry.invoke(ApiCaller.core(), route, {})

        self.assertEqual(result["code"], "SERVICE_UNAVAILABLE")

    def test_duplicate_and_wrong_namespace_are_rejected(self):
        self._register_bookmarks()
        with self.assertRaises(ValueError):
            self._register_bookmarks()
        with self.assertRaises(ValueError):
            self.registry.register_route(
                "toolbox",
                "plugins/bookmarks.card/list",
                lambda payload, context: None,
            )

    def test_non_json_response_returns_stable_error(self):
        self.registry.register_route(
            "core",
            "core/test/non-json",
            lambda payload, context: object(),
        )

        result = self.registry.invoke(ApiCaller.core(), "core/test/non-json", {})

        self.assertEqual(result["code"], "INVALID_RESPONSE")

    def test_list_routes_only_includes_authorized_routes(self):
        self._register_bookmarks(exported_capability="bookmarks.read")
        self.registry.register_route(
            "gateway_manager",
            "plugins/gateway_manager/status",
            lambda payload, context: {},
        )

        routes = self.registry.list_routes(
            ApiCaller.plugin("toolbox", {"bookmarks.read"})
        )

        self.assertEqual(
            [item["route"] for item in routes],
            ["plugins/bookmarks.card/list"],
        )

    def test_expected_major_version_is_enforced(self):
        route = self.registry.register_route(
            "bookmarks.card",
            "plugins/bookmarks.card/versioned",
            lambda payload, context: context.version,
            version="2.3",
            exported_capability="bookmarks.read",
        )
        caller = ApiCaller.plugin("toolbox", {"bookmarks.read"})

        self.assertEqual(
            self.registry.call(caller, route, expected_version="2.0"),
            "2.3",
        )
        with self.assertRaises(ApiError) as error:
            self.registry.call(caller, route, expected_version="1.9")
        self.assertEqual(error.exception.code, "INCOMPATIBLE_API_VERSION")


if __name__ == "__main__":
    unittest.main()
