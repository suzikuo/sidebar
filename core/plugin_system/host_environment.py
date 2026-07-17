from importlib import metadata
from pathlib import Path
from typing import Mapping

from packaging.tags import interpreter_name, interpreter_version, platform_tags

from core.data_layer.path_utils import PathManager
from core.plugin_system.api_contract import CURRENT_API_VERSION
from core.plugin_system.plugin_manifest import HostEnvironment, PluginManifestError


HOST_DISTRIBUTIONS = (
    "PySide6",
    "PySide6-Fluent-Widgets",
    "aiohttp",
    "cryptography",
    "packaging",
    "paramiko",
)


def read_app_version(base_dir: Path | None = None) -> str:
    """Read the application version shipped beside source or frozen assets."""

    version_path = (base_dir or PathManager.get_base_dir()) / "VERSION"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise PluginManifestError(
            "INVALID_HOST_ENVIRONMENT",
            f"Cannot read application version: {error}",
            field="app_version",
        ) from error
    if not version:
        raise PluginManifestError(
            "INVALID_HOST_ENVIRONMENT",
            "Application version file is empty.",
            field="app_version",
        )
    return version


def collect_host_package_versions() -> dict[str, str]:
    """Return versions for the explicit packages plugins may consume from host."""

    versions = {}
    for distribution in HOST_DISTRIBUTIONS:
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            continue
    return versions


def build_host_environment(
    *,
    app_version: str | None = None,
    host_packages: Mapping[str, str] | None = None,
) -> HostEnvironment:
    """Build normalized runtime compatibility facts for plugin validation."""

    try:
        platform_tag = next(platform_tags())
    except StopIteration as error:
        raise PluginManifestError(
            "INVALID_HOST_ENVIRONMENT",
            "Cannot determine the current platform tag.",
            field="platform_tag",
        ) from error

    return HostEnvironment(
        app_version=app_version or read_app_version(),
        api_version=str(CURRENT_API_VERSION),
        python_abi=f"{interpreter_name()}{interpreter_version()}",
        platform_tag=platform_tag,
        host_packages=(
            dict(host_packages)
            if host_packages is not None
            else collect_host_package_versions()
        ),
    )
