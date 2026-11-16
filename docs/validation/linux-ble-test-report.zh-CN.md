[English](linux-ble-test-report.md) · **简体中文**

# Linux BLE 受控复测与陈旧 LTK 根因报告（Test 1–4 & 对照验证）

> 本文在 [linux-ble-connect-findings.md](linux-ble-connect-findings.zh-CN.md)（2026-11-12）基础上，记录后续针对
> **“BlueZ 约 5 秒 `ServicesResolved=False` 断链”**、**“正常同步是否会破坏配对”**、
> **“残留 `Connected=True` 连接影响”** 以及 **“3 天历史数据校准与时区对齐”** 的完整受控真机实验（Test 1–4、Test 4 v2、Test 0、Test B），
> 并沉淀固化后的自愈机制与未来可复用的 Debug 排障流程。
>
> 设备地址统一脱敏为占位符 `C0:FF:EE:C0:FF:EE`。

---

## 1. 核心结论速览（TL;DR）

| # | 核心结论 | 证据来源 | 对使用与实现的指导 |
|---|---|---|---|
| 1 | **Test 1–3 的 5 秒反复掉线 = BlueZ 陈旧 `LTK`（Long Term Key）导致空口加密超时（HCI 错误码 `0x08`）** | Test 1–3 日志 + `btmon` `.btsnoop` | BlueZ 旧 `Device1` 对象缓存的 `LTK` 与手环不一致，内核发 `HCI LE Start Encryption` 后 5000 ms 被固件超时断链；此时 `ServicesResolved=False`、`RX/TX acl=0/0` |
| 2 | **Test 4 成功不是因为清缓存本身，而是清掉失效配对并配合 `MIBAND_BLUEZ_AGENT=1` 重建了一套有效 `LTK`** | Test 4 v1（`Paired=yes, Bonded=yes, Trusted=yes`） | 仅当 `LTK` 已失配时才需要 `bluetoothctl remove` + 配对 agent 重建；正常状态切勿每次无条件删配对 |
| 3 | **健康配对在手机 Zepp Life 正常同步并关蓝牙后依然完全可用，无需每次清缓存或开 `MIBAND_BLUEZ_AGENT=1`** | Pre-check + Test 0 + Test B | 保持 `Paired=yes / Bonded=yes / Trusted=yes / Connected=no` 直接运行即可：1 次 `direct connect` 直连（13.5–18 s），**0 WARNING / 0 ERROR**，稳跑 60 s + `--imu` |
| 4 | **无条件每次先 `remove` 配对反而有害** | 对比实验与 BlueZ 机制分析 | 每次清缓存会丢失 GATT 服务表缓存与 `direct connect` 免扫描快路径，重新暴露在约 9–9.8 s 未认证枚举看门狗下；若手机未完全断链还会触发 `AuthenticationCanceled` |
| 5 | **一次采集日志中出现多次 `Connect` 或重连是两层机制叠加**：① 待命等待 40–60 s 单脉冲的内核周期；② 会话断线后监督器自动重连 | Test 4 v2 vs Test B 对比 | `le-connection-abort-by-local` 是内核 40 s 发起周期重挂的正常日志；而会中途掉线多因链路被手机抢占、省电超时或复用了残留的 `Connected=True` 半温状态 |
| 6 | **3 天历史数据与 Zepp Life 精确对齐** | Test 4 v2（`--sync-history 3 --band-tz Asia/Shanghai`） | 同步 4318 分钟无空洞；同日步数 `8353` vs `8353` 完全一致；`detect_sessions()` 外延逻辑 + `--band-tz` 修复双重偏移后，睡眠区间 `22:15 -> 06:28` 与 Zepp `22:24 -> 06:27` 高度吻合 |

---

## 2. 受控实验总表（Test 1–4 与对照验证）

统一条件：手环与 Linux 主机间距 < 1 m，测试前手机确认同步完成并关闭手机蓝牙（除非表中另有说明）。

