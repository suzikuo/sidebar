from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    IconWidget,
    LineEdit,
    MessageBox,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SimpleCardWidget,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    ToolButton,
    TransparentToolButton,
)


def format_last_backup(value):
    if not value:
        return "尚未备份"
    try:
        return datetime.fromisoformat(str(value)).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return str(value)


class ProfileDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sources = []
        self.titleLabel = SubtitleLabel("新建备份", self)
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("例如：工作环境")
        self.sources_edit = LineEdit(self)
        self.sources_edit.setReadOnly(True)
        self.sources_edit.setPlaceholderText("可选")
        source_row = QWidget(self)
        source_layout = QHBoxLayout(source_row)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(6)
        source_layout.addWidget(self.sources_edit, 1)
        files = ToolButton(FluentIcon.DOCUMENT, source_row)
        files.setToolTip("添加文件")
        files.clicked.connect(self._choose_files)
        folder = ToolButton(FluentIcon.FOLDER, source_row)
        folder.setToolTip("添加目录")
        folder.clicked.connect(self._choose_source_directory)
        source_layout.addWidget(files)
        source_layout.addWidget(folder)

        destination_row = QWidget(self)
        destination_layout = QHBoxLayout(destination_row)
        destination_layout.setContentsMargins(0, 0, 0, 0)
        destination_layout.setSpacing(6)
        self.destination_edit = LineEdit(destination_row)
        self.destination_edit.setPlaceholderText("选择保存目录")
        destination = ToolButton(FluentIcon.FOLDER, destination_row)
        destination.setToolTip("选择保存目录")
        destination.clicked.connect(self._choose_destination)
        destination_layout.addWidget(self.destination_edit, 1)
        destination_layout.addWidget(destination)

        self.retention = SpinBox(self)
        self.retention.setRange(1, 30)
        self.retention.setValue(5)
        self.retention.setSuffix(" 份")

        form = QFormLayout()
        form.setContentsMargins(0, 8, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("名称", self.name_edit)
        form.addRow("文件来源", source_row)
        form.addRow("保存目录", destination_row)
        form.addRow("保留数量", self.retention)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addLayout(form)
        self.yesButton.setText("创建")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(500)

    def validate(self):
        return bool(self.name_edit.text().strip() and self.destination_edit.text().strip())

    def value(self):
        return {
            "name": self.name_edit.text().strip(),
            "sources": self.sources,
            "destination": self.destination_edit.text().strip(),
            "retention": self.retention.value(),
        }

    def _choose_files(self):
        values, _ = QFileDialog.getOpenFileNames(self, "选择要备份的文件")
        self._append_sources(values)

    def _choose_source_directory(self):
        value = QFileDialog.getExistingDirectory(self, "选择要备份的目录")
        self._append_sources([value] if value else [])

    def _choose_destination(self):
        value = QFileDialog.getExistingDirectory(self, "选择备份保存目录")
        if value:
            self.destination_edit.setText(value)

    def _append_sources(self, values):
        for value in values:
            if value and value not in self.sources:
                self.sources.append(value)
        self.sources_edit.setText("; ".join(self.sources))


class BackupProfileCard(SimpleCardWidget):
    backup_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile_id = profile["id"]
        self.setBorderRadius(8)
        self.setMinimumHeight(116)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 12, 14)
        layout.setSpacing(7)

        heading = QHBoxLayout()
        heading.setSpacing(8)
        heading.addWidget(StrongBodyLabel(profile["name"], self))
        heading.addStretch(1)
        backup = ToolButton(FluentIcon.SAVE, self)
        backup.setToolTip("立即备份")
        backup.clicked.connect(lambda: self.backup_requested.emit(self.profile_id))
        remove = TransparentToolButton(FluentIcon.DELETE, self)
        remove.setToolTip("删除配置")
        remove.clicked.connect(lambda: self.remove_requested.emit(self.profile_id))
        heading.addWidget(backup)
        heading.addWidget(remove)
        layout.addLayout(heading)

        metadata = QHBoxLayout()
        metadata.setSpacing(12)
        source_count = len(profile.get("sources", []))
        metadata.addWidget(CaptionLabel(f"{source_count} 个文件来源", self))
        metadata.addWidget(CaptionLabel(f"保留 {profile.get('retention', 5)} 份", self))
        metadata.addStretch(1)
        metadata.addWidget(CaptionLabel(format_last_backup(profile.get("last_backup")), self))
        layout.addLayout(metadata)

        destination_row = QHBoxLayout()
        destination_row.setSpacing(6)
        folder = IconWidget(FluentIcon.FOLDER, self)
        folder.setFixedSize(16, 16)
        destination = CaptionLabel(str(profile.get("destination", "")), self)
        destination.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        destination.setToolTip(str(profile.get("destination", "")))
        destination_row.addWidget(folder)
        destination_row.addWidget(destination, 1)
        layout.addLayout(destination_row)


