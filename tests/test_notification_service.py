import os
import threading
import unittest
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from core.notification import (
    NotificationAction,
    NotificationLevel,
    NotificationPresentation,
    NotificationRequest,
    NotificationService,
    NotificationStatus,
    PluginNotificationClient,
)
from core.notification.backends.base import NotificationCapabilities
from core.notification.backends.custom import CustomToastBackend
from core.state_store import StateStore
from core.settings.settings_manager import SettingsManager
from core.ui_kernel.design_tokens import DesignTokens
from core.ui_kernel.theme_engine import ThemeEngine


class RecordingBackend:
    name = "recording"
    capabilities = NotificationCapabilities(actions=True, progress=True)

    def __init__(self):
        self.shown = []
        self.updated = []
        self.dismissed = []
        self.closed = False

    def is_available(self):
        return True

    def show(self, request):
        self.shown.append(request)

    def update(self, request):
        self.updated.append(request)
        return True

    def dismiss(self, notification_id):
        self.dismissed.append(notification_id)
        return True

    def shutdown(self):
        self.closed = True


class NotificationServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.settings = {"enabled": True, "backend": "recording"}
        self.backend = RecordingBackend()
        self.service = NotificationService(
            {"recording": self.backend},
            settings_provider=lambda: self.settings,
            default_backend="recording",
        )
        self.service.set_ready()
        self.client = PluginNotificationClient(self.service, "example.plugin")

    def tearDown(self):
        self.service.shutdown()

    def test_show_update_dismiss_and_owner_isolation(self):
        result = self.client.show("Completed", "Background job finished", level=NotificationLevel.SUCCESS)
        self.assertEqual(result.status, NotificationStatus.SHOWN)
        self.assertEqual(len(self.backend.shown), 1)

        update = self.client.update(result.notification_id, message="100% complete")
        self.assertEqual(update.status, NotificationStatus.SHOWN)
        self.assertEqual(self.backend.updated[-1].message, "100% complete")

        other = PluginNotificationClient(self.service, "other.plugin")
        self.assertEqual(other.dismiss(result.notification_id).code, "OWNER_MISMATCH")
        self.assertEqual(self.client.dismiss(result.notification_id).status, NotificationStatus.DISMISSED)
        self.assertEqual(self.backend.dismissed, [result.notification_id])

    def test_disabled_notifications_are_suppressed(self):
        self.settings["enabled"] = False
        result = self.client.show("Ignored", "No display")
        self.assertEqual(result.status, NotificationStatus.SUPPRESSED)
        self.assertEqual(self.backend.shown, [])

    def test_dedupe_updates_existing_notification(self):
        first = self.client.show("Download", "10%", dedupe_key="download:1")
        second = self.client.show("Download", "20%", dedupe_key="download:1")
        self.assertEqual(first.notification_id, second.notification_id)
        self.assertEqual(len(self.backend.shown), 1)
        self.assertEqual(self.backend.updated[-1].message, "20%")

    def test_requests_from_worker_are_queued_to_qt_thread(self):
        result_holder = []

        def submit():
            result_holder.append(self.client.show("Worker", "Queued"))

        worker = threading.Thread(target=submit)
        worker.start()
        worker.join(1)
        self.assertEqual(result_holder[0].status, NotificationStatus.QUEUED)
        self.app.processEvents()
        self.assertEqual(len(self.backend.shown), 1)

    def test_request_validation_rejects_unsafe_identifiers(self):
        with self.assertRaises(ValueError):
            NotificationRequest("bad owner", "Title", "Message")
        with self.assertRaises(ValueError):
            NotificationRequest("plugin", "", "Message")
        with self.assertRaises(ValueError):
            NotificationRequest("plugin", "Title", "Message", presentation="compact")

    def test_plugin_can_choose_toast_presentation_and_background(self):
        result = self.client.show(
            "Sync complete",
            "12 files uploaded",
            presentation=NotificationPresentation.DETAILED,
            transparent_background=True,
        )
        self.assertEqual(result.status, NotificationStatus.SHOWN)
        request = self.backend.shown[-1]
        self.assertEqual(request.presentation, NotificationPresentation.DETAILED)
        self.assertTrue(request.transparent_background)

    def test_owner_cleanup_dismisses_active_notifications(self):
        first = self.client.show("One", "A")
        second = self.client.show("Two", "B")
        self.assertEqual(self.service.dismiss_owner("example.plugin"), 2)
        self.assertEqual(set(self.backend.dismissed), {first.notification_id, second.notification_id})

    def test_custom_toast_stacks_updates_and_emits_actions(self):
        backend = CustomToastBackend(max_visible=1)
        activated = []
        actions = []
        backend.activated.connect(activated.append)
        backend.action_triggered.connect(lambda notification_id, action_id: actions.append((notification_id, action_id)))
        first = NotificationRequest(
            "example.plugin",
            "First",
            "Initial text",
            actions=(NotificationAction("open", "Open"),),
        )
        second = NotificationRequest(
            "example.plugin",
            "Second",
            "Queued",
        )
        backend.show(first)
        backend.show(second)
        self.assertEqual(list(backend._visible), [first.notification_id])
        self.assertEqual(len(backend._pending), 1)

        updated = first.with_updates(message="Updated text")
        self.assertTrue(backend.update(updated))
        card = backend._visible[first.notification_id]
        self.assertEqual(card.message.text(), "Updated text")
        backend.update(first.with_updates(presentation=NotificationPresentation.COMPACT))
        self.assertTrue(card.message.isHidden())
        card.activated.emit(first.notification_id)
        self.assertEqual(activated, [first.notification_id])
        action_button = next(
            button
            for button in card.findChildren(QPushButton)
            if button.property("notification_action_id") == "open"
        )
        action_button.click()
        self.assertEqual(actions, [(first.notification_id, "open")])

        backend.dismiss(first.notification_id)
        self.app.processEvents()
        self.assertEqual(list(backend._visible), [second.notification_id])
        backend.shutdown()

    def test_backend_dismissal_releases_service_dedupe_record(self):
        backend = CustomToastBackend()
        service = NotificationService(
            {"custom": backend},
            settings_provider=lambda: {"enabled": True},
            default_backend="custom",
        )
        service.set_ready()
        client = PluginNotificationClient(service, "example.plugin")
        first = client.show("First", "Message", dedupe_key="job:1")
        backend.dismiss(first.notification_id)
        self.app.processEvents()
        replacement = client.show("Second", "Message", dedupe_key="job:1")
        self.assertEqual(replacement.status, NotificationStatus.SHOWN)
        self.assertNotEqual(first.notification_id, replacement.notification_id)
        service.shutdown()

    def test_settings_manager_migrates_legacy_notification_toggle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_store = StateStore(str(Path(temp_dir) / "state.json"))
            state_store.set("settings", {"general": {"enable_notifications": False}})
            manager = SettingsManager(ThemeEngine(DesignTokens()), state_store)
            self.assertFalse(manager.get_setting("notifications", "enabled"))

    def test_legacy_notification_paths_are_not_reintroduced(self):
        root = Path(__file__).resolve().parents[1]
        sources = [
            root / "main.py",
            root / "core" / "plugin_system" / "plugin_context.py",
            root / "plugins" / "time" / "logic.py",
        ]
        content = "\n".join(path.read_text(encoding="utf-8") for path in sources)
        self.assertNotIn("system:" + "notification", content)
        self.assertNotIn("send_" + "notification", content)
        self.assertNotIn("show" + "Message(", content)


if __name__ == "__main__":
    unittest.main()
