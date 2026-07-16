from urllib.parse import urlparse

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QTableWidgetItem,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    FlowLayout,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    ToolButton,
    TransparentToolButton,
)

from plugins.gateway_manager.models import normalize_path_prefix, validate_target_url


def _row_id(table, row):
    item = table.item(row, 0)
    if not item:
        return None
    return int(item.data(Qt.UserRole))


def _bool_text(value):
    return "是" if bool(value) else "否"


class ConfirmDialog(MessageBoxBase):
    def __init__(self, title, content, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(title, self)
        self.contentLabel = BodyLabel(content, self)
        self.contentLabel.setWordWrap(True)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.contentLabel)
        self.yesButton.setText("删除")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(420)


class ServiceDialog(MessageBoxBase):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("服务", self)
        self.nameInput = LineEdit(self)
        self.nameInput.setPlaceholderText("服务名称")
        self.targetInput = LineEdit(self)
        self.targetInput.setPlaceholderText("http://127.0.0.1:6694")
        self.enabledCheck = QCheckBox("启用", self)
        self.enabledCheck.setChecked(True)
        self.remarksInput = LineEdit(self)
        self.remarksInput.setPlaceholderText("备注")

        if data:
            self.nameInput.setText(data.get("name", ""))
            self.targetInput.setText(data.get("target_url", ""))
            self.enabledCheck.setChecked(bool(data.get("enabled", 1)))
            self.remarksInput.setText(data.get("remarks") or "")

        form = QFormLayout()
        form.addRow("名称：", self.nameInput)
        form.addRow("目标地址：", self.targetInput)
        form.addRow("", self.enabledCheck)
        form.addRow("备注：", self.remarksInput)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addLayout(form)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(480)

    def get_data(self):
        return {
            "name": self.nameInput.text().strip(),
            "target_url": self.targetInput.text().strip().rstrip("/"),
            "enabled": 1 if self.enabledCheck.isChecked() else 0,
            "remarks": self.remarksInput.text().strip(),
        }

    def validate(self):
        data = self.get_data()
        return bool(data["name"] and validate_target_url(data["target_url"]))


class GatewayDialog(MessageBoxBase):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("本地网关", self)
        self.nameInput = LineEdit(self)
        self.nameInput.setPlaceholderText("网关名称")
        self.hostInput = LineEdit(self)
        self.hostInput.setText("127.0.0.1")
        self.portInput = LineEdit(self)
        self.portInput.setPlaceholderText("8080")
        self.enabledCheck = QCheckBox("启用", self)
        self.enabledCheck.setChecked(True)
        self.autoStartCheck = QCheckBox("自动启动", self)
        self.remarksInput = LineEdit(self)
        self.remarksInput.setPlaceholderText("备注")

        if data:
            self.nameInput.setText(data.get("name", ""))
            self.hostInput.setText(data.get("listen_host", "127.0.0.1"))
            self.portInput.setText(str(data.get("listen_port", "")))
            self.enabledCheck.setChecked(bool(data.get("enabled", 1)))
            self.autoStartCheck.setChecked(bool(data.get("auto_start", 0)))
            self.remarksInput.setText(data.get("remarks") or "")

        form = QFormLayout()
        form.addRow("名称：", self.nameInput)
        form.addRow("监听地址：", self.hostInput)
        form.addRow("监听端口：", self.portInput)
        form.addRow("", self.enabledCheck)
        form.addRow("", self.autoStartCheck)
        form.addRow("备注：", self.remarksInput)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addLayout(form)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(420)

    def get_data(self):
        return {
            "name": self.nameInput.text().strip(),
            "listen_host": self.hostInput.text().strip() or "127.0.0.1",
            "listen_port": self.portInput.text().strip(),
            "enabled": 1 if self.enabledCheck.isChecked() else 0,
            "auto_start": 1 if self.autoStartCheck.isChecked() else 0,
            "remarks": self.remarksInput.text().strip(),
        }

    def validate(self):
        data = self.get_data()
        if not data["name"]:
            return False
        try:
            port = int(data["listen_port"])
        except ValueError:
            return False
        return 1 <= port <= 65535


class RouteDialog(MessageBoxBase):
    def __init__(self, db, parent=None, data=None):
        super().__init__(parent)
        self.db = db
        self.titleLabel = SubtitleLabel("分发规则", self)
        self.gatewayCombo = QComboBox(self)
        self.serviceCombo = QComboBox(self)
        self.prefixInput = LineEdit(self)
        self.prefixInput.setPlaceholderText("/6694")
        self.preserveHostCheck = QCheckBox("保留客户端 Host 头", self)
        self.enabledCheck = QCheckBox("启用", self)
        self.enabledCheck.setChecked(True)

        self._load_gateways()
        self._load_services()

        if data:
            self._set_combo_value(self.gatewayCombo, data.get("gateway_id"))
            self._set_combo_value(self.serviceCombo, data.get("service_id"))
            self.prefixInput.setText(data.get("path_prefix", ""))
            self.preserveHostCheck.setChecked(bool(data.get("preserve_host", 0)))
            self.enabledCheck.setChecked(bool(data.get("enabled", 1)))

        form = QFormLayout()
        form.addRow("网关：", self.gatewayCombo)
        form.addRow("服务：", self.serviceCombo)
        form.addRow("路径前缀：", self.prefixInput)
        form.addRow("", self.preserveHostCheck)
        form.addRow("", self.enabledCheck)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addLayout(form)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(500)

    def _load_gateways(self):
        for gateway in self.db.list_gateways():
            label = f"{gateway['name']} ({gateway['listen_host']}:{gateway['listen_port']})"
            self.gatewayCombo.addItem(label, gateway["id"])

    def _load_services(self):
        for service in self.db.list_services():
            label = f"{service['name']} -> {service['target_url']}"
            self.serviceCombo.addItem(label, service["id"])

    def _set_combo_value(self, combo, value):
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    def get_data(self):
        return {
            "gateway_id": self.gatewayCombo.currentData(),
            "service_id": self.serviceCombo.currentData(),
            "path_prefix": normalize_path_prefix(self.prefixInput.text()),
            "preserve_host": 1 if self.preserveHostCheck.isChecked() else 0,
            "enabled": 1 if self.enabledCheck.isChecked() else 0,
        }

    def validate(self):
        data = self.get_data()
        return bool(data["gateway_id"] and data["service_id"] and data["path_prefix"].startswith("/"))


