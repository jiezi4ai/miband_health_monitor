# Gadgetbridge 对标深度分析（暂只有中文版）

> **来源**：2026-11-19 对 [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge)（下称 GB）
> 与本项目的功能、数据链路、数据模型、UI/可视化、工程实践的系统性对标。
> **性质**：分析登记文档，不改变任何现有行为承诺；可落地的借鉴项整理为 §6 的建议表，
> 与 [improvement-plan.zh-CN.md](improvement-plan.zh-CN.md) 的既有条目显式联动，不重复登记。
> **2026-11-20 增补**：§7 为对全部结论的源码逐行核验结果（证实 / 证伪 / 需修正），
> §8 为据此给出的分阶段实施路线图；原"主要参考"顺延为 §9。
> **定位差异（贯穿全文的前提）**：GB 是 Android 上的"厂商 app 全面替代品"——用户每天随身
> 使用，它既是数据采集器、也是手环的宿主和遥控器；本项目是计算机侧的采集 / 分析 / 归档
> 工具。因此对标时把差距分为三类：**同链路可得**（同一条 BLE 链路就能拿到的数据）、
> **应用层缺口**（数据在手但没做出的分析/展示/自动化）、**定位不符**（属于"手环宿主"职责，
> 除非确有需求否则不跟）。

## 0. 方法与证据分级

> **2026-11-20 复核更新**：本节的"网络屏蔽"前提已经过时。复核时实测 `curl` 直连
> codeberg.org 返回 HTTP 200，并成功浅克隆 GB 全库（94 MB / 7356 文件，master HEAD
> `93d4d79`）到工作区外的本地克隆目录，对下文绝大多数结论完成了逐行核验。
> 核验结果登记于 **§7**：证实、证伪与需修正项均已列出，§6 建议表据此调整了落点与分档；
> **§8** 给出实施路线图。以下证据分级保留为分析当时的历史记录，不抹除。

本次分析（2026-11-19）当时的网络环境屏蔽了对 codeberg.org / github.com / gadgetbridge.org 的直接抓取
（DNS 解析为非公网地址），仅搜索通道可用（返回官方文档页与提交的 URL，无正文快照）。
因此每条 GB 结论按下表分级标注，诚实呈现证据边界：

| 标注 | 含义 |
|---|---|
| **[●] 仓内交叉验证** | 本仓库已直接核对过 GB 源码或实测过其行为：主要是 [investigations/sleep-fields.zh-CN.md](investigations/sleep-fields.zh-CN.md) §6（对 GB master `db00876` 的逐字段核对）与本仓库真机探测记录 |
| **[✓] 搜索确认** | 本次分析检索到对应的官方文档页 / 源文件 / 提交并附 URL；正文细节为页面主题级别，未逐字核验 |
| **[○] 模型知识** | 来自对 GB 这一知名开源代码库的既有了解；本环境无法逐行核验，一律以"约 / 据"措辞呈现，不作为可执行依据 |

