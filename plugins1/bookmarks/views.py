from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    Action,
    BodyLabel,
    CardWidget,
    FlowLayout,
    FluentIcon,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    PushButton,
    RoundMenu,
    SegmentedWidget,
    StrongBodyLabel,
    SubtitleLabel,
    TransparentToolButton,
)

from ui.components.base_widget import BScrollArea


class BookmarkTile(CardWidget):
    """A single bookmark tile with color and notes support"""

    itemClicked = Signal(str)  # Emits URL
    delete_requested = Signal(str)  # Emits URL
    edit_requested = Signal(str)
    move_up_requested = Signal(str)
    move_down_requested = Signal(str)

    def __init__(self, title, url, notes="", color=None, parent=None):
        super().__init__(parent)
        self.url = url
        self.notes = notes
        self.setFixedSize(160, 110)
        self.setCursor(Qt.PointingHandCursor)

        if notes:
            self.setToolTip(notes)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(4)

        # Icon
        self.iconWidget = IconWidget(FluentIcon.GLOBE, self)
        self.iconWidget.setFixedSize(24, 24)

        # Title
        self.titleLabel = StrongBodyLabel(title, self)
        self.titleLabel.setWordWrap(True)
        self.titleLabel.setAlignment(Qt.AlignCenter)

        self.layout.addStretch(1)
        self.layout.addWidget(self.iconWidget, 0, Qt.AlignCenter)
        self.layout.addWidget(self.titleLabel, 0, Qt.AlignCenter)
        self.layout.addStretch(1)

        # Apply color
        if color:
            self.setStyleSheet(f"""
                BookmarkTile {{
                    border-left: 4px solid {color};
                }}
            """)
            self.titleLabel.setTextColor(QColor(color))

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.LeftButton:
            self.itemClicked.emit(self.url)

    def contextMenuEvent(self, e):
        menu = RoundMenu(parent=self)
        editAction = Action(FluentIcon.EDIT, "Edit", self)
        deleteAction = Action(FluentIcon.DELETE, "Delete", self)
        upAction = Action(FluentIcon.UP, "Move Up", self)
        downAction = Action(FluentIcon.DOWN, "Move Down", self)

        editAction.triggered.connect(lambda: self.edit_requested.emit(self.url))
        deleteAction.triggered.connect(lambda: self.delete_requested.emit(self.url))
        upAction.triggered.connect(lambda: self.move_up_requested.emit(self.url))
        downAction.triggered.connect(lambda: self.move_down_requested.emit(self.url))

        menu.addAction(editAction)
        menu.addAction(upAction)
        menu.addAction(downAction)
        menu.addSeparator()
        menu.addAction(deleteAction)
        menu.exec(e.globalPos())


