# Agile Tiles - 项目说明文档

## 目录
- [项目概述](#项目概述)
- [技术栈](#技术栈)
- [代码架构](#代码架构)
- [核心功能](#核心功能)
- [PySide6-Fluent-Widgets 使用指南](#pyside6-fluent-widgets-使用指南)
- [开发注意事项](#开发注意事项)

---

## 项目概述

Agile Tiles 是一个基于 **PySide6** 和 **PySide6-Fluent-Widgets** 的现代化桌面应用程序，采用 Fluent Design 设计语言，提供插件化架构和优雅的用户界面。

### 主要特性
- 🎨 Fluent Design 现代化界面
- 🔌 插件化架构，支持动态加载/卸载插件
- ⚙️ 完整的设置管理系统
- 🎯 系统托盘支持
- 🌓 支持深色/浅色/跟随系统主题

---

## 技术栈

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | 编程语言 |
| PySide6 | 6.9.2 | Qt6 for Python 绑定 |
| PySide6-Fluent-Widgets | 1.x | Fluent Design 组件库 |
| SQLite | - | 本地数据存储 |

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
agile-tiles-master/
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
├── plugins/                # 插件目录
│   └── todo/               # Todo 插件示例
│       ├── manifest.json       # 插件清单
│       ├── plugin.py           # 插件实现
│       ├── task_manager.py     # 任务管理
│       └── db_manager.py       # 数据库管理
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
- 自动发现 `plugins/` 目录下的插件
- 根据 `manifest.json` 加载插件
- 管理插件生命周期 (load/unload)

#### 3. MainWindow - 主窗口
- 继承自 `qfluentwidgets.FluentWindow`
- 提供导航界面和插件接口管理
- 使用 `addSubInterface()` 添加插件页面

#### 4. SettingsManager - 设置管理器
- 管理应用设置的持久化
- 提供默认值和设置访问 API
- 支持分类设置 (general, appearance 等)

---

## 核心功能

### 1. 主题系统
```python
from qfluentwidgets import setTheme, Theme, setThemeColor

# 设置主题
setTheme(Theme.DARK)    # 深色主题
setTheme(Theme.LIGHT)   # 浅色主题
setTheme(Theme.AUTO)    # 跟随系统

# 设置强调色
setThemeColor("#FF6B9D")  # 自定义颜色
```

### 2. 插件系统
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

### 3. 设置界面
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