| 编号 | 初始 BlueZ 状态 | 操作变量（缓存 / Agent） | CLI 目标 | 实测结果 | 关键指标与日志特征 |
|---|---|---|---|---|---|
| **Test 1** | 旧绑定存在（`Connected=no`） | 不清缓存，无 `MIBAND_BLUEZ_AGENT` | 60 s 基础采集 | **失败**（`EXIT_CODE=1`） | 多次 `Connected=True` 后约 `5.15–5.18 s` 断链，`ServicesResolved=False`，`hciconfig RX/TX acl = 0/0` |
| **Test 2** | 旧绑定存在（同 Test 1） | 紧跟 Test 1，同条件复测 | 60 s 基础采集 | **失败**（`EXIT_CODE=1`） | 完全复现 `~5.16 s` 断链 + `ServicesResolved=False` |
| **Test 3** | 旧绑定存在 + 开启 `btmon -w` | 同步抓取 HCI `.btsnoop` | 60 s 抓包复现 | **失败**（`EXIT_CODE=1`） | `btmon` 实锤：`LE Connection Complete` → `LE Data Length Change (251B)` → `HCI LE Start Encryption` → **5000 ms 后 `Encryption Change / Disconnect Complete: Connection Timeout (0x08)`** |
| **Test 4 v1** | 先 `bluetoothctl remove` 清旧对象 | 启用 `MIBAND_BLUEZ_AGENT=1` | 60 s + `--imu` + `--sync-history 1` | **成功**（`EXIT_CODE=0`） | 触发全新 SMP 配对并写回 `Paired/Bonded/Trusted=True`，1440 条历史 + 1548 条 IMU，4 次 `[0x16]` 保活跑满 60 s |
| **Test 4 v2** | 已带残留 **`Connected=yes`** 初态 | 无清缓存（沿用 Test 4 v1 绑定），`--band-tz Asia/Shanghai` | `--sync-history 3` + 60 s | **成功但中途重连**（`EXIT_CODE=0`） | 阶段 1 复用残留连接并同步 4318 条历史，但在 ~39 s 处断线；阶段 2 扫描超时；步数 `8353 = 8353`、睡眠 `22:15–06:28` 对齐 Zepp `22:24–06:27` |
| **Pre-check** | 手机 Zepp Life 刚刚完成一次正常同步后关蓝牙 | 仅 `bluetoothctl info` 观测，**不动手环与缓存** | 状态核验 | **状态完好** | `Paired=yes, Bonded=yes, Trusted=yes, Connected=no` |
| **Test 0** | 紧接 Pre-check（`Connected=no`） | **不清缓存、不开 `MIBAND_BLUEZ_AGENT`** | 20 s 冒烟 | **成功**（`EXIT_CODE=0`） | 1 次 `direct connect`（18 s）直连，**0 WARNING / 0 ERROR** |
| **Test B** | 紧接 Test 0（`Connected=no`） | **不清缓存、不开 `MIBAND_BLUEZ_AGENT`** | 60 s + `--imu` 压力测试 | **成功**（`EXIT_CODE=0`） | 1 次 `direct connect`（13.5 s）直连，4 次 `[0x16]` 保活，IMU 达 `Seq 91`，**0 WARNING / 0 ERROR** |
| **Post-reboot** | 系统重启后（`Paired/Bonded/Trusted=yes, Connected=no`） | **不清缓存、不开 `MIBAND_BLUEZ_AGENT`** | `--imu --sync-history 1 --band-tz Asia/Shanghai --export-csv` 60 s | **成功**（`EXIT_CODE=0`） | 1 次 `direct connect`（30.9 s）直连，1440 条历史 + 44 HR + 1548 IMU 零掉线，**0 WARNING / 0 ERROR** |
| **Fresh Pair 1** | 先 `remove_device()` 彻底清零 BlueZ 对象（`not known to BlueZ yet`） | 模拟新机首次：`MIBAND_BLUEZ_AGENT=1` | `--imu --sync-history 1 --band-tz Asia/Shanghai --export-csv` 60 s | **成功**（`EXIT_CODE=0`） | 10.7 s 扫到脉冲，触发 `SERVICE_RESOLVE_GRACE` 10 s 宽限并 +1.8 s 解析成功，agent 自动授权 SMP，1440 条历史 + 45 HR + 1548 IMU，**0 WARNING / 0 ERROR** |
| **Fresh Pair 2** | 紧接 Fresh Pair 1（新配对已固化） | **不再开 `MIBAND_BLUEZ_AGENT`** | 默认 20 s 复连验证 | **成功**（`EXIT_CODE=0`） | `--doctor` 显示 `paired=yes trusted=yes`，默认命令 1 次建链直通（15 HR + 1 steps），**0 WARNING / 0 ERROR** |

