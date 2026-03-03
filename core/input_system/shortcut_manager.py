"""
Shortcut Manager
Handles global hotkey registration and callbacks.
Uses Windows native RegisterHotKey API via ctypes + QAbstractNativeEventFilter.
This approach is robust against lock-screen / sleep scenarios where
keyboard-hook based solutions (like the `keyboard` library) fail.
"""

import ctypes
import ctypes.wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

from core.logger import logger

# ── Windows constants ──────────────────────────────────────────────
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000  # Prevent key-repeat from firing the hotkey

WM_HOTKEY = 0x0312

# Modifier string → flag mapping
_MODIFIER_MAP = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
    "super": MOD_WIN,
}

# Common key name → virtual-key code mapping
_VK_MAP = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "page up": 0x21,
    "pagedown": 0x22,
    "page down": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "capslock": 0x14,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "printscreen": 0x2C,
    "pause": 0x13,
    # Function keys
    **{f"f{i}": (0x70 + i - 1) for i in range(1, 25)},
    # Numpad
    **{f"num{i}": (0x60 + i) for i in range(0, 10)},
    "multiply": 0x6A,
    "add": 0x6B,
    "subtract": 0x6D,
    "decimal": 0x6E,
    "divide": 0x6F,
    # Punctuation / misc  (US keyboard layout VK codes)
    ";": 0xBA,
    "=": 0xBB,
    ",": 0xBC,
    "-": 0xBD,
    ".": 0xBE,
    "/": 0xBF,
    "`": 0xC0,
    "[": 0xDB,
    "\\": 0xDC,
    "]": 0xDD,
    "'": 0xDE,
}


def _parse_hotkey(hotkey_str: str):
    """
    Parse a hotkey string like "alt+space" or "ctrl+shift+p"
    into (modifiers_flags, vk_code).

    Returns (None, None) on failure.
    """
    if not hotkey_str:
        return None, None

    parts = [p.strip().lower() for p in hotkey_str.split("+")]
    modifiers = MOD_NOREPEAT  # always include NOREPEAT
    vk = None

    for part in parts:
        if part in _MODIFIER_MAP:
            modifiers |= _MODIFIER_MAP[part]
        else:
            # Try named key
            if part in _VK_MAP:
                vk = _VK_MAP[part]
            elif len(part) == 1 and part.isalnum():
                # Single letter / digit → VkKeyScanW
                vk = ctypes.windll.user32.VkKeyScanW(ord(part)) & 0xFF
            else:
                logger.warning(f"Unknown key token: '{part}' in hotkey '{hotkey_str}'")
                return None, None

    if vk is None:
        logger.warning(f"No key code resolved for hotkey: '{hotkey_str}'")
        return None, None

    return modifiers, vk


# ── Native event filter ───────────────────────────────────────────
class _HotkeyNativeFilter(QAbstractNativeEventFilter):
    """
    Intercepts WM_HOTKEY messages from the Windows message queue
    and dispatches them to the ShortcutManager.
    """

    def __init__(self, manager: "ShortcutManager"):
        super().__init__()
        self._manager = manager

    # PySide6 signature: nativeEventFilter(eventType, message) -> (bool, result)
    def nativeEventFilter(self, eventType, message):
        try:
            if eventType == b"windows_generic_MSG":
                # message is a sip.voidptr / int – we need to read MSG.message
                # MSG struct layout (x64):
                #   HWND  hwnd    (8 bytes)
                #   UINT  message (4 bytes)  <- offset 8
                #   ...
                msg_ptr = int(message)
                # Read the UINT message field at offset 8 (64-bit) or 4 (32-bit)
                ptr_size = ctypes.sizeof(ctypes.c_void_p)
                msg_id = ctypes.c_uint.from_address(msg_ptr + ptr_size).value

                if msg_id == WM_HOTKEY:
                    # wParam is the hotkey id; at offset ptr_size + 4 (UINT size)
                    wparam = ctypes.c_ulonglong.from_address(
                        msg_ptr + ptr_size + 4
                    ).value
                    # Pad-align: on x64 wParam is at offset 16 actually
                    # Correct way: use struct-based parsing
                    wparam = self._read_wparam(msg_ptr)
                    self._manager._on_hotkey_triggered(int(wparam))
                    return True, 0
        except Exception as e:
            logger.error(f"Error in native event filter: {e}", exc_info=True)

        return False, 0

    @staticmethod
    def _read_wparam(msg_ptr: int) -> int:
        """Read wParam from a native MSG struct pointer."""
        # On 64-bit Windows the MSG struct is:
        #   HWND   hwnd     8 bytes  (offset 0)
        #   UINT   message  4 bytes  (offset 8)
        #   <pad>           4 bytes  (offset 12)  ← alignment to 8
        #   WPARAM wParam   8 bytes  (offset 16)
        #
        # On 32-bit Windows:
        #   HWND   hwnd     4 bytes  (offset 0)
        #   UINT   message  4 bytes  (offset 4)
        #   WPARAM wParam   4 bytes  (offset 8)
        ptr_size = ctypes.sizeof(ctypes.c_void_p)
        if ptr_size == 8:
            # 64-bit
            return ctypes.c_ulonglong.from_address(msg_ptr + 16).value
        else:
            # 32-bit
            return ctypes.c_ulong.from_address(msg_ptr + 8).value