class BackupRestoreWidget(QWidget):
    profile_added = Signal(dict)
    profile_removed = Signal(str)
    backup_requested = Signal(str)
    restore_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("backupRestorePage")
        self._profiles = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(SubtitleLabel("备份与恢复", self))
        header.addStretch(1)
        restore = PushButton("恢复归档", self, FluentIcon.HISTORY)
        restore.clicked.connect(self._choose_restore)
        add = PrimaryPushButton(FluentIcon.ADD, "新建备份", self)
        add.clicked.connect(self._add_profile)
        header.addWidget(restore)
        header.addWidget(add)
        layout.addLayout(header)

        status = QHBoxLayout()
        status.setContentsMargins(2, 0, 2, 0)
        status.addWidget(BodyLabel("备份配置", self))
        status.addStretch(1)
        self.profile_count = CaptionLabel("0 个", self)
        status.addWidget(self.profile_count)
        layout.addLayout(status)

        self.content_stack = QStackedWidget(self)
        self.scroll = ScrollArea(self.content_stack)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.enableTransparentBackground()
        self.list_content = QWidget(self.scroll)
        self.list_layout = QVBoxLayout(self.list_content)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.list_content)

        self.empty_view = QWidget(self.content_stack)
        empty_layout = QVBoxLayout(self.empty_view)
        empty_layout.addStretch(1)
        empty_icon = IconWidget(FluentIcon.SAVE, self.empty_view)
        empty_icon.setFixedSize(28, 28)
        empty_layout.addWidget(empty_icon, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(
            CaptionLabel("还没有备份配置", self.empty_view),
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
        empty_layout.addStretch(1)

        self.content_stack.addWidget(self.scroll)
        self.content_stack.addWidget(self.empty_view)
        layout.addWidget(self.content_stack, 1)

    def set_profiles(self, profiles):
        self._profiles = list(profiles or ())
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for profile in self._profiles:
            card = BackupProfileCard(profile, self.list_content)
            card.backup_requested.connect(self.backup_requested.emit)
            card.remove_requested.connect(self._confirm_remove)
            self.list_layout.addWidget(card)
        count = len(self._profiles)
        self.profile_count.setText(f"{count} 个")
        self.content_stack.setCurrentWidget(self.scroll if count else self.empty_view)

    def show_error(self, message):
        from qfluentwidgets import InfoBar, InfoBarPosition

        InfoBar.error("备份失败", str(message), parent=self, position=InfoBarPosition.TOP)

    def show_created(self, path):
        from qfluentwidgets import InfoBar, InfoBarPosition

        InfoBar.success("备份完成", str(path), parent=self, position=InfoBarPosition.TOP)

    def show_restored(self, result):
        from qfluentwidgets import InfoBar, InfoBarPosition

        message = f"恢复 {result['restoredFiles']} 个文件、{len(result['plugins'])} 个插件快照"
        InfoBar.success("恢复完成", message, parent=self, position=InfoBarPosition.TOP)

    def _add_profile(self):
        dialog = ProfileDialog(self.window())
        if dialog.exec() and dialog.validate():
            self.profile_added.emit(dialog.value())

    def _confirm_remove(self, profile_id):
        if MessageBox("删除备份配置", "只删除配置，不会删除已有归档。", self.window()).exec():
            self.profile_removed.emit(profile_id)

    def _choose_restore(self):
        archive, _ = QFileDialog.getOpenFileName(
            self,
            "选择备份归档",
            "",
            "Agile Tiles Backup (*.atbackup);;All Files (*)",
        )
        if not archive:
            return
        destination = QFileDialog.getExistingDirectory(self, "选择文件恢复目录")
        if not destination:
            return
        if MessageBox(
            "恢复备份",
            f"文件将恢复到：\n{destination}\n\n同名文件会被覆盖，确定继续？",
            self.window(),
        ).exec():
            self.restore_requested.emit(archive, destination)


__all__ = ["BackupRestoreWidget", "BackupProfileCard", "ProfileDialog", "format_last_backup"]