---

## 3. 机制拆解：为什么出现“多个 Error/Warning 与多次连接”

### 3.1 `btmon` 还原的 ~5 秒断链真相（Test 1–3）

当 BlueZ 中保存了旧配对记录，但手环曾被其他主机/App 刷新过配对密钥或清除过绑定，Linux 与手环的握手时序如下：

1. 内核收到脉冲（或发起 `Device1.Connect`），物理层建链成功（`LE Connection Complete`）；
2. 控制器完成参数协商：`LE Data Length Change`（251 字节）与 `LE Read Remote Used Features` 均正常返回；
3. 由于 BlueZ 认为该设备 `Paired=True`，Linux 内核主动向控制器下发 `HCI LE Start Encryption`，并传入 BlueZ 磁盘中**陈旧的 `LTK`**；
4. 手环固件用自己当前的密钥无法解密/认证该链路加密请求，既不触发上层 GATT 服务发现（因此 `ServicesResolved` 始终为 `False`，`acl` 数据包收发为 `0`），也在约 **5000 ms** 后直接超时断链（`Encryption Change: Connection Timeout (0x08)`）。

> 区分点：**陈旧 LTK 断链 ≈ 5.1 s 且 `RX/TX acl = 0/0`**；而**首次连接未认证看门狗 ≈ 9.0–9.8 s 且伴随大量 GATT 枚举 `acl > 0`（日志 `failed to discover services`）**。

### 3.2 为什么日志里会有多次 `Connect` 和重连

运行主程序（[cli/runner.py](../../miband_monitor/cli/runner.py) 中的 `run_monitor()`）时，“一次执行出现多轮日志”来自两个正常层级：

1. **单次建链窗口内的脉冲等待（正常）**：
   无手机连接的手环每 **40–60 秒**才发出 1 个可连接脉冲。Linux 内核单次 `LE Create Connection` 约 40 秒超时会报 `le-connection-abort-by-local`。`wait_for_bluez_link()` 会在 ~150 ms 后原地重挂等待下一个脉冲，并在 `direct`（49.5 s）未能命中时进入 `scan`（≥ 70 s）。这些期间的 INFO/WARNING 重试是预期设计，不代表失败。
2. **会话监督器的断线重连（正常容错）**：
   一旦某段会话在运行中途断链（如 Test 4 v2 阶段 1 复用了先前残留的 `Connected=True` 状态导致 ~39 s 断链，或手环省电/手机干扰断链），`run_monitor()` 会在指数退避（或刚断链时的 `0.3 s` 快速重连窗口）后新建下一轮会话继续完成 `--duration`。

### 3.3 为什么不应“每次启动前无条件清空 BlueZ 缓存”

1. **正常使用手机同步并不会破坏 Linux 绑定**：Test 0 与 Test B 已实锤验证，在 Zepp Life 正常同步完并关闭手机蓝牙后，Linux 侧原有 `Paired/Bonded/Trusted` 密钥依然有效，无需重新配对。
2. **保留缓存带来两项关键收益**：`direct connect` 可直接对已绑定设备发起建链而不依赖扫到脉冲；同时 BlueZ 已缓存 ~150 个 GATT 句柄，避免每次重新跑全量服务发现而撞上 ~9 s 看门狗。
3. **误删的代价**：如果手环侧仍与手机保有有效绑定且手机蓝牙未断开，删掉 BlueZ 缓存并强行发起配对反而会在空口被手环拒绝（`AuthenticationCanceled`）。

---

## 4. 代码层固化的自愈与保护逻辑