# ── ShortcutManager ───────────────────────────────────────────────
class ShortcutManager:
    """
    Manages global shortcuts for the application using
    Windows RegisterHotKey API.
    """

    def __init__(self, settings_manager):
        self.settings_manager = settings_manager
        self.shortcuts = {}  # action_id -> {hotkey, callback, hk_id, modifiers, vk}
        self.enabled = True
        self._next_hk_id = 1  # auto-incrementing hotkey id
        self._hk_id_to_action = {}  # hk_id -> action_id  (reverse lookup)

        # Native event filter (installed later via install_filter)
        self._filter = _HotkeyNativeFilter(self)

        # Listen for settings changes
        self.settings_manager.settings_changed.connect(self._on_settings_changed)

    # ── Public API ────────────────────────────────────────────────
    def install_filter(self, app):
        """
        Install the native event filter on the QApplication.
        Must be called once from main after QApplication is created.
        """
        app.installNativeEventFilter(self._filter)

    def register_shortcut(self, action_id: str, default_hotkey: str, callback):
        """
        Register a shortcut for an action.
        If a custom hotkey exists in settings, it uses that.
        Otherwise uses default_hotkey.
        """
        stored_hotkey = self.settings_manager.get_setting(
            "shortcuts", action_id, default_hotkey
        )

        hk_id = self._next_hk_id
        self._next_hk_id += 1

        self.shortcuts[action_id] = {
            "hotkey": stored_hotkey,
            "callback": callback,
            "hk_id": hk_id,
            "registered": False,
        }
        self._hk_id_to_action[hk_id] = action_id

        self._apply_shortcut(action_id)

    def unregister_shortcut(self, action_id: str):
        """Remove a shortcut."""
        data = self.shortcuts.get(action_id)
        if data:
            self._unregister_native(data)
            self._hk_id_to_action.pop(data["hk_id"], None)
            del self.shortcuts[action_id]

    def set_enabled(self, enabled: bool):
        """Enable or disable all shortcuts."""
        self.enabled = enabled
        if enabled:
            for action_id in self.shortcuts:
                self._apply_shortcut(action_id)
        else:
            for data in self.shortcuts.values():
                self._unregister_native(data)

    # ── Internal ──────────────────────────────────────────────────
    def _apply_shortcut(self, action_id: str):
        """Register the hotkey with the OS."""
        if not self.enabled:
            return

        data = self.shortcuts.get(action_id)
        if not data:
            return

        # Unregister if previously registered
        self._unregister_native(data)

        hotkey = data["hotkey"]
        if not hotkey:
            return

        modifiers, vk = _parse_hotkey(hotkey)
        if modifiers is None or vk is None:
            logger.error(f"Could not parse hotkey '{hotkey}' for action '{action_id}'")
            return

        hk_id = data["hk_id"]
        ok = ctypes.windll.user32.RegisterHotKey(None, hk_id, modifiers, vk)
        if ok:
            data["registered"] = True
            logger.info(
                f"Shortcut registered for {action_id}: {hotkey}  "
                f"(id={hk_id}, mod=0x{modifiers:04X}, vk=0x{vk:02X})"
            )
        else:
            err = ctypes.GetLastError()
            logger.error(
                f"RegisterHotKey failed for {action_id} ({hotkey}): error code {err}"
            )

    def _unregister_native(self, data: dict):
        """Unregister a single hotkey from the OS."""
        if data.get("registered"):
            ctypes.windll.user32.UnregisterHotKey(None, data["hk_id"])
            data["registered"] = False

    def _on_hotkey_triggered(self, hk_id: int):
        """Called by the native event filter when WM_HOTKEY fires."""
        action_id = self._hk_id_to_action.get(hk_id)
        if not action_id:
            return

        data = self.shortcuts.get(action_id)
        if not data:
            return

        callback = data["callback"]
        try:
            callback()
        except Exception as e:
            logger.error(
                f"Error in shortcut callback for {action_id}: {e}", exc_info=True
            )

    def _on_settings_changed(self, category, key, value):
        """Handle settings changes to update shortcuts."""
        if category == "shortcuts":
            if key in self.shortcuts:
                self.shortcuts[key]["hotkey"] = value
                self._apply_shortcut(key)
