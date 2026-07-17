# Agile Tiles 插件开发

当前正式支持的是 Windows x64、CPython 3.11 下的可信离线 `.atplugin`。纯 Python 插件只要使用宿主已携带的模块，安装和更新插件时不需要重新打包 Agile Tiles。

## 1. 从模板开始

复制 `templates/hello_plugin`，目录名建议与插件 ID 一致：

```text
my_plugin/
├── manifest.json
└── plugin.py
```

多文件插件可以增加 `views.py`、`services.py` 和 `assets/`。插件内部必须使用相对导入：

```python
from .views import MyPluginWidget
```

不要使用 `from plugins.other_plugin ...` 导入其他插件实现。

## 2. Manifest v2

最小 native manifest：

```json
{
  "manifest_version": 2,
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "entry": "plugin.py",
  "class": "MyPlugin",
  "api_version": "1.0",
  "compatibility": {
    "app": ">=1.0.0",
    "python_abi": "cp311",
    "platform": "win_amd64"
  },
  "dependencies": {
    "host": [],
    "python": [],
    "plugins": {}
  },
  "files": {},
  "native_modules": [],
  "requires_restart": false,
  "ui": {"type": "native"}
}
```

规则：

- `id` 使用小写字母、数字以及 `.`、`_`、`-`，并以字母开头。
- `entry` 必须是 `.py` bootstrap，不能直接指向 `.pyd`。
- 源目录中的 `files` 保持 `{}`；打包器生成包时自动写入全部文件 SHA-256。
- 修改代码后提升 `version`，再重新打包。
- `dependencies.host` 只声明 Agile Tiles 已提供的包；不要把 PySide6 等宿主库放进插件包。
- `dependencies.python` 当前必须为空，managed wheel 尚未接入生产运行时。
- `dependencies.plugins` 使用 `插件 ID -> PEP 440 版本范围`，例如 `{"gateway_manager": ">=1,<2"}`。

## 3. PluginBase

插件类继承 `PluginBase`，实现以下方法：

- `on_load()`：注册服务、读取状态或启动必要任务，不创建无用 UI。
- `on_unload()`：释放插件自己持有的资源。
- `get_icon()`：返回侧边栏图标。
- `get_thumbnail_widget()`：当前抽象契约要求实现；主侧边栏暂未消费它。
- `get_card_widget()`：返回详情区 QWidget，并缓存实例。

以 `templates/hello_plugin/plugin.py` 为可运行示例。后台任务、计时器、事件和通知优先通过 `self.context` 创建，以便卸载时统一清理。

## 4. 数据边界

- 少量设置、窗口状态和简单文档数据使用 `self.context.state`。
- 关系数据可以使用插件私有 SQLite，但 SQL 只放在本插件 repository/model，不写进 view。
- 插件数据位于 `%APPDATA%\AgileTiles\plugins\<plugin-id>`，卸载插件代码不会默认删除数据。
- 不直接读取或修改其他插件的数据库、文件和 Python 对象。

插件间修改由提供方导出命令，调用方不拼接具体路由：

```python
# provider
self.context.register_api_route(
    "set-enabled",
    self.set_enabled,
    version="1.0",
    exported_capability="gateway.write",
)
self.context.publish_event("changed", {"enabled": True})

# consumer manifest: dependencies.plugins 包含 provider，capabilities 包含 gateway.write
result = self.context.call_plugin(
    "provider", "set-enabled", {"enabled": True}, version="1.0"
)
self.context.subscribe_plugin_event("provider", "changed", self.on_changed)
```

前置依赖决定加载顺序；`exported_capability` 决定调用权限；主版本不兼容时调用会被拒绝。当前本地可信阶段的 capability 来自 manifest，在线插件目录启用前还会增加用户授权。

## 5. 打包

在项目根目录执行：

```powershell
python .\plugin_packer.py .\my_plugin --out .\dist
```

输出为：

```text
dist/my_plugin.atplugin
```

打包器会：

1. 忽略 `__pycache__`、`.pyc/.pyo` 和当前输出包。
2. 为 manifest 外的每个文件计算 SHA-256。
3. 同步包内 native module 哈希。
4. 创建根布局 `.atplugin`。
5. 调用与客户端相同的 manifest/package 检查器自验。

任何错误都会返回非零退出码，不生成新的正式包。

## 6. 安装和更新

1. 打开 Agile Tiles 设置。
2. 在“插件管理”中选择“添加插件”。
3. 选择 `.atplugin`。
4. 校验成功后重启 Agile Tiles。

更新使用相同 `id` 和新的 `version` 再次导入。安装器只写入 AppData 用户插件目录，不覆盖随主程序发布的 bundled 插件；更新加载失败时会按插件类型回滚或排队重启回滚。

设置页会显示来源、版本、加载/阻断、pending 和错误状态，并提供取消 pending、卸载用户版与安全回滚操作。

## 7. 当前限制

- 不支持客户端现场运行 `pip`。
- 不支持含 managed third-party wheel 的插件。
- 独立 `.pyd` 不是插件；原生模块必须放进 `.atplugin` 并由 `.py` bootstrap 导入。
- `.pyd` 的静态 ABI/PE 校验已经存在；真实第三方 `.pyd` 加载仍需按目标 ABI/DLL 单独验收。
- `ui.type=web` 仍是可选 POC，当前生产运行时不会自动承载 React/Vue 插件页面。
- 插件运行在主进程，不是安全沙箱，只安装自己编写或可信来源的包。

## 8. 构建主程序

发布只使用一个入口：

```powershell
python .\build.py
```

它委托 `AgileTiles.spec` 生成 `dist/AgileTiles` onedir。普通纯 Python 插件更新不需要重新构建这个目录。
