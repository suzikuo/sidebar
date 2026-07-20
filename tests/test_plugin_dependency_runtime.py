import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.plugin_system.plugin_dependency_resolver import (
    PluginDependencyResolutionError,
)
from core.plugin_system.plugin_dependency_runtime import (
    PluginDependencyRuntime,
    PluginDependencyRuntimeError,
)
from core.plugin_system.plugin_manifest import HostEnvironment


class _Store:
    def __init__(self):
        self.calls = []

    def materialize_many(self, artifacts, **kwargs):
        self.calls.append((tuple(artifacts), kwargs))
        return ("stored-grpc",)


class _Lease:
    def __init__(self):
        self.active = True
        self.closed = False

    def close(self):
        self.closed = True
        self.active = False


class PluginDependencyRuntimeTest(unittest.TestCase):
    @staticmethod
    def _host():
        return HostEnvironment(
            app_version="1.0.0",
            api_version="1.0",
            python_abi="cp311",
            platform_tag="win_amd64",
            host_packages={},
        )

    @staticmethod
    def _manifest(*, managed):
        return SimpleNamespace(
            dependencies=SimpleNamespace(python=("grpcio",) if managed else ())
        )

    def test_no_declared_dependencies_skips_store_and_activation(self):
        store = _Store()
        activated = []
        runtime = PluginDependencyRuntime(
            store=store,
            activate=lambda dependencies: activated.append(tuple(dependencies)),
        )

        prepared = runtime.prepare(
            {"plain": self._manifest(managed=False)},
            {"plain": "unused"},
            self._host(),
        )

        self.assertEqual(prepared, ())
        self.assertEqual(store.calls, [])
        self.assertEqual(activated, [])

    def test_materializes_resolved_set_once_and_closes_on_shutdown(self):
        store = _Store()
        lease = _Lease()
        runtime = PluginDependencyRuntime(store=store, activate=lambda _: lease)
        resolved = SimpleNamespace(
            python_abi="cp311",
            platform_tag="win_amd64",
            packages=(SimpleNamespace(artifact="grpc-wheel"),),
        )

        with patch.object(
            runtime,
            "_load_input",
            return_value="validated-input",
        ), patch(
            "core.plugin_system.plugin_dependency_runtime.resolve_dependency_set",
            return_value=resolved,
        ) as resolver:
            prepared = runtime.prepare(
                {"network_monitor": self._manifest(managed=True)},
                {"network_monitor": "plugin-path"},
                self._host(),
            )

        self.assertEqual(prepared, ("network_monitor",))
        self.assertTrue(runtime.active)
        resolver.assert_called_once()
        self.assertEqual(store.calls, [(("grpc-wheel",), {
            "target_python_abi": "cp311",
            "target_platform": "win_amd64",
        })])

        runtime.close()

        self.assertTrue(lease.closed)
        self.assertFalse(runtime.active)

    def test_resolution_failure_blocks_all_managed_plugins(self):
        runtime = PluginDependencyRuntime(store=_Store(), activate=lambda _: _Lease())
        error = PluginDependencyResolutionError(
            "DEPENDENCY_VERSION_CONFLICT",
            "Plugins require different grpcio versions.",
        )

        with patch.object(runtime, "_load_input", return_value="validated-input"), patch(
            "core.plugin_system.plugin_dependency_runtime.resolve_dependency_set",
            side_effect=error,
        ):
            with self.assertRaises(PluginDependencyRuntimeError) as caught:
                runtime.prepare(
                    {
                        "network_monitor": self._manifest(managed=True),
                        "other": self._manifest(managed=True),
                    },
                    {"network_monitor": "first", "other": "second"},
                    self._host(),
                )

        self.assertEqual(caught.exception.code, "DEPENDENCY_VERSION_CONFLICT")
        self.assertEqual(
            caught.exception.plugin_ids,
            ("network_monitor", "other"),
        )


if __name__ == "__main__":
    unittest.main()
