from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ColorPickerButton,
    LineEdit,
    PrimaryPushButton,
    Slider,
    SpinBox,
    SwitchButton,
)

from ui.components.base_widget import BScrollArea


class ConfigWidget(QWidget):
    config_changed = Signal(dict)
    shortcut_changed = Signal(str, str)  # action_id, new_hotkey
    keyword_search = Signal(str)  # keyword

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = BScrollArea(self)
        self.scroll_area.setWidgetResizable(True)

        self.scroll_content = QWidget()
        self.scroll_area.setWidget(self.scroll_content)

        layout = QVBoxLayout(self.scroll_content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        main_layout.addWidget(self.scroll_area)

        # ── TXT Path ──
        self.path_card = CardWidget(self)
        path_layout = QHBoxLayout(self.path_card)
        path_layout.addWidget(BodyLabel("歌词绝对路径", self.path_card))
        path_layout.addStretch(1)
        self.path_input = LineEdit(self.path_card)
        self.path_input.setPlaceholderText("C:/Users/Administrator/Desktop/name.txt")
        self.path_input.setMinimumWidth(300)
        self.path_input.textChanged.connect(self._on_changed)
        path_layout.addWidget(self.path_input)
        layout.addWidget(self.path_card)

        # ── Current Page ──
        self.page_card = CardWidget(self)
        page_layout = QHBoxLayout(self.page_card)
        page_layout.addWidget(BodyLabel("当前", self.page_card))
        page_layout.addStretch(1)
        self.page_input = SpinBox(self.page_card)
        self.page_input.setRange(1, 999999)
        self.page_input.valueChanged.connect(self._on_changed)
        page_layout.addWidget(self.page_input)
        layout.addWidget(self.page_card)

        # ── Search Keyword ──
        self.search_card = CardWidget(self)
        search_layout = QHBoxLayout(self.search_card)
        search_layout.addWidget(BodyLabel("搜索关键字", self.search_card))
        search_layout.addStretch(1)
        self.search_input = LineEdit(self.search_card)
        self.search_input.setPlaceholderText("输入关键字...")
        self.search_input.setMinimumWidth(150)
        self.search_btn = PrimaryPushButton("下一个", self.search_card)
        
        self.search_btn.clicked.connect(lambda: self.keyword_search.emit(self.search_input.text()))
        self.search_input.returnPressed.connect(lambda: self.keyword_search.emit(self.search_input.text()))
        
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_btn)
        layout.addWidget(self.search_card)

        # ── Page Length ──
        self.length_card = CardWidget(self)
        length_layout = QHBoxLayout(self.length_card)
        length_layout.addWidget(BodyLabel("每行长度", self.length_card))
        length_layout.addStretch(1)
        self.length_input = SpinBox(self.length_card)
        self.length_input.setRange(10, 500)
        self.length_input.valueChanged.connect(self._on_changed)
        length_layout.addWidget(self.length_input)
        layout.addWidget(self.length_card)

        # ── Is English ──
        self.english_card = CardWidget(self)
        english_layout = QHBoxLayout(self.english_card)
        english_layout.addWidget(BodyLabel("是否为英文", self.english_card))
        english_layout.addStretch(1)
        self.english_switch = SwitchButton(self.english_card)
        self.english_switch.checkedChanged.connect(self._on_changed)
        english_layout.addWidget(self.english_switch)
        layout.addWidget(self.english_card)

        # ── Line Break ──
        self.break_card = CardWidget(self)
        break_layout = QHBoxLayout(self.break_card)
        break_layout.addWidget(BodyLabel("换行分隔符号", self.break_card))
        break_layout.addStretch(1)
        self.break_input = LineEdit(self.break_card)
        self.break_input.setPlaceholderText(" ")
        self.break_input.textChanged.connect(self._on_changed)
        break_layout.addWidget(self.break_input)
        layout.addWidget(self.break_card)

        # ── Font Size ──
        self.font_size_card = CardWidget(self)
        font_size_layout = QHBoxLayout(self.font_size_card)
        font_size_layout.addWidget(BodyLabel("字体大小", self.font_size_card))
        font_size_layout.addStretch(1)
        self.font_size_input = SpinBox(self.font_size_card)
        self.font_size_input.setRange(8, 72)
        self.font_size_input.valueChanged.connect(self._on_changed)
        font_size_layout.addWidget(self.font_size_input)
        layout.addWidget(self.font_size_card)

        # ── Font Color ──
        self.font_color_card = CardWidget(self)
        font_color_layout = QHBoxLayout(self.font_color_card)
        font_color_layout.addWidget(BodyLabel("字体颜色", self.font_color_card))
        font_color_layout.addStretch(1)
        self.font_color_picker = ColorPickerButton(
            QColor("white"), "Select Color", self.font_color_card
        )
        self.font_color_picker.colorChanged.connect(self._on_changed)
        font_color_layout.addWidget(self.font_color_picker)
        layout.addWidget(self.font_color_card)

        # ── Background Opacity ──
        self.bg_opacity_card = CardWidget(self)
        bg_opacity_layout = QHBoxLayout(self.bg_opacity_card)
        bg_opacity_layout.addWidget(BodyLabel("背景透明度", self.bg_opacity_card))
        bg_opacity_layout.addStretch(1)
        self.bg_opacity_slider = Slider(Qt.Orientation.Horizontal, self.bg_opacity_card)
        self.bg_opacity_slider.setRange(0, 255)
        self.bg_opacity_slider.setMinimumWidth(200)
        self.bg_opacity_slider.valueChanged.connect(self._on_changed)
        bg_opacity_layout.addWidget(self.bg_opacity_slider)
        layout.addWidget(self.bg_opacity_card)

        # ── Lock Lyrics ──
        self.lock_card = CardWidget(self)
        lock_layout = QHBoxLayout(self.lock_card)
        lock_layout.addWidget(BodyLabel("锁定歌词窗口", self.lock_card))
        lock_layout.addStretch(1)
        self.lock_switch = SwitchButton(self.lock_card)
        self.lock_switch.checkedChanged.connect(self._on_changed)
        lock_layout.addWidget(self.lock_switch)
        layout.addWidget(self.lock_card)

        # ── Shortcuts ──
        self._add_shortcut_card(
            layout, "快捷键: 隐藏/显示歌词", "toggle_lyrics", "ctrl+alt+h"
        )
        self._add_shortcut_card(layout, "快捷键: 老板键", "boss_key", "ctrl+m")
        self._add_shortcut_card(layout, "快捷键: 上翻", "prev_page", "ctrl+,")
        self._add_shortcut_card(layout, "快捷键: 下翻", "next_page", "ctrl+.")

        # ── Jump Shortcut is handled by directly editing "当前页数" above, or we can add a jump button here.
        # But user mentioned `Ctrl+;` "需要设置跳转页面，才可以使用". We can just map it to focus the "Current Page" box.
        self._add_shortcut_card(layout, "快捷键: 跳转", "jump_page", "ctrl+;")

        layout.addStretch(1)

        self._shortcut_inputs = {}  # We will store them in _add_shortcut_card

    def _add_shortcut_card(self, parent_layout, label_text, action_id, default_val):
        card = CardWidget(self)
        layout = QHBoxLayout(card)
        layout.addWidget(BodyLabel(label_text, card))
        layout.addStretch(1)

        input_box = LineEdit(card)
        input_box.setPlaceholderText(default_val)

        btn = PrimaryPushButton("应用", card)
        btn.clicked.connect(
            lambda: self.shortcut_changed.emit(action_id, input_box.text())
        )

        layout.addWidget(input_box)
        layout.addWidget(btn)
        parent_layout.addWidget(card)

        if not hasattr(self, "_shortcut_inputs"):
            self._shortcut_inputs = {}
        self._shortcut_inputs[action_id] = input_box

    def set_config(self, config: dict):
        self.blockSignals(True)
        self.path_input.setText(config.get("txt_path", ""))
        self.page_input.setValue(config.get("current_page", 1))
        self.length_input.setValue(config.get("page_length", 50))
        self.english_switch.setChecked(config.get("is_english", False))
        self.break_input.setText(config.get("line_break", " "))

        self.font_size_input.setValue(config.get("font_size", 16))
        self.font_color_picker.setColor(QColor(config.get("font_color", "#FFFFFF")))
        self.bg_opacity_slider.setValue(config.get("bg_opacity", 100))
        self.lock_switch.setChecked(config.get("is_locked", False))

        self.blockSignals(False)

    def set_shortcuts(self, shortcuts: dict):
        self.blockSignals(True)
        for action_id, hotkey in shortcuts.items():
            if action_id in self._shortcut_inputs:
                self._shortcut_inputs[action_id].setText(hotkey)
        self.blockSignals(False)

    def _on_changed(self):
        config = {
            "txt_path": self.path_input.text(),
            "current_page": self.page_input.value(),
            "page_length": self.length_input.value(),
            "is_english": self.english_switch.isChecked(),
            "line_break": self.break_input.text() or " ",
            "font_size": self.font_size_input.value(),
            "font_color": self.font_color_picker.color.name(),
            "bg_opacity": self.bg_opacity_slider.value(),
            "is_locked": self.lock_switch.isChecked(),
        }
        self.config_changed.emit(config)

    def update_page_display(self, page_num: int):
        self.page_input.blockSignals(True)
        self.page_input.setValue(page_num)
        self.page_input.blockSignals(False)

    def focus_jump(self):
        self.page_input.setFocus()
        self.page_input.selectAll()
