# 网络监控插件

`network_monitor` 是一个宿主插件，应用流量、V2Ray、历史存储和悬浮窗都是它的内部模块，不会在侧边栏注册额外插件入口。

## 架构

```text
NetworkMonitorPlugin
  |- EtwApplicationTrafficSource     应用级 TCP/UDP 字节与 PID
  |- WindowsNetworkMonitor           系统网卡总字节
  |- V2RayCollector                  V2Ray 代理字节与扩展状态
  |- NetworkMonitorService           后台采样与异步查询
  |- TrafficHistoryApi               唯一历史数据访问入口
  |    `- TrafficHistoryRepository   SQLite、降采样、清理
  |- NetworkMonitorWidget            实时、历史、设置
  `- FloatingNetworkWidget           单个可配置悬浮窗
```

采集器只生成快照或标准记录，不直接访问 SQLite。数据库只由 `TrafficHistoryApi` 持有，写入、查询和统计都通过宿主 API 路由完成：

```text
plugins/network_monitor/submit
plugins/network_monitor/submit-v2ray
plugins/network_monitor/query
plugins/network_monitor/stats
```

该边界类似本地 FastAPI service：调用方提交 JSON，API 层验证来源、字段和单次记录上限，仓库实现不会泄漏到采集模块。

## 数据来源

| 来源 | 含义 | 失败时行为 |
| --- | --- | --- |
| `system` | 默认路由对应的活动网卡；可切换为 `GetIfTable2` 汇总全部活动非回环网卡 | 默认路由不可用时回退为全部活动网卡 |
| `application` | 按需启动的 ETW `Microsoft-Windows-Kernel-Network` 按 PID 汇总 | 默认关闭；仅应用列表降级，系统与 V2Ray继续工作 |
| `v2ray` | Xray `/debug/vars` 的 `proxy*` 出站累计字节 | 单独标记离线，不影响系统数据 |
| `direct` | `max(0, system - v2ray)` | 任一必要来源缺失时不可用 |

系统总流量和 V2Ray 代理流量始终分开存储、分开查询，不会混合为同一来源。`direct` 是估算值，因为系统接口包含链路/协议开销，而 V2Ray 是应用层计数。

应用级采集优先使用用户态 ETW。WFP 能提供更强的内核级识别和控制，但精确字节计数通常需要 callout 驱动、管理员安装和签名，不适合直接随 PySide6 热加载插件部署。未来可以用 WFP 服务替换 ETW 适配层，不影响上层模型和 UI。

## 历史窗口

SQLite 使用 WAL、短事务和唯一时间桶键。实时速率只保留在内存中；每秒快照会在内存合并，最多每分钟写入一次 SQLite。每条持久化值表示该分钟内的字节增量，聚合时直接求和，峰值单独保存。

| 表 | 粒度 | 保留时间 | 下采样目标 |
| --- | --- | --- | --- |
| `traffic_second` | 分钟写入点（兼容原表） | 1 小时 | 分钟 |
| `traffic_minute` | 分钟 | 24 小时 | 小时 |
| `traffic_hour` | 小时 | 30 天 | 天 |
| `traffic_day` | 天 | 365 天 | 淘汰 |

维护任务每分钟执行：先聚合已经闭合的时间桶，再删除超过窗口的数据。写入和聚合都具备唯一键约束，可在任务中断后重复执行。应用流量只在用户于设置中启用后才启动 ETW；未启用时既不加载 ETW 运行时，也不读取进程/连接信息。每次持久化最多保留 128 个活跃应用，其余合并为“其他应用”，因此磁盘增长有明确上界。

## 界面行为

- “实时流量”持续更新系统、V2Ray 和直连；应用列表仅在设置中启用“应用级流量”后更新。
- 应用列表支持总流量、下载、上传和应用名称排序；流量排序采用平滑分数和稳定次排序，短暂停流的进程会以 0 B/s 保留 5 秒，减少相邻进程反复换位或整行闪烁。
- 窄侧栏隐藏 PID/连接列，完整路径、PID 和连接数保留在应用名称提示中；宽布局显示全部五列。
- “历史趋势”打开期间约每 1.5 秒异步刷新，不需要切出页面再进入。
- 历史来源可单独选择系统、V2Ray、直连或应用合计；范围支持最近 1 分钟、1 小时、今天、7 天、30 天和 1 年，其中 1 年范围使用日级数据。
- 折线图分别显示上传和下载趋势，柱状图显示应用累计流量排行。

## V2Ray 配置

v2rayN 的 Xray Core 通常使用“本地混合端口 + 4”作为 Metrics 端口。例如本地混合端口为 `21189` 时，默认地址为：

```text
http://127.0.0.1:21193/debug/vars
```

需要在 v2rayN 中开启实时速度/流量统计并重启 Core。Metrics 地址只允许 loopback（`127.0.0.1`、`::1`、`localhost`），不能暴露到局域网或公网。可从项目根目录验证：

```powershell
python -m tools.check_v2ray_stats --port 21193 --count 10
```

V2Ray 采集模块预留了节点名称、实时延迟和路由字段。当前 Metrics 接口只负责流量；后续接入 v2rayN 管理接口时，可以独立补充这些元数据并按设置决定是否显示在悬浮窗。

## 悬浮窗

- 只创建一个悬浮窗，默认显示“代理 + 直连”。
- 可切换为“系统 + 直连”“系统 + 代理”或“系统 + 代理 + 直连”。
- 可控制是否显示 V2Ray 节点、延迟和路由元数据。
- 支持单行/双行、大小、字号、背景颜色、透明度、字体颜色、位置和鼠标穿透锁定。
- 显示开关和外观修改会立即应用；位置在拖动结束后保存。
