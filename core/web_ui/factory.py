from typing import Iterable

from .web_plugin_host import WebPluginHost


def create_web_plugin_view(
    registry,
    owner_id: str,
    content_root,
    *,
    entry: str = "index.html",
    capabilities: Iterable[str] = (),
    autoload: bool = True,
    parent=None,
):
    """Create the configured QWidget web provider for a plugin surface."""
    return WebPluginHost(
        registry,
        owner_id,
        content_root,
        entry=entry,
        capabilities=capabilities,
        autoload=autoload,
        parent=parent,
    )
