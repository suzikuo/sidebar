from qfluentwidgets import FluentIcon

from ..base import ToolboxFeature
from .view import PasswordGeneratorWidget


class PasswordGeneratorTool(ToolboxFeature):
    @property
    def name(self) -> str:
        return "密码生成器"

    @property
    def description(self) -> str:
        return "快速生成随机密码"

    @property
    def icon(self):
        return FluentIcon.POWER_BUTTON

    def create_widget(self):
        return PasswordGeneratorWidget()
