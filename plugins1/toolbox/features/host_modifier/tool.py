from qfluentwidgets import FluentIcon

from ..base import ToolboxFeature
from .view import HostModifierWidget


class HostModifierTool(ToolboxFeature):
    @property
    def name(self) -> str:
        return "Host 文件修改器"

    @property
    def description(self) -> str:
        return "本地Host文件修改."

    @property
    def icon(self):
        return FluentIcon.EDIT

    def create_widget(self):
        return HostModifierWidget()
