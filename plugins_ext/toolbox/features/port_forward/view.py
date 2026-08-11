from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QHeaderView, QTableWidgetItem
from qfluentwidgets import (TableWidget, PrimaryPushButton, ToolButton, FluentIcon, 
                            MessageBoxBase, SubtitleLabel, LineEdit, BodyLabel, InfoBar, InfoBarPosition)

from .backend import add_proxy, delete_proxy, get_proxies, validate_proxy_rule

class ProxyTaskThread(QThread):
    finished_signal = Signal(bool)
    
    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        
    def run(self):
        try:
            res = self.func(*self.args, **self.kwargs)
            self.finished_signal.emit(bool(res))
        except Exception:
            self.finished_signal.emit(False)

class PortProxyDialog(MessageBoxBase):
    """ Dialog for adding/editing port proxy """
    def __init__(self, parent=None, proxy_data=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("配置端口转发", self)
        
        self.listenAddrEdit = LineEdit(self)
        self.listenAddrEdit.setPlaceholderText("例如: 0.0.0.0")
        
        self.listenPortEdit = LineEdit(self)
        self.listenPortEdit.setValidator(QIntValidator(1, 65535, self))
        self.listenPortEdit.setPlaceholderText("例如: 8080")
        
        self.connectAddrEdit = LineEdit(self)
        self.connectAddrEdit.setPlaceholderText("例如: 127.0.0.1")
        
        self.connectPortEdit = LineEdit(self)
        self.connectPortEdit.setValidator(QIntValidator(1, 65535, self))
        self.connectPortEdit.setPlaceholderText("例如: 80")
        
        # Add widgets to the view layout
        self.viewLayout.addWidget(self.titleLabel)
        
        self.viewLayout.addWidget(BodyLabel("侦听地址 (Listen Address):"))
        self.viewLayout.addWidget(self.listenAddrEdit)
        
        self.viewLayout.addWidget(BodyLabel("侦听端口 (Listen Port):"))
        self.viewLayout.addWidget(self.listenPortEdit)
        
        self.viewLayout.addWidget(BodyLabel("连接到地址 (Connect Address):"))
        self.viewLayout.addWidget(self.connectAddrEdit)
        
        self.viewLayout.addWidget(BodyLabel("连接到端口 (Connect Port):"))
        self.viewLayout.addWidget(self.connectPortEdit)
        
        self.widget.setMinimumWidth(350)
        
        self.listenAddrEdit.setText("0.0.0.0")
        self.connectAddrEdit.setText("172.19.108.136")
        
        if proxy_data:
            self.listenAddrEdit.setText(proxy_data['listen_address'])
            self.listenPortEdit.setText(proxy_data['listen_port'])
            self.connectAddrEdit.setText(proxy_data['connect_address'])
            self.connectPortEdit.setText(proxy_data['connect_port'])
            self.listenAddrEdit.setEnabled(False)
            self.listenPortEdit.setEnabled(False)
            
    def get_data(self):
        return {
            'listen_address': self.listenAddrEdit.text().strip(),
            'listen_port': self.listenPortEdit.text().strip(),
            'connect_address': self.connectAddrEdit.text().strip(),
            'connect_port': self.connectPortEdit.text().strip()
        }

class PortForwardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(20, 20, 20, 20)
        self.vBoxLayout.setSpacing(10)
        
        # Toolbar
        self.toolbar_layout = QHBoxLayout()
        self.add_btn = PrimaryPushButton(FluentIcon.ADD, "添加规则", self)
        self.refresh_btn = ToolButton(FluentIcon.SYNC, self)
        
        self.toolbar_layout.addWidget(self.add_btn)
        self.toolbar_layout.addWidget(self.refresh_btn)
        self.toolbar_layout.addStretch(1)
        
        # Table
        self.table = TableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "侦听地址 (Listen)", "侦听端口", 
            "连接到地址 (Connect)", "连接到端口", "操作"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        
        self.vBoxLayout.addLayout(self.toolbar_layout)
        self.vBoxLayout.addWidget(self.table)
        
        # Connections
        self.add_btn.clicked.connect(self.on_add_clicked)
        self.refresh_btn.clicked.connect(self.load_data)
        
        # Initial load
        self.load_data()
        
    def load_data(self):
        self.table.setRowCount(0)
        proxies = get_proxies()
        for idx, proxy in enumerate(proxies):
            self.table.insertRow(idx)
            self.table.setItem(idx, 0, QTableWidgetItem(proxy['listen_address']))
            self.table.setItem(idx, 1, QTableWidgetItem(proxy['listen_port']))
            self.table.setItem(idx, 2, QTableWidgetItem(proxy['connect_address']))
            self.table.setItem(idx, 3, QTableWidgetItem(proxy['connect_port']))
            
            # Actions layuot
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(0, 0, 0, 0)
            
            edit_btn = ToolButton(FluentIcon.EDIT)
            delete_btn = ToolButton(FluentIcon.DELETE)
            
            edit_btn.clicked.connect(lambda checked=False, p=proxy: self.on_edit_clicked(p))
            delete_btn.clicked.connect(lambda checked=False, p=proxy: self.on_delete_clicked(p))
            
            action_layout.addWidget(edit_btn)
            action_layout.addWidget(delete_btn)
            action_layout.addStretch(1)
            
            self.table.setCellWidget(idx, 4, action_widget)
            
    def _run_proxy_task(self, func, *args):
        self.setEnabled(False)
        self.thread = ProxyTaskThread(func, *args)
        self.thread.finished_signal.connect(self._on_task_finished)
        self.thread.start()

    def _on_task_finished(self, success):
        self.setEnabled(True)
        self.load_data()

        if not success:
            InfoBar.error(
                title="Operation failed",
                content="The port forwarding command was cancelled or failed.",
                parent=self,
                position=InfoBarPosition.TOP,
            )

    def _validate_rule_data(self, data):
        try:
            return validate_proxy_rule(
                data["listen_address"] or "0.0.0.0",
                data["listen_port"],
                data["connect_address"] or "127.0.0.1",
                data["connect_port"],
            )
        except ValueError as exc:
            InfoBar.error(
                title="Invalid rule",
                content=str(exc),
                parent=self,
                position=InfoBarPosition.TOP,
            )
            return None

    def on_add_clicked(self):
        dialog = PortProxyDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if not data['listen_port'] or not data['connect_port']:
                InfoBar.error("错误", "端口不能为空", parent=self, position=InfoBarPosition.TOP)
                return
            
            rule = self._validate_rule_data(data)
            if rule is None:
                return

            self._run_proxy_task(
                add_proxy,
                rule['listen_address'],
                rule['listen_port'],
                rule['connect_address'],
                rule['connect_port'],
            )

    def on_edit_clicked(self, proxy):
        dialog = PortProxyDialog(self, proxy_data=proxy)
        if dialog.exec():
            data = dialog.get_data()
            if not data['connect_port']:
                InfoBar.error("错误", "端口不能为空", parent=self, position=InfoBarPosition.TOP)
                return
                
            rule = self._validate_rule_data(data)
            if rule is None:
                return

            self._run_proxy_task(
                add_proxy,
                rule['listen_address'],
                rule['listen_port'],
                rule['connect_address'],
                rule['connect_port'],
            )
            
    def on_delete_clicked(self, proxy):
        self._run_proxy_task(delete_proxy, proxy['listen_address'], proxy['listen_port'])
