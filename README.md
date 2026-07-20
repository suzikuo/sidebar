# Agile Tiles - 项目说明文档

## 目录
- [项目概述](#项目概述)
- [技术栈](#技术栈)
- [代码架构](#代码架构)
- [核心功能](#核心功能)
- [插件开发](#插件开发)
- [PySide6-Fluent-Widgets 使用指南](#pyside6-fluent-widgets-使用指南)
- [开发注意事项](#开发注意事项)

---

## 项目概述

Agile Tiles 是一个基于 **PySide6** 和 **PySide6-Fluent-Widgets** 的无边框桌面侧边栏工具。插件入口在顶部或屏幕侧边自然滚动，Settings 固定；插件详情继续使用紧凑的原生 Qt 界面。

### 主要特性
- 🎨 Fluent Design 现代化界面
- 🔌 插件化架构，支持动态加载/卸载插件
- 支持 manifest v2 `.atplugin` 离线安装、更新、回滚和卸载
- 支持插件前置依赖、版本约束以及受控命令/事件调用
- ⚙️ 完整的设置管理系统
- 🎯 系统托盘支持
- 🌓 支持深色/浅色/跟随系统主题

---

## 技术栈

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.11 | 编程语言与插件 ABI |
| PySide6 | 6.10.2 | Qt6 for Python 绑定 |
| PySide6-Fluent-Widgets | 1.11.0 | Fluent Design 组件库 |
| SQLite | - | 本地数据存储 |
| aiohttp | - | 异步本地网关、HTTP/WebSocket 反向代理 |

### 官方资源

| 资源 | 地址 |
|------|------|
| PySide6-Fluent-Widgets GitHub | https://github.com/zhiyiYo/PyQt-Fluent-Widgets |
| 官方文档 | https://qfluentwidgets.com |
| 组件画廊 | https://qfluentwidgets.com/gallery |
| Pro 版本 | https://qfluentwidgets.com/pages/pro |

---

## 代码架构

```
sidebar/
├── main.py                 # 应用入口点
├── requirements.txt        # 依赖列表
├── core/                   # 核心模块
│   ├── plugin_system/      # 插件系统
│   │   ├── plugin_manager.py   # 插件管理器
│   │   ├── plugin_base.py      # 插件基类
│   │   └── event_bus.py        # 事件总线
│   ├── settings/           # 设置系统
│   │   ├── settings_manager.py     # 设置管理器
│   │   ├── fluent_settings_card.py # Fluent 设置界面
│   │   └── settings_card.py        # 传统设置界面
│   ├── window_system/      # 窗口系统
│   │   └── main_window.py      # 主窗口 (FluentWindow)
│   ├── ui_kernel/          # UI 核心
│   │   ├── theme_engine.py     # 主题引擎
│   │   ├── design_tokens.py    # 设计令牌
│   │   └── view_host/          # 视图宿主
│   ├── data_layer/         # 数据层
│   │   └── data_service.py     # 数据服务
│   └── state_store.py      # 状态持久化
├── plugins1/               # 官方插件包源码（不内置进宿主发布包）
├── build_plugins.py        # 批量生成独立 .atplugin
└── ui/                     # UI 组件
    └── components/         # 公共组件
```

### 核心模块说明

#### 1. main.py - 应用入口
```python
# 关键点：QApplication 必须在模块级别创建，在导入 qfluentwidgets 之前
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)  # 第22行

# 然后才能导入 qfluentwidgets
from qfluentwidgets import setTheme, Theme, setThemeColor
```

#### 2. PluginManager - 插件管理器
- 默认只发现 AppData `user-plugins/` 下已安装的插件
- 仓库 `plugins1/` 是打包源码，不作为正式发布的内置插件目录
- 根据 manifest 前置依赖拓扑加载插件
- 管理安装、更新、启停、回滚和卸载事务

#### 3. Window System - 窗口系统
- `SidebarWindow` 是无系统标题栏的主入口，支持顶部/左侧/右侧布局
- 插件位于可滚动区，Settings 固定在末端
- `DetailWindow` 承载各插件原生详情界面
- `ControlCenterWindow` 是从托盘右键打开的独立前端管理窗口，负责完整设置、插件管理、官方市场和诊断

#### 4. SettingsManager - 设置管理器
- 管理应用设置的持久化
- 提供默认值和设置访问 API
- 支持分类设置 (general, appearance 等)

---

## 核心功能

### 1. 官方插件包与功用介绍
Agile Tiles 基于插件化架构，以下功能以独立 `.atplugin` 提供，可按需安装：

- ⏱️ **Time (时钟与倒计时)**：一个优雅的侧边栏时钟挂件，支持添加与管理闹钟任务。特别提供 **桌面悬浮时钟** 模式，并且可以在到达闹铃设定前5分钟无缝切换成显眼的倒计时，挂件支持穿透防误触、无边框与自适应拖拽定位。
- 📖 **ThiefBook (摸鱼阅读器)**：采用类似“桌面歌词”悬浮窗设计的 txt 阅读器插件。支持热键翻页、老板键快捷隐藏；支持自定义样式大小，并且在调整配置时搭载了绝对进度锚点算法，保证缩放文本不丢进度。
- 🛠️ **Toolbox (开发工具箱)**：集成了诸如 `端口转发管理 (netsh Portproxy)` 规则可视化增删改查等日常系统运维和网络代理小工具。
- 🔗 **SSH Manager (SSH 会话管理)**：可建立、添加与整理多台远程服务器环境的快捷 SSH 连接。
- 🌐 **Gateway Manager (本地网关管理)**：可视化管理多个本地监听网关与多个 Cloudflare Tunnel，支持多 Tunnel 指向同一 Router 端口、Path Prefix 路由、HTTP 反向代理、流式响应和 WebSocket 代理。
- 🚀 **App Launcher (应用启动器)**：便于存放和快速拉起常用的本地应用与常用目录。
- 🔖 **Bookmarks (书签管理)**：可分门别类地收纳高频访问的开发测试网页链接与系统命令书签。

### 2. 主题系统
```python
from qfluentwidgets import setTheme, Theme, setThemeColor

# 设置主题
setTheme(Theme.DARK)    # 深色主题
setTheme(Theme.LIGHT)   # 浅色主题
setTheme(Theme.AUTO)    # 跟随系统

# 设置强调色
setThemeColor("#FF6B9D")  # 自定义颜色
```

### 3. 插件系统接入点
每个插件需要：
- `manifest.json` - 插件元数据
- `plugin.py` - 继承 `PluginBase` 的实现类

```python
class TodoPlugin(PluginBase):
    def on_load(self):
        """插件加载时调用"""
        pass
    
    def on_unload(self):
        """插件卸载时调用"""
        pass
    
    def get_card_widget(self) -> QWidget:
        """返回插件的 UI 组件"""
        return self._build_ui()
```

### 4. 快速设置与控制中心

- 侧边栏 Settings 只保留主题、侧边栏行为和通知等高频快速配置。
- 托盘图标右键选择“控制中心”，可进入完整设置、已安装插件、官方市场和关于/诊断页面。
- 官方市场读取发行版随附且经过校验的 `.atplugin` 包；安装、更新、卸载和回滚继续遵循现有事务与重启语义。
- 控制中心是本地 Vue 页面，通过受限 QWebChannel API 调用 Python，不启动本地 HTTP 服务，也不向前端暴露插件包路径。

原生快速设置使用 `SettingCardGroup` 组织设置项：
使用 `SettingCardGroup` 组织设置项：
```python
# 创建设置组
general_group = SettingCardGroup("通用设置", self)

# 开关设置
switch_card = SwitchSettingCard(
    FluentIcon.POWER_BUTTON,
    "开机启动",
    "系统启动时自动运行",
    parent=general_group
)
general_group.addSettingCard(switch_card)

# 按钮设置  
push_card = PushSettingCard(
    "选择颜色",
    FluentIcon.PALETTE,
    "强调色",
    "自定义主题颜色",
    parent=general_group
)
```

## 插件开发

正式插件使用 manifest v2 `.atplugin`。批量构建仓库中的全部官方插件：

```powershell
python .\build_plugins.py
```

输出位于 `dist/plugins/`。这些包是独立插件介质，不会被 `python .\build.py` 复制到宿主目录；可以通过控制中心“官方市场”目录或“导入插件包”安装。应用不会从宿主发布目录静默安装。模板、单包打包、安装、数据边界和当前依赖限制见 [PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md)。

宿主与插件的构建命令分开：

```powershell
# 只构建 Agile Tiles 宿主
python .\build.py

# 单独生成插件包（可选）
python .\build_plugins.py
```

---

## PySide6-Fluent-Widgets 使用指南

### 安装
```bash
pip install PySide6-Fluent-Widgets
# 注意：不要安装 PyQt-Fluent-Widgets，那是 PyQt 版本
```

### 重要：QApplication 创建顺序
```python
# ✅ 正确做法：先创建 QApplication
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

# 然后再导入 qfluentwidgets
from qfluentwidgets import FluentWindow, setTheme

# ❌ 错误做法：在 QApplication 之前导入
from qfluentwidgets import FluentWindow  # 会报错！
app = QApplication(sys.argv)
```

### 常用组件

#### 窗口类
| 组件 | 说明 |
|------|------|
| `FluentWindow` | 标准 Fluent 主窗口 |
| `MSFluentWindow` | 微软风格 Fluent 窗口 |
| `SplitFluentWindow` | 分栏式 Fluent 窗口 |

#### 设置卡片
| 组件 | 说明 | 是否需要 ConfigItem |
|------|------|---------------------|
| `SwitchSettingCard` | 开关设置 | ❌ 不需要 |
| `PushSettingCard` | 按钮设置 | ❌ 不需要 |
| `ComboBoxSettingCard` | 下拉框设置 | ✅ 需要 |
| `RangeSettingCard` | 滑块设置 | ✅ 需要 |

#### 基础组件
| 组件 | 说明 |
|------|------|
| `CardWidget` | 卡片容器 |
| `ScrollArea` | 滚动区域 |
| `ComboBox` | 下拉选择框 |
| `LineEdit` | 输入框 |
| `PrimaryPushButton` | 主要按钮 |
| `PushButton` | 普通按钮 |

#### 标签类
| 组件 | 说明 |
|------|------|
| `TitleLabel` | 标题标签 |
| `SubtitleLabel` | 副标题 |
| `BodyLabel` | 正文标签 |
| `CaptionLabel` | 说明文字 |

#### 反馈组件
| 组件 | 说明 |
|------|------|
| `InfoBar` | 消息提示条 |
| `MessageBox` | 消息对话框 |
| `Dialog` | 对话框 |

### 使用示例

#### 创建 FluentWindow
```python
from qfluentwidgets import FluentWindow, NavigationItemPosition, FluentIcon

class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("My App")
        self.resize(1000, 700)
        
        # 添加导航项
        self.addSubInterface(
            widget,
            FluentIcon.HOME,
            "首页"
        )
        
        # 底部导航项
        self.addSubInterface(
            settings_widget,
            FluentIcon.SETTING,
            "设置",
            position=NavigationItemPosition.BOTTOM
        )
```

#### 显示 InfoBar 通知
```python
from qfluentwidgets import InfoBar, InfoBarPosition

# 成功提示
InfoBar.success(
    title="成功",
    content="操作已完成",
    orient=Qt.Horizontal,
    isClosable=True,
    position=InfoBarPosition.TOP,
    duration=2000,
    parent=self
)

# 其他类型
InfoBar.info(...)     # 信息
InfoBar.warning(...)  # 警告
InfoBar.error(...)    # 错误
```

#### 自定义设置卡片（不使用 ConfigItem）
```python
from qfluentwidgets import CardWidget, ComboBox, BodyLabel, IconWidget

card = CardWidget(parent)
card.setFixedHeight(70)

layout = QHBoxLayout(card)
layout.addWidget(IconWidget(FluentIcon.BRUSH))

text_layout = QVBoxLayout()
text_layout.addWidget(BodyLabel("主题模式"))
text_layout.addWidget(BodyLabel("选择主题"))
layout.addLayout(text_layout)

combo = ComboBox()
combo.addItems(["深色", "浅色", "系统"])
layout.addWidget(combo)
```

---

## 开发注意事项

### 1. 库版本选择
- **PySide6 项目** → 使用 `PySide6-Fluent-Widgets`
- **PyQt5/6 项目** → 使用 `PyQt-Fluent-Widgets`
- 两者 API 相同，但不能混用！

### 2. QApplication 创建顺序
必须在导入任何 qfluentwidgets 组件之前创建 QApplication。

### 3. ConfigItem 与设置管理
- `RangeSettingCard`, `ComboBoxSettingCard` 等需要 `ConfigItem`
- 如果使用自定义设置管理系统，请使用 `CardWidget` + 基础组件自行组合

### 4. 主题切换
使用 `setTheme()` 会自动更新所有 qfluentwidgets 组件的样式。

### 5. 图标系统
使用 `FluentIcon` 枚举获取内置图标：
```python
from qfluentwidgets import FluentIcon

icon = FluentIcon.HOME
icon = FluentIcon.SETTING
icon = FluentIcon.PALETTE
```

---

## 常见问题

### Q: "Must construct a QApplication before a QWidget"
**A:** 确保在 `main.py` 中先创建 QApplication，再导入 qfluentwidgets 模块。

### Q: ComboBoxSettingCard 报错 "configItem required"
**A:** 使用 `CardWidget` + `ComboBox` 自行组合，或使用 `QConfig` 系统。

### Q: 如何自定义主题色？
**A:** 使用 `setThemeColor("#HEX")` 设置任意颜色。

---

## 更新日志

### 2026-02-02
- 修复 qfluentwidgets 库兼容性问题
- 重构 main.py 导入顺序
- 重写 fluent_settings_card.py 使用兼容 API

### 2026-03-24
- [Time] 为时钟/倒计时插件新增透明无边框、支持拖拽及防误触锁定的桌面时钟模式
- [ThiefBook] 修复在阅读器中调整“单页字数”或“字体”时意外丢失阅读进度（自动重置页码）的问题，引入绝对进度锚点进行无缝重排
