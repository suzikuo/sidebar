from typing import Iterable

from .contracts import WebViewHost
from .runtime import ensure_native_qwebview_available


def create_web_plugin_view(
    registry,
    owner_id: str,
    content_root,
    *,
    entry: str = "index.html",
    capabilities: Iterable[str] = (),
    autoload: bool = True,
    parent=None,
) -> WebViewHost:
    """Create the configured QWidget web provider for a plugin surface."""
    ensure_native_qwebview_available()
    from .web_plugin_host import WebPluginHost

    return WebPluginHost(
        registry,
        owner_id,
        content_root,
        entry=entry,
        capabilities=capabilities,
        autoload=autoload,
        parent=parent,
    )
