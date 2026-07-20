"""Prepare one verified third-party dependency set before plugin imports."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from core.plugin_system.plugin_dependency_activation import (
    DependencyActivationLease,
    PluginDependencyActivationError,
)
from core.plugin_system.plugin_dependency_lock import (
    parse_and_validate_dependency_lock,
)
from core.plugin_system.plugin_dependency_resolver import (
    PluginDependencyInput,
    PluginDependencyResolutionError,
    resolve_dependency_set,
)
from core.plugin_system.plugin_integrity import validate_plugin_directory
from core.plugin_system.plugin_manifest import (
    HostEnvironment,
    PluginManifest,
    PluginManifestError,
)
from core.plugin_system.plugin_wheel import PluginWheelError, inspect_wheel


class PluginDependencyRuntimeError(RuntimeError):
    """A managed dependency failure that blocks one or more plugins."""

    def __init__(self, code: str, message: str, plugin_ids=()):
        super().__init__(message)
        self.code = code
        self.plugin_ids = tuple(sorted(set(plugin_ids)))


class PluginDependencyRuntime:
    """Materialize and activate declared plugin wheels once per application run."""

    def __init__(self, store=None, activate=None):
        if store is None:
            from core.plugin_system.plugin_dependency_store import PluginDependencyStore

            store = PluginDependencyStore()
        self._store = store
        self._activate = activate or DependencyActivationLease.activate
        self._lease = None
        self._prepared_plugin_ids = ()

    @property
    def active(self) -> bool:
        return self._lease is not None and self._lease.active

    @property
    def prepared_plugin_ids(self) -> tuple[str, ...]:
        return self._prepared_plugin_ids

    def prepare(self, manifests: Mapping[str, PluginManifest], plugin_paths, host):
        """Activate dependencies for enabled plugins before any plugin module imports."""

        if self._lease is not None:
            raise PluginDependencyRuntimeError(
                "DEPENDENCY_RUNTIME_ALREADY_PREPARED",
                "Plugin dependency runtime is already prepared; restart to change it.",
                self._prepared_plugin_ids,
            )
        if not isinstance(host, HostEnvironment):
            raise PluginDependencyRuntimeError(
                "INVALID_HOST_ENVIRONMENT",
                "Managed dependencies require a valid plugin host environment.",
            )

        managed_ids = tuple(
            sorted(
                plugin_id
                for plugin_id, manifest in manifests.items()
                if manifest.dependencies.python
            )
        )
        if not managed_ids:
            return ()

        try:
            inputs = {
                plugin_id: self._load_input(
                    plugin_id,
                    manifests[plugin_id],
                    plugin_paths[plugin_id],
                )
                for plugin_id in managed_ids
            }
            resolved = resolve_dependency_set(
                inputs,
                host_packages=host.host_packages,
                host_imports=host.host_imports,
                host_dll_basenames=host.host_dll_basenames,
            )
            stored = self._store.materialize_many(
                (item.artifact for item in resolved.packages),
                target_python_abi=resolved.python_abi,
                target_platform=resolved.platform_tag,
            )
            self._lease = self._activate(stored)
        except PluginDependencyRuntimeError:
            raise
        except PluginManifestError as error:
            raise PluginDependencyRuntimeError(
                error.code,
                str(error),
                managed_ids,
            ) from error
        except PluginWheelError as error:
            raise PluginDependencyRuntimeError(
                error.code,
                str(error),
                managed_ids,
            ) from error
        except PluginDependencyResolutionError as error:
            raise PluginDependencyRuntimeError(
                error.code,
                str(error),
                managed_ids,
            ) from error
        except PluginDependencyActivationError as error:
            raise PluginDependencyRuntimeError(
                error.code,
                str(error),
                managed_ids,
            ) from error
        except Exception as error:
            raise PluginDependencyRuntimeError(
                getattr(error, "code", "DEPENDENCY_RUNTIME_FAILED"),
                str(error),
                managed_ids,
            ) from error

        self._prepared_plugin_ids = managed_ids
        return managed_ids

    def close(self):
        lease = self._lease
        self._lease = None
        self._prepared_plugin_ids = ()
        if lease is not None:
            lease.close()

    @staticmethod
    def _load_input(plugin_id: str, manifest: PluginManifest, plugin_path):
        root = Path(plugin_path).resolve(strict=True)
        validate_plugin_directory(root, manifest)
        lock_path = root.joinpath(*manifest.dependencies.lock.split("/"))
        lock = parse_and_validate_dependency_lock(lock_path.read_bytes(), manifest)
        artifacts = tuple(
            inspect_wheel(
                root.joinpath(*package.wheel.split("/")),
                target_python_abi=lock.target.python_abi,
                target_platform=lock.target.platform_tag,
                expected_name=package.name,
                expected_version=package.version,
                expected_sha256=package.sha256,
            )
            for package in lock.packages
        )
        return PluginDependencyInput(lock=lock, wheels=artifacts)


__all__ = ["PluginDependencyRuntime", "PluginDependencyRuntimeError"]
