import random

from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
)

from core.plugin_system.plugin_base import PluginBase


class HelloPlugin(PluginBase):
    """
    一个简单的示例插件，展示如何与系统交互。
    """

    def __init__(self, context):
        super().__init__(context)
        self.name = "Hello Plugin"
        self.description = (
            "这是一个测试插件，用于演示如何通过 .atplugin 添加插件。"
        )
        self.ui_widget = None

    def on_load(self):
        print(f"[{self.name}] 插件已成功加载！")

    def on_unload(self):
        print(f"[{self.name}] 插件正在卸载...")

    def get_icon(self):
        """返回侧边栏图标"""
        return FluentIcon.MESSAGE

    def get_thumbnail_widget(self):
        """侧边栏小图标背景"""
        btn = QPushButton("👋")
        btn.setFixedSize(40, 40)
        btn.setFlat(True)
        btn.setStyleSheet("background: transparent; font-size: 20px;")
        return btn

    def get_card_widget(self) -> QWidget:
        """主界面组件"""
        if self.ui_widget is None:
            self.ui_widget = QWidget()
            layout = QVBoxLayout(self.ui_widget)

            title = BodyLabel("欢迎使用 Hello Plugin!")
            title.setStyleSheet(
                "font-size: 24px; font-weight: bold; margin-bottom: 10px;"
            )
            layout.addWidget(title)

            desc = BodyLabel(self.description)
            desc.setWordWrap(True)
            layout.addWidget(desc)

            # 交互示例
            btn = PrimaryPushButton("点击我！", self.ui_widget)
            btn.clicked.connect(self._on_btn_clicked)
            layout.addWidget(btn)

            layout.addStretch(1)

        return self.ui_widget

    def _on_btn_clicked(self):
        quotes = [
            "你好，世界！",
            "侧边栏工作得很好！",
            "插件化架构让一切变得简单。",
            "这是一个来自 .atplugin 的消息。",
            "保持专注，保持高效。",
        ]
        quote = random.choice(quotes)

        # 使用 InfoBar 显示消息
        from PySide6.QtCore import Qt

        InfoBar.success(
            title="Hello Plugin",
            content=quote,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self.ui_widget,
        )
