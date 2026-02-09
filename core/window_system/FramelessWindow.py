from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QPalette, Qt
from PySide6.QtWidgets import QWidget
from qframelesswindow import TitleBar
from qframelesswindow.linux import LinuxFramelessWindow, LinuxWindowEffect


class FramelessWindow(LinuxFramelessWindow, QWidget):
    def _initFrameless(self):
        self.windowEffect = LinuxWindowEffect(self)
        self.titleBar = TitleBar(self)
        self._isResizeEnabled = True

        # ⭐⭐⭐ 关键：启用真正的透明窗口 ⭐⭐⭐
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

        # 清空 palette，避免 WM / Qt 兜底填黑
        self.setPalette(QPalette())

        self.updateFrameless()
        QCoreApplication.instance().installEventFilter(self)

        self.titleBar.raise_()
        self.resize(500, 500)
