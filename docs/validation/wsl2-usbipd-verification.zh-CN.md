# WSL2 + usbipd 蓝牙直通与真机连接验证

> **记录时间**：2026-11-17 ～ 2026-11-19（Asia/Shanghai）。
> **脱敏说明**：设备地址一律为占位符（`C0:FF:EE:C0:FF:EE` 等），个人路径写作 `~/Works/...`，
> 内网主机名与 IP 已略去；所有时序、计数、MTU 与退出码为原始实测值，未做改写。
> 本文由当时的本地工作笔记（`temp/wsl_test/`，git 忽略）整理而来；笔记原件保留在本地。

## 1. 结论速览

| 验证项 | 结果 |
|---|---|
| WSL2 重建 venv + 无硬件全链路 | ✅ `--demo` 通过；pytest **392 passed / 4 skipped** |
| 内置 Intel 蓝牙（`8087:0026`）usbipd 直通 | ⛔ WSL 内核 `btintel` 不支持该批次（hw variant 29），固件无法下载 |
| 外接 BARROT dongle（`33fa:0012`）直通（内核 6.6.87.2） | ⛔ `btusb` 缺设备 ID + quirk，HCI 初始化超时，`hci0` 恒 DOWN |
| 外接 BARROT dongle 直通（升级 WSL 3.0.5 / 内核 6.18.58.1） | ✅ `hci0` UP RUNNING，BlueZ / bleak 扫描正常，`--doctor` 0 error |
| **真机连接 + 采集（P0）** | ✅ 两次会话退出码 0：建链 10 s / 2.4 s、ECDH 认证成功、MTU 247、心率 46 条、电量 48%、`dropped: 0` |

## 2. 环境

| 项 | 值 |
|---|---|
| 宿主 | Windows 11，内置蓝牙 Intel `8087:0026`（Arrow Lake 批次，hw variant 29） |
| WSL | 2.6.3.0（内核 6.6.87.2）→ 升级 **3.0.5.0（内核 6.18.58.1）**，Ubuntu 22.04.5 |
| 外接 dongle | BARROT `33fa:0012`（Windows 侧驱动 Code 31，专供 WSL 直通） |
| usbipd-win | 5.3.0（bind/attach/`--auto-attach`） |
| 项目环境 | uv 管理的 Python 3.12.13 venv，`~/Works/.../miband_health_monitor` |
| 手环 | Mi Smart Band 6；广播 MAC 与 `.env` 的 `DEVICE_ID` 一致（占位 `C0:FF:EE:C0:FF:EE`） |

## 3. 直通路线的三次失败与根因

1. **内置 Intel，attach 被已配对音频设备否决**：`Attach Request failed - Device busy`，
   Windows 事件日志为 `CM_Query_And_Remove_SubTree returned CR_REMOVE_VETOED`
   （Audio Sink 句柄未释放），且 `Disable-PnpDevice` 留下 PnP 挂起态——**需重启 Windows 清理**。
2. **内置 Intel，attach 成功但控制器不可用**：`hci0: Unsupported Intel hw variant (29)`，
   BD 地址全零、恒 DOWN。结论：**该批次芯片在当前 WSL 内核下无驱动支持**，非 usbipd 问题。
3. **BARROT dongle，6.6 内核下 HCI 初始化超时**：`Read Buffer Size / Reset` 超时，
   `hci0` 有真实 MAC 但始终 DOWN。对照上游：`linux-6.6.y` 最新稳定分支与
   **WSL 内核 6.18.58.1 源码均含 `{ USB_DEVICE(0x33fa, 0x0012) }` + BTUSB_BARROT quirk**——
   升级 WSL 即解决，无需换 dongle。

升级后实测：`hci0` UP RUNNING（ACL MTU 679:9），`bluetoothctl` Powered=yes，
`btmgmt find -l` 与 `BleakScanner` 均能发现 BLE 设备；无害噪音两条——
`hcitool lescan` 走旧 ioctl 报错（用 bluetoothctl/btmgmt/bleak 即可）、
dmesg `Unexpected continuation: 1 bytes`（克隆芯片事件分片）。

## 4. P0 真机会话时间线（2026-11-18 07:22–07:27）

