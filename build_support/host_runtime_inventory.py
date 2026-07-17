from __future__ import annotations

from build_support._host_runtime_closure import (
    DistributionProvider,
    build_package_inventory,
)
from build_support._host_runtime_dlls import scan_runtime_dlls
from build_support._inventory_common import BuildInventoryError


def build_host_runtime_inventory(
    root_requirements,
    *,
    distribution_provider: DistributionProvider,
    marker_environment=None,
    top_level_overrides=None,
):
    """Build the exact installed package closure for explicit pinned roots."""

    return build_package_inventory(
        root_requirements,
        distribution_provider=distribution_provider,
        marker_environment=marker_environment,
        top_level_overrides=top_level_overrides,
    )


__all__ = [
    "BuildInventoryError",
    "DistributionProvider",
    "build_host_runtime_inventory",
    "scan_runtime_dlls",
]