另外，本仓库与 GB 的关系已有纪律性声明（README §7 / [architecture.md](architecture.md#6-third-party-and-compatibility-exemptions)）：
**GB 是 AGPL-3.0 的协议参考对象，本项目不复制其代码**。本分析延续同一纪律：以下所有
借鉴点均为**行为与模式**层面的学习，落地时是独立实现。

## 1. GB 的本质：三条设计主线

理解 GB「有什么、为什么这么设计」，比逐项罗列功能更重要：

1. **"free and cloudless" 作为产品哲学 [✓]**：GB 官方把
   [无互联网访问](https://gadgetbridge.org/basics/topics/internet/) 作为立身之本——数据全部
   落本地 SQLite，需要联网的仅有天气（由用户自选的天气 app 通过广播供给
   [✓](https://gadgetbridge.org/internals/development/weather-support/)）、Bangle.js 应用商店
   与可选的 [internet-helper 外挂](https://gadgetbridge.org/basics/integrations/internet-helper/)
   [✓]，且都以"用户显式选择"为前提。厂商云账号完全不接触。
2. **可插拔设备模型**：每种设备 = 一个 `DeviceCoordinator`（能力声明：支持什么数据、什么
   文件、什么设置）+ 一个 `DeviceSupport`（协议实现）+ 共用的 `BtLEQueue`（串行 GATT 队列）。
   官方 [new-gadget 教程](https://gadgetbridge.org/internals/development/new-gadget/) [✓]
   把这三件套作为接入新设备的标准路径，这是 GB 能覆盖上百个设备家族的根本原因。
3. **一切设备 I/O 经过单一前台服务**：`DeviceCommunicationService`（Android Service）
   持有全部连接与队列，UI（ControlCenter、图表页）与外部生产者（通知、天气、日历接收器）
   一律只发 intent，结果以广播回流 [✓ 文件
   `service/DeviceCommunicationService.java`](https://codeberg.org/Freeyourgadget/Gadgetbridge/src/branch/master/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/DeviceCommunicationService.java)。
   收益：BLE 生命周期与 UI 生命周期解耦、多生产者统一入口、外部 app 可经
   [intent API](https://gadgetbridge.org/internals/automations/intents/) [✓] 自动化而无需链接代码库。

本项目与这三条主线的关系：①隐私哲学上**已同路**（本地-only、`WEB_TOKEN`、隐私门禁
甚至更严）；②③则是**架构差距**所在，详见 §3。

## 2. 功能对标：GB 有而本项目没有的

### 2.1 同链路可得（同一台 Band 6、同一条 BLE 链路就能拉到的数据）

| 数据 / 能力 | GB 现状（证据） | 本项目现状 |
|---|---|---|
| 运动记录总结（类型 / 时长 / 心率区间等） | Huami 抓取框架含运动总结 / 详情操作（[抓取框架重构提交 58d4ebf509](https://codeberg.org/Freeyourgadget/Gadgetbridge/commit/58d4ebf509f2111f01a37cf6c067accac8061a1c) [✓]；详情抓取按运动自身时区对齐，[提交 #3592](https://codeberg.org/Freeyourgadget/Gadgetbridge/commit/4bfb7d4621) [✓]），解析为总结实体 + 结构化指标 [○]；[sports 功能页](https://gadgetbridge.org/basics/features/sports/) [✓] | 无——`workout/` 只有实时会话（[session.py](../miband_monitor/workout/session.py)），不抓手环侧运动记录 |
| 运动 GPS 轨迹 | 详情抓取含轨迹（对有 GPS 的设备），详情页自绘折线渲染（`ActivitySummariesGpsFragment` [✓ 文件](https://codeberg.org/azisanw/Gadgetbridge/raw/commit/4c7476845b466cdc8d2eb3275eaa89994ffadc1b/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/activities/ActivitySummariesGpsFragment.java)）；另有 OpenTracks 导出 [✓] | 无，且**已可确证不适用**：Band 6 无 GPS 硬件，GB 侧其运动记录同样不含轨迹 [✓]；带内是否产出总结记录仍需 `probe_fetch_types.py` 实测（见 §6 B-12） |
| 压力 / PAI / 睡眠呼吸率 / 每日最大心率 | GB 对 Huami 家族有成套的衍生健康指标抓取操作：stress 与背景 SpO₂（[提交 f68e4c865b](https://codeberg.org/Freeyourgadget/Gadgetbridge/commit/f68e4c865b)、持久化 23e9a3deb1）、睡眠呼吸率（[提交 3a5d5dfbb0](https://codeberg.org/Freeyourgadget/Gadgetbridge/commit/3a5d5dfbb0)、持久化 e55a35eced）、PAI（[提交 c79a833bbf](https://codeberg.org/Freeyourgadget/Gadgetbridge/commit/c79a833bbf)、持久化 a1e07b5d1b）、每日最大心率（[提交 9d966c8179](https://codeberg.org/Freeyourgadget/Gadgetbridge/commit/9d966c8179)）[✓]；仪表盘有压力专用卡片（`DashboardStressSimpleWidget` [✓]） | 无。**但**：本仓库真机探测显示 Band 6 对 `0x2c` 类抓取返回"接受、声明 0 条"（[investigations/sleep-fields.zh-CN.md](investigations/sleep-fields.zh-CN.md) §6.4 [●]），固件是否实际产出这些指标须先复测，不可照抄 GB 的能力矩阵 |
| 设备报告的每日汇总 | Zepp OS 系列有 `DailySummary` 实体（设备侧每日总结）[○] | 无；本项目按分钟数据自行汇总（路线不同，见 §4 的取舍讨论） |
| 电池状态事件化 | 电池为事件（`GBDeviceEventBatteryInfo` [○]）→ 广播 → UI/仪表盘 | 仅 `0x2A19` best-effort 读取（[battery.py](../miband_monitor/ble/battery.py)），不进看板、无低电提醒 |
| 下行配置：连续心率采样间隔、手环时间同步 | 首连初始化事务会下发校时（PineTime 示例 [✓ 源码](https://codeberg.org/Freeyourgadget/Gadgetbridge/blame/commit/b97b26ce3a19da8d384f95305f4900d155eb919a/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/pinetime/PineTimeJFSupport.java)）；Huami 系可设置心率测量间隔等 [○] | 无下行校时；心率靠标准 HR 服务 + 12 s 保活。**校时对本项目有实际意义**：历史数据用的是手环侧时间戳，手环漂移会直接扭曲分钟对齐 |
| 每设备可协商的抓取闸门 | `supportsSleepScore()` 等 Coordinator 闸门决定发不发某抓取请求 [●]（见 §3.3） | 无闸门概念，靠真机试探（`tools/probe_fetch_types.py`）积累事实 |

### 2.2 应用层缺口（数据或链路在手，但分析 / 展示 / 自动化没做）

| 能力 | GB 现状（证据） | 本项目现状 |
|---|---|---|
| 整库备份 / 恢复 | 全库 SQLite 导出导入 + [定时自动导出](https://gadgetbridge.org/internals/automations/auto-export/) [✓]；[数据管理文档](https://gadgetbridge.org/internals/development/data-management/) [✓] | 只有 CSV 导出（`export_csv.py`）；无备份/恢复命令、无定时导出 |
| 面向外部工具的标准化出口 | intent API 自动化契约 [✓](https://gadgetbridge.org/internals/automations/intents/)；[Sleep as Android](https://gadgetbridge.org/basics/integrations/sleep-as-android/) [✓]、[Health Connect](https://gadgetbridge.org/basics/integrations/health-connect/) [✓]、OpenTracks 导出 [✓] | 有本地 HTTP API / SSE，但无对外契约文档、无与既有生态（GPX、CSV 约定之外）的对接形态 |
| 日 / 周 / 月多粒度图表 | ChartsActivity 分页切换日 / 周 / 月（"Enable left/right swipe in the charts activity" 字符串 [✓]） | 实时看板（会话内）+ 离线看板（固定 7 天）两件套，无粒度切换 |
| 会话切分（从历史数据自动识别运动时段） | `StepAnalysis` 把按分钟样本切分为 ActivitySession，逐段给总结 [○] | 无；`workout/` 靠人工触发 |
| 睡眠得分卡 | 仪表盘睡眠得分卡片（`DashboardSleepScoreWidget` [✓ 文件](https://codeberg.org/bkcodeberg/Gadgetbridge/src/commit/3fbbfd6900bc720d9c518a6086ec55921878cd64/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/activities/dashboard/DashboardSleepScoreWidget.java)） | 有睡眠效率 / 深睡占比 KPI，无综合得分语义 |
| 多语言界面 | Weblate 社区翻译（[项目页](https://hosted.weblate.org/projects/freeyourgadget/gadgetbridge/) [✓]） | 看板标签仅简体中文（README 已自我声明） |

### 2.3 定位不符（"手环宿主"职责，除非确有需求不跟）

通知转发（[notifications](https://gadgetbridge.org/basics/features/notifications/) [✓]）、来电与
快捷回复（[calls-replies](https://gadgetbridge.org/basics/features/calls-replies/) [✓]）、天气（JSON over chunked2021，[`Huami2021Weather.java`](https://codeberg.org/Freeyourgadget/Gadgetbridge/src/commit/93449b1fea7b1d9f20be2aae1501e75d75bbaa6e/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huami/Huami2021Weather.java) [✓]） /
日历 / 闹钟下发、找手机、音乐控制、固件侧载 / AGPS 更新
（[huami-gps](https://gadgetbridge.org/internals/topics/huami-gps/) [✓]；Band 6 的固件更新 GB 亦支持，[提交 cbadb9c7](https://codeberg.org/Freeyourgadget/Gadgetbridge/commit/cbadb9c7aee605dc6b5539c02865e3bfe57bb3bf) [✓]）、表盘与应用安装
（[Bangle.js](https://gadgetbridge.org/gadgets/wearables/banglejs/) [✓]）——这些都是"替代厂商
app 日常宿主"的职责。本项目作为计算机侧监测器，默认不做；其中通知 / 天气 / 校时若用户
提出，属于"下行能力"开发项（§6 B-15 / B-10）。GB 覆盖数百种设备 / 上百个家族
（[gadgets 索引](https://gadgetbridge.org/gadgets/) [✓]；总数无官方数字，约数百 [○]）、
自 0.68.0 支持多设备同时连接（[release 0.68.0](https://gadgetbridge.org/blog/release-0_68_0/) [✓]）
——对本项目属于**远期形态**问题：Band 7/8 及新小米手表已换 Zepp OS / protobuf 协议
（[zeppos](https://gadgetbridge.org/basics/topics/zeppos/) [✓]、
[xiaomi-protobuf](https://gadgetbridge.org/basics/topics/xiaomi-protobuf/) [✓]），若未来扩展
设备面，GB 的 Coordinator/Support/Queue 抽象就是现成的演进路线图。

### 2.4 反向对照：本项目已领先或 GB 同样没解决的

对标应当双向诚实，以下事实避免"GB 一切都好"的错觉：

1. **睡眠三字节，GB 也没解开**：`sleep`/`deep_sleep`/`rem_sleep` 三列，GB 的处理是
   `& 127` 后与任意阈值（REM>55 / 深睡>42）比较，作者自注 *"thresholds are arbitrary … not
   accurate"*；本仓库已证明这些常量是从其它机型拟合的、对 Band 6 明显失真
   （[investigations/sleep-fields.zh-CN.md](investigations/sleep-fields.zh-CN.md) §6.3 [●]）。
2. **Band 6 无固件侧睡眠会话**：`0x48` 返回 0 条，GB 也不对 Band 6 请求它
   （`HuamiFetcher` 的 `supportsSleepScore` 闸门默认 false [●]）——两家都只能靠推导。
   GB 侧同时确认：含 REM 的睡眠分期与得分仅 Zepp OS 设备经 protobuf 提供
   （[提交 849a7dc996](https://codeberg.org/Freeyourgadget/Gadgetbridge/src/commit/849a7dc9965ee6835e4bb49473a69d9f7716d9de) [✓]），与仓内结论互证。
3. **0x26 整夜血氧**：上游 GB 对 `duration`/尾部字节仍标 `TODO save`
   （[validation/history-hardware.zh-CN.md](validation/history-hardware.zh-CN.md) [●]），本项目
   已真机验证 30 B 布局并整夜落库。
4. **测试工程**：GB 的自动化测试规模有限，长年依赖真机社区测试 [○]；本项目
   "仿真手环 + 390+ 免硬件测试 + 三平台 CI" 反而是更强项，应保持而非照搬 GB。
5. **原始 IMU 流**：GB 不做 Band 6 的 25 Hz 原始加速度流（这是科研向能力），本项目独有。

## 3. 代码实现与数据链路：值得借鉴的六件事

### 3.1 BtLEQueue：单队列 + 事务串行化（本项目已自知缺口）

GB 的 GATT 操作模型 [✓ 文件
`service/btle/BtLEQueue.java`](https://codeberg.org/Freeyourgadget/Gadgetbridge/src/branch/master/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/btle/BtLEQueue.java)：
一个专用队列线程 + `Transaction`（有序的读/写/订阅动作组，`TransactionBuilder` 流式组装）；
每个动作发出后线程在锁上等待对应 GATT 回调再走下一步；连接 / 断开也走同一队列，与业务
操作不竞态；任一动作失败即中止整个事务；链路级错误清空队列并（若开自动重连）循环重试
（有界固定间隔，非指数退避）[○]。

**对本项目的意义**：本仓库已经把"引入类 GB BtLEQueue 机制"列为已知改进项
（[guides/cross-platform.zh-CN.md](guides/cross-platform.zh-CN.md) §2.5"GATT 写锁"行）。当前
`ble/link.py` 的写路径靠 `_gatt_lock` 与重试散点防护，属"够用但不成体系"；GB 的启示是
**事务语义**（一组相关动作要么按序全做、要么干净中止）比"每处加锁"更能压制跨平台栈的
时序怪癖（BlueZ `InProgress`、WinRT 队列重入等）。

> **复核（2026-11-20，见 §7.2）**：事务语义、`CountDownLatch` 等 GATT 回调闩锁、单动作失败
> 中止整个事务、链路错误清队列均属实；但本节两处 `[○]` 结论被源码证伪——重连是**有上限的
> 指数退避**（`AutoConnectIntervalReceiver.java` 明写 `mDelay*2`、封顶 64s），并非"固定间隔、
> 非指数退避"；连接/断开走 `mGattMonitor` 锁 + `mConnectionLatch`，**不在**事务队列内。
> 另：`_gatt_lock` 实际定义在 `ble/client.py:151`，不在 `ble/link.py`（B-5 落点需修正）。

### 3.2 FetchSession 框架化：把"抓取"变成一个模板

GB 把 Huami 的历史抓取统一成 AbstractFetchOperation 模板：带时间戳的初始化请求 → 计数/
长度协商 → 分块回传 + 逐块确认 → 进度事件 → 完成帧 ACK → 错误恢复，各数据类型只在
"解析回调"与"类型号"上不同 [○]。本项目的 `history/fetcher.py` + `sync.py` 实现了同样的协议
阶段，但按数据类型各写一套；若未来加运动 / stress / PAI 抓取（§2.1），先抽一个
`fetch_session` 模板（init → chunk → complete → ack 的状态机 + 进度回调），新类型只写解析器。
这与现有 `BandHistoryFetcher` 的"一轮抓取"边界天然吻合，重构不必改行为。

同一框架还有一条**数据完整性细节**值得记录：GB 把"上次同步到的时间"存为设备偏好，并给
用户一个可重置的 fetch time 入口（[issue #3091 "set fetch time"](https://codeberg.org/Freeyourgadget/Gadgetbridge/issues/3091)
[✓]）；其抓取代码注释明言——初始化请求的命令字节选择不当，手环会丢弃明细且不再重发 [✓]。
对本项目的含义：任何将来的"定时历史同步"都应有显式的 lastSync 记录与用户可重置手段，
并谨慎对待抓取命令字节；这正好并入 §6 B-1 的能力闸门表。

### 3.3 能力闸门：Coordinator 的 supports*() 模式

GB 对每台设备有一层能力声明（`supportsActivityDataFetching` / `supportsSleepScore` / …），
协议层据此决定"发不发某请求"[○]。**本项目已经吃过没有这层闸门的亏**：真机探测 `0x48` /
`0x2c` 均返回"接受、声明 0 条"（[investigations/sleep-fields.zh-CN.md](investigations/sleep-fields.zh-CN.md)
§6.4 [●]），而 GB 靠 `MiBand6Coordinator` 不覆写 `supportsSleepScore()` 就避免了这次空抓。
落地形态不必是 GB 那样的接口体系：一张"Band 6 已验证能力表"（哪些抓取类型有数据、哪些
探测过为空、探测日期）放进 `history/protocol.py` 常量区或配置，`sync_history` 据此跳过已知
空类型，比运行时反复试探更诚实。

### 3.4 设备级状态机 + busy 语义 + 事件总线

GB 的 `GBDevice.State`（NOT_CONNECTED → CONNECTING → CONNECTED → INITIALIZING →
INITIALIZED）+ 独立 busy 任务锁（"fetch activity data"这类人类可读的占用标记）+ 每次状态
变化以 `ACTION_DEVICE_CHANGED` 广播 [○]。带→手机方向，协议解码出的 `GBDeviceEvent*`
（电池、版本、找手机、音乐控制…）统一经 `handleGBDeviceEvent` 分发
（[✓ `service/AbstractDeviceSupport.java`](https://codeberg.org/Freeyourgadget/Gadgetbridge/raw/commit/fea3bf50a4747e4be21daf7deaa5f1ea8f9c8936/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/AbstractDeviceSupport.java)）。

本项目现状：认证有状态机（`ble/auth_state.py`），但设备整体生命周期状态散在 CLI 日志与
`cli/runner.py` 里；电池 / MTU / 版本等"事件"只进日志不进数据面。借鉴价值：一个
`DeviceEvent` 小类型（电池 / 连接 / 重新连接计数）+ `cli/callbacks` 转发到 `TelemetryHub`，
看板就能显示电量与链路状态——链路是本项目用户排障的第一关注点，让它可见是纯收益。

### 3.5 首连初始化事务：一次有序下发

GB 首连后的 INITIALIZING 阶段是一个事务：校时（PineTime 示例 [✓ 上文 URL]）、语言、
请求版本 / 电池、必要时刷天气 [○]。对本项目，最有价值的一条是**校时下行**：历史抓取的
时间戳全部以手环时钟为准（[guides/data-formats.zh-CN.md](guides/data-formats.zh-CN.md) 的时间
语义），而项目侧没有任何机制管手环漂移。若真机验证可行，"连接成功后把手环时间校准到
计算机时钟"是花小钱防大歪的事（§6 B-10，需先真机确认 Band 6 的校时写入格式；另注意**新固件把部分旧 chunked
   消息类型（音乐 / 天气 / 设置）迁到了 chunked2021 通道**——[提交 4242f5ccd4](https://codeberg.org/Freeyourgadget/Gadgetbridge/commit/4242f5ccd4426891dc6333cca7049ec4a12b13ea)、
   [提交 b99da8b596](https://codeberg.org/Freeyourgadget/Gadgetbridge/commit/b99da8b596) [✓]，
   任何下行开发前须先判明手环固件代际）。

### 3.6 数据模型：存原始值、读时归一化、gap 显式化

GB 的样本模型是"存储原始 + 读取归一化"：每设备一张按分钟样本表（`HuamiExtendedActivitySample`
含 `unknown1/sleep/deepSleep/remSleep` 等原始列，与本项目 8 B/分钟布局逐字段一致 [●]），
归一化（rawKind 低四位 → `ActivityKind` 统一枚举：activity/light/deep/REM/not-worn）在各设备
的 SampleProvider 读取时完成，且查询区间会**补齐为显式 unset 样本**，图表层因此能把
"没有数据"与"0 数值"画成两种东西 [○]。

对本项目的映射：本项目已经存原始列（`history/parsers.py` 产出的 `kind,intensity,steps,
heart_rate,unknown1,sleep,deep_sleep,rem_sleep`），但 kind→语义的映射散在
`sleep/constants.py`、离线看板与文档三处。集中成一个 `ActivityKind` 式常量表 + 单一映射
函数（含"不佩戴"这个一等公民——本仓库正是通过 GB 源码核对才把 `0xF3` 判为不佩戴 [●]），
后续新数据类型接入时语义就不会漂移。

> **复核（2026-11-20，见 §7.2/§7.3）**：8 B/分钟字段布局逐字段一致、`fillGaps()` 显式 unset
> 补齐均属实；但两处需修正——其一，`rawKind` **没有**"低四位"掩码（`getKind()` 直接
> `normalizeType(getRawKind())`，且 REM=`0x01000000` 无法用 4 位表示）；其二，本项目的 kind
> 单点判定其实已存在于 `sleep/samples.py:47-80`（`kind_code`/`is_nonwear`/`is_sleep_kind`），
> B-9 应是"把离线看板的 `BAND_*` 与 JS 着色收敛到该单点"，而非从零建映射。

## 4. UI、数据可视化与数据理解

### 4.1 多粒度 + 同轴时间轴

GB 图表页（`activities/charts/`，[✓ `AbstractChartFragment`](https://codeberg.org/Freeyourgadget/Gadgetbridge/src/commit/89bc1d8a7d40ae7f6511077166a5ee91828d1c42/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/activities/charts/AbstractChartFragment.java)）
以日 / 周 / 月粒度切换，同一条时间轴上叠：步数柱（含强度着色）+ 心率线 + 按睡眠分期
着色的色带；缺口一律渲染为 unset/透明而非补零 [○]（渲染库为 MPAndroidChart 的自定义
子类 + 自绘睡眠视图 [○]，细节本环境未能逐行核验）。

本项目离线看板已有正确的缺口纪律（"按真实时间戳定位、SpO₂ 断档不虚构线段、心率缺失
画灰带"），缺的是**粒度选择**（现固定 `--days 7`）与**同轴叠加**。落地建议：`--days`
之外加 `--range day|week|month` 语义档位；活动柱 + 心率线 + 睡眠色带同轴渲染（睡眠色带
代码 `offline_dashboard/svg.py` 已具备，只差叠到活动图上）。

### 4.2 睡眠 hypnogram 与"未知"着色

GB 的 `SleepDetailsView` 把深睡 / 浅睡 / REM / 清醒画成分钟级色段，未佩戴与未知各有
独立颜色 [○]。本项目 hypnogram 色带（`svg.py` 游程压缩）结构同构，但缺 REM 通道
（Band 6 数据源本身无 REM，本仓库已证明 [●]）。可借鉴的不是加 REM，而是**把
"不佩戴 / 无数据"在色带中显式上色**，替代现在的整段留白——阅读者一眼区分"没戴"与
"没同步"。

### 4.3 KPI 卡片化与可配置时间范围

GB 仪表盘是卡片化的（步数、睡眠时长、睡眠得分、压力、HRV、组合目标卡，各卡可点入
详情、可选 today/yesterday/week 范围；REM 在 today 卡上单列——
[✓ 提交 "Display REM sleep separately"](https://codeberg.org/Freeyourgadget/Gadgetbridge/commit/5320b095fa67b2d396a07d67b3c1a684d60c151f)）。
本项目 `offline_dashboard/kpis.py` 的 KPI 是固定"最近一夜 + 汇总"语义。借鉴点：让每张 KPI
带时间范围参数（昨晚 / 7 天均值 / 全库），并把 4.1 的粒度切换与 KPI 范围联动。

### 4.4 会话切分：把"每天的活动"切成有意义的段

GB 的 `StepAnalysis` 在读取时把分钟样本切成 ActivitySession（含自动识别的运动段），
每段给出起止、步数、强度总结 [○]。对本项目这是**数据理解层面**最有价值的一条：
`activity_history` 已经有每分钟强度与步数，但"今天我几点到几点在快走"这种问题现在
只能靠肉眼看柱状图。一个按强度阈值 + 连续性切分的纯函数（放 `reports/` 或
`offline_dashboard/collect`），既能出"当日活动节律"卡片，也能为将来的运动记录抓取
（§6 B-12）提供对齐基准。

### 4.5 数据理解的诚实性：两家同路，GB 的自适应思路值得吸收

本仓库与 GB 在"睡眠分期是推导值"上态度一致：GB 的 `SleepStageEstimator`（Kotlin）文件头
自注 *"a heuristic without ground truth"*，机制为——清醒/睡眠用 Cole-Kripke 权重 + Webster
重评分，分期用**心率相对滚动基线的偏移** + HRV + 时间先验（深睡前半夜、REM 后半夜）+
运动惩罚，最后以"深睡 10–25%、REM 15–30%"的比例闭环自适应阈值 [●]（仓内核对自
[investigations/sleep-fields.zh-CN.md](investigations/sleep-fields.zh-CN.md) §6.5）。

这正是 improvement-plan **R-4** 既定的算法升级方向（滚动基线偏移代替全局分位 + 比例闭环），
GB 的实现提供了"闭环目标区间 + 时间先验"两个本项目尚未纳入的成分。落地即 R-4 第 2 步，
无需新立项。

### 4.6 运动详情页的零依赖渲染

GB 的运动 GPS 详情是**自绘 canvas 折线**（无地图瓦片、无外部地图库 [○]，另有镜像称部分
实现用 osmdroid，本环境未核验），配速/速度曲线复用同一套图表代码 [○]。这与本项目
"零 web 框架依赖、单文件离线 HTML"的哲学完全同构：若 §6 B-12 落地，轨迹渲染应当延续
`offline_dashboard` 的自绘 SVG 路线，而不是引入地图库。

## 5. 其它值得学习

1. **隐私作为品牌而非附录**：GB 官网与 README 把 "free and cloudless" 放在标题里，
   [internet 专页](https://gadgetbridge.org/basics/topics/internet/) 逐条说明哪些功能才需要
   联网 [✓]。本项目的隐私实践（本地-only、0600、占位符纪律、`check_privacy` 门禁）实质
   更严，但表达方式是"安全摘要 + 隐私指南"。启示是叙事层面的：把"数据不出本机"提炼为
   README 首屏卖点。
2. **面向用户的能力矩阵页**：[gadgetbridge.org/gadgets/](https://gadgetbridge.org/gadgets/)
   让用户在接入前就知道"我的设备能做什么" [✓]。本项目的对应物是
   [guides/cross-platform.zh-CN.md](guides/cross-platform.zh-CN.md) 的验证矩阵 + §6 B-1 的
   能力闸门表——两者合并即是本项目的"gadgets 页"。
3. **增量接入的社区工程**：GB 靠 Coordinator/Support 三件套 + [new-gadget 教程](https://gadgetbridge.org/internals/development/new-gadget/) [✓]
   把"支持一个新设备"的门槛降到社区可参与；CHANGELOG 纪律、Weblate 翻译、CalVer 版本
   （[2026.11.0 发布](https://gadgetbridge.org/blog/release-2026_11_00/) [✓]）都是长寿命
   项目的公共经验。本项目单设备单维护者，现阶段更受用的是其**文档即证据**的对应物——
   本仓库的 validation/investigations 体例已与之相当，保持即可。
4. **发现 / 配对体验的重写历史**：GB 0.72.0 曾整体重写设备发现
   （[release 0.72.0](https://gadgetbridge.org/blog/release-0_72_0/) [✓]）——配对与发现是
   BLE 工具的用户第一痛点，值得持续投资。本项目 `--doctor` / `live_scan` /
   [guides/faq.zh-CN.md](guides/faq.zh-CN.md) 的排障体系已在正确的路上。
5. **自动备份**：GB 的 [定时自动导出](https://gadgetbridge.org/internals/automations/auto-export/) [✓]
   值得直接吸收：SQLite 单文件 + WAL 的备份就是"安全拷贝 + 校验"，加一个
   `--backup PATH` 或 tools 脚本（含保留 N 份的轮换），成本约一个小脚本。
6. **多设备是远期解药**：Band 6 之后的设备已换协议族（Zepp OS / protobuf [✓ 上文]）。若
   项目有设备扩展预期，§3 的四件抽象（能力闸门、抓取模板、状态机、事件总线）加上
   `ble/backends.py` 现有注入边界，就是"下一个设备接入时不重写"的保险。

## 6. 借鉴优先级建议表

> 量级：小 ≈ 单文件 ≤300 行内完成；中 ≈ 跨 2–3 模块或有真机验证依赖；大 ≈ 新数据链路。
> 与 [improvement-plan.zh-CN.md](improvement-plan.zh-CN.md) 的关系：B-3 即 R-4 第 2 步，
> 不重复登记；其余为候选新条目，采纳时按 R-登记簿体例入册。
>
> **复核修订（2026-11-20，依据 §7）**：下表已按源码核验结果就地修正 3 处落点——
> B-5 落点从 `ble/link.py` 改为 `ble/client.py`/`streams.py` 之上；B-6 从"新抽模板"改为
> "在现有 `fetch_payload` 上补进度/错误恢复/解析器插拔"；B-14 从"新建电池通道"改为
> "把已有 workout 电量路径提升为通用 series 并覆盖默认会话"。分档结论见 §7.4，
> 执行顺序见 §8。

| 编号 | 借鉴点 | GB 对应 | 本项目落点 | 量级 | 优先级 |
|---|---|---|---|---|---|
| B-1 | Band 6 能力闸门表（抓取类型白名单，含"已探测为空"记录） | Coordinator `supports*()` | [history/protocol.py](../miband_monitor/history/protocol.py) + `sync.py` | 小 | P1 |
| B-2 | `schema_version` + 显式迁移函数 | GreenDAO `GadgetbridgeUpdate_NN` | [storage/schema.py](../miband_monitor/storage/schema.py) | 小 | P1 |
| B-9 | kind→语义统一常量表 + 单点映射 | `ActivityKind` / SampleProvider | [history/parsers.py](../miband_monitor/history/parsers.py) + [sleep/constants.py](../miband_monitor/sleep/constants.py) | 小 | P1 |
| B-3 | 滚动基线 + 比例闭环的睡眠分期 | `SleepStageEstimator` | [sleep/classification.py](../miband_monitor/sleep/classification.py) | 中 | P1（=R-4 第 2 步） |
| B-14 | 电池 / 链路事件进数据面与看板 | `GBDeviceEventBatteryInfo` | [ble/battery.py](../miband_monitor/ble/battery.py) + [cli/workout_runner.py](../miband_monitor/cli/workout_runner.py) 已有路径 → 提升为通用 series + 覆盖默认会话 | 小 | P2 |
| B-11 | 整库备份 + 定时自动导出 | auto-export | `tools/` 新脚本或 CLI 参数 | 小 | P2 |
| B-10 | 连接后校时下行（先真机确认写入格式） | 首连初始化事务 | `ble/` 新命令 + `cli/runner.py` | 小-中 | P2 |
| B-4 | 设备级状态机 + busy 语义 | `GBDevice.State` | `ble/` + `cli/runner.py` | 中 | P2 |
| B-5 | GATT 事务化串行队列 | `BtLEQueue`/`Transaction` | [ble/client.py](../miband_monitor/ble/client.py)（锁所在）+ `streams.py`/`chunked.py` 之上（非 `link.py`） | 中 | P2 |
| B-6 | FetchSession 增强（进度回调 + 错误恢复 + 解析器插拔，为 B-12/B-13 铺路） | AbstractFetchOperation | [history/fetcher.py](../miband_monitor/history/fetcher.py) 现有 `fetch_payload` 统一模板上扩展 | 中 | P2 |
| B-7 | 日 / 周 / 月粒度 + 同轴叠加 + "不佩戴"显式着色 | ChartsActivity | [offline_dashboard/](../miband_monitor/offline_dashboard/) | 中 | P2 |
| B-8 | KPI 卡片可配置时间范围 | DashboardFragment widgets | [offline_dashboard/kpis.py](../miband_monitor/offline_dashboard/kpis.py) | 小-中 | P2 |
| B-12 | 运动总结抓取（Band 6 已确证不含 GPS 轨迹；总结记录产出仍需 `probe_fetch_types.py` 验证） | Workout fetch ops（[抓取框架提交 58d4ebf509](https://codeberg.org/Freeyourgadget/Gadgetbridge/commit/58d4ebf509f2111f01a37cf6c067accac8061a1c) [✓]） | `history/` 新类型 + `workout/` | 大 | P3 |
| B-13 | stress / PAI / 睡眠呼吸率 / 每日最大心率抓取（同上先探测；`0x2c` 曾返回 0 条） | stress / PAI / respiratory-rate / max-HR fetch ops（提交见 §2.1 [✓]） | `history/` | 大 | P3 |
| B-15 | 通知 / 天气等下行（仅在用户提出时评估） | externalevents 系列 | `ble/` 下行通道 | 大 | P3（暂缓） |

## 7. 源码逐行核验结果（2026-11-20）

> **性质**：本节是对 §0 证据分级的实际升级——把当时只能标 `[○]/[✓]` 的结论，用真实源码
> 逐行核对。方法：`curl` 直连 codeberg 成功（HTTP 200），浅克隆 master HEAD `93d4d79`
> 到工作区外的本地克隆目录（94 MB / 7356 文件），两路独立核对 GB 侧结论与本项目侧
> 现状描述。**未改动任何源码**。提交哈希类引用因浅克隆只有一个提交而无法核验，标"无法核验"
> 而非"证伪"。

### 7.1 完全证实（零偏差，可放心作为蓝本）

| 结论（原文位置） | 核验证据 | 状态 |
|---|---|---|
| §4.5 睡眠算法全套：Cole-Kripke 权重、Webster 重评分、滚动基线偏移 + HRV、时间先验、运动惩罚、比例闭环 | `util/sleep/SleepStageEstimator.kt`：7 个 Cole-Kripke 权重、`DEFAULT_PASSES=3`、`baselineHalf=45`、`variabilityWeight=0.5f`、`deepPriorSlope=-1.0f`/`remPriorSlope=1.2f`、`deepShareMin=0.10f`/`Max=0.25f`、`remShareMin=0.15f`/`Max=0.30f`；"heuristic without ground truth" 自注在 L111 | 逐数字精确一致 |
| §3.2 抓取框架六阶段 + lastSync 偏好 + 重置入口 | `AbstractFetchOperation.java` 的 init/长度协商(counter+1)/逐块确认/进度/ACK(0x01 删除、0x09 保留)/CRC；`saveLastSyncTimestamp()` 写设备偏好；`OtherDebugFragment.kt` 可重置 | 属实 |
| §3.3 能力闸门：`supportsSleepScore` 基类默认 false，MiBand6 不覆写 → 不请求 0x48 | `AbstractDeviceCoordinator.java:1150` 默认 false；`MiBand6Coordinator` 通篇无覆写；`HuamiFetcher.java:101` 以该值作闸门，`HuamiFetchDataType.SLEEP_SESSION(0x48)` | 属实，含完整因果链 |
| §2.4 睡眠三字节 `&127` + `REM>55`/`深睡>42` + "arbitrary…not accurate" 自注 | `HuamiExtendedSampleProvider.java:125-142` 逐字吻合（为 fallback 路径；有睡眠会话时设备数据优先覆盖） | 属实 |
| §2.1 stress/SpO2/呼吸率/PAI/每日最大心率 fetch 操作类 | `operations/fetch/` 下 `FetchStressAuto/ManualOperation`、`FetchSpo2SleepOperation`、`FetchSleepRespiratoryRateOperation`、`FetchPaiOperation`、`FetchHeartRateMaxOperation` 全部存在（另有 HRV/温度等 20+ 类） | 属实 |
| §1 单一前台服务 + intent API；§4.1 日/周/月切换字符串与按钮；§4.4 `StepAnalysis` 切分会话；§2.2 整库备份/auto-export/Sleep as Android/Health Connect/OpenTracks | `DeviceCommunicationService.java`（1213 行，前台服务 + 广播回流）；`ActivityChartsActivity.java:261-274` + `strings.xml:1583`；`StepAnalysis.java:41-45`；`util/backup/`、`PeriodicExporter.kt`、`externalevents/` 下各集成 | 属实 |
| §3.4 设备 State 机 + busy 标记 + 事件分发 | `GBDevice.java` 状态枚举（比文档更丰富）、`setBusyTask`/`isBusy()`、`ACTION_DEVICE_CHANGED`；`AbstractDeviceSupport.handleGBDeviceEvent()`；`devices/deviceevents/` 20+ 事件类 | 属实 |
| §2.3 0.68.0 多设备同时连接 | `CHANGELOG.md:2086` 明载；`AbstractBTLEMultiDeviceSupport` 的 `mQueues[deviceIdx]`；每设备一队列/线程 | 属实（提交号无法核验，CHANGELOG + 源码证实） |

### 7.2 被证伪 / 需修正的 GB 结论

| 文档结论（标注） | 核验结果 | 影响 |
|---|---|---|
| §3.1 重连"有界固定间隔、非指数退避"[○] | **证伪**：`AutoConnectIntervalReceiver.java:114-116` 注释 "Exponential backoff with a limit of 64 seconds"，`mDelay = Math.min(mDelay * 2, 64000)` | 不可照抄"固定间隔"；正确策略是有上限指数退避 + 立即重连分支 |
| §3.1 "连接/断开也走同一队列"[○] | **证伪**：`connect()`/`disconnect()` 走 `synchronized(mGattMonitor)`，不入 `mTransactions`；派发线程靠 `mConnectionLatch` 等待 | 借鉴时应描述为"独立锁 + 闩锁与业务串行化" |
| §3.6 "rawKind 低四位 → ActivityKind"[○] | **证伪**：`AbstractActivitySample.getKind()` 无掩码，直接 `normalizeType(getRawKind())`；`REM_SLEEP=0x01000000` 超出 4 位。归一化在各 Provider 完成则属实 | 落地用完整 code 常量表，勿假设低四位 |
| §3.6 "每设备一张样本表" | 概念属实，实为**共享表 + `device_id` 列** | 表述修正，不影响借鉴 |
| §2.2 Zepp OS `DailySummary` 实体[○] | **找不到**：仅 `service/devices/xiaomi/activity/impl/DailySummaryParser.java`（Xiaomi 文件解析器） | 不可据此声称 GB 有该实体 |
| §2.2 图表把"无数据/0"画成两种颜色[○] | 部分证实：`fillGaps()` 的 unset 补齐属实，但 `StagesRenderer.kt` 是 `row=-1 → continue` **留白跳过**，非独立颜色 | 视觉惯例按"未知=不绘制"理解 |
| §2.2/§4.6 多个类名 | `DashboardStressSimpleWidget`/`DashboardSleepScoreWidget` → 实为 `StressWidget.kt`/`SleepScoreWidget.kt`；`SleepDetailsView` → `StagesRenderer.kt`；`ChartsActivity` → `ActivityChartsActivity`；`ActivitySummariesGpsFragment` → 找不到，实为 `WorkoutGpsFragment.kt` | 引用类名需更正 |
| §4.6 "canvas 自绘而非地图库"[○] | 部分属实：自绘 Canvas 图表确实大量存在（`StagesRenderer`/`MiniChartView` 等），但底座是 MPAndroidChart，且地图库/地图集成并存 | "而非地图库"属过度概括 |

### 7.3 本项目现状描述的偏差（影响"是否重复造轮子"）

15 项逐条核对结果：**8 项属实**（B-2/B-10/B-11/B-7/B-8/B-12/B-13 + §2.4 交叉验证基础）、
**7 项部分属实**（B-1/B-3/B-4/B-9/B-14/B-5/B-6）。对建议成立影响最大的三处：

| 编号 | 文档现状描述 | 源码实际 | 修正后的建议 |
|---|---|---|---|
| **B-6** | `fetcher.py` 按类型各写一套、无统一模板 | **不符**：`BandHistoryFetcher.fetch_payload:201-296` 已是统一 init→metadata→chunk→CRC→ack→close 模板，三种类型共用，仅 `data_type` 不同；只缺显式进度回调与错误恢复闭环 | 不新抽模板，在现有模板上补进度/错误恢复 + 解析器插拔化 |
| **B-14** | 电池只进日志、不进看板 | **不符**：`workout_runner.py:80-99` 已有 `run_battery_probe()` → `record_battery()` → `hub.publish_workout()` 路径，workout 看板显示 `battery_pct` | 把电量从 workout snapshot 提升为独立 series，覆盖默认（非 workout）会话——后者目前根本不读电池 |
| **B-5** | `_gatt_lock` 在 `ble/link.py` | **文件归属错**：`link.py` 无锁；`_gatt_lock` 在 `client.py:151`，用于 `streams.py`/`battery.py`/`auth_connect.py`/`auth_handshake.py` | 落点改为 `client.py`/`streams.py`/`chunked.py` 之上 |

其余部分属实项的修正要点：B-1 的 0x48 已以常量注释形式事实跳过、`sync.py` 有三个布尔开关，
宜升级为带探测日期的结构化白名单；B-9 的 kind 单点判定已在 `sleep/samples.py`，应收敛
`offline_dashboard/constants.py` 的 `BAND_*` 与 `history_charts.js` 的 `code===3` 着色；
B-3 当前是"每夜自身分布内的静态分位"（非文档所说"全局分位"），已有 ±7 分钟滚动 SD；
B-13 "无每日最大心率抓取"≠"完全无 max HR"——实时 workout 有会话级 max HR。

### 7.4 分档结论

- **可直接采纳（依据扎实，6 项）**：B-2、B-3、B-7、B-8、B-10、B-11。其中 B-10 校时有实据——GB 的 `HuamiSupport.setCurrentTime()` 写标准 `CURRENT_TIME` 特征，而本项目已读标准服务，但写入字节格式（`getTimeBytes(TimeUnit.SECONDS)`）须真机确认。
- **方向成立、需修正落点（6 项）**：B-1、B-4、B-5、B-6、B-9、B-14。
- **证据弱 / 暂缓（3 项）**：B-12（Band 6 运动总结产出未确证）、B-13（`0x2c` 曾返回 0 条）、B-15（定位不符，文档已暂缓）。

**两个必须注意的前置依赖**：
1. **B-3 = 改进计划 R-4 第 2 步**，而 R-4 总览明确"算法升级待 ≥3 夜数据"——可行性被样本量卡住；且 Band 6 无 REM 数据源，GB 比例闭环的 REM 部分不适用，照搬会引入伪指标。
2. **B-12/B-13 的量级"大"含真机验证依赖**，手环侧是否产出总结/衍生指标未经证实，不可用"GB 有"直接推断"Band 6 有"（本项目 `0x2c`/`0x48` 均曾返回"接受、声明 0 条"）。

## 8. 建议实施路线图

> **前提**：[improvement-plan.zh-CN.md](improvement-plan.zh-CN.md) 的 R-1~R-8 已全部闭环或流程固化
> （截至 2026-11-19），本路线图是接在其后的下一批工作。按"先消除事实错误 → 快赢 → 架构安全网 →
> 数据理解 → 验证驱动"排序，每个阶段可独立验收。量级沿用 §6 定义（小 ≈ 单文件 ≤300 行、
> 中 ≈ 2–3 模块或含真机验证、大 ≈ 新数据链路）。

### 阶段 0：先修正事实基线（半天，零代码）

| 动作 | 目的 | 产出 |
|---|---|---|
| 按 §7.2 更正正文被证伪描述；按 §7.3 修正 B-5/B-6/B-14 落点 | 避免后续按错误落点施工、重复造轮子 | 本文已就地更新完成 |
| 核实 `data/zepp_nights.json` 当前夜数与 `device` 字段完备性 | 决定 B-3 是否解锁 | 夜数清单；<3 夜则 B-3 保持挂起 |
| 用 `tools/probe_fetch_types.py` 复测 `0x2c`/运动总结类型 | 决定 B-12/B-13 是否启动 | 带日期的探测记录 → 并入 B-1 白名单 |

> **阶段 0 已执行（2026-11-20）**，原始证据与闸门结论见
> [validation/gadgetbridge-gate0.zh-CN.md](validation/gadgetbridge-gate0.zh-CN.md)：
> `data/zepp_nights.json` 不存在（0 夜）→ **B-3 挂起**；`0x2c` 探测为空 → **B-13 挂起**；
> `0x05 SPORTS_SUMMARIES` 探测非 0 条（declares 320，真实时间戳）→ **B-12 解锁**（仍依赖 B-5→B-6 架构链）。
> 落点纠错三处（B-5/B-6/B-14）已与源码逐行核实一致，正文无需再改。

### 阶段 1：快赢（P1，小改动，约 1–2 天）

| 项 | 动作要点 | 验收 |
|---|---|---|
| B-2 `schema_version` + 迁移函数 | 在 `storage/schema.py` 加版本常量与显式 `migrate()`，`sqlite.py` 打开时校验 | 旧库打开不丢数据；版本断言有单测 |
| B-9 kind 统一 | 以 `sleep/samples.py` 单点为准，收敛 `offline_dashboard/constants.py` 的 `BAND_*` 与 `history_charts.js` 着色 | 三处编码同源；不佩戴色带一致 |
| B-1 能力闸门表 | 把 0x48/`0x2c` 探测事实升级为 `history/protocol.py` 带日期白名单，`sync.py` 显式读取跳过 | `sync_history` 不再试探已知空类型 |
| B-11 整库备份 | `tools/` 加 SQLite 安全拷贝 + 校验脚本（含保留 N 份轮换） | 备份可恢复；`--backup PATH` 可用 |

> **阶段 1 已实施（2026-11-20）**，四项全部完成、基线全绿，详见
> [validation/gadgetbridge-phase1.zh-CN.md](validation/gadgetbridge-phase1.zh-CN.md)。
> B-2 以 `PRAGMA user_version` 打戳并留显式迁移表；B-9 把 `BAND_*` 收敛到 `sleep/samples.py` 单点、
> JS 改读 payload 码表；B-1 白名单落 `history/capabilities.py`（独立模块守住协议文件 300 行预算），
> `sync_history` 过闸门跳过已知空类型；B-11 用在线备份 API + `integrity_check`/行数校验，含 `--backup PATH`。
> 单测 415 passed / 11 skipped（阶段 0 为 393），demo + `--backup` + `--doctor` + 五项 CI 门禁全绿。

### 阶段 2：架构安全网（P2，中改动，约 2–4 天）

| 项 | 动作要点 | 依赖 |
|---|---|---|
| B-5 GATT 事务队列 | 在 `client.py` 锁之上引入 Transaction 语义（有序动作组 + 回调闩锁 + 失败中止 + 错误清队列）；复用 GB 的**有上限指数退避**而非文档原述 | 不改协议行为；仿真手环回归全绿 |
| B-4 设备状态机 + busy | 复用 `dashboard/hub.py:publish_event` 与 workout 状态机模式，不新建事件总线 | 与 B-14 共用事件通道 |
| B-6 FetchSession 增强 | 在现有 `fetch_payload` 上补显式进度回调、错误恢复/重发、解析器插拔 | 为 B-12/B-13 铺路 |

> **阶段 2 已实施（2026-11-20）**，三项全部完成、协议行为零改动、基线全绿，详见
> [validation/gadgetbridge-phase2.zh-CN.md](validation/gadgetbridge-phase2.zh-CN.md)。
> B-5 新建 `backoff.py`（×2 封顶的指数退避）+ `ble/transactions.py`（有序动作/回调闩锁/失败中止/链路错误清队列），
> 队列建造在 client 的**同一个 `_gatt_lock`** 之上；B-6 新建 `history/fetch_session.py`（进度回调/链路恢复/
> 解析器注册表），`fetch_payload` 模板本体不变；B-4 新建 `ble/device_state.py`，经 `hub.publish_event` 发
> `device` 事件（与 B-14 电池共用通道）。单测 440 passed / 11 skipped（阶段 1 为 415），
> demo + `--backup` + `--doctor` + 五项 CI 门禁全绿，实测 1 s 会话经 hub 收到 5 个 device 事件。

### 阶段 3：数据理解与可视化（P2，约 2–3 天）

| 项 | 动作要点 | 验收 |
|---|---|---|
| B-7 多粒度 + 同轴 + 不佩戴着色 | `--range day\|week\|month` 语义档位；活动柱 + 心率线 + 睡眠色带同轴；hypnogram 给"不佩戴/无数据"显式上色 | 缺口仍渲染为 unset，不补零 |
| B-8 KPI 时间范围 | `_kpis()` 加 range 参数，与 B-7 粒度联动 | 昨晚/7 天/全库三档可切换 |
| B-14 电池通用 series | 把 workout 电量路径提升为独立 series，覆盖默认会话 | 看板显示电量与链路状态 |
| B-3 睡眠算法升级 | **未实施，属后续工作**。闸门在阶段 3 实施时点（2026-11-20 上午）尚未满足；同日晚间 `data/zepp_nights.json` 写入 8 夜参照（7 个带 `device` 的可用夜）后解锁。校准已给出候选读法：分值字节 `deep>40`（深睡单项 16.7 min 平均误差）+ `rem>50`（REM 经分值字节阈值可读出，平均误差 19.1 min）。R-4 第 2 步的滚动基线与阈值切换均待实施 | 逐夜分钟误差 <15 min（**不用 8–13% 占比**：Zepp 本期自报 5.6%–19.9%），`derived: true` 不变 |

> **2026-11-20 校准结论（7 夜）**：现役心率排名法深睡+REM 平均误差 **58.5 分钟**且恒不产 REM；
> 改读分值字节（`deep>40`）可降到 **16.7**（深睡单项），联合最优 `deep>40, rem>50` 为 **29.0**。
> 同时修掉两个静默 bug：`find_session` 拿午睡当整夜、`activity_history` 重复分钟使卧床时长翻倍。
> 详见 [validation/sleep-calibration-2026-11.zh-CN.md](validation/sleep-calibration-2026-11.zh-CN.md)。

> **阶段 3 已实施（2026-11-20）**，B-7 / B-8 / B-14 三项完成，`sleep/classification.py` 未改动；
> **B-3 在本阶段实施时点仍挂起**（当时复核 `data/zepp_nights.json` 不存在，0 夜 < 3 夜），
> **同日晚间闸门解锁**（8 夜参照写入、7 个带 `device` 的可用夜，校准结论见上 blockquote），
> 但算法切换未在本阶段实施。详见
> [validation/gadgetbridge-phase3.zh-CN.md](validation/gadgetbridge-phase3.zh-CN.md)
> 与 [validation/sleep-calibration-2026-11.zh-CN.md](validation/sleep-calibration-2026-11.zh-CN.md)。
> B-7 新增 `offline_dashboard/ranges.py`（day/week/month/all）+ `combined.py`（同轴分桶）+
> `assets/history_coaxis.js`（步数柱/心率线/睡眠色带同轴），hypnogram 把"未佩戴斜纹 / 有记录无心率灰块 /
> 无记录留空"分为三态；B-8 的 `_kpis()` 加 `range=` 与页眉口径标签；B-14 把电量提升为 hub 懒创建
> series（`METRIC_KINDS` 不变），默认会话仅在有看板 hub 或有 workout 时轮询，设备状态经
> `event_latest` 在刷新页面时即可见。单测 461 passed / 11 skipped（阶段 2 为 440，新增 21 项），
> demo + `--doctor` + 五项门禁全绿；`--range week` / `--range all` 离线 CLI 冒烟通过。

### 阶段 4：验证驱动的双向能力（P2–P3，依赖真机，约 3–5 天）

| 项 | 前置 | 动作 |
|---|---|---|
| B-10 校时下行 | 真机确认 Band 6 的 `CURRENT_TIME` 写入格式与固件代际（旧 chunked vs chunked2021） | 写标准 CTS 特征，失败不阻断会话 |
| B-12 运动总结抓取 | 阶段 0 probe 证实有数据 | 新 fetch 类型 + 解析；Band 6 不含 GPS 轨迹，SVG 自绘延续零依赖路线 |
| B-13 衍生指标抓取 | **重划范围**：`0x2c` 是不可解析的透明文件仓（GB 自己也不解析），改按类型码逐个探测 | **`0x0d` PAI 与 `0x13` 自动压力有数据**（后者需逐日核对量纲）；`0x12/0x38/0x3a/0x3d/0x49` 接受但 0 条 |
| B-15 通知/天气下行 | **仅用户明确提出时** | 暂缓，不排期 |

> **阶段 4 已实施（2026-11-20，第一轮）**：B-10 / B-12 完成并真机验证；B-13 按原范围（`0x2c`）
> 复测仍为空、**按原范围挂起**，B-15 继续暂缓。详见
> [validation/gadgetbridge-phase4.zh-CN.md](validation/gadgetbridge-phase4.zh-CN.md)。
> B-10 新增 `ble/time_sync.py`（CTS `0x2A2B` 的 Mi Band 11 字节变体，读漂移/写校时，失败不阻断），
> 真机漂移 -0.3 s、写入成功；B-12 新增 `history/summary_parser.py`（v512+/519 布局）、
> `storage/summary_schema.py`（`activity_summary`，schema v2）、`--sync-sports` 与离线运动记录表，
> 真机抓到 v519 treadmill 总结（493 步 / 578.6 m / HR 119–143）。真机还暴露并修正了一个游标 bug：
> 0x05 必须按 `end_ts + 1s` 推进，按 `start+1s` 会反复返回同一条（与 GB 保存 endTime 一致）。
> `0x2c` 复测原始回复 `10 01 01 00 00 00 00 …`（declares 0），故 B-13 不实现。
> 单测 488 passed / 11 skipped（阶段 3 为 461，新增 27 项），demo + `--doctor` + 五项门禁全绿。

> **B-13 重划范围后部分落地（2026-11-20，第二轮）**：不再纠缠 `0x2c`（它是不可解析的透明文件仓，
> GB 自己也不解析），改按类型码逐个探测。`0x13` 自动压力**全链路落地**（解析器 + schema v3 +
> `--sync-stress` + 存储/看板接线）：抓到 5761 分钟、每分钟 1 字节（`0xFF`/`0xFE` 双哨兵），
> 与 Zepp 页面逐日核对六项全中（均值按向下取整口径）。`0x0d` PAI **仅解析器与能力登记落地，
> 未接入同步链路**——真机证实手环只存 App 下发的**滞后镜像**（同步后才前进到 11-17），
> 不适合作为常规抓取流，故无 `--sync-pai`；如需当前值应看 App 侧。PAI 与 Zepp 页面五项数值
> 逐项一致（50 / 14 / 7 / 7 / 0），`pai_today` 等于三分量之和。
> **教训**：同一会话连问两个"有数据"的类型会让后续全部回 `0x02`（手环只留一个取数上下文），
> 必须一码一连接——上一轮因此误判"压力在 App 侧"。
> 详见 [validation/derived-metrics-probe-2026-11.zh-CN.md](validation/derived-metrics-probe-2026-11.zh-CN.md)。
> 第二轮后单测 **517 passed / 11 skipped**（阶段 4 第一轮为 488），五项门禁全绿（2026-11-22 复核）。

### 依赖关系与止损点

- **阶段 0 是闸门**：probe 结果与 Zepp 夜数直接决定 B-3/B-12/B-13 能否进入后续阶段；探测为空就保持挂起，不凭 GB 能力矩阵推进。
- **B-6 → B-12/B-13 是已兑现的依赖链**：`fetch_with_recovery`（有上限退避的链路恢复）与解析器
  注册表被 `sync_history` 与 0x05/0x13 抓取实际采用。**B-5 的 GattTransactionQueue 机制就绪但
  尚未接入主链路**——按"协议行为零改动"硬约束，现有写路径仍直接用 `_gatt_lock`；事务队列是
  预留给后续下行能力（B-15 类）与新链路改造的底座，采用前不应声称其为生效的安全网。
- **B-4 与 B-14 共用事件通道**，宜同批实现以免二次改造。
- **每个阶段结束跑全链路**：`pytest -q` + 仿真手环 demo + `--doctor`；真机项额外做一次连接/抓取验证。

## 9. 主要参考

- GB 仓库与关键文件：[Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge) ·
  [BtLEQueue.java](https://codeberg.org/Freeyourgadget/Gadgetbridge/src/branch/master/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/btle/BtLEQueue.java) ·
  [DeviceCommunicationService.java](https://codeberg.org/Freeyourgadget/Gadgetbridge/src/branch/master/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/DeviceCommunicationService.java) ·
  [AbstractDeviceSupport.java](https://codeberg.org/Freeyourgadget/Gadgetbridge/raw/commit/fea3bf50a4747e4be21daf7deaa5f1ea8f9c8936/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/AbstractDeviceSupport.java) ·
  [AbstractChartFragment.java](https://codeberg.org/Freeyourgadget/Gadgetbridge/src/commit/89bc1d8a7d40ae7f6511077166a5ee91828d1c42/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/activities/charts/AbstractChartFragment.java) ·
  [ActivitySummariesGpsFragment.java](https://codeberg.org/azisanw/Gadgetbridge/raw/commit/4c7476845b466cdc8d2eb3275eaa89994ffadc1b/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/activities/ActivitySummariesGpsFragment.java) ·
  [HuamiExtendedSampleProvider.java](https://codeberg.org/Freeyourgadget/Gadgetbridge/src/commit/758da0fa2e392164fffbc4ca999b26c74906d14d/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/huami/HuamiExtendedSampleProvider.java)
- GB 官方文档：[gadgets 索引](https://gadgetbridge.org/gadgets/) ·
  [internet 专页](https://gadgetbridge.org/basics/topics/internet/) ·
  [intents 自动化](https://gadgetbridge.org/internals/automations/intents/) ·
  [auto-export](https://gadgetbridge.org/internals/automations/auto-export/) ·
  [data-management](https://gadgetbridge.org/internals/development/data-management/) ·
  [new-gadget 教程](https://gadgetbridge.org/internals/development/new-gadget/) ·
  [sports](https://gadgetbridge.org/basics/features/sports/) ·
  [huami-gps](https://gadgetbridge.org/internals/topics/huami-gps/) ·
  [release 0.68.0](https://gadgetbridge.org/blog/release-0_68_0/) ·
  [release 2026.11.0](https://gadgetbridge.org/blog/release-2026_11_00/)
- 本仓库的交叉验证基础：[investigations/sleep-fields.zh-CN.md](investigations/sleep-fields.zh-CN.md) §6 ·
  [validation/history-hardware.zh-CN.md](validation/history-hardware.zh-CN.md) ·
  [guides/cross-platform.zh-CN.md](guides/cross-platform.zh-CN.md) §2.5 ·
  [improvement-plan.zh-CN.md](improvement-plan.zh-CN.md) R-4
