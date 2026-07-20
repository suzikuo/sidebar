import sys

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFontComboBox,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel

from core.data_layer.path_utils import PathManager
from ui.components.base_widget import BScrollArea


class SettingsCard(QWidget):
    """
    Main Settings UI.
    Layout: Left Sidebar (Categories) | Right Content (Details)
    Style: BewlyCat inspired (Clean, Modern, Rounded)
    """

    # Signals for settings changes
    theme_changed = Signal(str)  # theme_mode
    font_changed = Signal(str, int, str)  # family, size, weight
    sidebar_position_changed = Signal(str)  # position

    def __init__(self, settings_manager):
        super().__init__()
        self.settings_manager = settings_manager
        self.theme_engine = settings_manager.theme_engine

        # Main Layout
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # 1. Left Sidebar (Categories)
        self.category_bar = QWidget()
        self.category_bar.setFixedWidth(180)
        self.category_bar.setObjectName("SettingsCategoryBar")
        self.category_layout = QVBoxLayout(self.category_bar)
        self.category_layout.setContentsMargins(10, 20, 10, 20)
        self.category_layout.setSpacing(5)

        # Category List
        self.category_list = QListWidget()
        self.category_list.setFrameShape(QFrame.NoFrame)
        self.category_list.setFocusPolicy(Qt.NoFocus)
        self.category_list.setObjectName("SettingsCategoryList")

        categories = ["General", "Appearance", "Fonts", "Plugins", "About"]
        for cat in categories:
            item = QListWidgetItem(cat)
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            item.setSizeHint(QSize(0, 40))
            self.category_list.addItem(item)

        self.category_list.currentRowChanged.connect(self._on_category_changed)
        self.category_layout.addWidget(self.category_list)

        # 2. Right Content Area
        self.content_area = BScrollArea()
        self.content_area.setFrameShape(QFrame.NoFrame)
        self.content_area.setWidgetResizable(True)
        self.content_area.setObjectName("SettingsContentArea")

        self.content_container = QWidget()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(30, 30, 30, 30)
        self.content_layout.setSpacing(20)
        self.content_layout.setAlignment(Qt.AlignTop)

        self.content_area.setWidget(self.content_container)

        # Add to main layout
        self.layout.addWidget(self.category_bar)
        self.layout.addWidget(self.content_area)

        # Apply Style
        self._apply_style()

        # Select first category
        self.category_list.setCurrentRow(0)

    def _apply_style(self):
        self.setStyleSheet("""
            #SettingsCategoryBar {
                background-color: rgba(245, 245, 247, 0.5);
                border-right: 1px solid #E5E5E5;
            }
            #SettingsContentArea {
                background-color: transparent;
            }
            QListWidget {
                background: transparent;
                outline: none;
            }
            QListWidget::item {
                border-radius: 8px;
                padding-left: 10px;
                color: #555;
                font-weight: 500;
            }
            QListWidget::item:selected {
                background-color: #FFFFFF;
                color: #000;
                border: 1px solid #EAEAEA;
            }
            QListWidget::item:hover:!selected {
                background-color: rgba(0, 0, 0, 0.03);
            }
            
            QLabel.SectionHeader {
                font-size: 18px;
                font-weight: bold;
                color: #333;
                margin-bottom: 10px;
            }
            
            QFrame.SettingGroup {
                background-color: #FFFFFF;
                border-radius: 12px;
                border: 1px solid #EAEAEA;
            }
        """)

    def _on_category_changed(self, row):
        # Clear current content safely
        for i in reversed(range(self.content_layout.count())):
            item = self.content_layout.itemAt(i)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                else:
                    self.content_layout.removeItem(item)

        category = self.category_list.item(row).text()

        title = BodyLabel(category)
        title.setProperty("class", "SectionHeader")
        title.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 20px;")
        self.content_layout.addWidget(title)

        if category == "General":
            self._build_general_settings()
        elif category == "Appearance":
            self._build_appearance_settings()
        elif category == "Fonts":
            self._build_font_settings()
        elif category == "Plugins":
            self._build_plugins_settings()
        elif category == "About":
            self._build_about_settings()

        self.content_layout.addStretch()

    def _create_setting_row(self, label_text, control_widget, description=None):
        container = QFrame()
        container.setProperty("class", "SettingGroup")
        container.setStyleSheet("""
            background-color: #FFF; 
            border-radius: 8px; 
            border: 1px solid #EEE;
        """)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(15, 12, 15, 12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        lbl = BodyLabel(label_text)
        lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #333;")
        text_layout.addWidget(lbl)

        if description:
            desc = BodyLabel(description)
            desc.setStyleSheet("font-size: 12px; color: #888;")
            desc.setWordWrap(True)
            text_layout.addWidget(desc)

        layout.addLayout(text_layout)
        layout.addStretch()
        layout.addWidget(control_widget)

        return container

    def _build_general_settings(self):
        """Build general settings section."""
        # Startup
        cb_startup = QCheckBox()
        startup_enabled = self.settings_manager.get_setting(
            "general", "run_on_startup", False
        )
        cb_startup.setChecked(startup_enabled)
        cb_startup.toggled.connect(
            lambda checked: self.settings_manager.set_setting(
                "general", "run_on_startup", checked
            )
        )
        self.content_layout.addWidget(
            self._create_setting_row(
                "Run on Startup",
                cb_startup,
                "Launch Agile Tiles automatically when you log in.",
            )
        )

        # Notifications
        cb_notify = QCheckBox()
        notify_enabled = self.settings_manager.get_setting(
            "notifications", "enabled", True
        )
        cb_notify.setChecked(notify_enabled)
        cb_notify.toggled.connect(
            lambda checked: self.settings_manager.set_setting(
                "notifications", "enabled", checked
            )
        )
        self.content_layout.addWidget(
            self._create_setting_row(
                "Enable Notifications",
                cb_notify,
                "Show system notifications for reminders.",
            )
        )

        # Auto-hide delay
        delay_slider = QSlider(Qt.Horizontal)
        delay_slider.setRange(500, 3000)
        delay_slider.setSingleStep(100)
        current_delay = self.settings_manager.get_setting(
            "general", "auto_hide_delay", 1000
        )
        delay_slider.setValue(current_delay)
        delay_slider.setFixedWidth(200)

        delay_container = QWidget()
        delay_layout = QHBoxLayout(delay_container)
        delay_layout.setContentsMargins(0, 0, 0, 0)
        delay_layout.addWidget(delay_slider)
        delay_label = BodyLabel(f"{current_delay}ms")
        delay_label.setFixedWidth(60)
        delay_label.setStyleSheet("color: #666; font-size: 12px;")
        delay_layout.addWidget(delay_label)

        def update_delay(value):
            delay_label.setText(f"{value}ms")
            self.settings_manager.set_setting("general", "auto_hide_delay", value)

        self.content_layout.addWidget(
            self._create_setting_row(
                "Auto-hide Delay",
                delay_container,
                "Time before sidebar hides when mouse leaves (milliseconds).",
            )
        )

        # Open AppData button
        open_btn = QPushButton("Open AppData Folder")
        open_btn.setStyleSheet("""
            QPushButton {
                background-color: #F5F5F5;
                color: #555;
                border: 1px solid #DDD;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #E8E8E8;
            }
        """)
        open_btn.clicked.connect(self._open_appdata_dir)
        self.content_layout.addWidget(
            self._create_setting_row(
                "App Data Storage",
                open_btn,
                "Open the folder where settings and databases are stored.",
            )
        )

    def _build_appearance_settings(self):
        """Build appearance settings section."""
        # Theme Mode
        theme_group = QButtonGroup(self)
        theme_container = QWidget()
        theme_layout = QHBoxLayout(theme_container)
        theme_layout.setSpacing(10)

        current_theme = self.settings_manager.get_setting(
            "appearance", "theme_mode", "dark"
        )

        for theme in ["System", "Light", "Dark"]:
            rb = QRadioButton(theme)
            rb.setStyleSheet("font-size: 13px;")
            if theme.lower() == current_theme:
                rb.setChecked(True)
            theme_group.addButton(rb)
            theme_layout.addWidget(rb)
            rb.toggled.connect(
                lambda checked, t=theme: self._on_theme_changed(t) if checked else None
            )

        self.content_layout.addWidget(
            self._create_setting_row(
                "Theme Mode",
                theme_container,
                "Select your preferred appearance. Changes require restart.",
            )
        )

        # Sidebar Position
        pos_combo = QComboBox()
        pos_combo.addItems(["Right", "Left"])
        current_pos = self.settings_manager.get_setting(
            "appearance", "sidebar_position", "right"
        )
        pos_combo.setCurrentText(current_pos.capitalize())
        pos_combo.currentTextChanged.connect(
            lambda text: self._on_position_changed(text.lower())
        )
        pos_combo.setFixedWidth(120)
        self.content_layout.addWidget(
            self._create_setting_row(
                "Sidebar Position",
                pos_combo,
                "Choose which side of the screen the sidebar attaches to. Requires restart.",
            )
        )

        # Sidebar Width
        width_slider = QSlider(Qt.Horizontal)
        width_slider.setRange(300, 700)
        width_slider.setSingleStep(10)
        current_width = self.settings_manager.get_setting(
            "appearance", "sidebar_width", 500
        )
        width_slider.setValue(current_width)
        width_slider.setFixedWidth(200)

        width_container = QWidget()
        width_layout = QHBoxLayout(width_container)
        width_layout.setContentsMargins(0, 0, 0, 0)
        width_layout.addWidget(width_slider)
        width_label = BodyLabel(f"{current_width}px")
        width_label.setFixedWidth(60)
        width_label.setStyleSheet("color: #666; font-size: 12px;")
        width_layout.addWidget(width_label)

        def update_width(value):
            width_label.setText(f"{value}px")
            self.settings_manager.set_setting("appearance", "sidebar_width", value)

        width_slider.valueChanged.connect(update_width)

        self.content_layout.addWidget(
            self._create_setting_row(
                "Sidebar Width",
                width_container,
                "Adjust the expanded width of the sidebar.",
            )
        )

        # Accent Color
        color_btn = QPushButton("Choose Color")
        current_color = self.settings_manager.get_setting(
            "appearance", "accent_color", "#FF6B9D"
        )
        color_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {current_color};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)
        color_btn.clicked.connect(lambda: self._choose_accent_color(color_btn))

        self.content_layout.addWidget(
            self._create_setting_row(
                "Accent Color",
                color_btn,
                "Choose the primary accent color for the application.",
            )
        )

    def _build_font_settings(self):
        """Build font settings section."""
        # Font Family
        font_combo = QFontComboBox()
        current_font = self.settings_manager.get_setting(
            "appearance", "font_family", "Segoe UI"
        )
        font_combo.setCurrentFont(QFont(current_font))
        font_combo.setFixedWidth(200)
        font_combo.currentFontChanged.connect(
            lambda font: self._on_font_changed(font.family())
        )

        self.content_layout.addWidget(
            self._create_setting_row(
                "Font Family", font_combo, "Select the font family for the application."
            )
        )

        # Font Size
        size_spin = QSpinBox()
        size_spin.setRange(10, 18)
        current_size = self.settings_manager.get_setting("appearance", "font_size", 13)
        size_spin.setValue(current_size)
        size_spin.setFixedWidth(80)
        size_spin.valueChanged.connect(
            lambda value: self.settings_manager.set_setting(
                "appearance", "font_size", value
            )
        )

        self.content_layout.addWidget(
            self._create_setting_row(
                "Font Size", size_spin, "Adjust the base font size (10-18pt)."
            )
        )

        # Font Weight
        weight_combo = QComboBox()
        weight_combo.addItems(["Light", "Normal", "Medium", "Bold"])
        current_weight = self.settings_manager.get_setting(
            "appearance", "font_weight", "normal"
        )
        weight_combo.setCurrentText(current_weight.capitalize())
        weight_combo.setFixedWidth(120)
        weight_combo.currentTextChanged.connect(
            lambda text: self.settings_manager.set_setting(
                "appearance", "font_weight", text.lower()
            )
        )

        self.content_layout.addWidget(
            self._create_setting_row(
                "Font Weight", weight_combo, "Select the font weight/thickness."
            )
        )

        # Preview
        preview_label = BodyLabel("The quick brown fox jumps over the lazy dog")
        preview_label.setStyleSheet(f"""
            background-color: #F5F5F5;
            border: 1px solid #DDD;
            border-radius: 6px;
            padding: 20px;
            font-family: '{current_font}';
            font-size: {current_size}pt;
            color: #333;
        """)
        preview_label.setAlignment(Qt.AlignCenter)

        preview_frame = QFrame()
        preview_frame.setStyleSheet(
            "background-color: #FFF; border-radius: 8px; border: 1px solid #EEE;"
        )
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(15, 15, 15, 15)

        preview_title = BodyLabel("Font Preview")
        preview_title.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #333; margin-bottom: 10px;"
        )
        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(preview_label)

        self.content_layout.addWidget(preview_frame)

    def _build_plugins_settings(self):
        """Build plugins management section."""
        from ui.components.plugin_list_widget import PluginListWidget

        # Get plugin manager from main app (we need to pass it through)
        # For now, show a placeholder
        desc = BodyLabel(
            "Plugin management allows you to enable/disable installed plugins."
        )
        desc.setStyleSheet("color: #666; margin-bottom: 15px;")
        desc.setWordWrap(True)
        self.content_layout.addWidget(desc)

        # Try to get plugin manager
        try:
            # This is a bit hacky, but we need access to the plugin manager
            # In a production app, this would be passed through properly
            import __main__

            if hasattr(__main__, "app_instance") and hasattr(
                __main__.app_instance, "plugin_manager"
            ):
                plugin_list = PluginListWidget(
                    __main__.app_instance.plugin_manager, self.settings_manager
                )
                self.content_layout.addWidget(plugin_list)
            else:
                placeholder = BodyLabel("Plugin manager not available")
                placeholder.setStyleSheet(
                    "color: #999; font-style: italic; padding: 20px;"
                )
                self.content_layout.addWidget(placeholder)
        except:
            placeholder = BodyLabel("Plugin manager not available")
            placeholder.setStyleSheet("color: #999; font-style: italic; padding: 20px;")
            self.content_layout.addWidget(placeholder)

    def _build_about_settings(self):
        """Build about section."""
        info_frame = QFrame()
        info_frame.setStyleSheet(
            "background-color: #FFF; border-radius: 8px; border: 1px solid #EEE;"
        )
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(20, 20, 20, 20)
        info_layout.setSpacing(15)

        # App name
        app_name = BodyLabel("Agile Tiles")
        app_name.setStyleSheet("font-size: 24px; font-weight: bold; color: #333;")
        info_layout.addWidget(app_name)

        # Version
        version = BodyLabel("Version 0.2.0")
        version.setStyleSheet("font-size: 14px; color: #666;")
        info_layout.addWidget(version)

        # Description
        desc = BodyLabel(
            "A modern desktop productivity tool with plugin support.\nCreated with Python and PySide6."
        )
        desc.setStyleSheet("color: #666; line-height: 1.6; margin-top: 10px;")
        desc.setWordWrap(True)
        info_layout.addWidget(desc)

        # System info
        sys_info = BodyLabel(f"Python {sys.version.split()[0]} • {sys.platform}")
        sys_info.setStyleSheet("font-size: 11px; color: #999; margin-top: 10px;")
        info_layout.addWidget(sys_info)

        self.content_layout.addWidget(info_frame)

        # Buttons
        btn_layout = QHBoxLayout()

        check_btn = QPushButton("Check for Updates")
        check_btn.setFixedWidth(150)
        check_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF6B9D;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #FF5A8C;
            }
        """)
        btn_layout.addWidget(check_btn)

        btn_layout.addStretch()

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setFixedWidth(150)
        reset_btn.clicked.connect(self._reset_settings)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #F5F5F5;
                color: #555;
                border: 1px solid #DDD;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #E8E8E8;
            }
        """)
        btn_layout.addWidget(reset_btn)

        self.content_layout.addLayout(btn_layout)

    def _on_theme_changed(self, theme: str):
        """Handle theme change."""
        self.settings_manager.set_setting("appearance", "theme_mode", theme.lower())
        self.theme_changed.emit(theme.lower())

        # Apply theme to theme engine
        self.theme_engine.set_theme_mode(theme.lower())

        QMessageBox.information(
            self,
            "Theme Changed",
            f"Theme changed to {theme}.\nPlease restart the application for changes to take full effect.",
        )

    def _open_appdata_dir(self):
        """Open the AppData directory in explorer."""
        path = PathManager.get_app_data_root()
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_position_changed(self, position: str):
        """Handle sidebar position change."""
        self.settings_manager.set_setting("appearance", "sidebar_position", position)
        self.sidebar_position_changed.emit(position)

        # Show restart notice
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            self,
            "Position Changed",
            f"Sidebar position changed to {position}.\nPlease restart the application for changes to take effect.",
        )

    def _on_font_changed(self, family: str):
        """Handle font family change."""
        self.settings_manager.set_setting("appearance", "font_family", family)
        size = self.settings_manager.get_setting("appearance", "font_size", 13)
        weight = self.settings_manager.get_setting(
            "appearance", "font_weight", "normal"
        )

        # Apply font to theme engine
        self.theme_engine.set_font(family, size)

        self.font_changed.emit(family, size, weight)

        # Show restart notice
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            self,
            "Font Changed",
            f"Font changed to {family}.\nPlease restart the application for changes to take effect.",
        )

    def _choose_accent_color(self, button: QPushButton):
        """Open color picker for accent color."""
        current_color = self.settings_manager.get_setting(
            "appearance", "accent_color", "#FF6B9D"
        )
        color = QColorDialog.getColor(
            QColor(current_color), self, "Choose Accent Color"
        )

        if color.isValid():
            color_hex = color.name()
            self.settings_manager.set_setting("appearance", "accent_color", color_hex)

            # Apply to theme engine
            self.theme_engine.set_accent_color(color_hex)

            button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color_hex};
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    opacity: 0.9;
                }}
            """)

    def _reset_settings(self):
        """Reset all settings to defaults."""
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Are you sure you want to reset all settings to defaults?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.settings_manager.reset_to_defaults()
            # Refresh the current category
            current_row = self.category_list.currentRow()
            self._on_category_changed(current_row)

            QMessageBox.information(
                self,
                "Settings Reset",
                "All settings have been reset to defaults.\nPlease restart the application.",
            )
