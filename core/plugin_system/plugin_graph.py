from __future__ import annotations

from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from types import MappingProxyType
from typing import Iterable, Mapping

from core.plugin_system.plugin_manifest import PluginManifest


@dataclass(frozen=True)
class PluginBlockReason:
    code: str
    dependency_id: str | None
    message: str


@dataclass(frozen=True)
class PluginGraphResult:
    load_order: tuple[str, ...]
    blocked: Mapping[str, tuple[PluginBlockReason, ...]]
    required_by: Mapping[str, tuple[str, ...]]


def resolve_plugin_graph(
    manifests: Mapping[str, PluginManifest],
    enabled_ids: Iterable[str],
    preferred_order: Iterable[str] = (),
) -> PluginGraphResult:
    """Resolve required plugin relationships without enabling or installing anything."""

    manifest_map = dict(manifests)
    enabled = frozenset(enabled_ids)
    rank = {}
    for plugin_id in preferred_order:
        if plugin_id in enabled and plugin_id not in rank:
            rank[plugin_id] = len(rank)
    order_key = lambda plugin_id: (rank.get(plugin_id, len(rank)), plugin_id)
    ordered_enabled = tuple(sorted(enabled, key=order_key))

    reverse_dependencies: dict[str, list[str]] = {}
    blocked: dict[str, tuple[PluginBlockReason, ...]] = {}
    for plugin_id in ordered_enabled:
        reasons = []
        for requirement in manifest_map[plugin_id].dependencies.plugins:
            reverse_dependencies.setdefault(requirement.plugin_id, []).append(plugin_id)
            dependency = manifest_map.get(requirement.plugin_id)
            if dependency is None:
                reasons.append(
                    PluginBlockReason(
                        "PLUGIN_DEPENDENCY_MISSING",
                        requirement.plugin_id,
                        f"Required plugin is not installed: {requirement.plugin_id}",
                    )
                )
            elif requirement.plugin_id not in enabled:
                reasons.append(
                    PluginBlockReason(
                        "PLUGIN_DEPENDENCY_DISABLED",
                        requirement.plugin_id,
                        f"Required plugin is disabled: {requirement.plugin_id}",
                    )
                )
            elif not requirement.accepts(dependency.version):
                reasons.append(
                    PluginBlockReason(
                        "PLUGIN_DEPENDENCY_VERSION_MISMATCH",
                        requirement.plugin_id,
                        f"Required plugin version is incompatible: {requirement.plugin_id}",
                    )
                )
        if reasons:
            blocked[plugin_id] = tuple(reasons)

    _propagate_blocked_dependencies(blocked, manifest_map, ordered_enabled)
    while True:
        graph = _active_graph(manifest_map, enabled, blocked)
        sorter = TopologicalSorter(graph)
        try:
            sorter.prepare()
        except CycleError as error:
            cycle_nodes = frozenset(error.args[1])
            for plugin_id in sorted(cycle_nodes, key=order_key):
                blocked[plugin_id] = (
                    PluginBlockReason(
                        "PLUGIN_DEPENDENCY_CYCLE",
                        None,
                        "Plugin is part of a required dependency cycle.",
                    ),
                )
            _propagate_blocked_dependencies(blocked, manifest_map, ordered_enabled)
            continue
        break

    load_order = []
    while sorter.is_active():
        ready = tuple(sorted(sorter.get_ready(), key=order_key))
        load_order.extend(ready)
        sorter.done(*ready)

    required_by = {
        plugin_id: tuple(sorted(dependents, key=order_key))
        for plugin_id, dependents in sorted(reverse_dependencies.items())
    }
    return PluginGraphResult(
        load_order=tuple(load_order),
        blocked=MappingProxyType(dict(sorted(blocked.items()))),
        required_by=MappingProxyType(required_by),
    )


def _active_graph(manifests, enabled, blocked):
    active = enabled - blocked.keys()
    return {
        plugin_id: {
            requirement.plugin_id
            for requirement in manifests[plugin_id].dependencies.plugins
            if requirement.plugin_id in active
        }
        for plugin_id in sorted(active)
    }


def _propagate_blocked_dependencies(blocked, manifests, ordered_enabled) -> None:
    changed = True
    while changed:
        changed = False
        for plugin_id in ordered_enabled:
            if plugin_id in blocked:
                continue
            reasons = tuple(
                PluginBlockReason(
                    "PLUGIN_DEPENDENCY_BLOCKED",
                    requirement.plugin_id,
                    f"Required plugin cannot load: {requirement.plugin_id}",
                )
                for requirement in manifests[plugin_id].dependencies.plugins
                if requirement.plugin_id in blocked
            )
            if reasons:
                blocked[plugin_id] = reasons
                changed = True
__all__ = [
    "PluginBlockReason",
    "PluginGraphResult",
    "resolve_plugin_graph",
]