针对 Test 1–4 与 Test 4 v2 暴露出的两类异常前驱状态，[bluez/](../../miband_monitor/bluez/__init__.py) 与 [ble/](../../miband_monitor/ble/client.py) 层已内置以下分级自愈机制（**仅针对已证实的故障证据触发，不干扰健康配对**）：

| 触发条件 | 代码位置 | 自动动作 | 保护边界 |
|---|---|---|---|
| 启动直连检测时发现 **`Connected=True` 且 `ServicesResolved=False`**（幽灵残留） | [ble/discovery.py](../../miband_monitor/ble/discovery.py) `_direct_connect_target()` | 调用 `bluez.disconnect_device()` 清理幽灵链路，打印 `WARNING` 并等待 0.3 s 后从干净状态续连 | **只清理已确认 `Connected=True` 的现成对象**，绝不对“挂起中的 `Connect`”发 `Disconnect`，防止 BARROT 适配器假死 |
| 复用 **`Connected=True` 且 `ServicesResolved=True`** 残留连接时，Bleak 交接失败或首轮 GATT/ECDH 握手失败 | [ble/link.py](../../miband_monitor/ble/link.py) / [ble/auth_connect.py](../../miband_monitor/ble/auth_connect.py) | 打 `WARNING` 并调用 `bluez.disconnect_device()` 清除半温/失效的旧连接，下轮回到干净的 `Connected=no` 重建 | 仅当 `_reused_bluez_link=True` 时执行，不影响新连脉冲 |
| 单轮或跨 `run_monitor` 重试**连续命中 `dropped_unresolved >= 2`**（在 `ServicesResolved=True` 前就约 5 s 掉线），且确认设备当前处于 `Paired=True` | [bluez/link.py](../../miband_monitor/bluez/link.py) + [ble/link.py](../../miband_monitor/ble/link.py) `_recover_from_stale_bond()` + [cli/runner.py](../../miband_monitor/cli/runner.py) | ① `wait_for_bluez_link()` 在第 2 次未解析掉线后提前返回 `"dropped-unresolved"` 避免干等；② 调用 `bluez.remove_device()` 移除陈旧 `Device1` 对象；③ 自动拉起 `BlueZPairingAgent` 并重置 `_trusted_paths`，在剩余预算或下次重试中完成干净重配 | ① **必须 `paired_device()` 非空**（未配对设备不误删）；② 单次运行期 `_stale_bond_reset_attempted` **只触发一次**，防止手机抢链时死循环删缓存 |

---

## 5. 未来常见问题与系统化 Debug 思路

### 5.1 每次动手排查前的“首选复位与状态基线检查”

若遇到连接突然卡死、扫描持续 `other BLE=0` 或连续重试无果，**优先把硬件级 USB 复位 + 重启蓝牙栈 + `--doctor` 检查作为排查第一步**（不会清空已有配对密钥与 GATT 缓存，比直接删配对或 `power off/on` 更安全有效）：

```bash
# 0. 首选快速复位与核验（会短暂断开本机其他蓝牙外设；非 33fa:0012 请先用 lsusb 查 vid:pid）
sudo usbreset 33fa:0012 && sudo systemctl restart bluetooth
.venv/bin/python miband_client.py --doctor

# 1. 若仅做只读基线检查：确认手机蓝牙已关闭 / Zepp Life 未在后台占链
python3 miband_client.py --doctor

# 2. 查看 BlueZ 对象四状态（关注 Paired / Bonded / Trusted / Connected）
bluetoothctl info C0:FF:EE:C0:FF:EE | grep -E "Paired|Bonded|Trusted|Connected|ServicesResolved"

# 3. 检查 USB 适配器电源/控制器在线与 HCI 计数基线
hciconfig hci0
```

健康等待状态的预期输出：
- `Paired: yes`、`Bonded: yes`、`Trusted: yes`、`Connected: no`（若上一进程异常强杀留下了 `Connected: yes`，先观察重连是否自愈，或 `bluetoothctl disconnect C0:FF:EE:C0:FF:EE`）。

### 5.2 按现象快速分型与排障路径

