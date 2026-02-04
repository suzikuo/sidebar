import os
import sys

from PySide6.QtGui import QColor, QGuiApplication
from qfluentwidgets import (
    FluentIcon,
    Theme,
)

app = QGuiApplication(sys.argv)  # 必须先初始化 Qt GUI 环境
icon = FluentIcon.APPLICATION.icon(Theme.LIGHT, color=QColor(255, 255, 255, 0))
pixmap = icon.pixmap(256, 256)
print(pixmap.save("icon.png"))
app.quit()

from PIL import Image

# 打开 PNG
img = Image.open("icon.png")

# 保存为 ICO
img.save("icon.ico", format="ICO")

os.remove("icon.png")
