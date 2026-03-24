from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

import __main__
from core.logger import logger
from core.plugin_system.plugin_base import PluginBase
from plugins.thiefbook.config_widget import ConfigWidget
from plugins.thiefbook.lyrics_widget import LyricsWidget
from plugins.thiefbook.reader import ThiefBookReader


class ThiefBookPlugin(PluginBase):
    """
    Thief Book Plugin implementation.
    """

    def __init__(self, context):
        super().__init__(context)
        self._config_widget = None
        self._lyrics_widget = None
        self._reader = ThiefBookReader()

    def on_load(self):
        logger.info("Thief Book plugin loaded.")

        # Load config from state
        config = self.context.state.get(
            "config",
            {
                "txt_path": "",
                "current_page": 1,
                "page_length": 50,
                "is_english": False,
                "line_break": " ",
                "font_size": 16,
                "font_color": "#FFFFFF",
                "bg_opacity": 100,
                "is_locked": False,
                "show_lyrics": True,
            },
        )
        self._reader.update_config(config)

        # Ensure lyrics widget is created and updated
        if not self._lyrics_widget:
            self._lyrics_widget = LyricsWidget()
            self._lyrics_widget.position_changed.connect(self._on_lyrics_moved)

        self._lyrics_widget.apply_config(config)
        self._update_lyrics()

        if config.get("show_lyrics", True):
            self._lyrics_widget.show()
        else:
            self._lyrics_widget.hide()

        # Register shortcuts
        self._register_shortcuts()

    def on_unload(self):
        logger.info("Thief Book plugin unloaded.")
        if self._lyrics_widget:
            self._lyrics_widget.close()
            self._lyrics_widget = None

        self._unregister_shortcuts()

    # ── Widgets ──

    def get_thumbnail_widget(self) -> QWidget:
        # Returning None or a dummy widget. The sidebar will use get_icon() instead if missing
        return None

    def get_card_widget(self) -> QWidget:
        if not self._config_widget:
            self._config_widget = ConfigWidget()

            # Load config from state
            config = self.context.state.get(
                "config",
                {
                    "txt_path": "",
                    "current_page": 1,
                    "page_length": 50,
                    "is_english": False,
                    "line_break": " ",
                    "font_size": 16,
                    "font_color": "#FFFFFF",
                    "bg_opacity": 100,
                    "is_locked": False,
                    "show_lyrics": True,
                },
            )
            self._config_widget.set_config(config)

            # Populate shortcuts from settings_manager
            shortcut_mgr = __main__.app_instance.shortcut_manager
            shortcuts = {
                "toggle_lyrics": shortcut_mgr.settings_manager.get_setting(
                    "shortcuts", "thiefbook.toggle_lyrics", "ctrl+alt+h"
                ),
                "boss_key": shortcut_mgr.settings_manager.get_setting(
                    "shortcuts", "thiefbook.boss_key", "ctrl+m"
                ),
                "prev_page": shortcut_mgr.settings_manager.get_setting(
                    "shortcuts", "thiefbook.prev_page", "ctrl+,"
                ),
                "next_page": shortcut_mgr.settings_manager.get_setting(
                    "shortcuts", "thiefbook.next_page", "ctrl+."
                ),
                "jump_page": shortcut_mgr.settings_manager.get_setting(
                    "shortcuts", "thiefbook.jump_page", "ctrl+;"
                ),
            }
            self._config_widget.set_shortcuts(shortcuts)

            self._config_widget.config_changed.connect(self._on_config_changed)
            self._config_widget.shortcut_changed.connect(self._on_shortcut_changed)
            self._config_widget.keyword_search.connect(self._on_keyword_search)

        return self._config_widget

    def get_icon(self):
        return FluentIcon.BOOK_SHELF

    # ── Logic ──

    def _on_config_changed(self, config: dict):
        # Preserve show_lyrics state (which might not be in config UI)
        old_config = self.context.state.get("config", {})
        config["show_lyrics"] = old_config.get("show_lyrics", True)

        self.context.state.set("config", config)
        self._reader.update_config(config)
        if self._lyrics_widget:
            self._lyrics_widget.apply_config(config)
        self._update_lyrics()

    def _on_shortcut_changed(self, action_id: str, new_hotkey: str):
        # Update setting
        shortcut_mgr = __main__.app_instance.shortcut_manager
        shortcut_mgr.settings_manager.set_setting(
            "shortcuts", f"thiefbook.{action_id}", new_hotkey
        )

    def _on_keyword_search(self, keyword: str):
        if self._reader.search_keyword(keyword):
            self._update_lyrics()
            self._save_current_page()
        # # Apply updated shortcuts
        # self._unregister_shortcuts()
        # self._register_shortcuts()

    def _update_lyrics(self):
        if self._lyrics_widget:
            text = self._reader.get_current_text()
            self._lyrics_widget.set_text(text)

    def _on_lyrics_moved(self, x: int, y: int):
        config = self.context.state.get("config", {})
        config["window_x"] = x
        config["window_y"] = y
        self.context.state.set("config", config)

    def _save_current_page(self):
        # Save page number back to config without full re-load
        config = self.context.state.get("config", {})
        config["current_page"] = self._reader.current_page
        self.context.state.set("config", config)

        # Also update the config widget if it's open
        if self._config_widget:
            self._config_widget.update_page_display(self._reader.current_page)

    # ── Global Shortcuts Callback ──

    def _do_prev_page(self):
        if self._reader.prev_page():
            self._update_lyrics()
            self._save_current_page()

    def _do_next_page(self):
        if self._reader.next_page():
            self._update_lyrics()
            self._save_current_page()

    def _do_boss_key(self):
        if self._reader.toggle_boss_key():
            self._update_lyrics()

    def _do_toggle_lyrics(self):
        if self._lyrics_widget:
            config = self.context.state.get("config", {})
            current = config.get("show_lyrics", True)
            new_state = not current
            config["show_lyrics"] = new_state
            self.context.state.set("config", config)

            if new_state:
                self._lyrics_widget.show()
            else:
                self._lyrics_widget.hide()

    def _do_jump(self):
        # Focus the jump line edit in the config window
        # To do this, we need to make sure the detail view of this plugin is open
        self.context.open_detail_view()
        # The main app will open detail view asynchronously, so we delay focus jump slightly
        self.context.run_async(self._delayed_focus_jump)

    def _delayed_focus_jump(self):
        import time

        time.sleep(0.5)
        self.context.throttle_ui(
            lambda: self._config_widget.focus_jump() if self._config_widget else None
        )

    def _register_shortcuts(self):
        shortcut_mgr = __main__.app_instance.shortcut_manager

        shortcut_mgr.register_shortcut(
            "thiefbook.toggle_lyrics", "ctrl+alt+h", self._do_toggle_lyrics
        )
        shortcut_mgr.register_shortcut(
            "thiefbook.prev_page", "ctrl+,", self._do_prev_page
        )
        shortcut_mgr.register_shortcut(
            "thiefbook.next_page", "ctrl+.", self._do_next_page
        )
        shortcut_mgr.register_shortcut(
            "thiefbook.boss_key", "ctrl+m", self._do_boss_key
        )
        shortcut_mgr.register_shortcut("thiefbook.jump_page", "ctrl+;", self._do_jump)

    def _unregister_shortcuts(self):
        shortcut_mgr = __main__.app_instance.shortcut_manager

        shortcut_mgr.unregister_shortcut("thiefbook.toggle_lyrics")
        shortcut_mgr.unregister_shortcut("thiefbook.prev_page")
        shortcut_mgr.unregister_shortcut("thiefbook.next_page")
        shortcut_mgr.unregister_shortcut("thiefbook.boss_key")
        shortcut_mgr.unregister_shortcut("thiefbook.jump_page")
