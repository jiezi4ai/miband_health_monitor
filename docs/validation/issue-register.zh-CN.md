# 问题闭环登记册（issue register）

> **目的**：让「已知问题」有唯一的状态去处，避免散落在叙事文档里被遗忘。
> 每条包含：症状、根因/证据、状态与关闭证据。修复即改状态；新问题先登记再修。
> 编号沿用 [linux-validation.zh-CN.md](linux-validation.zh-CN.md)（L 系列），
> 现存风险见 [improvement-plan.zh-CN.md](../improvement-plan.zh-CN.md)（R 系列）。

## 状态总览

| 编号 | 症状（一句话） | 严重度 | 状态 | 关闭证据 |
|---|---|---|---|---|
| L1 | `.env` 读取路径未收紧权限（实测 0644，文档称 0600） | 中 | ✅ 已修复 | CLI 启动预检调用 `secure_env_file`（[cli/args.py](../../miband_monitor/cli/args.py)）；doctor 保留 WARN 兜底 |
| L2 | 遥测产物权限过大（0664/0644） | 中 | ✅ 已修复 | 写线程启动即收紧 0600（[storage/writer.py](../../miband_monitor/storage/writer.py)、[sqlite.py](../../miband_monitor/storage/sqlite.py) `secure_database_files`） |
| L3 | 输出目录不可写/被占 → 未捕获 traceback | 低 | ✅ 已修复 | [cli/app.py](../../miband_monitor/cli/app.py) 捕获 `TelemetryStore` 的 `OSError`，输出可操作日志并返回退出码 1；[storage/store.py](../../miband_monitor/storage/store.py) 抛错时带路径 |
| L4 | `history_dashboard.py` 对缺失 DB 静默成功 | 低 | ✅ 已修复 | [offline_dashboard/collect.py](../../miband_monitor/offline_dashboard/collect.py) 显式 `FileNotFoundError` |
| L5 | 跨平台文档与事实不符 | 低 | ◐ 部分 | Linux 表述已修正；**基线数字漂移**移交 [R-1](../improvement-plan.zh-CN.md#r-1-测试基线数字在文档间漂移) |
| L6 | 探针/校准脚本用法示例写死 Windows venv 路径 | 低 | ✅ 已修复 | `probe_fetch_types` / `probe_sleep_session` / `calibrate_sleep` 用法改为平台中立 |
| L7 | Linux 配对环节缺失（不配对 ~36s 断链） | 高 | ✅ 已修复 | 内置 NoInputNoOutput 配对 agent（[bluez/pairing.py](../../miband_monitor/bluez/pairing.py)）+ trust 默认 + 文档场景 A/B |
| L8 | 探针脚本超时参数不一致（无手环时不退出） | 低 | ✅ 已修复 | `probe_fetch_types` / `probe_sleep_session` 补 `--scan-timeout`（默认 120s，与全局默认一致） |
| L9 | 未配对时 ~36s 断链 + 误导性 D-Bus 报错 | 高 | ✅ 已修复 | [linux-validation.zh-CN.md](linux-validation.zh-CN.md) §7，真机复验 |
| L10 | ATT MTU 从未协商（恒 23） | 中 | ✅ 已修复 | 同上 §7：显式 `_acquire_mtu()`，实测 247 |
| L11 | 首次全量 GATT 枚举在 ~9s 看门狗内跑不完 | 中 | ◐ 已缓解 | 长驻 `Device1.Connect` + `SERVICE_RESOLVE_GRACE` 10s 宽限（[bluez/link.py](../../miband_monitor/bluez/link.py)）；看门狗本身是固件行为，无法根除 |
| L12 | 取消挂起 LE Create Connection → BARROT 射频假死 | 高 | ✅ 已修复 | 链路循环绝不中途 `Disconnect`（[bluez/link.py](../../miband_monitor/bluez/link.py) 语义）；恢复工具 [reset_bt_adapter.py](../../tools/reset_bt_adapter.py) |
| L13 | bleak 3.0.2 在 `le-connection-abort-by-local` 上死锁 41s | 中 | ✅ 已修复 | `wait_for_bluez_link` 接管重挂，绕过 bleak 内部 abort 处理 |
| L14 | `DuplicateData=True` 每 ~5s 重启扩展扫描（假死诱因） | 中 | ✅ 已修复 | [bluez/scanner.py](../../miband_monitor/bluez/scanner.py) 默认 `False` + `MIBAND_BLUEZ_DUPLICATE_DATA` 覆盖 |

## 使用约定

1. 新发现的问题先在本表登记（症状 + 复现证据），再去修；
2. 修复后补「关闭证据」列的文件引用，叙事文档只留根因分析本身；
3. 与具体风险改进方案相关的条目在备注中链到
   [improvement-plan.zh-CN.md](../improvement-plan.zh-CN.md)，两处状态保持一致；
4. `N1–N5`（非缺陷备注，避免误判）保留在
   [linux-validation.zh-CN.md](linux-validation.zh-CN.md) §5，不入本表。