| 现象 / 日志关键字 | 根因判断 | 确认方法 | 解决动作 |
|---|---|---|---|
| 频繁 `dropped-unresolved-after-5.xs`、`ServicesResolved=False`，`RX/TX acl=0/0` | **BlueZ 陈旧 LTK**（密钥与手环不同步） | 自愈日志是否触发 `clearing cached BlueZ bond`；或 `btmon` 看 `LE Start Encryption` 后是否回 `0x08` | **自愈未生效或仅单次尝试时**：手动 `bluetoothctl remove C0:FF:EE:C0:FF:EE`，再用 `MIBAND_BLUEZ_AGENT=1 python3 miband_client.py 30` 重建配对 |
| 建链后 ~9–9.8 s 断链，`failed to discover services, device disconnected`（`acl > 0`） | **首次 GATT 全量枚举超时**，触发手环未认证看门狗 | `Paired: no` 或刚清过缓存首次枚举 | 靠近适配器并保持手环亮屏重跑一次；一旦出现 `Trusted=yes` 与缓存建立即恢复 |
| 扫描 25 s 无**任何**周边 BLE 设备上报、`Opcode 0x2041/0x2042 failed: -112`、`Δevents == Δcommands` | **USB 适配器射频扫描状态机假死**（常见于 BARROT `33fa:0012`） | `hciconfig hci0` 两次采样对比 `events - commands == 0` 且手机都扫不到其他设备 | 必须物理/USB 级复位：`sudo usbreset 33fa:0012 && sudo systemctl restart bluetooth`（`bluetoothctl power off/on` 无效） |
| 能扫到周围其他 BLE 设备，但 90 s 内就是扫不到手环 | ① 手机仍连着手环；② 手环重启后丢了 Zepp 下发的“公共广播”状态 | 打开手机确认手环蓝牙图标状态，或用 Zepp Life 看是否直连中 | 用手机 Zepp Life 完整同步一次手环，确认退出后**关闭手机蓝牙**再试 |
| `MIBAND_BLUEZ_AGENT=1` 期间建链报错 `AuthenticationCanceled`（`0x05`） | 手环内部仍锁死在手机/原绑定端，或配对时机冲突 | `btmon` / `journalctl -u bluetooth` 见 `AuthenticationCanceled` | 确认手机蓝牙完全关闭；必要时重启手环蓝牙或在 Zepp Life 解绑重绑 |
| `already connected in BlueZ; reusing connection` 后紧接着断链或卡认证 | 上一进程强杀/挂死遗留了半温 `Connected=True` | `bluetoothctl info C0:FF:EE:C0:FF:EE` 启动前已显示 `Connected: yes` | 代码在复用失败后会自动 `disconnect_device()` 回退；也可先 `bluetoothctl disconnect C0:FF:EE:C0:FF:EE` 清零再测 |
| 历史报告 / 睡眠时间整体差 8 小时，或当日步数跨午夜切分不对 | `BAND_TZ` 未与手环本地时区一致 | `--sync-history` / `sleep_analysis.py` 未传 `--band-tz` | 传入 `--band-tz Asia/Shanghai`（或 `.env` 设置 `BAND_TZ=Asia/Shanghai`），使入库与报表口径统一 |

### 5.3 需要深度抓包取证时的标准操作

若遇到新固件或未知 D-Bus/HCI 异常，按以下无侵入流程收集完整证据（避免直接把原始 `.btsnoop` 或真实地址外发）：

1. **终端 1 启动内核/HCI 抓包**（从 `Connected=no` 干净初态开始）：
   ```bash
   sudo btmon -w /tmp/miband_btmon.btsnoop
   ```
2. **终端 2 执行复现**：
   ```bash
   python3 miband_client.py 30 --log-level DEBUG 2>&1 | tee /tmp/miband_run.log
   ```
3. **离线提取关键 HCI 事件对照时间戳**：
   ```bash
   btmon -r /tmp/miband_btmon.btsnoop | grep -E "LE Connection|Start Encryption|Encryption Change|Disconnect Complete|Pairing|LTK"
   ```
4. **提交或归档前运行仓库脱敏校验**：
   ```bash
   python3 tools/check_privacy.py
   ```
