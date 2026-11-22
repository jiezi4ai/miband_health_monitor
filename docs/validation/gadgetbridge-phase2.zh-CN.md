# 阶段 2 实施记录：架构安全网（P2）（2026-11-20）

> 性质：执行 [gadgetbridge-benchmark.zh-CN.md](../gadgetbridge-benchmark.zh-CN.md) §8「阶段 2：架构安全网」的
> 实施登记。三项 B-5 / B-6 / B-4 全部落地，**不改协议行为**（仿真手环回归全绿），基线全绿。
> 前置阶段记录：[阶段 0 闸门](gadgetbridge-gate0.zh-CN.md)、[阶段 1 快赢](gadgetbridge-phase1.zh-CN.md)。

## 总览

| 项 | 内容 | 状态 | 关键文件 |
|---|---|---|---|
| B-5 | GATT 事务队列（有序动作 + 回调闩锁 + 失败中止 + 错误清队列 + 有上限指数退避） | ✅ 完成 | `backoff.py`、`ble/transactions.py`、`ble/client.py` |
| B-6 | FetchSession 增强（进度回调 + 错误恢复/重发 + 解析器插拔） | ✅ 完成 | `history/fetch_session.py`、`history/fetcher.py`、`history/sync.py` |
| B-4 | 设备状态机 + busy 语义（共用 hub 事件通道） | ✅ 完成 | `ble/device_state.py`、`ble/client.py`、`cli/runner.py` |

**依赖链遵守**：B-5 → B-6 先稳固事务队列与抓取模板增强；B-4 与 B-14 共用 `hub.publish_event`
通道（本阶段建立设备事件通道，B-14 电量后续直接复用，无需二次改造）。

---

## B-5 · GATT 事务队列

- 新建 `miband_monitor/backoff.py`：`ExponentialBackoff`（`next_delay()` 翻倍并封顶，`reset()`，
  `immediate_first` 对应 GB 首连立即重试分支）。**采用 GB 的有上限指数退避策略**（×2、封顶），不是
  基准文档原述的"固定间隔"。
- 新建 `miband_monitor/ble/transactions.py`：
  - `GattAction` / `Transaction` / `TransactionBuilder`——**有序动作组**（write/read/wait_callback/step
    流式组装），`Transaction.execute()` 逐条 await，任一动作失败即 `ActionFailed` 中止后续；
  - `CallbackLatch`——**回调闩锁**（notification 回调 `release`，另一协程 `wait(timeout)`，无轮询无丢唤醒）；
  - `GattTransactionQueue`——**复用 client 的 `_gatt_lock`**（无第二个竞争锁），失败中止事务；
    **链路级错误（transient）先 `clear()` 清空排队事务**（generation 机制让等待者中止），再按退避重试；
    连接/断开不入队（留在其自身生命周期锁）。
- `MiBand6Client`：`self.gatt_queue = GattTransactionQueue(self._gatt_lock)`（建造在**同一个锁**之上），
  新增 `run_transaction(builder)`。`ble` 包导出全部符号。
- 协议行为不变：现有写路径（`_write_gatt` / chunked / battery）原样保留；事务层是新增可选能力。
- 单测：`tests/ble/test_transactions.py`（11 项）——退避翻倍封顶、immediate-first、有序执行、失败中止、
  原始异常透传、链路错误退避重试、非链路错误不重试、排队事务被清、回调闩锁释放/超时、错误分类。

## B-6 · FetchSession 增强

- 新建 `miband_monitor/history/fetch_session.py`：
  - `FetchProgress` / `FetchSession`——**显式进度回调**（phase 快照：metadata/complete/ack/empty/error），
    不经由它改变协议流程；
  - `fetch_with_recovery()`——**错误恢复/重发**：仅对 transient 链路错误重试，复用 `ExponentialBackoff`
    有上限退避；协议/业务拒绝（如 `HistoryFetchError`）立即上抛不重试；
  - `PARSERS` 注册表 + `register_parser()` / `parse_with()`——**解析器插拔**：B-12/B-13 新类型只需注册解析器，
    无需改 sync 循环；未注册类型回退到既有 `_parse_payload`。
