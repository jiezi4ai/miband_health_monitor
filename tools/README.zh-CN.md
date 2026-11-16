[English](README.md) · **简体中文**

# 诊断与取证工具

这些脚本是主客户端的可选配套工具。它们不属于遥测链路的一部分，而且多数会与真实硬件交互，
运行前请先阅读对应模块的 docstring。

| 脚本 | 用途 |
|---|---|
| capture_history_payload.py | 抓取手环侧历史原始 payload（.bin + SHA-256 元数据），用于离线验证。 |
| import_spo2_sleep.py | 解码抓取到的 0x26 payload，并通过 TelemetryStore 回放。 |
| probe_declared.py | 询问固件还保留多少历史数据，但不消费这些数据。 |
| probe_fetch_types.py | 查询任意历史类型码并打印起始日期回复。 |
| probe_sleep_session.py | 探测华米 SLEEP_SESSION (0x48) 历史类型。 |
| probe_battery.py | 非破坏性探测标准蓝牙 Battery Service (0x180F / 0x2A19) 是否可用。 |
| calibrate_sleep.py | 用 Zepp Life 的数字对照睡眠字节的候选读法。 |
| remediate.py | 独立运行脚本化连接排障与一键修复 Playbook（与 `gui.py` / `--gui` 共享后端）。 |
| reset_bt_adapter.py | Linux 人工恢复工具：自动读取 USB `<vid:pid>`，执行 `sudo usbreset` + 重启 `bluetooth` 并运行 `--doctor`。 |
| check_file_sizes.py | CI 守门：第一方代码/资源文件必须 ≤ 300 行。 |
| check_privacy.py | CI 守门：Git 跟踪文件中不得出现真实 MAC、auth key 或家目录路径。 |
| check_docs_links.py | CI 守门：相对 Markdown 链接必须可以解析。 |

所有命令都在仓库根目录执行，例如：

    ./.venv/bin/python tools/check_file_sizes.py
    ./.venv/bin/python tools/capture_history_payload.py --days 7

第一方实现位于 miband_monitor/；这些 CLI 只负责导入它，并保留参数解析与面向硬件的诊断逻辑。
