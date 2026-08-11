__all__ = [
    "WebApiBridge",
    "WebPluginHost",
    "WebViewHost",
    "create_web_plugin_view",
    "is_web_url_allowed",
    "detect_webview2_runtime",
    "ensure_native_qwebview_available",
    "missing_runtime_message",
    "resolve_web_entry",
]


def __getattr__(name):
    if name == "WebApiBridge":
        from .api_bridge import WebApiBridge

        return WebApiBridge
    if name == "create_web_plugin_view":
        from .factory import create_web_plugin_view

        return create_web_plugin_view
    if name == "WebViewHost":
        from .contracts import WebViewHost

        return WebViewHost
    if name in {"WebPluginHost", "is_web_url_allowed", "resolve_web_entry"}:
        from .web_plugin_host import (
            WebPluginHost,
            is_web_url_allowed,
            resolve_web_entry,
        )

        return {
            "WebPluginHost": WebPluginHost,
            "is_web_url_allowed": is_web_url_allowed,
            "resolve_web_entry": resolve_web_entry,
        }[name]
    if name in {
        "detect_webview2_runtime",
        "ensure_native_qwebview_available",
        "missing_runtime_message",
    }:
        from .runtime import (
            detect_webview2_runtime,
            ensure_native_qwebview_available,
            missing_runtime_message,
        )

        return {
            "detect_webview2_runtime": detect_webview2_runtime,
            "ensure_native_qwebview_available": ensure_native_qwebview_available,
            "missing_runtime_message": missing_runtime_message,
        }[name]
    raise AttributeError(name)
