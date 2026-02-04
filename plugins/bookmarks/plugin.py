import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import QPushButton, QWidget
from qfluentwidgets import Action, FluentIcon, MessageBox, RoundMenu

from core.data_layer.path_utils import PathManager
from core.plugin_system.plugin_base import PluginBase
from plugins.bookmarks.dialogs import AddBookmarkDialog, AddGroupDialog
from plugins.bookmarks.views import BookmarksWidget


class BookmarksPlugin(PluginBase):
    """
    Controller for Bookmarks Plugin v2.
    Handles data modeling for notes, colors, and sorting.
    """

    def __init__(self, context):
        super().__init__(context)
        self.groups = []
        self.bookmarks = []
        self.active_group_id = None
        self.ui_widget = None

        # Setup Data Paths
        self.data_dir = Path(self.context.get_data_dir())
        self.data_file = self.data_dir / "bookmarks.json"

        # Migrate Legacy Data
        PathManager.migrate_plugin_data(
            self.context.plugin_id, Path(__file__).parent, files=["bookmarks.json"]
        )

    def on_load(self):
        print(f"[BookmarksPlugin] Loading v2... ID: {self.context.plugin_id}")
        self._load_data()

    def on_unload(self):
        self._save_data()

    def get_card_widget(self) -> QWidget:
        if self.ui_widget is None:
            self.ui_widget = BookmarksWidget()

            # Connect signals
            self.ui_widget.add_requested.connect(self._handle_add_bookmark)
            self.ui_widget.add_group_requested.connect(self._handle_add_group)
            self.ui_widget.delete_group_requested.connect(self._handle_delete_group)
            self.ui_widget.edit_group_requested.connect(self._handle_edit_group)
            self.ui_widget.url_clicked.connect(self._handle_url_clicked)
            self.ui_widget.delete_bookmark_requested.connect(
                self._handle_delete_bookmark
            )
            self.ui_widget.edit_bookmark_requested.connect(self._handle_edit_bookmark)
            self.ui_widget.group_changed.connect(self._handle_group_changed)
            self.ui_widget.move_up_requested.connect(self._handle_move_up)
            self.ui_widget.move_down_requested.connect(self._handle_move_down)

            self._refresh_ui(refresh_groups=True)

        return self.ui_widget

    def get_icon(self):
        """Sidebar icon"""
        from qfluentwidgets import FluentIcon

        return FluentIcon.GLOBE

    def get_thumbnail_widget(self) -> QWidget:
        btn = QPushButton("🌍")
        btn.setFixedSize(40, 40)
        btn.setFlat(True)
        btn.setStyleSheet(
            "QPushButton { color: white; font-size: 24px; background: transparent; border: none; }"
        )
        return btn

    def get_context_menu_items(self):
        """Add custom context menu items."""
        menus = []

        # grouped_bookmarks = { group_id: [bookmarks] }
        grouped_bookmarks = {g["id"]: [] for g in self.groups}
        ungrouped = []

        for bm in self.bookmarks:
            gid = bm.get("group_id")
            if gid is not None and gid in grouped_bookmarks:
                grouped_bookmarks[gid].append(bm)
            else:
                ungrouped.append(bm)

        # Create menus for groups
        for group in self.groups:
            bms = grouped_bookmarks.get(group["id"], [])
            if not bms:
                continue

            menu = RoundMenu(group["name"], self.ui_widget)

            # Apply group color to the menu icon
            icon = FluentIcon.FOLDER
            if group.get("color"):
                icon = icon.icon(color=QColor(group["color"]))

            menu.setIcon(icon)

            for bm in bms:
                action = Action(FluentIcon.TAG, bm["title"], self.ui_widget)
                # Capture bm['url'] correctly in lambda
                action.triggered.connect(
                    lambda checked=False, url=bm["url"]: self._handle_url_clicked(url)
                )
                menu.addAction(action)

            menus.append(menu)

        # Add ungrouped bookmarks directly
        for bm in ungrouped:
            action = Action(FluentIcon.TAG, bm["title"], self.ui_widget)
            action.triggered.connect(
                lambda checked=False, url=bm["url"]: self._handle_url_clicked(url)
            )
            menus.append(action)

        return menus

    def get_preferred_width(self):
        return 400

    def _load_data(self):
        if self.data_file.exists():
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.groups = data.get("groups", [])
                        self.bookmarks = data.get("bookmarks", [])
                    else:
                        self.groups = [{"id": 0, "name": "Default"}]
                        self.bookmarks = data
                        for i, b in enumerate(self.bookmarks):
                            b["group_id"] = b.get("group_id", 0)
                            b["order"] = i
            except Exception as e:
                print(f"[BookmarksPlugin] Load error: {e}")
                self.groups = [{"id": 0, "name": "Default"}]
                self.bookmarks = []
        else:
            self.groups = [{"id": 0, "name": "General"}, {"id": 1, "name": "Work"}]
            self.bookmarks = [
                {
                    "title": "Baidu",
                    "url": "https://www.baidu.com",
                    "group_id": 0,
                    "order": 0,
                    "notes": "Search engine",
                    "color": "#0078d4",
                },
                {
                    "title": "Github",
                    "url": "https://github.com",
                    "group_id": 1,
                    "order": 1,
                    "notes": "Code hosting",
                    "color": "#107c10",
                },
            ]
            self._save_data()

        # Ensure all bookmarks have an order
        for i, b in enumerate(self.bookmarks):
            if "order" not in b:
                b["order"] = i

    def _save_data(self):
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"groups": self.groups, "bookmarks": self.bookmarks},
                    f,
                    indent=4,
                    ensure_ascii=False,
                )
        except Exception as e:
            print(f"[BookmarksPlugin] Save error: {e}")

    def _refresh_ui(self, refresh_groups=False):
        if self.ui_widget:
            if refresh_groups:
                self.ui_widget.update_groups(self.groups)

            # Sort and Filter
            display_items = self.bookmarks
            if self.active_group_id is not None:
                display_items = [
                    b
                    for b in display_items
                    if b.get("group_id") == self.active_group_id
                ]

            display_items.sort(key=lambda x: x.get("order", 0))
            self.ui_widget.update_bookmarks(display_items)

    def _handle_group_changed(self, group_id):
        self.active_group_id = group_id
        self._refresh_ui()

    def _handle_add_group(self):
        dialog = AddGroupDialog(self.ui_widget)
        if dialog.exec() and dialog.validate():
            data = dialog.get_data()
            new_id = max([g["id"] for g in self.groups], default=-1) + 1
            self.groups.append(
                {"id": new_id, "name": data["name"], "color": data.get("color")}
            )
            self._save_data()
            self._refresh_ui(refresh_groups=True)

    def _handle_edit_group(self, group_id):
        group = next((g for g in self.groups if g["id"] == group_id), None)
        if not group:
            return

        dialog = AddGroupDialog(
            self.ui_widget, name=group["name"], color=group.get("color")
        )
        if dialog.exec() and dialog.validate():
            data = dialog.get_data()
            group["name"] = data["name"]
            group["color"] = data.get("color")
            self._save_data()
            self._refresh_ui(refresh_groups=True)

    def _handle_delete_group(self, group_id):
        # Find group name
        group = next((g for g in self.groups if g["id"] == group_id), None)
        if not group:
            return

        w = MessageBox(
            "Delete Group",
            f"Are you sure you want to delete '{group['name']}'? Bookmarks will become ungrouped.",
            self.ui_widget,
        )
        if w.exec():
            # Remove group
            self.groups = [g for g in self.groups if g["id"] != group_id]
            # Ungroup bookmarks
            for b in self.bookmarks:
                if b.get("group_id") == group_id:
                    b["group_id"] = None

            self._save_data()
            self.active_group_id = None
            self._refresh_ui(refresh_groups=True)
            self.ui_widget.show_message("Deleted", f"Group '{group['name']}' removed")

    def _handle_add_bookmark(self):
        dialog = AddBookmarkDialog(
            self.groups, self.ui_widget, group_id=self.active_group_id
        )
        if dialog.exec() and dialog.validate():
            data = dialog.get_data()
            data["order"] = len(self.bookmarks)
            self.bookmarks.append(data)
            self._save_data()
            self._refresh_ui()

    def _handle_url_clicked(self, url):
        if not url.startswith("http"):
            url = "https://" + url
        QDesktopServices.openUrl(QUrl(url))
        self.context.close_detail_view()

    def _handle_delete_bookmark(self, url):
        self.bookmarks = [b for b in self.bookmarks if b["url"] != url]
        self._save_data()
        self._refresh_ui()

    def _handle_edit_bookmark(self, url):
        bm = next((b for b in self.bookmarks if b["url"] == url), None)
        if not bm:
            return

        dialog = AddBookmarkDialog(
            self.groups,
            self.ui_widget,
            title=bm["title"],
            url=bm["url"],
            group_id=bm.get("group_id"),
            notes=bm.get("notes", ""),
            color=bm.get("color"),
        )
        if dialog.exec() and dialog.validate():
            data = dialog.get_data()
            bm.update(data)
            self._save_data()
            self._refresh_ui()

    def _handle_move_up(self, url):
        idx = next((i for i, b in enumerate(self.bookmarks) if b["url"] == url), -1)
        if idx > 0:
            self.bookmarks[idx]["order"], self.bookmarks[idx - 1]["order"] = (
                self.bookmarks[idx - 1].get("order", idx - 1),
                self.bookmarks[idx].get("order", idx),
            )
            # Re-sort list for safety
            self.bookmarks.sort(key=lambda x: x.get("order", 0))
            # Normalize order
            for i, b in enumerate(self.bookmarks):
                b["order"] = i
            self._save_data()
            self._refresh_ui()

    def _handle_move_down(self, url):
        idx = next((i for i, b in enumerate(self.bookmarks) if b["url"] == url), -1)
        if idx != -1 and idx < len(self.bookmarks) - 1:
            self.bookmarks[idx]["order"], self.bookmarks[idx + 1]["order"] = (
                self.bookmarks[idx + 1].get("order", idx + 1),
                self.bookmarks[idx].get("order", idx),
            )
            self.bookmarks.sort(key=lambda x: x.get("order", 0))
            for i, b in enumerate(self.bookmarks):
                b["order"] = i
            self._save_data()
            self._refresh_ui()
