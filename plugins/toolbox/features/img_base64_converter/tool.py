from qfluentwidgets import FluentIcon

from ..base import ToolboxFeature
from .view import ImageBase64ConverterWidget


class ImageBase64ConverterTool(ToolboxFeature):
    @property
    def name(self) -> str:
        return "Base64/图片 互转"

    @property
    def description(self) -> str:
        return "在图片文件与 Base64 编码序列之间快速转换"

    @property
    def icon(self):
        # Using PHOTO or IMAGE icon
        return FluentIcon.PHOTO

    def create_widget(self):
        return ImageBase64ConverterWidget()