class TunnelDialog(MessageBoxBase):
    def __init__(self, db, parent=None, data=None):
        super().__init__(parent)
        self.db = db
        self.titleLabel = SubtitleLabel("Cloudflare Tunnel", self)
        self.nameInput = LineEdit(self)
        self.nameInput.setPlaceholderText("隧道名称 / 人员")
        self.pathInput = LineEdit(self)
        self.pathInput.setPlaceholderText("cloudflared 或 cloudflared.exe 完整路径")
        self.tokenInput = LineEdit(self)
        self.tokenInput.setEchoMode(QLineEdit.Password)
        self.tokenInput.setPlaceholderText("Cloudflare 隧道 Token")
        self.gatewayCombo = QComboBox(self)
        self.enabledCheck = QCheckBox("启用", self)
        self.enabledCheck.setChecked(True)
        self.autoStartCheck = QCheckBox("自动启动", self)
        self.remarksInput = LineEdit(self)
        self.remarksInput.setPlaceholderText("备注")

        self._load_gateways()

        if data:
            self.nameInput.setText(data.get("name", ""))
            self.pathInput.setText(data.get("cloudflared_path", "cloudflared"))
            self.tokenInput.setText(data.get("token", ""))
            self._set_combo_value(self.gatewayCombo, data.get("gateway_id"))
            self.enabledCheck.setChecked(bool(data.get("enabled", 1)))
            self.autoStartCheck.setChecked(bool(data.get("auto_start", 0)))
            self.remarksInput.setText(data.get("remarks") or "")
        else:
            self.pathInput.setText("cloudflared")

        form = QFormLayout()
        form.addRow("名称：", self.nameInput)
        form.addRow("cloudflared:", self.pathInput)
        form.addRow("Token：", self.tokenInput)
        form.addRow("网关：", self.gatewayCombo)
        form.addRow("", self.enabledCheck)
        form.addRow("", self.autoStartCheck)
        form.addRow("备注：", self.remarksInput)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addLayout(form)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(560)

    def _load_gateways(self):
        self.gatewayCombo.addItem("未映射网关", None)
        for gateway in self.db.list_gateways():
            label = f"{gateway['name']} ({gateway['listen_host']}:{gateway['listen_port']})"
            self.gatewayCombo.addItem(label, gateway["id"])

    def _set_combo_value(self, combo, value):
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    def get_data(self):
        return {
            "name": self.nameInput.text().strip(),
            "cloudflared_path": self.pathInput.text().strip() or "cloudflared",
            "token": self.tokenInput.text().strip(),
            "gateway_id": self.gatewayCombo.currentData(),
            "enabled": self.enabledCheck.isChecked(),
            "auto_start": self.autoStartCheck.isChecked(),
            "remarks": self.remarksInput.text().strip(),
        }

    def validate(self):
        data = self.get_data()
        return bool(data["name"] and data["token"])


class TunnelCard(CardWidget):
    start_requested = Signal(int)
    stop_requested = Signal(int)
    edit_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, tunnel, status, gateway_running=False, parent=None):
        super().__init__(parent)
        self.tunnel_id = tunnel["id"]
        self.setFixedSize(252, 146)

        running = bool(status.get("running"))
        enabled = bool(tunnel["enabled"])
        error = status.get("last_error") or ""
        router = "未映射网关"
        if tunnel["gateway_name"]:
            router = f"{tunnel['gateway_name']} ({tunnel['listen_port']})"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        header = QHBoxLayout()
        icon = IconWidget(FluentIcon.IOT, self)
        icon.setFixedSize(20, 20)
        name_label = StrongBodyLabel(tunnel["name"], self)
        name_label.setStyleSheet("font-size: 12px; font-weight: 600;")
        status_dot = QWidget(self)
        status_dot.setFixedSize(10, 10)
        status_dot.setStyleSheet(f"background-color: {self._status_color(running, enabled, error)}; border-radius: 5px;")

        header.addWidget(icon)
        header.addWidget(name_label)
        header.addStretch(1)
        header.addWidget(status_dot)
        layout.addLayout(header)

        state = "运行中" if running else "已停止"
        if not enabled:
            state = "已禁用"
        if error:
            state = "异常"
        router_state = "网关运行中" if gateway_running else "网关已停止"
        if not tunnel["gateway_name"]:
            router_state = "未映射"

        layout.addWidget(CaptionLabel(f"隧道：{state}", self))
        layout.addWidget(CaptionLabel(f"网关：{router} / {router_state}", self))

        detail = error or tunnel["remarks"] or ""
        if detail:
            detail_label = CaptionLabel(detail, self)
            detail_label.setWordWrap(True)
            detail_label.setToolTip(detail)
            layout.addWidget(detail_label)

        layout.addStretch(1)
        actions = QHBoxLayout()
        actions.addStretch(1)
        if running:
            toggle_btn = TransparentToolButton(FluentIcon.PAUSE, self)
            toggle_btn.setToolTip("停止隧道")
            toggle_btn.clicked.connect(lambda: self.stop_requested.emit(self.tunnel_id))
        else:
            toggle_btn = TransparentToolButton(FluentIcon.PLAY, self)
            toggle_btn.setToolTip("启动隧道")
            toggle_btn.setEnabled(enabled)
            toggle_btn.clicked.connect(lambda: self.start_requested.emit(self.tunnel_id))

        edit_btn = TransparentToolButton(FluentIcon.EDIT, self)
        edit_btn.setToolTip("编辑隧道")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.tunnel_id))
        delete_btn = TransparentToolButton(FluentIcon.DELETE, self)
        delete_btn.setToolTip("删除隧道")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.tunnel_id))
        actions.addWidget(toggle_btn)
        actions.addWidget(edit_btn)
        actions.addWidget(delete_btn)
        layout.addLayout(actions)

    def _status_color(self, running, enabled, error):
        if error:
            return "#d13438"
        if running:
            return "#107c10"
        if enabled:
            return "#8a8a8a"
        return "#605e5c"


