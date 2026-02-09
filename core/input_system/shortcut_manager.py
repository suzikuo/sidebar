"""
Shortcut Manager
Handles global hotkey registration and callbacks.
Uses the `keyboard` library.
"""

import time

import keyboard

from core.logger import logger


class ShortcutManager:
    """
    Manages global shortcuts for the application.
    """

    def __init__(self, settings_manager):
        self.settings_manager = settings_manager
        self.shortcuts = {}  # action_id -> {hotkey: str, callback: callable}
        self.enabled = True

        # Listen for settings changes to update shortcuts dynamically
        self.settings_manager.settings_changed.connect(self._on_settings_changed)

    def register_shortcut(self, action_id, default_hotkey, callback):
        """
        Register a shortcut for an action.
        If a custom hotkey exists in settings, it uses that.
        Otherwise uses default_hotkey.
        """
        # Get stored hotkey or use default
        stored_hotkey = self.settings_manager.get_setting(
            "shortcuts", action_id, default_hotkey
        )

        self.shortcuts[action_id] = {
            "hotkey": stored_hotkey,
            "callback": callback,
            "hook": None,
        }

        self._apply_shortcut(action_id)

    def _apply_shortcut(self, action_id):
        """Apply the shortcut using the keyboard library."""
        if not self.enabled:
            return

        data = self.shortcuts.get(action_id)
        if not data:
            return

        hotkey = data["hotkey"]
        callback = data["callback"]

        # Remove existing hook if any
        if data.get("hook"):
            try:
                keyboard.remove_hotkey(data["hook"])
            except Exception:
                pass
            data["hook"] = None

        if hotkey:
            try:
                # Use call_soon_threadsafe if callback interacts with QT
                # But here we just assume the callback handles thread safety or is simple
                # Actually keyboard callbacks run in a separate thread, so we should be careful.
                # However, for showing windows/signals, Qt signals are thread-safe.
                data["hook"] = keyboard.add_hotkey(
                    hotkey, lambda: self._safe_callback(callback), suppress=True
                )
                logger.info(f"Shortcut registered for {action_id}: {hotkey}")
            except Exception as e:
                logger.error(
                    f"Failed to register shortcut for {action_id} ({hotkey}): {e}",
                    exc_info=True,
                )

    def _safe_callback(self, callback):
        """Execute callback and handle errors."""
        try:
            callback()
        except Exception as e:
            logger.error(
                f"Error in shortcut callback for {callback}: {e}", exc_info=True
            )
            # Prevent rapid firing issues?
            time.sleep(0.1)

    def unregister_shortcut(self, action_id):
        """Remove a shortcut."""
        data = self.shortcuts.get(action_id)
        if data and data.get("hook"):
            try:
                keyboard.remove_hotkey(data["hook"])
            except Exception:
                pass
        if action_id in self.shortcuts:
            del self.shortcuts[action_id]

    def _on_settings_changed(self, category, key, value):
        """Handle settings changes to update shortcuts."""
        if category == "shortcuts":
            if key in self.shortcuts:
                # Update stored hotkey
                self.shortcuts[key]["hotkey"] = value
                # Re-apply
                self._apply_shortcut(key)

    def set_enabled(self, enabled):
        """Enable or disable all shortcuts."""
        self.enabled = enabled
        if enabled:
            for action_id in self.shortcuts:
                self._apply_shortcut(action_id)
        else:
            keyboard.unhook_all_hotkeys()
            for data in self.shortcuts.values():
                data["hook"] = None
