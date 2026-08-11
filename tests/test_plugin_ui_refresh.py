import unittest

from PySide6.QtWidgets import QApplication

from plugins.backup_restore.views import BackupProfileCard, BackupRestoreWidget
from plugins.command_palette.views import CommandPaletteWidget
from plugins.plugin_diagnostics.views import PluginDiagnosticsWidget
from plugins.system_monitor.views import SystemMonitorWidget
from plugins.windows_controls.views import WindowsControlsWidget


class PluginUiRefreshTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _settle(self, widget, width=500):
        widget.resize(width, 700)
        widget.show()
        self.app.processEvents()

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            if widget.objectName() in {
                "commandPalettePage",
                "systemMonitorPage",
                "windowsControlsPage",
                "backupRestorePage",
                "pluginDiagnosticsPage",
            }:
                widget.close()
                widget.deleteLater()
        self.app.processEvents()

    def test_command_palette_has_empty_state_and_stable_table(self):
        widget = CommandPaletteWidget()
        self._settle(widget)
        widget.set_commands([])
        self.assertIs(widget.content_stack.currentWidget(), widget.empty_view)

        widget.set_commands(
            [
                {
                    "id": "sample",
                    "name": "示例命令",
                    "category": "系统",
                    "subtitle": "打开示例",
                }
            ]
        )
        self.assertIs(widget.content_stack.currentWidget(), widget.table)
        self.assertEqual(widget.table.rowCount(), 1)
        self.assertEqual(widget.table.columnWidth(3), 74)

    def test_metric_pages_reflow_between_compact_and_wide_layouts(self):
        monitor = SystemMonitorWidget()
        self._settle(monitor)
        self.assertEqual(monitor._metric_columns, 2)
        monitor.resize(1000, 700)
        self.app.processEvents()
        self.assertEqual(monitor._metric_columns, 4)

        diagnostics = PluginDiagnosticsWidget()
        self._settle(diagnostics)
        self.assertEqual(diagnostics._metric_columns, 2)
        self.assertTrue(diagnostics.plugin_table.isColumnHidden(4))
        diagnostics.resize(1000, 700)
        self.app.processEvents()
        self.assertEqual(diagnostics._metric_columns, 4)
        self.assertFalse(diagnostics.plugin_table.isColumnHidden(4))

    def test_windows_controls_reflows_controls_and_keeps_scroll_area(self):
        widget = WindowsControlsWidget()
        self._settle(widget)
        self.assertEqual(widget._quick_columns, 2)
        self.assertEqual(widget._session_columns, 2)
        self.assertIsNotNone(widget.scroll.widget())
        widget.resize(1000, 700)
        self.app.processEvents()
        self.assertEqual(widget._quick_columns, 3)
        self.assertEqual(widget._session_columns, 4)

    def test_backup_restore_uses_cards_and_empty_state(self):
        widget = BackupRestoreWidget()
        self._settle(widget)
        widget.set_profiles(
            [
                {
                    "id": "daily",
                    "name": "每日备份",
                    "sources": ["C:/data"],
                    "destination": "C:/backups",
                    "retention": 5,
                }
            ]
        )
        self.assertIs(widget.content_stack.currentWidget(), widget.scroll)
        self.assertIsInstance(widget.list_layout.itemAt(0).widget(), BackupProfileCard)
        widget.set_profiles([])
        self.assertIs(widget.content_stack.currentWidget(), widget.empty_view)


if __name__ == "__main__":
    unittest.main()
