from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    FluentIcon,
    ImageLabel,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    SegmentedWidget,
    StrongBodyLabel,
    TextEdit,
)

from .logic import ImageBase64Converter


class ImageBase64ConverterWidget(QWidget):
    """
    Widget for converting between Image and Base64.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.converter = ImageBase64Converter()

        self.vLayout = QVBoxLayout(self)
        self.vLayout.setContentsMargins(30, 30, 30, 30)
        self.vLayout.setSpacing(20)

        # Tab Selector
        self.pivot = SegmentedWidget(self)
        self.pivot.addItem("img2base64", "图片转Base64")
        self.pivot.addItem("base642img", "Base64转图片")
        self.pivot.currentItemChanged.connect(self._on_pivot_changed)
        self.vLayout.addWidget(self.pivot)

        # Main Content Area
        self.stackedWidget = QWidget(self)
        self.stackedLayout = QVBoxLayout(self.stackedWidget)
        self.stackedLayout.setContentsMargins(0, 0, 0, 0)
        self.vLayout.addWidget(self.stackedWidget)

        # Image to Base64 View
        self.img2base64_widget = QWidget()
        self._setup_img2base64_ui()
        self.stackedLayout.addWidget(self.img2base64_widget)

        # Base64 to Image View
        self.base642img_widget = QWidget()
        self._setup_base642img_ui()
        self.stackedLayout.addWidget(self.base642img_widget)
        self.base642img_widget.hide()

        self.pivot.setCurrentItem("img2base64")

    def _setup_img2base64_ui(self):
        layout = QVBoxLayout(self.img2base64_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # Image Selection
        self.img_card = CardWidget(self)
        img_layout = QVBoxLayout(self.img_card)

        self.preview_label = ImageLabel(self)
        self.preview_label.setFixedSize(200, 200)
        self.preview_label.setBorderRadius(8, 8, 8, 8)
        self.preview_label.setAlignment(Qt.AlignCenter)
        img_layout.addWidget(self.preview_label, 0, Qt.AlignCenter)

        self.select_btn = PushButton(FluentIcon.PHOTO, "选择图片", self)
        self.select_btn.clicked.connect(self._select_image)
        img_layout.addWidget(self.select_btn, 0, Qt.AlignCenter)

        layout.addWidget(self.img_card)

        # Base64 Output
        layout.addWidget(StrongBodyLabel("Base64 结果", self))
        self.base64_output = TextEdit(self)
        self.base64_output.setReadOnly(True)
        self.base64_output.setPlaceholderText("选择图片后将自动生成 Base64 编码")
        layout.addWidget(self.base64_output)

        # Actions
        self.img_action_layout = QHBoxLayout()
        self.copy_btn = PrimaryPushButton(FluentIcon.COPY, "复制 Base64", self)
        self.copy_btn.clicked.connect(self._copy_base64)
        self.img_action_layout.addStretch(1)
        self.img_action_layout.addWidget(self.copy_btn)
        layout.addLayout(self.img_action_layout)

    def _setup_base642img_ui(self):
        layout = QVBoxLayout(self.base642img_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        # Base64 Input
        layout.addWidget(StrongBodyLabel("Base64 输入", self))
        self.base64_input = TextEdit(self)
        self.base64_input.setPlaceholderText(
            "在这里粘贴 Base64 编码 (支持 `data:image/...;base64,` 前缀)"
        )
        layout.addWidget(self.base64_input)

        # Actions
        self.b64_action_layout = QHBoxLayout()
        self.convert_btn = PrimaryPushButton(FluentIcon.PLAY, "转换为图片", self)
        self.convert_btn.clicked.connect(self._convert_to_image)
        self.b64_action_layout.addStretch(1)
        self.b64_action_layout.addWidget(self.convert_btn)
        layout.addLayout(self.b64_action_layout)

        # Preview & Save
        self.res_card = CardWidget(self)
        res_layout = QVBoxLayout(self.res_card)
        self.res_preview = ImageLabel(self)
        self.res_preview.setFixedSize(200, 200)
        self.res_preview.setBorderRadius(8, 8, 8, 8)
        self.res_preview.setAlignment(Qt.AlignCenter)
        res_layout.addWidget(self.res_preview, 0, Qt.AlignCenter)

        self.save_btn = PushButton(FluentIcon.SAVE, "保存图片", self)
        self.save_btn.clicked.connect(self._save_image)
        self.save_btn.setEnabled(False)
        res_layout.addWidget(self.save_btn, 0, Qt.AlignCenter)

        layout.addWidget(self.res_card)

    def _on_pivot_changed(self, route_key):
        if route_key == "img2base64":
            self.img2base64_widget.show()
            self.base642img_widget.hide()
        else:
            self.img2base64_widget.hide()
            self.base642img_widget.show()

    def _select_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"
        )
        if path:
            try:
                b64 = self.converter.image_to_base64(path)
                self.base64_output.setText(b64)
                self.preview_label.setImage(path)
                InfoBar.success("成功", "图片已转换为 Base64", parent=self)
            except Exception as e:
                InfoBar.error("错误", str(e), parent=self)

    def _copy_base64(self):
        text = self.base64_output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            InfoBar.success(
                "已复制", "Base64 编码已复制到剪贴板", duration=2000, parent=self
            )

    def _convert_to_image(self):
        b64_text = self.base64_input.toPlainText().strip()
        if not b64_text:
            return

        # Simple validation & preview
        try:
            # We'll save it to a temp file for preview if it's too complex to handle QPixmap from b64 directly easily
            # But let's try direct QPixmap first
            clean_b64 = b64_text
            if "," in b64_text:
                clean_b64 = b64_text.split(",", 1)[1]

            import base64

            img_data = base64.b64decode(clean_b64)
            pixmap = QPixmap()
            pixmap.loadFromData(img_data)

            if pixmap.isNull():
                raise ValueError("无效的图片数据")

            self.res_preview.setPixmap(
                pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.save_btn.setEnabled(True)
            self._temp_img_data = img_data
            InfoBar.success("成功", "Base64 已解析，请保存图片", parent=self)
        except Exception as e:
            InfoBar.error("错误", f"解析失败: {e}", parent=self)

    def _save_image(self):
        if not hasattr(self, "_temp_img_data"):
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存图片",
            "converted_image.png",
            "PNG (*.png);;JPEG (*.jpg);;All Files (*)",
        )
        if path:
            try:
                with open(path, "wb") as f:
                    f.write(self._temp_img_data)
                InfoBar.success("成功", f"图片已保存至: {path}", parent=self)
            except Exception as e:
                InfoBar.error("错误", str(e), parent=self)