class GatewayCard(CardWidget):
    start_requested = Signal(int)
    stop_requested = Signal(int)
    edit_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, gateway, route_count, status, parent=None):
        super().__init__(parent)
        self.gateway_id = gateway["id"]
        self.setFixedSize(244, 140)

        running = bool(status.get("running"))
        enabled = bool(gateway["enabled"])
        error = status.get("error") or ""
        listen = f"{gateway['listen_host']}:{gateway['listen_port']}"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        header = QHBoxLayout()
        icon = IconWidget(FluentIcon.IOT, self)
        icon.setFixedSize(20, 20)
        self.nameLabel = StrongBodyLabel(gateway["name"], self)
        self.nameLabel.setStyleSheet("font-size: 12px; font-weight: 600;")
        self.statusDot = QWidget(self)
        self.statusDot.setFixedSize(10, 10)
        self._set_status_style(running, enabled, error)

        header.addWidget(icon)
        header.addWidget(self.nameLabel)
        header.addStretch(1)
        header.addWidget(self.statusDot)
        layout.addLayout(header)

        status_text = "运行中" if running else "已停止"
        if not enabled:
            status_text = "已禁用"
        if error:
            status_text = "异常"

        layout.addWidget(CaptionLabel(f"监听：{listen}", self))
        layout.addWidget(CaptionLabel(f"规则：{route_count}  状态：{status_text}", self))
        if error:
            error_label = CaptionLabel(error, self)
            error_label.setWordWrap(True)
            error_label.setToolTip(error)
            layout.addWidget(error_label)
        else:
            remarks = gateway["remarks"] or ""
            if remarks:
                remark_label = CaptionLabel(remarks, self)
                remark_label.setWordWrap(True)
                layout.addWidget(remark_label)

        layout.addStretch(1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        if running:
            toggle_btn = TransparentToolButton(FluentIcon.PAUSE, self)
            toggle_btn.setToolTip("停止网关")
            toggle_btn.clicked.connect(lambda: self.stop_requested.emit(self.gateway_id))
        else:
            toggle_btn = TransparentToolButton(FluentIcon.PLAY, self)
            toggle_btn.setToolTip("启动网关")
            toggle_btn.setEnabled(enabled)
            toggle_btn.clicked.connect(lambda: self.start_requested.emit(self.gateway_id))

        edit_btn = TransparentToolButton(FluentIcon.EDIT, self)
        edit_btn.setToolTip("编辑网关")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.gateway_id))

        delete_btn = TransparentToolButton(FluentIcon.DELETE, self)
        delete_btn.setToolTip("删除网关")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.gateway_id))

        actions.addWidget(toggle_btn)
        actions.addWidget(edit_btn)
        actions.addWidget(delete_btn)
        layout.addLayout(actions)

    def _set_status_style(self, running, enabled, error):
        if error:
            color = "#d13438"
        elif running:
            color = "#107c10"
        elif enabled:
            color = "#8a8a8a"
        else:
            color = "#605e5c"
        self.statusDot.setStyleSheet(f"background-color: {color}; border-radius: 5px;")


