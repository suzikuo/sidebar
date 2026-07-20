"""Trusted local plugin package catalog used by the control center."""

from collections.abc import Mapping
from pathlib import Path

from packaging.version import Version

from core.plugin_system.plugin_manifest import (
    PluginManifestError,
    check_compatibility,
)
from core.plugin_system.plugin_package import (
    PluginPackageError,
    inspect_plugin_package,
)


class PluginCatalogService:
    def __init__(self, package_dirs, plugin_manager):
        self._package_dirs = tuple(
            Path(path).expanduser().resolve(strict=False) for path in package_dirs
        )
        self._plugin_manager = plugin_manager
        self._packages = {}

    def snapshot(self):
        entries, errors = self._scan()
        statuses = {
            status.plugin_id: status
            for status in self._plugin_manager.get_plugin_statuses()
        }
        catalog = []
        for plugin_id, package_info in sorted(
            entries.items(), key=lambda item: item[1].normalized_manifest.name.casefold()
        ):
            manifest = package_info.normalized_manifest
            status = statuses.get(plugin_id)
            compatible, compatibility_code, compatibility_message = (
                self._compatibility(manifest)
            )
            installed_version = (
                status.selected_version or status.user_version if status else None
            )
            action = self._action_for(
                manifest.version,
                installed_version,
                status,
                compatible,
            )
            marketplace = manifest.extensions.get("marketplace", {})
            if not isinstance(marketplace, Mapping):
                marketplace = {}
            catalog.append(
                {
                    "pluginId": plugin_id,
                    "name": manifest.name,
                    "version": str(manifest.version),
                    "author": manifest.author,
                    "description": manifest.description,
                    "category": str(marketplace.get("category") or "工具"),
                    "compatible": compatible,
                    "compatibilityCode": compatibility_code,
                    "compatibilityMessage": compatibility_message,
                    "installedVersion": installed_version,
                    "enabled": status.enabled if status else False,
                    "restartRequired": status.restart_required if status else False,
                    "action": action,
                }
            )
        return {"entries": catalog, "errors": errors}

    def package_path(self, plugin_id):
        self._scan()
        package_info = self._packages.get(plugin_id)
        if package_info is None:
            return None
        compatible, _, _ = self._compatibility(package_info.normalized_manifest)
        return package_info.package_path if compatible else None

    def _scan(self):
        selected = {}
        errors = []
        for package_dir in self._package_dirs:
            if not package_dir.is_dir():
                continue
            for package_path in sorted(
                package_dir.glob("*.atplugin"), key=lambda path: path.name.casefold()
            ):
                try:
                    info = inspect_plugin_package(package_path)
                except (PluginPackageError, OSError) as error:
                    errors.append(
                        {
                            "package": package_path.name,
                            "code": getattr(error, "code", "PACKAGE_READ_FAILED"),
                            "message": str(error),
                        }
                    )
                    continue
                current = selected.get(info.plugin_id)
                if (
                    current is None
                    or info.normalized_manifest.version
                    > current.normalized_manifest.version
                ):
                    selected[info.plugin_id] = info
        self._packages = selected
        return selected, errors

    def _compatibility(self, manifest):
        host = self._plugin_manager.host_environment
        if host is None:
            return False, "HOST_ENVIRONMENT_UNAVAILABLE", "宿主兼容性信息不可用。"
        try:
            check_compatibility(manifest, host)
        except PluginManifestError as error:
            return False, error.code, str(error)
        return True, None, None

    @staticmethod
    def _action_for(catalog_version, installed_version, status, compatible):
        if not compatible:
            return "incompatible"
        if status and status.transaction and status.transaction.requires_restart:
            return "pending"
        if not installed_version:
            return "install"
        try:
            installed = Version(str(installed_version))
        except Exception:
            return "update"
        if catalog_version > installed:
            return "update"
        if catalog_version < installed:
            return "older"
        return "installed"