- `history/fetcher.py::fetch_payload` 加可选 `session=` 参数，在 4 个相位点发进度（模板本体不变，符合 §7.3
  "不新抽模板"）；为避免超出 300 行预算，压缩了 3 处冗长错误分支（日志语义保留）。
- `history/sync.py`：`sync_history` 加可选 `on_progress`，抓取改走 `fetch_with_recovery`，解析改走 `parse_with`，
  能力闸门（B-1）仍在候选阶段过滤。
- 单测：`tests/history/test_fetch_session.py`（7 项）——进度相位、链路错误重试后成功、非链路错误不重试、
  重试次数上限、解析器注册/覆盖、内建回退、注入解析器。修正 2 处既有测试 fake 签名以兼容 `session=`。

## B-4 · 设备状态机 + busy

- 新建 `miband_monitor/ble/device_state.py`：`DeviceState`（NOT_CONNECTED→CONNECTING→CONNECTED→
  INITIALIZING→INITIALIZED）、合法转移表（意外跳变允许但事件打 `unexpected` 标记）、busy 任务
  （`set_busy`/`clear_busy`/`is_busy`，对应 GB `setBusyTask`）、`note_reconnect()`、`reset()`、`as_dict()`。
- **共用事件通道**：所有状态/busy/重连变化经注入的 `publish` 回调（runner 传入 `hub.publish_event`），
  event `kind="device"`，与 B-14 电池事件的 `"battery"` 同走 hub 的 out-of-band 流，未新建事件总线。
- `MiBand6Client`：`self.device_state = DeviceStateMachine()`、`attach_event_publisher()`、`set_device_state()`，
  BLE 层保持 dashboard 无关。
- `cli/runner.py`：会话中挂载 hub publisher；attempt>1 记重连；connect/auth/stream-start/teardown 分别
  转 CONNECTING/CONNECTED/INITIALIZING→INITIALIZED/NOT_CONNECTED；历史抓取期间 `set_busy("fetch activity data")`。
  （为守住 300 行预算压缩了若干多行日志调用，**保留测试断言的关键短语**如 "consecutive 0-packet scans"、
  "since disconnect"。）
- 单测：`tests/ble/test_device_state.py`（7 项）——合法/意外转移、busy 幂等、重连/复位、时间戳透传、
  无 publisher 静默、client 暴露状态机并经 hub 发事件。

---

## 阶段 2 全链路基线（2026-11-20，全绿）

| 检查 | 命令 | 结果 |
|---|---|---|
| 单测 | `python -m pytest -q` | **440 passed, 11 skipped**（38.2s；阶段 1 为 415，新增 25 项） |
| 仿真手环 demo + 备份 | `miband_client.py --demo 2 --imu --sync-history 1 --sync-sleep-spo2 --storage both --export-csv --backup ...` | 退出码 0；6 类产物非空；备份 `integrity_check` + 行数校验通过 |
| 预检 | `miband_client.py --doctor` | **0 error / 0 warning** |
| 文件预算 | `tools/check_file_sizes.py` | OK：268 个首方文件 ≤300 行 |
| 文档链接 | `tools/check_docs_links.py` | OK：743 条链接可解析 |
| 测试数量 | `tools/check_test_baseline.py` | OK：采集 451，4 处声明在容差内 |
| 隐私 | `tools/check_privacy.py` | OK：358 个跟踪文件无真实凭据 |
| 事件通道实测 | demo + hub 拦截 | 1 s 会话经 `hub.publish_event` 收到 **5 个 `device` 事件** |

演示产物落在 `data/phase2-demo/`、`data/phase2-backup.db`（gitignored）。

## 备注与边界

- **协议行为零改动**是硬约束：B-5 事务层与 B-6 恢复层均为可选/叠加，现有写路径、抓取模板本体未改；仿真与
  BlueZ 相关测试（含 adapter-deaf 韧性）全绿。
- B-12/B-13 仍未启动：阶段 0 已确证 `0x05` 有数据、`0x2c` 为空；B-6 的解析器注册表为其铺好了"只写解析器"
  的接入点，但真正抓取仍按依赖链等后续实施。
- 阶段 3 的 B-14（电量通用 series）可直接向 `hub.publish_event("battery", ...)` 发事件，与本阶段 `device`
  事件共用通道。
- 未触碰工作区既有未提交内容；改动均限于本阶段涉及文件。