前置：手机 Zepp Life 打开一次后关闭手机蓝牙（手环恢复公共广播）；
`scan_live.py`（`DuplicateData=False`）90 s 内捕获 4 次手环广播脉冲。

| 时间 | 事件 |
|---|---|
| 07:22:43 | 启动，Linux/BlueZ 长驻 `Device1.Connect` 待命（预算 120 s） |
| 07:23:13 | 第 30 s 捕获广播脉冲 → armed BLE link |
| 07:23:23 | 建链 + 服务解析完成（1 次 connect 请求） |
| 07:23:25 | ATT MTU 协商 = **247**，chunked 监听就绪 |
| 07:23:27 | **Chunked ECDH 认证成功**；心率/步数流开启（步数 115 / 77 m / 6 kcal） |
| 07:24:31 | 正常断开，退出码 0；`dropped: 0`；60 s 内心率 **46 条（63–78 BPM）** |

第二次会话（workout 模式，验证重连路径 + 电量 + 历史 gap-fill）：

| 时间 | 事件 |
|---|---|
| 07:24:59 | 启动；第 **50 s** 捕获脉冲（与“每 40–78 s 一发”实测一致） |
| 07:25:51 | 脉冲命中后 **2.4 s** 内建链 + 服务解析完成 |
| 07:25:55 | ECDH 再次成功，MTU 247 |
| 07:26:16 | **电量读取成功（标准 0x180F/0x2A19）** |
| 07:26:26 | Workout ACTIVITY gap-fill：从手环侧取回 2 条分钟级历史 |
| 07:26:29 | 正常断开，退出码 0；HR 22 条（avg 73.3 / max 77），`reconnects=0` |

## 5. 连接后的 BlueZ 状态与观察

- **SMP bond 未持久化（`Paired: no`）但 `Trusted: yes`**：应用层 ECDH 认证与采集不受影响；
  重连靠“扫描等脉冲 → 建链”完成。推测手环仍与手机保持绑定、拒绝新 SMP bond。
- `Connected: yes` 为会话正常断开后的**残留属性**；项目代码对
  “Connected=True + ServicesResolved=False” 有自愈清理逻辑，下次运行遇异常会自行恢复。
- 每次连接仍需等一次广播脉冲（30 s / 50 s）：这是 Mi Band 6 无手机链路时的固件行为，
  不是缺陷。全程未出现 `-112`、`le-connection-abort-by-local`、适配器假死等已知故障特征。
- **经验**：`scan_ble.py` 硬编码 `DuplicateData=True`，对 BARROT 适配器会触发
  扩描重启进而射频假死（见 [linux-ble-connect-findings.md](linux-ble-connect-findings.md) R5），
  排障时用 `scan_live.py` 更安全。

## 6. 后续建议（当时记录，仍有效）

1. 日常采集直接 `miband_client.py 60 --scan-timeout 120`；
   若再现“扫描正常但收不到任何包”的假死，执行 `sudo usbreset 33fa:0012 &&
   sudo systemctl restart bluetooth`（power off/on 无效）。
2. WSL 重启后需重新 `usbipd attach --wsl --busid <id>`（可加 `--auto-attach`）；
   attach 前建议关闭 Windows 蓝牙无线电，避免已配对音频设备重新占用内置适配器。
3. Windows 原生路径（WinRT/bleak）同样真机可用（本仓库 `data/` 已有其采集记录），
   不依赖 USB/IP。

## 7. 复现命令

```bash
# 0) 自检
.venv/bin/python miband_client.py --doctor

# 1) 安全扫描探针（避免 DuplicateData=True 卡死 BARROT dongle）
.venv/bin/python scan_live.py

# 2) 首次连接（无 BlueZ 缓存场景）+ 60 s 采集
MIBAND_BLUEZ_AGENT=1 .venv/bin/python miband_client.py 60 --scan-timeout 120

# 3) 电量 + 重连 + 手环历史验证
MIBAND_BLUEZ_AGENT=1 .venv/bin/python miband_client.py 30 \
    --workout --battery-interval 10 --scan-timeout 120

# 4) 可选离线看板
.venv/bin/python history_dashboard.py --db data/mi_band.db
```
