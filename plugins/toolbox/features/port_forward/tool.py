from qfluentwidgets import FluentIcon

from ..base import ToolboxFeature
from .view import PortForwardWidget

class PortForwardTool(ToolboxFeature):
    @property
    def name(self) -> str:
        return "端口转发"

    @property
    def description(self) -> str:
        return "本地端口映射与转发配置\n(Netsh Portproxy)"

    @property
    def icon(self):
        return FluentIcon.LINK

    def create_widget(self):
        return PortForwardWidget()
