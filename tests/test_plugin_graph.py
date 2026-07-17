import unittest

from core.plugin_system.plugin_graph import resolve_plugin_graph
from core.plugin_system.plugin_manifest import parse_manifest


def manifest(plugin_id, version="1.0.0", plugins=None):
    return parse_manifest(
        {
            "manifest_version": 2,
            "id": plugin_id,
            "name": plugin_id,
            "version": version,
            "entry": "plugin.py",
            "class": "Plugin",
            "api_version": "1.0",
            "compatibility": {
                "app": ">=1.0",
                "python_abi": "cp311",
                "platform": "win_amd64",
            },
            "dependencies": {
                "host": [],
                "python": [],
                "plugins": plugins or {},
            },
            "files": {"plugin.py": "0" * 64},
            "native_modules": [],
            "requires_restart": False,
            "ui": {"type": "native"},
        }
    )


class PluginGraphTest(unittest.TestCase):
    def test_dependency_order_wins_and_preferred_order_breaks_ready_ties(self):
        manifests = {
            item.plugin_id: item
            for item in (
                manifest("alpha"),
                manifest("beta"),
                manifest("charlie", plugins={"alpha": ">=1"}),
                manifest("delta", plugins={"beta": ">=1"}),
            )
        }

        result = resolve_plugin_graph(
            manifests,
            enabled_ids=manifests,
            preferred_order=("delta", "beta", "charlie", "alpha"),
        )

        self.assertEqual(result.load_order, ("beta", "alpha", "delta", "charlie"))
        self.assertEqual(result.blocked, {})
        self.assertEqual(result.required_by["alpha"], ("charlie",))
        self.assertEqual(result.required_by["beta"], ("delta",))

    def test_reports_missing_disabled_and_version_mismatch_together(self):
        manifests = {
            "consumer": manifest(
                "consumer",
                plugins={
                    "disabled": ">=1",
                    "missing": ">=1",
                    "provider": ">=2",
                },
            ),
            "disabled": manifest("disabled"),
            "provider": manifest("provider", "1.5.0"),
        }

        result = resolve_plugin_graph(
            manifests,
            enabled_ids={"consumer", "provider"},
            preferred_order=("consumer", "provider"),
        )

        self.assertEqual(result.load_order, ("provider",))
        self.assertEqual(
            tuple(reason.code for reason in result.blocked["consumer"]),
            (
                "PLUGIN_DEPENDENCY_DISABLED",
                "PLUGIN_DEPENDENCY_MISSING",
                "PLUGIN_DEPENDENCY_VERSION_MISMATCH",
            ),
        )
        self.assertEqual(
            tuple(reason.dependency_id for reason in result.blocked["consumer"]),
            ("disabled", "missing", "provider"),
        )
        self.assertNotIn("disabled", result.blocked)

    def test_dependency_blocking_propagates_transitively(self):
        manifests = {
            "alpha": manifest("alpha", plugins={"beta": ">=1"}),
            "beta": manifest("beta", plugins={"charlie": ">=1"}),
            "charlie": manifest("charlie", plugins={"missing": ">=1"}),
        }

        result = resolve_plugin_graph(
            manifests,
            enabled_ids=manifests,
            preferred_order=("alpha", "beta", "charlie"),
        )

        self.assertEqual(result.load_order, ())
        self.assertEqual(result.blocked["charlie"][0].code, "PLUGIN_DEPENDENCY_MISSING")
        self.assertEqual(result.blocked["beta"][0].code, "PLUGIN_DEPENDENCY_BLOCKED")
        self.assertEqual(result.blocked["beta"][0].dependency_id, "charlie")
        self.assertEqual(result.blocked["alpha"][0].dependency_id, "beta")
        self.assertEqual(result.required_by["beta"], ("alpha",))
        self.assertEqual(result.required_by["charlie"], ("beta",))
        self.assertEqual(result.required_by["missing"], ("charlie",))

    def test_required_cycles_are_blocked_before_their_dependents(self):
        manifests = {
            "alpha": manifest("alpha", plugins={"beta": ">=1"}),
            "beta": manifest("beta", plugins={"alpha": ">=1"}),
            "consumer": manifest("consumer", plugins={"beta": ">=1"}),
            "free": manifest("free"),
        }

        result = resolve_plugin_graph(
            manifests,
            enabled_ids=manifests,
            preferred_order=("consumer", "free", "alpha", "beta"),
        )

        self.assertEqual(result.load_order, ("free",))
        self.assertEqual(result.blocked["alpha"][0].code, "PLUGIN_DEPENDENCY_CYCLE")
        self.assertEqual(result.blocked["beta"][0].code, "PLUGIN_DEPENDENCY_CYCLE")
        self.assertEqual(
            result.blocked["consumer"][0].code,
            "PLUGIN_DEPENDENCY_BLOCKED",
        )
        self.assertEqual(result.blocked["consumer"][0].dependency_id, "beta")

    def test_result_collections_are_immutable(self):
        manifests = {"alpha": manifest("alpha")}
        result = resolve_plugin_graph(manifests, {"alpha"}, ())

        with self.assertRaises(TypeError):
            result.blocked["alpha"] = ()
        with self.assertRaises(TypeError):
            result.required_by["alpha"] = ()


if __name__ == "__main__":
    unittest.main()
