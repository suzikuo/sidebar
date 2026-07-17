import unittest
from dataclasses import replace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from core.plugin_system.plugin_status import PluginStatus, PluginTransactionStatus
from core.settings.fluent_settings_card import FluentSettingsCard


def _status(plugin_id, **changes):
    status = PluginStatus(
        plugin_id=plugin_id,
        name=plugin_id.replace("_", " ").title(),
        selected_version="1.0.0",
        source="bundled",
        enabled=True,
        user_present=False,
        user_version=None,
        transaction=None,
        can_uninstall=False,
        can_rollback=False,
        restart_required=False,
        loaded=True,
    )
    return replace(status, **changes)


class _PluginManager:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.order = [status.plugin_id for status in statuses if status.selected_version]
        self.calls = []
        self.enable_result = (True, "Plugin state updated.")

    def get_plugin_statuses(self):
        return tuple(self.statuses)

    def get_plugin_order(self):
        return list(self.order)

    def set_plugin_order(self, order):
        self.order = list(order)

    def set_plugin_enabled(self, plugin_id, enabled):
        self.calls.append(("enable", plugin_id, enabled))
        if self.enable_result[0]:
            self.statuses = [
                replace(status, enabled=enabled, loaded=enabled)
                if status.plugin_id == plugin_id
                else status
                for status in self.statuses
            ]
        return self.enable_result

    def install_plugin(self, path):
        self.calls.append(("install", path))
        return True, "Plugin queued."

    def cancel_pending_plugin_change(self, plugin_id):
        self.calls.append(("cancel", plugin_id))
        return True, "Pending change cancelled."

    def queue_uninstall_plugin(self, plugin_id):
        self.calls.append(("uninstall", plugin_id))
        return True, "Uninstall queued."

    def queue_rollback_plugin(self, plugin_id):
        self.calls.append(("rollback", plugin_id))
        return True, "Rollback queued."


class _SettingsManager:
    def __init__(self, plugin_manager):
        self.plugin_manager = plugin_manager
        self.settings = {}

    def get_setting(self, category, key, default=None):
        return self.settings.get((category, key), default)

    def set_setting(self, category, key, value):
        self.settings[(category, key)] = value

    def reset_to_defaults(self):
        self.settings.clear()


class PluginSettingsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        pending = PluginTransactionStatus(
            operation="install",
            state="pending",
            version="2.0.0",
            generation=1,
            load_verified=None,
            error_code=None,
            error_message=None,
        )
        self.manager = _PluginManager(
            [
                _status(
                    "user_plugin",
                    source="user",
                    selected_version="2.0.0",
                    user_present=True,
                    user_version="2.0.0",
                    can_uninstall=True,
                    can_rollback=True,
                ),
                _status(
                    "blocked_plugin",
                    source="user",
                    loaded=False,
                    user_present=True,
                    user_version="1.0.0",
                    blocked_code="PLUGIN_DEPENDENCY_DISABLED",
                    blocked_reason="Required plugin provider is disabled.",
                    blocking_dependents=("consumer_plugin",),
                    update_error="Previous update failed.",
                    compatibility_error="Requires Agile Tiles < 2.",
                ),
                _status(
                    "pending_plugin",
                    source="user",
                    loaded=False,
                    user_present=True,
                    user_version="1.0.0",
                    transaction=pending,
                    restart_required=True,
                ),
            ]
        )
        self.widget = FluentSettingsCard(_SettingsManager(self.manager))
        self.addCleanup(self.widget.close)

    def test_status_cards_use_plugin_status_and_native_actions(self):
        user_text = self.widget.plugin_cards["user_plugin"].contentLabel.text()
        blocked_text = self.widget.plugin_cards["blocked_plugin"].contentLabel.text()
        pending_text = self.widget.plugin_cards["pending_plugin"].contentLabel.text()

        self.assertIn("v2.0.0 · 用户 · 已加载", user_text)
        self.assertIn("已阻止：Required plugin provider is disabled.", blocked_text)
        self.assertIn("依赖方：consumer_plugin", blocked_text)
        self.assertIn("更新失败：Previous update failed.", blocked_text)
        self.assertIn("不兼容：Requires Agile Tiles < 2.", blocked_text)
        self.assertIn("安装/更新：等待重启", pending_text)
        self.assertIn(("pending_plugin", "cancel"), self.widget.plugin_action_buttons)
        self.assertTrue(
            self.widget.plugin_action_buttons[("user_plugin", "uninstall")].isEnabled()
        )
        self.assertFalse(
            self.widget.plugin_action_buttons[("blocked_plugin", "uninstall")].isEnabled()
        )
        self.assertIn(("user_plugin", "rollback"), self.widget.plugin_action_buttons)

        self.widget.resize(500, 900)
        self.widget.show()
        self.app.processEvents()
        for card in self.widget.plugin_cards.values():
            with self.subTest(plugin=card.objectName()):
                self.assertLessEqual(card.switchButton.geometry().right(), card.width())
                self.assertLessEqual(card.contentLabel.geometry().bottom(), card.height())
        blocked_card = self.widget.plugin_cards["blocked_plugin"]
        self.assertEqual(
            blocked_card.height(),
            70 + 18 * blocked_card.contentLabel.text().count("\n"),
        )

    @patch("qfluentwidgets.InfoBar.error")
    def test_failed_toggle_uses_manager_and_restores_status(self, error_bar):
        self.manager.enable_result = (False, "Required plugin is disabled.")
        shortcut_group = self.widget.shortcut_group

        self.widget.plugin_cards["user_plugin"].switchButton.setChecked(False)
        self.app.processEvents()

        self.assertIn(("enable", "user_plugin", False), self.manager.calls)
        self.assertTrue(self.widget.plugin_cards["user_plugin"].switchButton.isChecked())
        self.assertIs(self.widget.shortcut_group, shortcut_group)
        error_bar.assert_called_once()

    @patch("qfluentwidgets.InfoBar.success")
    @patch("qfluentwidgets.MessageBox")
    def test_lifecycle_actions_refresh_only_plugin_group(self, message_box, success_bar):
        message_box.return_value.exec.return_value = True
        shortcut_group = self.widget.shortcut_group

        self.widget.plugin_action_buttons[("pending_plugin", "cancel")].click()
        self.widget.plugin_action_buttons[("user_plugin", "uninstall")].click()
        self.widget.plugin_action_buttons[("user_plugin", "rollback")].click()

        self.assertIn(("cancel", "pending_plugin"), self.manager.calls)
        self.assertIn(("uninstall", "user_plugin"), self.manager.calls)
        self.assertIn(("rollback", "user_plugin"), self.manager.calls)
        self.assertEqual(message_box.return_value.exec.call_count, 2)
        self.assertEqual(success_bar.call_count, 3)
        self.assertIs(self.widget.shortcut_group, shortcut_group)

    @patch("qfluentwidgets.InfoBar.success")
    @patch("core.settings.fluent_settings_card.QFileDialog.getOpenFileName")
    def test_import_accepts_atplugin_and_keeps_shortcut_group(self, file_dialog, _):
        file_dialog.return_value = (r"C:\plugins\sample.atplugin", "")
        shortcut_group = self.widget.shortcut_group

        self.widget._on_install_plugin()

        self.assertIn(("install", r"C:\plugins\sample.atplugin"), self.manager.calls)
        self.assertEqual(file_dialog.call_args.args[3], "Agile Tiles Plugin (*.atplugin)")
        self.assertIs(self.widget.shortcut_group, shortcut_group)


if __name__ == "__main__":
    unittest.main()