class BookmarksWidget(QWidget):
    """Main view for Bookmarks plugin with sorting and advanced features"""

    add_requested = Signal()
    add_group_requested = Signal()
    url_clicked = Signal(str)
    delete_bookmark_requested = Signal(str)
    delete_group_requested = Signal(int)
    edit_group_requested = Signal(int)
    edit_bookmark_requested = Signal(str)
    move_up_requested = Signal(str)
    move_down_requested = Signal(str)
    group_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(20, 20, 20, 20)
        self.mainLayout.setSpacing(15)

        # Header
        self.headerLayout = QHBoxLayout()
        self.titleLabel = BodyLabel("Bookmarks", self)
        self.titleLabel.setStyleSheet("font-size: 24px; font-weight: bold;")

        self.addGroupButton = TransparentToolButton(FluentIcon.FOLDER_ADD, self)
        self.addGroupButton.setToolTip("Add Group")
        self.addGroupButton.clicked.connect(self.add_group_requested.emit)

        self.deleteGroupButton = TransparentToolButton(FluentIcon.DELETE, self)
        self.deleteGroupButton.setToolTip("Delete Current Group")
        self.deleteGroupButton.clicked.connect(self._on_delete_group_clicked)
        self.deleteGroupButton.hide()  # Hidden by default for "All"

        self.editGroupButton = TransparentToolButton(FluentIcon.EDIT, self)
        self.editGroupButton.setToolTip("Edit Current Group")
        self.editGroupButton.clicked.connect(self._on_edit_group_clicked)
        self.editGroupButton.hide()

        self.addButton = PushButton(FluentIcon.ADD, "Add Link", self)
        self.addButton.clicked.connect(self.add_requested.emit)

        self.headerLayout.addWidget(self.titleLabel)
        self.headerLayout.addStretch(1)
        self.headerLayout.addWidget(self.editGroupButton)
        self.headerLayout.addWidget(self.deleteGroupButton)
        self.headerLayout.addWidget(self.addGroupButton)
        self.headerLayout.addWidget(self.addButton)

        self.mainLayout.addLayout(self.headerLayout)

        # Group Selector
        self.segmentedWidget = SegmentedWidget(self)
        self.current_route_key = "all"
        self.segmentedWidget.addItem(routeKey="all", text="All")
        self.segmentedWidget.setCurrentItem("all")
        self.segmentedWidget.currentItemChanged.connect(
            self._on_group_selection_changed
        )
        self.mainLayout.addWidget(self.segmentedWidget)

        # Scroll Area for Flow Layout
        self.scrollArea = BScrollArea(self)
        self.scrollArea.setWidgetResizable(True)

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.containerLayout = QVBoxLayout(self.container)
        self.containerLayout.setContentsMargins(0, 0, 0, 0)
        self.containerLayout.setSpacing(20)
        self.containerLayout.setAlignment(Qt.AlignTop)

        self.scrollArea.setWidget(self.container)
        self.mainLayout.addWidget(self.scrollArea)

    def _on_group_selection_changed(self, routeKey):
        self.current_route_key = routeKey
        is_all = routeKey == "all"
        self.deleteGroupButton.setVisible(not is_all)
        self.editGroupButton.setVisible(not is_all)
        group_id = None if is_all else int(routeKey.replace("group_", ""))
        self.group_changed.emit(group_id)

    def _on_delete_group_clicked(self):
        if self.current_route_key != "all":
            group_id = int(self.current_route_key.replace("group_", ""))
            self.delete_group_requested.emit(group_id)

    def _on_edit_group_clicked(self):
        if self.current_route_key != "all":
            group_id = int(self.current_route_key.replace("group_", ""))
            self.edit_group_requested.emit(group_id)

    def update_groups(self, groups):
        self.groups = groups
        self.group_map = {g["id"]: g for g in groups}
        self.segmentedWidget.clear()
        self.segmentedWidget.addItem(routeKey="all", text="All")
        for g in groups:
            self.segmentedWidget.addItem(routeKey=f"group_{g['id']}", text=g["name"])
        self.segmentedWidget.setCurrentItem("all")

    def update_bookmarks(self, bookmarks):
        """Rebuild the tile list with support for partitioned view"""
        # Clear previous items
        while self.containerLayout.count():
            item = self.containerLayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        def create_flow_widget(items, group_color=None):
            widget = QWidget()
            layout = FlowLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(15)

            for bm in items:
                # Inherit color if not set on bookmark
                effective_color = bm.get("color") or group_color

                tile = BookmarkTile(
                    title=bm.get("title", ""),
                    url=bm.get("url", ""),
                    notes=bm.get("notes", ""),
                    color=effective_color,
                    parent=widget,
                )
                tile.itemClicked.connect(self.url_clicked.emit)
                tile.delete_requested.connect(self.delete_bookmark_requested.emit)
                tile.edit_requested.connect(self.edit_bookmark_requested.emit)
                tile.move_up_requested.connect(self.move_up_requested.emit)
                tile.move_down_requested.connect(self.move_down_requested.emit)
                layout.addWidget(tile)

            return widget

        if self.current_route_key == "all":
            # Group bookmarks by group
            grouped_bookmarks = {g["id"]: [] for g in self.groups}
            ungrouped = []

            for bm in bookmarks:
                gid = bm.get("group_id")
                if gid is not None and gid in grouped_bookmarks:
                    grouped_bookmarks[gid].append(bm)
                else:
                    ungrouped.append(bm)

            # Render each group
            for group in self.groups:
                bms = grouped_bookmarks.get(group["id"], [])
                if not bms:
                    continue

                # Header
                header = SubtitleLabel(group["name"], self.container)
                self.containerLayout.addWidget(header)

                # Bookmarks
                flow_widget = create_flow_widget(bms, group.get("color"))
                self.containerLayout.addWidget(flow_widget)

            # Render ungrouped if any
            if ungrouped:
                header = SubtitleLabel("Ungrouped", self.container)
                self.containerLayout.addWidget(header)
                flow_widget = create_flow_widget(ungrouped)
                self.containerLayout.addWidget(flow_widget)

        else:
            # Single group view
            # Note: bookmarks passed here are already filtered by the plugin for the active group
            # But we need the group color
            group_id = (
                int(self.current_route_key.replace("group_", ""))
                if "group_" in self.current_route_key
                else None
            )
            group_color = (
                self.group_map.get(group_id, {}).get("color")
                if group_id is not None
                else None
            )

            flow_widget = create_flow_widget(bookmarks, group_color)
            self.containerLayout.addWidget(flow_widget)

        self.containerLayout.addStretch(1)

    def show_message(self, title, content, type="success"):
        if type == "success":
            InfoBar.success(
                title,
                content,
                duration=2000,
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
        elif type == "error":
            InfoBar.error(
                title,
                content,
                duration=3000,
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