class GatewayManagerWidget(QWidget):
    def __init__(self, db, plugin, parent=None):
        super().__init__(parent)
        self.db = db
        self.plugin = plugin
        self._gateway_cards_signature = None
        self._tunnel_cards_signature = None
        self._status_table_signature = None

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(14, 14, 14, 14)
        self.mainLayout.setSpacing(8)

        self._build_header()
        self.pageMenu = QMenu(self)
        self.pageStack = QStackedWidget(self)
        self.mainLayout.addWidget(self.pageStack)

        self._build_overview_tab()
        self._build_cloudflare_tab()
        self._build_services_tab()
        self._build_gateways_tab()
        self._build_routes_tab()
        self._build_status_tab()
        self.pageStack.setCurrentIndex(0)
        self.refresh_all()

    def _build_header(self):
        header = QHBoxLayout()
        self.titleLabel = BodyLabel("网关管理", self)
        self.titleLabel.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.statusLabel = BodyLabel("未启动", self)

        self.startBtn = PrimaryPushButton(FluentIcon.PLAY, "全部启动", self)
        self.stopBtn = PushButton(FluentIcon.PAUSE, "全部停止", self)
        self.refreshBtn = ToolButton(FluentIcon.SYNC, self)
        self.menuBtn = QToolButton(self)
        self.menuBtn.setText("☰")
        self.menuBtn.setToolTip("页面菜单")
        self.menuBtn.setPopupMode(QToolButton.InstantPopup)

        self.startBtn.clicked.connect(self._on_start_all)
        self.stopBtn.clicked.connect(self._on_stop_all)
        self.refreshBtn.clicked.connect(self.refresh_all)

        header.addWidget(self.titleLabel)
        header.addStretch(1)
        header.addWidget(self.statusLabel)
        header.addWidget(self.startBtn)
        header.addWidget(self.stopBtn)
        header.addWidget(self.refreshBtn)
        header.addWidget(self.menuBtn)
        self.mainLayout.addLayout(header)

    def _add_page(self, widget, title):
        index = self.pageStack.addWidget(widget)
        action = self.pageMenu.addAction(title)
        action.triggered.connect(lambda checked=False, page_index=index: self.pageStack.setCurrentIndex(page_index))
        self.menuBtn.setMenu(self.pageMenu)

    def _build_overview_tab(self):
        tab = QWidget(self)
        outer_layout = QVBoxLayout(tab)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(tab)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)

        tunnel_toolbar = QHBoxLayout()
        self.addTunnelOverviewBtn = PrimaryPushButton(FluentIcon.ADD, "添加隧道", tab)
        self.addTunnelOverviewBtn.clicked.connect(self._on_add_tunnel)
        tunnel_toolbar.addWidget(StrongBodyLabel("Cloudflare 隧道", tab))
        tunnel_toolbar.addStretch(1)
        tunnel_toolbar.addWidget(self.addTunnelOverviewBtn)

        self.tunnelOverviewContainer = QWidget(tab)
        self.tunnelOverviewContainer.setStyleSheet("background: transparent;")
        self.tunnelOverviewLayout = FlowLayout(self.tunnelOverviewContainer)
        self.tunnelOverviewLayout.setContentsMargins(0, 0, 0, 0)
        self.tunnelOverviewLayout.setSpacing(12)

        gateway_toolbar = QHBoxLayout()
        self.addGatewayOverviewBtn = PushButton(FluentIcon.ADD, "添加网关", tab)
        self.addGatewayOverviewBtn.clicked.connect(self._on_add_gateway)
        gateway_toolbar.addWidget(StrongBodyLabel("本地网关", tab))
        gateway_toolbar.addStretch(1)
        gateway_toolbar.addWidget(self.addGatewayOverviewBtn)

        self.overviewContainer = QWidget(tab)
        self.overviewContainer.setStyleSheet("background: transparent;")
        self.overviewLayout = FlowLayout(self.overviewContainer)
        self.overviewLayout.setContentsMargins(0, 0, 0, 0)
        self.overviewLayout.setSpacing(12)

        layout.addLayout(tunnel_toolbar)
        layout.addWidget(self.tunnelOverviewContainer)
        layout.addSpacing(10)
        layout.addLayout(gateway_toolbar)
        layout.addWidget(self.overviewContainer)
        layout.addStretch(1)
        scroll.setWidget(content)
        outer_layout.addWidget(scroll)
        self._add_page(tab, "总览")

    def _build_cloudflare_tab(self):
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        self.cloudflareStatusLabel = BodyLabel("Cloudflare 隧道：0/0 运行中", tab)
        self.addTunnelBtn = PrimaryPushButton(FluentIcon.ADD, "添加隧道", tab)
        self.startAllTunnelsBtn = PushButton(FluentIcon.PLAY, "全部启动", tab)
        self.stopAllTunnelsBtn = PushButton(FluentIcon.PAUSE, "全部停止", tab)
        self.addTunnelBtn.clicked.connect(self._on_add_tunnel)
        self.startAllTunnelsBtn.clicked.connect(self._on_start_all_tunnels)
        self.stopAllTunnelsBtn.clicked.connect(self._on_stop_all_tunnels)
        toolbar.addWidget(self.cloudflareStatusLabel)
        toolbar.addStretch(1)
        toolbar.addWidget(self.addTunnelBtn)
        toolbar.addWidget(self.startAllTunnelsBtn)
        toolbar.addWidget(self.stopAllTunnelsBtn)

        self.tunnelsTable = TableWidget(tab)
        self.tunnelsTable.setColumnCount(7)
        self.tunnelsTable.setHorizontalHeaderLabels(
            ["名称", "网关", "启用", "自动", "运行中", "错误", "操作"]
        )
        self.tunnelsTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tunnelsTable.verticalHeader().hide()

        layout.addLayout(toolbar)
        layout.addWidget(self.tunnelsTable)
        self._add_page(tab, "Cloudflare 隧道")

    def _build_services_tab(self):
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        toolbar = QHBoxLayout()
        self.addServiceBtn = PrimaryPushButton(FluentIcon.ADD, "添加服务", tab)
        self.addServiceBtn.clicked.connect(self._on_add_service)
        toolbar.addWidget(self.addServiceBtn)
        toolbar.addStretch(1)

        self.servicesTable = TableWidget(tab)
        self.servicesTable.setColumnCount(5)
        self.servicesTable.setHorizontalHeaderLabels(["名称", "目标地址", "启用", "备注", "操作"])
        self.servicesTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.servicesTable.verticalHeader().hide()

        layout.addLayout(toolbar)
        layout.addWidget(self.servicesTable)
        self._add_page(tab, "服务")

    def _build_gateways_tab(self):
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        toolbar = QHBoxLayout()
        self.addGatewayBtn = PrimaryPushButton(FluentIcon.ADD, "添加网关", tab)
        self.addGatewayBtn.clicked.connect(self._on_add_gateway)
        toolbar.addWidget(self.addGatewayBtn)
        toolbar.addStretch(1)

        self.gatewaysTable = TableWidget(tab)
        self.gatewaysTable.setColumnCount(6)
        self.gatewaysTable.setHorizontalHeaderLabels(
            ["名称", "监听", "启用", "自动启动", "备注", "操作"]
        )
        self.gatewaysTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.gatewaysTable.verticalHeader().hide()

        layout.addLayout(toolbar)
        layout.addWidget(self.gatewaysTable)
        self._add_page(tab, "网关")

    def _build_routes_tab(self):
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        toolbar = QHBoxLayout()
        self.addRouteBtn = PrimaryPushButton(FluentIcon.ADD, "添加规则", tab)
        self.addRouteBtn.clicked.connect(self._on_add_route)
        toolbar.addWidget(self.addRouteBtn)
        toolbar.addStretch(1)

        self.routesTable = TableWidget(tab)
        self.routesTable.setColumnCount(7)
        self.routesTable.setHorizontalHeaderLabels(
            ["网关", "前缀", "服务", "目标地址", "Host", "启用", "操作"]
        )
        self.routesTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.routesTable.verticalHeader().hide()

        layout.addLayout(toolbar)
        layout.addWidget(self.routesTable)
        self._add_page(tab, "分发规则")

    def _build_status_tab(self):
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        self.statusTable = TableWidget(tab)
        self.statusTable.setColumnCount(6)
        self.statusTable.setHorizontalHeaderLabels(["网关", "监听", "运行中", "规则", "请求数", "错误"])
        self.statusTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.statusTable.verticalHeader().hide()

        layout.addWidget(StrongBodyLabel("运行状态", tab))
        layout.addWidget(self.statusTable)
        self._add_page(tab, "状态")

    def refresh_all(self):
        self.refresh_cloudflare_status()
        self.refresh_cloudflare_tunnels()
        self.refresh_services()
        self.refresh_gateways()
        self.refresh_routes()
        self.refresh_status()

    def refresh_tunnel_cards(self):
        tunnel_status = self.plugin.get_cloudflare_statuses()
        gateway_status = self.plugin.get_status()
        tunnels = self.db.list_cloudflare_tunnels()
        signature = tuple(
            (
                tunnel["id"],
                tunnel["name"],
                tunnel["enabled"],
                tunnel["remarks"],
                tunnel["gateway_id"],
                tunnel["gateway_name"],
                tunnel["listen_port"],
                bool(tunnel_status.get(tunnel["id"], {}).get("running")),
                tunnel_status.get(tunnel["id"], {}).get("last_error") or "",
                bool(gateway_status.get(tunnel["gateway_id"], {}).get("running"))
                if tunnel["gateway_id"]
                else False,
            )
            for tunnel in tunnels
        )
        if signature == self._tunnel_cards_signature:
            return

        self._tunnel_cards_signature = signature
        self.tunnelOverviewLayout.takeAllWidgets()
        for tunnel in tunnels:
            gateway_id = tunnel["gateway_id"]
            gateway_running = bool(gateway_status.get(gateway_id, {}).get("running")) if gateway_id else False
            card = TunnelCard(
                tunnel,
                tunnel_status.get(tunnel["id"], {}),
                gateway_running=gateway_running,
                parent=self.tunnelOverviewContainer,
            )
            card.start_requested.connect(self._on_start_tunnel)
            card.stop_requested.connect(self._on_stop_tunnel)
            card.edit_requested.connect(self._on_edit_tunnel)
            card.delete_requested.connect(self._on_delete_tunnel)
            self.tunnelOverviewLayout.addWidget(card)

    def refresh_gateway_cards(self):
        status = self.plugin.get_status()
        route_counts = {}
        for route in self.db.list_routes():
            route_counts[route["gateway_id"]] = route_counts.get(route["gateway_id"], 0) + 1

        gateways = self.db.list_gateways()
        signature = tuple(
            (
                gateway["id"],
                gateway["name"],
                gateway["listen_host"],
                gateway["listen_port"],
                gateway["enabled"],
                gateway["remarks"],
                route_counts.get(gateway["id"], 0),
                bool(status.get(gateway["id"], {}).get("running")),
                status.get(gateway["id"], {}).get("error") or "",
            )
            for gateway in gateways
        )
        if signature == self._gateway_cards_signature:
            return

        self._gateway_cards_signature = signature
        self.overviewLayout.takeAllWidgets()
        for gateway in gateways:
            gateway_id = gateway["id"]
            card = GatewayCard(
                gateway,
                route_counts.get(gateway_id, 0),
                status.get(gateway_id, {}),
                self.overviewContainer,
            )
            card.start_requested.connect(self._on_start_gateway)
            card.stop_requested.connect(self._on_stop_gateway)
            card.edit_requested.connect(self._on_edit_gateway)
            card.delete_requested.connect(self._on_delete_gateway)
            self.overviewLayout.addWidget(card)

    def refresh_services(self):
        self.servicesTable.setRowCount(0)
        for row, service in enumerate(self.db.list_services()):
            self.servicesTable.insertRow(row)
            self._set_item(self.servicesTable, row, 0, service["name"], service["id"])
            self._set_item(self.servicesTable, row, 1, service["target_url"])
            self._set_item(self.servicesTable, row, 2, _bool_text(service["enabled"]))
            self._set_item(self.servicesTable, row, 3, service["remarks"] or "")
            self.servicesTable.setCellWidget(row, 4, self._action_widget(self._on_edit_service, self._on_delete_service, service["id"]))

    def refresh_gateways(self):
        self.gatewaysTable.setRowCount(0)
        for row, gateway in enumerate(self.db.list_gateways()):
            self.gatewaysTable.insertRow(row)
            listen = f"{gateway['listen_host']}:{gateway['listen_port']}"
            self._set_item(self.gatewaysTable, row, 0, gateway["name"], gateway["id"])
            self._set_item(self.gatewaysTable, row, 1, listen)
            self._set_item(self.gatewaysTable, row, 2, _bool_text(gateway["enabled"]))
            self._set_item(self.gatewaysTable, row, 3, _bool_text(gateway["auto_start"]))
            self._set_item(self.gatewaysTable, row, 4, gateway["remarks"] or "")
            self.gatewaysTable.setCellWidget(row, 5, self._action_widget(self._on_edit_gateway, self._on_delete_gateway, gateway["id"]))

    def refresh_routes(self):
        self.routesTable.setRowCount(0)
        for row, route in enumerate(self.db.list_routes()):
            self.routesTable.insertRow(row)
            gateway = f"{route['gateway_name']} ({route['listen_port']})"
            host_mode = "保留" if route["preserve_host"] else "目标"
            self._set_item(self.routesTable, row, 0, gateway, route["id"])
            self._set_item(self.routesTable, row, 1, route["path_prefix"])
            self._set_item(self.routesTable, row, 2, route["service_name"])
            self._set_item(self.routesTable, row, 3, route["target_url"])
            self._set_item(self.routesTable, row, 4, host_mode)
            self._set_item(self.routesTable, row, 5, _bool_text(route["enabled"]))
            self.routesTable.setCellWidget(row, 6, self._action_widget(self._on_edit_route, self._on_delete_route, route["id"]))

    def refresh_cloudflare_tunnels(self):
        self.tunnelsTable.setRowCount(0)
        statuses = self.plugin.get_cloudflare_statuses()
        for row, tunnel in enumerate(self.db.list_cloudflare_tunnels()):
            self.tunnelsTable.insertRow(row)
            status = statuses.get(tunnel["id"], {})
            router = "未映射网关"
            if tunnel["gateway_name"]:
                router = f"{tunnel['gateway_name']} ({tunnel['listen_host']}:{tunnel['listen_port']})"
            error = status.get("last_error") or ""
            self._set_item(self.tunnelsTable, row, 0, tunnel["name"], tunnel["id"])
            self._set_item(self.tunnelsTable, row, 1, router)
            self._set_item(self.tunnelsTable, row, 2, _bool_text(tunnel["enabled"]))
            self._set_item(self.tunnelsTable, row, 3, _bool_text(tunnel["auto_start"]))
            self._set_item(self.tunnelsTable, row, 4, _bool_text(status.get("running")))
            self._set_item(self.tunnelsTable, row, 5, error)
            self.tunnelsTable.setCellWidget(row, 6, self._tunnel_action_widget(tunnel["id"], bool(status.get("running"))))

    def refresh_status(self):
        status = self.plugin.get_status()
        total_gateways = len(self.db.list_gateways())
        signature = (
            total_gateways,
            tuple(
                sorted(
                    (gateway_id, tuple(sorted(item.items())))
                    for gateway_id, item in status.items()
                )
            ),
        )
        if signature == self._status_table_signature:
            self.refresh_cloudflare_status()
            return
        self._status_table_signature = signature

        self.statusTable.setRowCount(0)
        running = 0
        for row, item in enumerate(status.values()):
            self.statusTable.insertRow(row)
            listen = f"{item['listen_host']}:{item['listen_port']}"
            is_running = bool(item["running"])
            running += 1 if is_running else 0
            self._set_item(self.statusTable, row, 0, item["name"])
            self._set_item(self.statusTable, row, 1, listen)
            self._set_item(self.statusTable, row, 2, _bool_text(is_running))
            self._set_item(self.statusTable, row, 3, str(item["routes"]))
            self._set_item(self.statusTable, row, 4, str(item["requests_total"]))
            self._set_item(self.statusTable, row, 5, item["error"] or "")

        total_gateways = len(self.db.list_gateways())
        self.statusLabel.setText(f"网关运行：{running}/{total_gateways}")
        self.refresh_gateway_cards()
        self.refresh_cloudflare_status()

    def refresh_cloudflare_status(self):
        status = self.plugin.get_cloudflare_status()
        self.cloudflareStatusLabel.setText(
            f"Cloudflare 隧道：{status['running_count']}/{status['total_count']} 运行中"
        )
        self.refresh_tunnel_cards()

    def _set_item(self, table, row, column, text, item_id=None):
        item = QTableWidgetItem(str(text))
        if item_id is not None:
            item.setData(Qt.UserRole, int(item_id))
        table.setItem(row, column, item)

    def _action_widget(self, edit_handler, delete_handler, item_id):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        edit_btn = ToolButton(FluentIcon.EDIT, widget)
        delete_btn = ToolButton(FluentIcon.DELETE, widget)
        edit_btn.clicked.connect(lambda checked=False, value=item_id: edit_handler(value))
        delete_btn.clicked.connect(lambda checked=False, value=item_id: delete_handler(value))
        layout.addWidget(edit_btn)
        layout.addWidget(delete_btn)
        layout.addStretch(1)
        return widget

    def _tunnel_action_widget(self, tunnel_id, running):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        toggle_btn = ToolButton(FluentIcon.PAUSE if running else FluentIcon.PLAY, widget)
        edit_btn = ToolButton(FluentIcon.EDIT, widget)
        delete_btn = ToolButton(FluentIcon.DELETE, widget)
        if running:
            toggle_btn.clicked.connect(lambda checked=False, value=tunnel_id: self._on_stop_tunnel(value))
        else:
            toggle_btn.clicked.connect(lambda checked=False, value=tunnel_id: self._on_start_tunnel(value))
        edit_btn.clicked.connect(lambda checked=False, value=tunnel_id: self._on_edit_tunnel(value))
        delete_btn.clicked.connect(lambda checked=False, value=tunnel_id: self._on_delete_tunnel(value))
        layout.addWidget(toggle_btn)
        layout.addWidget(edit_btn)
        layout.addWidget(delete_btn)
        layout.addStretch(1)
        return widget

    def _on_start_all(self):
        tunnels_ok = self.plugin.start_all_cloudflare_tunnels()
        routers_ok = self.plugin.start_all()
        if tunnels_ok and routers_ok:
            self.refresh_status()
            self.refresh_cloudflare_tunnels()
            InfoBar.success("成功", "Tunnel 和 Router 已全部启动", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)
        else:
            self.refresh_all()
            InfoBar.warning("警告", "部分 Tunnel 或 Router 启动失败", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

    def _on_stop_all(self):
        self.plugin.stop_all_cloudflare_tunnels()
        self.plugin.stop_all()
        self.refresh_status()
        self.refresh_cloudflare_tunnels()
        InfoBar.info("提示", "Tunnel 和 Router 已全部停止", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)

    def _on_start_gateway(self, gateway_id):
        if self.plugin.start_gateway(gateway_id):
            self.refresh_all()
            InfoBar.success("成功", "Router 已启动", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)
        else:
            InfoBar.error("错误", "Router 已禁用或启动失败", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

    def _on_stop_gateway(self, gateway_id):
        if self.plugin.stop_gateway(gateway_id):
            self.refresh_all()
            InfoBar.info("提示", "Router 已停止", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)
        else:
            InfoBar.error("错误", "Router 停止失败", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

    def _on_add_tunnel(self):
        dialog = TunnelDialog(self.db, self.window())
        if dialog.exec():
            data = dialog.get_data()
            if not dialog.validate():
                self._show_validation_error("Tunnel 名称和 token 不能为空")
                return
            self.db.save_cloudflare_tunnel(data)
            self._after_tunnel_change("Tunnel 已添加")

    def _on_edit_tunnel(self, tunnel_id):
        row = self.db.get_cloudflare_tunnel(tunnel_id)
        if not row:
            return
        was_running = self.plugin.is_cloudflare_running(tunnel_id)
        dialog = TunnelDialog(self.db, self.window(), dict(row))
        if dialog.exec():
            data = dialog.get_data()
            if not dialog.validate():
                self._show_validation_error("Tunnel 名称和 token 不能为空")
                return
            self.db.save_cloudflare_tunnel(data, tunnel_id)
            if was_running:
                self.plugin.stop_cloudflare_tunnel(tunnel_id)
                self.plugin.start_cloudflare_tunnel(tunnel_id)
            self._after_tunnel_change("Tunnel 已更新")

    def _on_delete_tunnel(self, tunnel_id):
        if not self._confirm_delete("删除 Tunnel", "确定要删除这个 Cloudflare Tunnel 吗？正在运行的进程会先停止。"):
            return
        self.plugin.stop_cloudflare_tunnel(tunnel_id)
        self.db.delete_cloudflare_tunnel(tunnel_id)
        self._after_tunnel_change("Tunnel 已删除")

    def _on_start_tunnel(self, tunnel_id):
        if self.plugin.start_cloudflare_tunnel(tunnel_id):
            self.refresh_all()
            InfoBar.success("成功", "Tunnel 已启动", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)
        else:
            self.refresh_all()
            InfoBar.error("错误", "Tunnel 启动失败", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

    def _on_stop_tunnel(self, tunnel_id):
        self.plugin.stop_cloudflare_tunnel(tunnel_id)
        self.refresh_all()
        InfoBar.info("提示", "Tunnel 已停止", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)

    def _on_start_all_tunnels(self):
        if self.plugin.start_all_cloudflare_tunnels():
            self.refresh_all()
            InfoBar.success("成功", "Tunnel 已全部启动", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)
        else:
            self.refresh_all()
            InfoBar.warning("警告", "部分 Tunnel 启动失败", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

    def _on_stop_all_tunnels(self):
        self.plugin.stop_all_cloudflare_tunnels()
        self.refresh_all()
        InfoBar.info("提示", "Tunnel 已全部停止", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)

    def _after_tunnel_change(self, message):
        self.refresh_all()
        InfoBar.success("成功", message, parent=self.window(), position=InfoBarPosition.TOP, duration=2000)

    def _on_add_service(self):
        dialog = ServiceDialog(self.window())
        if dialog.exec():
            data = dialog.get_data()
            if not dialog.validate():
                self._show_validation_error("服务名称和有效目标地址不能为空")
                return
            self.db.execute(
                "INSERT INTO services (name, target_url, enabled, remarks) VALUES (?, ?, ?, ?)",
                (data["name"], data["target_url"], data["enabled"], data["remarks"]),
            )
            self._after_config_change("服务已添加")

    def _on_edit_service(self, service_id):
        row = self.db.fetchone("SELECT * FROM services WHERE id = ?", (service_id,))
        if not row:
            return
        dialog = ServiceDialog(self.window(), dict(row))
        if dialog.exec():
            data = dialog.get_data()
            if not dialog.validate():
                self._show_validation_error("服务名称和有效目标地址不能为空")
                return
            self.db.execute(
                "UPDATE services SET name=?, target_url=?, enabled=?, remarks=? WHERE id=?",
                (data["name"], data["target_url"], data["enabled"], data["remarks"], service_id),
            )
            self._after_config_change("服务已更新")

    def _on_delete_service(self, service_id):
        if not self._confirm_delete("删除服务", "确定要删除这个服务吗？相关路由也会一起删除。"):
            return
        self.db.execute("DELETE FROM services WHERE id = ?", (service_id,))
        self._after_config_change("服务已删除")

    def _on_add_gateway(self):
        dialog = GatewayDialog(self.window())
        if dialog.exec():
            data = dialog.get_data()
            if not dialog.validate():
                self._show_validation_error("Router 名称和有效端口不能为空")
                return
            if not self._save_gateway(data):
                return
            self._after_config_change("Router 已添加")

    def _on_edit_gateway(self, gateway_id):
        row = self.db.fetchone("SELECT * FROM gateways WHERE id = ?", (gateway_id,))
        if not row:
            return
        dialog = GatewayDialog(self.window(), dict(row))
        if dialog.exec():
            data = dialog.get_data()
            if not dialog.validate():
                self._show_validation_error("Router 名称和有效端口不能为空")
                return
            if not self._save_gateway(data, gateway_id):
                return
            self._after_config_change("Router 已更新")

    def _save_gateway(self, data, gateway_id=None):
        try:
            port = int(data["listen_port"])
            if gateway_id is None:
                self.db.execute(
                    """
                    INSERT INTO gateways (name, listen_host, listen_port, enabled, auto_start, remarks)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (data["name"], data["listen_host"], port, data["enabled"], data["auto_start"], data["remarks"]),
                )
            else:
                self.db.execute(
                    """
                    UPDATE gateways
                    SET name=?, listen_host=?, listen_port=?, enabled=?, auto_start=?, remarks=?
                    WHERE id=?
                    """,
                    (data["name"], data["listen_host"], port, data["enabled"], data["auto_start"], data["remarks"], gateway_id),
                )
            return True
        except Exception as exc:
            InfoBar.error("错误", f"保存 Router 失败：{exc}", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)
            return False

    def _on_delete_gateway(self, gateway_id):
        if not self._confirm_delete("删除 Router", "确定要删除这个 Router 吗？相关路由会被删除，关联的 Tunnel 会保留但变为未映射。"):
            return
        self.plugin.stop_gateway(gateway_id)
        self.db.execute("DELETE FROM gateways WHERE id = ?", (gateway_id,))
        self._after_config_change("Router 已删除")

    def _on_add_route(self):
        if not self.db.list_gateways() or not self.db.list_services():
            self._show_validation_error("请先创建至少一个 Router 和一个服务")
            return
        dialog = RouteDialog(self.db, self.window())
        if dialog.exec():
            data = dialog.get_data()
            if not dialog.validate():
                self._show_validation_error("Router、服务和路径前缀不能为空")
                return
            if not self._save_route(data):
                return
            self._after_config_change("分发规则已添加")

    def _on_edit_route(self, route_id):
        row = self.db.fetchone("SELECT * FROM gateway_routes WHERE id = ?", (route_id,))
        if not row:
            return
        dialog = RouteDialog(self.db, self.window(), dict(row))
        if dialog.exec():
            data = dialog.get_data()
            if not dialog.validate():
                self._show_validation_error("Router、服务和路径前缀不能为空")
                return
            if not self._save_route(data, route_id):
                return
            self._after_config_change("分发规则已更新")

    def _save_route(self, data, route_id=None):
        try:
            if route_id is None:
                self.db.execute(
                    """
                    INSERT INTO gateway_routes (gateway_id, service_id, path_prefix, preserve_host, enabled)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (data["gateway_id"], data["service_id"], data["path_prefix"], data["preserve_host"], data["enabled"]),
                )
            else:
                self.db.execute(
                    """
                    UPDATE gateway_routes
                    SET gateway_id=?, service_id=?, path_prefix=?, preserve_host=?, enabled=?
                    WHERE id=?
                    """,
                    (data["gateway_id"], data["service_id"], data["path_prefix"], data["preserve_host"], data["enabled"], route_id),
                )
            return True
        except Exception as exc:
            InfoBar.error("错误", f"保存分发规则失败：{exc}", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)
            return False

    def _on_delete_route(self, route_id):
        if not self._confirm_delete("删除分发规则", "确定要删除这条分发规则吗？"):
            return
        self.db.execute("DELETE FROM gateway_routes WHERE id = ?", (route_id,))
        self._after_config_change("分发规则已删除")

    def _after_config_change(self, message):
        self.plugin.reload_runtime()
        self.refresh_all()
        InfoBar.success("成功", message, parent=self.window(), position=InfoBarPosition.TOP, duration=2000)

    def _show_validation_error(self, message):
        InfoBar.error("错误", message, parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

    def _confirm_delete(self, title, content):
        dialog = ConfirmDialog(title, content, self.window())
        return bool(dialog.exec())


class GatewaySidebarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self._orientation = "vertical"
        self._init_ui()

    def _init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.layout.setAlignment(Qt.AlignCenter)

        self.label = StrongBodyLabel("GW\n0", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-size: 10px; color: #666666;")
        self.layout.addWidget(self.label)

    def set_orientation(self, orientation: str):
        self._orientation = orientation
        self._update_display()

    def set_count(self, count: int):
        if self._count == count:
            return
        self._count = count
        self._update_display()

    def _update_display(self):
        if self._orientation == "top":
            self.label.setText(f"GW: {self._count}")
        else:
            self.label.setText(f"GW\n{self._count}")
        color = "#107c10" if self._count > 0 else "#666666"
        self.label.setStyleSheet(f"font-size: 10px; color: {color};")
