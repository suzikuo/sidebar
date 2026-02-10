"""
Modern Fluent Design Settings Card
Uses PySide6-Fluent-Widgets components
Only uses components that work without ConfigItem
"""

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    PushSettingCard,
    SettingCardGroup,
    SwitchSettingCard,
    TitleLabel,
)

from core.data_layer.path_utils import PathManager
from ui.components.base_widget import BScrollArea

from .shortcut_picker import ShortcutPickerButton


class FluentSettingsCard(QWidget):
    """
    Modern Fluent Design Settings Interface using native qfluentwidgets components.
    Uses only components that don't require ConfigItem.
    """

    theme_changed = Signal(str)

    def __init__(self, settings_manager):
        super().__init__()
        self.settings_manager = settings_manager
        self.setObjectName("FluentSettingsCard")
        self._init_ui()

    def _init_ui(self):
        """Initialize the Fluent UI with proper SettingCardGroups."""
        # Import qfluentwidgets components
        from qfluentwidgets import BodyLabel

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(20)

        # Title
        title = TitleLabel("设置")
        layout.addWidget(title)

        # Scroll Area for settings
        scroll = BScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setViewportMargins(0, 0, 0, 0)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(20)

        # === General Settings Group ===
        general_group = SettingCardGroup("通用设置", self)

        # Auto-start switch
        self.startup_card = SwitchSettingCard(
            FluentIcon.POWER_BUTTON,
            "开机启动",
            "系统启动时自动运行 Agile Tiles",
            parent=general_group,
        )
        self.startup_card.switchButton.setChecked(
            self.settings_manager.get_setting("general", "run_on_startup", False)
        )
        self.startup_card.switchButton.checkedChanged.connect(
            lambda checked: self.settings_manager.set_setting(
                "general", "run_on_startup", checked
            )
        )
        general_group.addSettingCard(self.startup_card)

        # Notifications switch
        self.notify_card = SwitchSettingCard(
            FluentIcon.MESSAGE, "启用通知", "显示系统通知提醒", parent=general_group
        )
        self.notify_card.switchButton.setChecked(
            self.settings_manager.get_setting("general", "enable_notifications", True)
        )
        self.notify_card.switchButton.checkedChanged.connect(
            lambda checked: self.settings_manager.set_setting(
                "general", "enable_notifications", checked
            )
        )
        general_group.addSettingCard(self.notify_card)

        # Edge auto-hide + hover auto-show (combined feature)
        self.hover_card = SwitchSettingCard(
            FluentIcon.MOVE,
            "贴边隐藏与悬停显示",
            "开启后，鼠标离开侧边栏时自动贴边隐藏，移入时自动显示。\n关闭后侧边栏将始终保持展开状态，仅可通过快捷键收起。",
            parent=general_group,
        )
        self.hover_card.switchButton.setChecked(
            self.settings_manager.get_setting("general", "enable_mouse_hover", True)
        )
        self.hover_card.switchButton.checkedChanged.connect(
            lambda checked: self.settings_manager.set_setting(
                "general", "enable_mouse_hover", checked
            )
        )
        general_group.addSettingCard(self.hover_card)

        content_layout.addWidget(general_group)

        # === Appearance Settings Group ===
        appearance_group = SettingCardGroup("外观设置", self)

        # Theme mode - using custom card with ComboBox
        self._add_theme_card(appearance_group, ComboBox, FluentIcon, BodyLabel)

        # Sidebar Position - using custom card with ComboBox
        self._add_sidebar_position_card(
            appearance_group, ComboBox, FluentIcon, BodyLabel
        )

        # Accent color
        self.color_card = PushSettingCard(
            "选择颜色",
            FluentIcon.PALETTE,
            "强调色",
            "自定义应用程序的主题颜色",
            parent=appearance_group,
        )
        self.color_card.clicked.connect(self._choose_accent_color)
        appearance_group.addSettingCard(self.color_card)

        # Peek Width
        self._add_slider_card(
            group=appearance_group,
            icon=FluentIcon.LAYOUT,
            title="隐藏边框宽度",
            content="侧边栏隐藏时显示的边框宽度（像素）",
            min_val=0,
            max_val=10,
            value=self.settings_manager.get_setting("appearance", "peek_width", 2),
            callback=lambda val: self.settings_manager.set_setting(
                "appearance", "peek_width", val
            ),
        )

        # Sidebar Background Opacity
        self._add_slider_card(
            group=appearance_group,
            icon=FluentIcon.TRANSPARENT,
            title="侧边栏不透明度",
            content="侧边栏背景的不透明度（值越大越不透明）",
            min_val=0,
            max_val=100,
            value=int(
                self.settings_manager.get_setting(
                    "appearance", "sidebar_bg_opacity", 0.9
                )
                * 100
            ),
            callback=lambda val: self.settings_manager.set_setting(
                "appearance", "sidebar_bg_opacity", val / 100.0
            ),
        )

        # Detail Window Background Opacity
        self._add_slider_card(
            group=appearance_group,
            icon=FluentIcon.TRANSPARENT,
            title="详情页不透明度",
            content="详情页背景的不透明度（值越大越不透明）",
            min_val=10,
            max_val=100,
            value=int(
                self.settings_manager.get_setting(
                    "appearance", "detail_bg_opacity", 0.9
                )
                * 100
            ),
            callback=lambda val: self.settings_manager.set_setting(
                "appearance", "detail_bg_opacity", val / 100.0
            ),
        )

        # Hidden Sidebar Border Color
        self.border_color_card = PushSettingCard(
            "选择颜色",
            FluentIcon.BRUSH,
            "边框颜色",
            "设置侧边栏的边缘颜色",
            parent=appearance_group,
        )
        self.border_color_card.clicked.connect(self._choose_sidebar_border_color)
        appearance_group.addSettingCard(self.border_color_card)

        # Sidebar Height
        self._add_slider_card(
            group=appearance_group,
            icon=FluentIcon.TILES,
            title="侧边栏高度",
            content="侧边栏占屏幕高度的百分比",
            min_val=20,
            max_val=100,
            value=int(
                self.settings_manager.get_setting(
                    "appearance", "sidebar_height_percent", 0.8
                )
                * 100
            ),
            callback=lambda val: self.settings_manager.set_setting(
                "appearance", "sidebar_height_percent", val / 100.0
            ),
        )

        # Sidebar Hidden Height
        self._add_slider_card(
            group=appearance_group,
            icon=FluentIcon.HIDE,
            title="侧边栏隐藏时的高度",
            content="侧边栏隐藏（Peek 状态）时占屏幕高度的百分比",
            min_val=20,
            max_val=100,
            value=int(
                self.settings_manager.get_setting(
                    "appearance", "sidebar_hidden_height_percent", 0.8
                )
                * 100
            ),
            callback=lambda val: self.settings_manager.set_setting(
                "appearance", "sidebar_hidden_height_percent", val / 100.0
            ),
        )

        # Detail Window Min Height
        self._add_slider_card(
            group=appearance_group,
            icon=FluentIcon.FULL_SCREEN,
            title="详情页最小高度",
            content="设置插件详情页的最小高度 (像素)",
            min_val=300,
            max_val=1200,
            value=self.settings_manager.get_setting(
                "appearance", "detail_min_height", 700
            ),
            callback=lambda val: self.settings_manager.set_setting(
                "appearance", "detail_min_height", val
            ),
        )

        # Sidebar Vertical Offset Reset
        self.reset_pos_card = PushSettingCard(
            "重置位置",
            FluentIcon.MOVE,
            "侧边栏垂直位置",
            "将侧边栏恢复到屏幕中心",
            parent=appearance_group,
        )
        self.reset_pos_card.clicked.connect(self._reset_sidebar_position)
        appearance_group.addSettingCard(self.reset_pos_card)

        # Max Plugins Displayed
        self._add_slider_card(
            group=appearance_group,
            icon=FluentIcon.TILES,
            title="显示插件数量限制",
            content="侧边栏最多显示的插件数量（0表示不限制）",
            min_val=0,
            max_val=20,
            value=self.settings_manager.get_setting(
                "appearance", "max_plugins_count", 0
            ),
            callback=lambda val: self.settings_manager.set_setting(
                "appearance", "max_plugins_count", val
            ),
        )

        content_layout.addWidget(appearance_group)

        # === Storage Settings Group ===
        storage_group = SettingCardGroup("数据与存储", self)

        self.open_appdata_card = PushSettingCard(
            "打开目录",
            FluentIcon.FOLDER,
            "应用数据目录",
            "打开 Agile Tiles 存放配置和数据库的 AppData 目录",
            parent=storage_group,
        )
        self.open_appdata_card.clicked.connect(self._open_appdata_dir)
        storage_group.addSettingCard(self.open_appdata_card)

        content_layout.addWidget(storage_group)

        # === Plugins Group ===
        self.plugin_group_layout = content_layout  # Store for refreshing
        self._add_plugin_group(content_layout)

        # === About Section ===
        about_group = SettingCardGroup("关于", self)

        # Version info
        self.version_card = PushSettingCard(
            "检查更新",
            FluentIcon.INFO,
            "Agile Tiles",
            "版本 1.0.0 - Modern Desktop Productivity",
            parent=about_group,
        )
        self.version_card.clicked.connect(self._check_updates)
        about_group.addSettingCard(self.version_card)

        # Reset settings
        self.reset_card = PushSettingCard(
            "重置",
            FluentIcon.SYNC,
            "重置设置",
            "将所有设置恢复为默认值",
            parent=about_group,
        )
        self.reset_card.clicked.connect(self._reset_settings)
        about_group.addSettingCard(self.reset_card)

        content_layout.addWidget(about_group)

        # Add stretch at bottom
        content_layout.addStretch(1)

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _add_theme_card(self, parent_group, ComboBox, FluentIcon, BodyLabel):
        """Add a custom theme selection card using CardWidget."""
        from qfluentwidgets import IconWidget

        # Create custom card
        card = CardWidget(parent_group)
        card.setFixedHeight(70)

        h_layout = QHBoxLayout(card)
        h_layout.setContentsMargins(20, 12, 20, 12)

        # Icon
        icon_widget = IconWidget(FluentIcon.BRUSH, card)
        icon_widget.setFixedSize(20, 20)
        h_layout.addWidget(icon_widget)

        # Text
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        title_label = BodyLabel("主题模式", card)
        content_label = BodyLabel("选择应用程序的显示主题", card)
        content_label.setStyleSheet("color: gray; font-size: 12px;")
        text_layout.addWidget(title_label)
        text_layout.addWidget(content_label)
        h_layout.addLayout(text_layout)

        h_layout.addStretch(1)

        # ComboBox
        self.theme_combo = ComboBox(card)
        self.theme_combo.addItems(["深色", "浅色", "跟随系统"])
        current_theme = self.settings_manager.get_setting(
            "appearance", "theme_mode", "dark"
        )
        theme_index = {"dark": 0, "light": 1, "system": 2}.get(current_theme, 0)
        self.theme_combo.setCurrentIndex(theme_index)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        h_layout.addWidget(self.theme_combo)

        parent_group.addSettingCard(card)

    def _add_sidebar_position_card(self, parent_group, ComboBox, FluentIcon, BodyLabel):
        """Add a custom sidebar position selection card using CardWidget."""
        from qfluentwidgets import IconWidget

        # Create custom card
        card = CardWidget(parent_group)
        card.setFixedHeight(70)

        h_layout = QHBoxLayout(card)
        h_layout.setContentsMargins(20, 12, 20, 12)

        # Icon
        icon_widget = IconWidget(FluentIcon.ALIGNMENT, card)
        icon_widget.setFixedSize(20, 20)
        h_layout.addWidget(icon_widget)

        # Text
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        title_label = BodyLabel("侧边栏位置", card)
        content_label = BodyLabel("选择侧边栏显示的位置", card)
        content_label.setStyleSheet("color: gray; font-size: 12px;")
        text_layout.addWidget(title_label)
        text_layout.addWidget(content_label)
        h_layout.addLayout(text_layout)

        h_layout.addStretch(1)

        # ComboBox
        self.position_combo = ComboBox(card)
        self.position_combo.addItems(["左侧", "右侧", "顶部"])
        current_position = self.settings_manager.get_setting(
            "appearance", "sidebar_position", "right"
        )
        position_index = {"left": 0, "right": 1, "top": 2}.get(current_position, 1)
        self.position_combo.setCurrentIndex(position_index)
        self.position_combo.currentIndexChanged.connect(self._on_position_changed)
        h_layout.addWidget(self.position_combo)

        parent_group.addSettingCard(card)

    def _on_position_changed(self, index: int):
        """Handle sidebar position change."""
        from qfluentwidgets import InfoBar, InfoBarPosition

        position_map = {0: "left", 1: "right", 2: "top"}
        position_name = position_map.get(index, "right")
        self.settings_manager.set_setting(
            "appearance", "sidebar_position", position_name
        )

        InfoBar.success(
            title="位置已更改",
            content=f"侧边栏位置已设置为{['左侧', '右侧', '顶部'][index]}",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self,
        )

    def _on_theme_changed(self, index: int):
        """Handle theme change."""
        from qfluentwidgets import InfoBar, InfoBarPosition, Theme, setTheme

        theme_map = {0: "dark", 1: "light", 2: "system"}
        theme_name = theme_map.get(index, "dark")
        self.settings_manager.set_setting("appearance", "theme_mode", theme_name)

        # Apply theme immediately
        if theme_name == "dark":
            setTheme(Theme.DARK)
        elif theme_name == "light":
            setTheme(Theme.LIGHT)
        else:
            setTheme(Theme.AUTO)

        self.theme_changed.emit(theme_name)

        InfoBar.success(
            title="主题已更改",
            content=f"已切换到{['深色', '浅色', '系统'][index]}主题",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self,
        )

    def _choose_accent_color(self):
        """Open color picker for accent color."""
        from PySide6.QtWidgets import QColorDialog
        from qfluentwidgets import InfoBar, InfoBarPosition, setThemeColor

        current_color = self.settings_manager.get_setting(
            "appearance", "accent_color", "#FF6B9D"
        )

        color = QColorDialog.getColor(QColor(current_color), self, "选择强调色")
        if color.isValid():
            color_hex = color.name()
            self.settings_manager.set_setting("appearance", "accent_color", color_hex)
            setThemeColor(color_hex)

            InfoBar.success(
                title="颜色已更改",
                content=f"强调色已设置为 {color_hex}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )

    def _choose_sidebar_border_color(self):
        """Open color picker for hidden sidebar border color."""
        from PySide6.QtWidgets import QColorDialog
        from qfluentwidgets import InfoBar, InfoBarPosition

        current_color = self.settings_manager.get_setting(
            "appearance", "sidebar_border_color", "#FF0000"
        )

        color = QColorDialog.getColor(QColor(current_color), self, "选择隐藏边框颜色")
        if color.isValid():
            color_hex = color.name()
            self.settings_manager.set_setting(
                "appearance", "sidebar_border_color", color_hex
            )

            InfoBar.success(
                title="颜色已更改",
                content=f"隐藏边框颜色已设置为 {color_hex}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )

    def _add_slider_card(
        self, group, icon, title, content, min_val, max_val, value, callback
    ):
        """Add a manual slider card."""
        from qfluentwidgets import IconWidget, Slider

        card = CardWidget(group)
        card.setFixedHeight(80)

        h_layout = QHBoxLayout(card)
        h_layout.setContentsMargins(20, 10, 20, 10)
        h_layout.setSpacing(20)

        # Icon
        icon_widget = IconWidget(icon, card)
        icon_widget.setFixedSize(24, 24)
        h_layout.addWidget(icon_widget)

        # Labels
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        title_label = BodyLabel(title, card)
        content_label = BodyLabel(content, card)
        content_label.setStyleSheet("color: gray; font-size: 12px;")
        text_layout.addWidget(title_label)
        text_layout.addWidget(content_label)
        h_layout.addLayout(text_layout)

        h_layout.addStretch(1)

        # Slider
        slider_layout = QVBoxLayout()
        slider_layout.setAlignment(Qt.AlignCenter)

        slider = Slider(Qt.Horizontal, card)
        slider.setRange(min_val, max_val)
        slider.setValue(value)
        slider.setFixedWidth(150)

        # Value Label
        val_label = BodyLabel(str(value), card)
        val_label.setAlignment(Qt.AlignCenter)

        slider.valueChanged.connect(lambda v: (val_label.setText(str(v)), callback(v)))

        h_layout.addWidget(slider)
        h_layout.addWidget(val_label)

        group.addSettingCard(card)

    def _check_updates(self):
        """Check for updates."""
        from qfluentwidgets import InfoBar, InfoBarPosition

        InfoBar.info(
            title="检查更新",
            content="您正在使用最新版本！",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

    def _reset_sidebar_position(self):
        """Reset sidebar vertical offset to 0 (center)."""
        from qfluentwidgets import InfoBar, InfoBarPosition

        self.settings_manager.set_setting("appearance", "sidebar_y_offset", 0)

        InfoBar.success(
            title="位置已重置",
            content="侧边栏已恢复到屏幕中心",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self,
        )

    def _open_appdata_dir(self):
        """Open the AppData directory in explorer."""
        path = PathManager.get_app_data_root()
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _reset_settings(self):
        """Reset all settings to defaults."""
        from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox

        box = MessageBox("确认重置", "确定要将所有设置恢复为默认值吗？", self)

        if box.exec():
            self.settings_manager.reset_to_defaults()

            InfoBar.success(
                title="设置已重置",
                content="所有设置已恢复为默认值，请重启应用",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )

    def get_preferred_width(self) -> int:
        """Return preferred width for the settings card."""
        return self.settings_manager.get_setting("appearance", "sidebar_width", 500)

        return self.settings_manager.get_setting("appearance", "sidebar_width", 500)

    def _add_plugin_group(self, layout):
        """Add plugin management section."""
        if not self.settings_manager.plugin_manager:
            return

        # === Shortcuts Group ===
        # Check if group already exists (for refresh)
        if hasattr(self, "shortcut_group"):
            self.shortcut_group.deleteLater()
            self.plugin_group.deleteLater()

        self.shortcut_group = SettingCardGroup("快捷键", self)

        # Global: Toggle Sidebar
        self._add_shortcut_card(
            self.shortcut_group,
            "sidebar_toggle",
            FluentIcon.MENU,
            "显示/隐藏侧边栏",
            "全局快捷键",
            "toggle_sidebar",
            "alt+space",
        )

        layout.addWidget(self.shortcut_group)

        # === Plugins Group ===
        self.plugin_group = SettingCardGroup("插件管理", self)

        manifests = self.settings_manager.plugin_manager.get_all_manifests()

        # Use stored order
        ordered_ids = self.settings_manager.plugin_manager.get_plugin_order()

        for index, pid in enumerate(ordered_ids):
            if pid not in manifests:
                continue

            manifest = manifests[pid]
            # Use name from manifest, default to capitalized ID
            default_name = pid.split(".")[-1].replace("_", " ").title()
            name = manifest.get("name", default_name)
            description = manifest.get("description", "No description available")

            # 1. Enable/Disable Toggle
            card = SwitchSettingCard(
                FluentIcon.TILES, name, description, parent=self.plugin_group
            )

            # Add Up/Down buttons
            from qfluentwidgets import ToolButton

            # Up Button
            btn_up = ToolButton(FluentIcon.UP, card)
            btn_up.setFixedSize(30, 30)
            btn_up.setToolTip("上移")
            btn_up.clicked.connect(lambda _, p=pid: self._move_plugin(p, -1))
            if index == 0:
                btn_up.setEnabled(False)

            # Down Button
            btn_down = ToolButton(FluentIcon.DOWN, card)
            btn_down.setFixedSize(30, 30)
            btn_down.setToolTip("下移")
            btn_down.clicked.connect(lambda _, p=pid: self._move_plugin(p, 1))
            if index == len(ordered_ids) - 1:
                btn_down.setEnabled(False)

            # Insert buttons before the switch (which is usually at the end)
            # SwitchSettingCard layout: icon, labels, space, switch
            # We want: icon, labels, space, UP, DOWN, switch

            # Access the internal layout
            # Usually hBoxLayout.
            # Let's try adding them. They will be added to the end.
            # To insert before switch, we need to know where switch is.
            # qfluentwidgets SwitchSettingCard usually has self.switchButton.
            # We can remove switchButton and re-add it? Or insertWidget.

            # card.hBoxLayout.addWidget(btn_up)
            # card.hBoxLayout.addWidget(btn_down)

            # But we want them before the switch.
            # Assuming hBoxLayout has the switch as the last item.
            count = card.hBoxLayout.count()
            # Insert at count-1 (before switch)
            card.hBoxLayout.insertWidget(count - 1, btn_up)
            card.hBoxLayout.insertWidget(count - 1, btn_down)
            card.hBoxLayout.insertSpacing(count - 1, 10)

            # Determine checked state
            disabled_list = self.settings_manager.get_setting("plugins", "disabled", [])
            is_enabled = pid not in disabled_list
            card.switchButton.setChecked(is_enabled)

            # Connect
            card.switchButton.checkedChanged.connect(
                lambda checked, p=pid: self._on_plugin_toggled(p, checked)
            )

            self.plugin_group.addSettingCard(card)

            # 2. Add Shortcut for this plugin to the shortcut group
            self._add_shortcut_card(
                self.shortcut_group,
                f"plugin_{pid}",
                FluentIcon.APPLICATION,
                f"{name} 快捷键",
                f"快速打开 {name}",
                f"plugin.{pid}",
                None,
            )

        layout.addWidget(self.plugin_group)

    def _move_plugin(self, plugin_id, direction):
        """Move plugin up or down in the list."""
        manager = self.settings_manager.plugin_manager
        current_order = manager.get_plugin_order()

        if plugin_id not in current_order:
            return

        index = current_order.index(plugin_id)
        new_index = index + direction

        if 0 <= new_index < len(current_order):
            # Swap
            current_order[index], current_order[new_index] = (
                current_order[new_index],
                current_order[index],
            )
            manager.set_plugin_order(current_order)

            # Refresh UI
            self._add_plugin_group(self.plugin_group_layout)

    def _add_shortcut_card(
        self, group, card_id, icon, title, content, setting_key, default_val
    ):
        """Add a shortcut setting card."""
        from qfluentwidgets import IconWidget

        card = CardWidget(group)
        card.setFixedHeight(70)

        h_layout = QHBoxLayout(card)
        h_layout.setContentsMargins(20, 10, 20, 10)
        h_layout.setSpacing(20)

        # Icon
        icon_widget = IconWidget(icon, card)
        icon_widget.setFixedSize(24, 24)
        h_layout.addWidget(icon_widget)

        # Labels
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        title_label = BodyLabel(title, card)
        content_label = BodyLabel(content, card)
        content_label.setStyleSheet("color: gray; font-size: 12px;")
        text_layout.addWidget(title_label)
        text_layout.addWidget(content_label)
        h_layout.addLayout(text_layout)

        h_layout.addStretch(1)

        # Shortcut Button
        current_val = self.settings_manager.get_setting(
            "shortcuts", setting_key, default_val
        )
        btn = ShortcutPickerButton(current_val, card)
        btn.shortcutChanged.connect(
            lambda val, k=setting_key: self.settings_manager.set_setting(
                "shortcuts", k, val
            )
        )

        h_layout.addWidget(btn)

        group.addSettingCard(card)

    def _on_plugin_toggled(self, plugin_id, checked):
        """Handle plugin enable/disable toggle."""
        disabled_list = self.settings_manager.get_setting("plugins", "disabled", [])
        # We need a copy to modify
        new_list = list(disabled_list)

        if checked:
            # Enable -> Remove from disabled list
            if plugin_id in new_list:
                new_list.remove(plugin_id)
        else:
            # Disable -> Add to disabled list
            if plugin_id not in new_list:
                new_list.append(plugin_id)

        self.settings_manager.set_setting("plugins", "disabled", new_list)
