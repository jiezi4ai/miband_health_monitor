[English](linux-ble-connect-findings.md) · **简体中文**

# Linux 下“手环经常连不上”排查纪实与根因清单（2026-11-12）

> 本文记录 2026-11-12 在 Ubuntu 24.04 / BlueZ 5.72 / 内核 6.8 上，针对
> “Linux 下手环经常无法连接”的一组受控真机实验，以及据此完成的代码修订。
> 目的是**把黑盒变成可复现的事实**：每一条结论都附有观测手段与实测数据，
> 方便以后出现回归时直接对照。
>
> 前一轮记录见 `docs/validation/linux-validation.md`（2026-11-08，L1–L10 问题清单）。

## 0. 结论速览（TL;DR）

| # | 结论 | 影响 |
|---|---|---|
| 1 | **手机蓝牙关闭后，小米手环 6 每 40–60 秒才发 1 个孤立广播脉冲**；屏幕熄灭时完全不发，**点亮/滑动屏幕不会让它发得更快** | 一切“短窗口连接 + 重新扫描”的策略都会陷入蛙跳错位，永远等不到脉冲 |
| 2 | **取消一个“挂起中”的 `LE Create Connection`（`Disconnect`/超时取消）会让 BARROT `33fa:0012` 适配器扫描静默假死**：HCI 命令照常回复，空口广播事件恒为 0 | 现场表现为“扫描器正常启动但一个包都收不到”，只有 USB 级复位能恢复 |
| 3 | `bleak` **3.0.2** 把 `le-connection-abort-by-local` 误判为“曾经连上过”，会等待一个永不到来的 `Connected=false`，**卡死 41 秒** | 单次 `connect()` 无法跨过内核 40 秒发起周期，必须自己接管重挂 |
| 4 | BlueZ 在 `ServicesResolved` 之后仍要跑 SMP（`new_auth`）与内置 HID/device-info 探测，此时**第一条 GATT 写/`start_notify` 会堵在单条 ATT 队列后面**（实测 56.8 秒） | 认证第一步不能紧贴 `ServicesResolved` 发出，必须留结算窗口并加超时 |
| 5 | `DuplicateData=True` 在 BT 5.x/6.x 上让 BlueZ **每 ~5 秒重启一次扩展扫描**（75 秒内 31 条 `0x2041/0x2042`） | 是该适配器假死的诱因之一，默认值已改为 `False` |
| 6 | 历史上（11-09）连续 9 次成功会话**都是在 `Trusted=True` 下完成的**，`hog-lib` 报错是在会话结束断链时才结算打印，**不是阻塞根因** | 不应为了躲 HID 插件而关掉 `Trusted`；`Trusted` 反而是内核自动回连与 GATT 缓存的前提 |
| 7 | “扫到 → 立刻 `Connect`”是有效的（10 ms 内送达即可撞上同一簇广播尾帧），**但前提是不能中途取消** | 本次修订把它固化为 `wait_for_bluez_link()` 待命循环 |

## 1. 环境

| 项 | 值 |
|---|---|
| 主机 | Ubuntu 24.04.5 LTS，内核 `6.8.0-147`，x86-64 |
| 蓝牙栈 | BlueZ `5.72`，`bluetooth.service` active |
| 适配器 | `hci0`，USB `33fa:0012`，**BARROT Bluetooth 6.0 Adapter**（厂商 ID 2279） |
| 适配器电源 | `/sys/bus/usb/devices/6-4/power/control = auto`，`autosuspend_delay_ms = 2000` |
| Python | 3.13（conda），`bleak 3.0.2`，`dbus-fast` |
| 手环 | Mi Smart Band 6，MAC `C0:FF:EE:C0:FF:EE`（公共地址，非 RPA） |
| 已配对设备 | AirPods、LIFT 鼠标、花再音箱等（BLE 扫描期间会争夺控制器） |

## 2. 观测方法（可复用）

1. **HCI 空口事件差值法**（本轮最关键的工具）。`hciconfig hci0` 的 `events`
   统计“收到的 HCI 事件”，含 `Command Complete` 与 `LE Meta`。
   一次采样窗口内：

   ```
   air_events = Δevents − Δcommands
   ```

   - `air_events > 0`：控制器真的把空口包上报给了主机（射频正常工作）；
   - `Δevents == Δcommands`（即 `air_events == 0`）：**主机下发的每条命令都只回了
     `Command Complete`，没有任何广播上报** —— 此时说“手环没广播”与“适配器聋了”
     在应用层无法区分，必须结合“是否有别的设备在广播”以及 USB 复位后是否恢复来判断。

2. **`journalctl -u bluetooth` / `journalctl -k`**：抓 `new_auth()`、`hog-lib.c`、
   `Opcode 0x2041/0x2042 failed: -112`、`start background scanning failed: -112`。

3. **只扫不连探针**（唯一不改变硬件状态的测量）：连续扫描 N 秒、**绝不调用
   `Connect`/`Disconnect`**，逐包记录到达时间戳、`Δt`、RSSI、`ManufacturerData`
   与 `ServiceData`。这一探针跑完适配器保持健康，可连续复测。

4. **数据落盘交叉验证**：`data/heart_rate.jsonl`、`data/steps.jsonl` 的
   `iso_time` 是“真的认证成功并采到数据”的硬证据，可用来反查当时的
   `journalctl` 记录（本轮据此纠正了“11-09 成功是因为 `Trusted=False`”的误判）。

## 3. 受控实验时间线

时间均为本机 UTC（`TZ=Etc/UTC`）。

| 编号 | 时间 | 操作/条件 | 关键观测 | 结论 |
|---|---|---|---|---|
| 2A-2 | 06:33:07–06:34:16 | `Trusted=False`，亮屏滑屏 | 抓到脉冲后 5.8 s 建链，8.7 s 内交换 `acl_tx=+166 / acl_rx=+165`，随后 `failed to discover services, device disconnected`；`hog-lib.c` 报错 **0 条** | 物理链路与 GATT 枚举都在进行，被手环 ~9 s 未认证看门狗踢掉 |
| 2A-3 | 06:38:06、06:38:11 | 预检扫描 `stop()` 后 1 ms 立刻 `Powered=false` | `Opcode 0x2041 failed: -112`、`start background scanning failed: -112`，随后 75 s 零广播 | 扫停与电源切换的竞态会直接打坏扩展扫描状态机 |
| 2A-4 | 06:43–06:47 | 仅 D-Bus `Powered=false/true` 复位 | 75 s 内 `commands=+31 / events=+31`，`air_events=+0` | **D-Bus 软复位恢复不了射频**，必须 USB 级复位 |
| 2A-5 | 06:49:24 / 06:50:05 / 06:50:57 | USB 复位后，`DuplicateData=False` | 三个脉冲间隔 **40.5 s / 52.2 s**；每次 `Connect(15~20 s)` 均 `acl=0` | 脉冲周期 > 连接窗口，形成“蛙跳错位”：每次脉冲都被扫描器吃掉 |
| 2A-6 | 07:54:44 → 07:55:59 | 抓脉冲后 10 ms 内 `Connect`，分段续挂 | 建链成功 `acl_tx=+7 / acl_rx=+6`，9.76 s 被踢；0.15 s 后原地重挂；07:55:02 `le-connection-abort-by-local`；**bleak 空等 41.11 s**；BlueZ 对象在停止扫描后 59.6 s 仍存活 | ① “抓包即连”可行；② bleak 3.0.2 有 abort 死锁；③ 待命中的 `Connect` 能阻止对象被回收 |
| 2A-7 | 08:05:57 → 08:07:22 | 35 s 切片超时后 bleak 自动 `Disconnect` | 取消挂起连接后进入重扫，50 s 内 `air_events=+0` | **取消挂起 `Connect` 会把适配器弄聋**（与 2A-3 同源） |
| 2A-8 | 08:23:00 → 08:24:56 | USB 复位后 `Trusted=True` + 单次 `Connect(95 s)` | 115 s 内 `acl=0`，两个完整内核 41 s 发起周期，系统零报错，对象 `UUIDs` 只有 `0xfee0`（无 `0x1812`） | 首次建链前 `Trusted` 无法凭空空口触发；仍需一次真实脉冲命中 |
| **1-A** | 08:31:21–08:31:56 | 手环停在**“心率”测量页**，只扫不连 35 s | **仅 1 个包**（`t=+21.7 s`，RSSI −54，`ServiceData 0x1074 = 4212 步`），其余时间 `air_events=0` | 心率页**不会**带来密集广播 |
| **1-B** | 08:35:17–08:35:52 | 主表盘/菜单**连续上下滑动**，只扫不连 35 s | **0 个包**（`air_events=0`） | **滑屏不触发广播**，与文档旧描述相反 |
| 历史对照 | 11-09 23:25–23:41 | 旧代码（`c220a97e`，`Trusted=True`） | **9 次会话全部认证成功**：心率 50 条（79–101 bpm）、步数 93 条、IMU 929 条、历史 1188 条；同期 `bluetoothd` 在 **23:26:10 / 23:31:33 / 23:34:28** 打印 `hog-lib.c ... unlikely error` | HID 报错是**断链时结算**打印的，不是阻塞根因；`Trusted=True` 是成功路径 |
| 历史对照 | 06:12–06:19 | 未提交代码（`Trusted=True`） | 6 次自动回连，间隔约 61 s，每次都走到 `new_auth()` | 只要 GATT 表被缓存，内核自动回连可靠 |

### 3.1 单脉冲广播到底长什么样

`1-A` 抓到的唯一样本：

```
mfg  = 343: 02ffff...ff02 f229feea46be   # 华米厂商数据，尾部 0x02 = 可连接标志
svc  = 0000fee0...: 74100000             # 0x1074 = 4212 步（小端）
rssi = -54 dBm
```

即：**脉冲本身携带实时数据且是可连接广播（`ADV_IND`）**，只是出现频率极低。
另有一台已绑定设备的 `ServiceData` 在多次采样中随步数变化，说明载荷是实时的。

## 4. 根因清单

### R1 · 单脉冲广播 + 短连接窗口 = 蛙跳错位（P0）
- **现象**：反复出现“扫得到、连不上”，或每两次脉冲才成功一次。
- **证据**：2A-5 三个脉冲 `40.5 s / 52.2 s` 间隔；每次 `Connect` 只等 15–20 s 就超时退回扫描。
- **机制**：脉冲到达 → 扫描器消费 → 进 `Connect` 等 20 s（错过下一次脉冲）→ 退回扫描 →
  下一次脉冲又被扫描器吃掉……相位永久错开。
- **修订**：`bluez_support.link_standby_budget()` 保证预算 ≥ `BAND_PULSE_PERIOD`（70 s）；
  `_open_bluez_link()` 不再在重试中回到扫描。

### R2 · 取消挂起连接 → 适配器扫描假死（P0，最隐蔽）
- **现象**：扫描器启动正常、`hciconfig` 计数在涨，但 `air_events` 恒 0，一个包都收不到。
- **证据**：2A-3（扫停后 1 ms 切电源 → `-112`）、2A-7（35 s 超时 `Disconnect` 后 50 s 零广播）、
  2A-4（`Powered=false/true` 无法恢复，`commands=+31 / events=+31`）。
- **结论**：`-112 = -EHOSTDOWN`，需要 **USB 端口级复位**（`usbreset` 或拔插）。
- **修订**：待命循环**永不主动 `Disconnect`**；`disconnect_device()` 增加“仅用于清理幽灵连接”的
  文档约束；扫描心跳在“连续 25 s 零包”时打印明确复位指引。

### R3 · bleak 3.0.2 在 `le-connection-abort-by-local` 上死锁 41 s（P1）
- **证据**：2A-6 `07:55:02.691 → 07:55:43.802`；源码中该分支无条件
  `await local_disconnect_monitor_event.wait()`，而内核从未连上时 BlueZ 不会发 `Connected=false`。
- **修订**：不再让单次 `bleak.connect()` 承担跨周期任务；由
  `bluez_support.wait_for_bluez_link()` 直接用 D-Bus 维持一个 `Device1.Connect`，
  abort 后 ~150 ms 重挂，成功后再把已建立的连接交给 `bleak`。

### R4 · SMP / 内置 profile 探测抢占 ATT 队列（P1）
- **证据**：`06:12:11.767` `ServicesResolved` → 1 ms 后 `start_notify(0x0017)` 发出 →
  `06:12:13` `new_auth() No agent available` → 卡 56.8 s。
  另 2A-2 中 `hog-lib.c` 的 `unlikely error` 在断链瞬间集中结算。
- **修订**：`_settle_after_link()` 在 `ServicesResolved` 后等待 `SMP_SETTLE_DELAY`（默认 1.5 s，
  可用 `MIBAND_SMP_SETTLE_DELAY` 覆盖）；`_start_chunked_listener()` 用 6 s × 2 次的有界重试
  替代裸 `await`。

### R5 · `DuplicateData=True` 的 5 秒重启风（P1）
- **证据**：75 s 扫描期间 `commands=+31`，正好 15 个周期 ×2 +1。
- **修订**：`scanner_kwargs()` 默认 `DuplicateData=False`；保留
  `MIBAND_BLUEZ_DUPLICATE_DATA=1` 供实验。

### R6 · 陈旧 RSSI 假直连（P1）
- **证据/机制**：`Trusted=True` 的对象会长期保留最后一个 `RSSI`，
  “有 RSSI 就算新鲜”不成立。
- **修订**：`_direct_connect_target()` 只接受 **bonded** 设备或真正 `Connected+ServicesResolved`
  的连接；`active_cached_device()` 标记为 legacy 且不再被调用。

### R7 · 嵌套重试导致总预算失控（P1）
- **证据**：旧 `_connect_with_transient_retry` 每次 15 s 超时后嵌套 `_discover_device(45 s)`，
  最坏 `10 + 90 + 3×(15+45) + 15 ≈ 295 s`，架空了 `duration`。
- **修订**：预算由 `connect_timeout`（默认 75 s，`link_standby_budget()` 兜底 70 s）统一约束；
  重试不再嵌套扫描。

### R8 · 文档与提示误导（P2）
- “点亮并滑动屏幕即可广播” → 实测无效；
- “`bluetoothctl pair` 先配对” → 仍绑定手机的手环常回 `AuthenticationCanceled` 并触发删缓存；
  正确的一步是 `trust`（`pair` 仅在内置 agent 场景下可选）；
- `--doctor` 把“未配对”说成必然 40 s 断链，与实测（~9 s 枚举看门狗、`Trusted` 即可自动回连）不符。
- **修订**：`doctor.py` 文案、`describe_ble_error()`、本文与 `docs/guides/cross-platform.md`、`README.md` 同步更新。

### R9 · 未认证看门狗（~9–9.8 s）与首次全量枚举（P1，硬件约束）
- **证据**：亮屏活跃态 3.7 s 枚举完 = 成功；刚息屏 8.7 s 交换 331 包后被踢；深休眠 9.76 s 仅 6 轮。
- **结论**：首次连接（BlueZ 尚无 GATT 缓存）要求建链瞬间手环处于“刚被唤醒”的高速连接间隔；
  一旦 BlueZ 缓存了服务表，后续连接不再需要完整枚举。
- **对策**：这次修订负责“把连接窗口拉够长 + 抓住第一个可用脉冲”；
  “建链瞬间的物理状态”仍取决于手环是否刚被唤醒（见 §7 待验证项）。

## 5. 代码修订对照

| 文件 | 变更 | 对应根因 |
|---|---|---|
| `bluez_support.py` | 新增 `LE_CONN_TIMEOUT`、`CONNECT_SLICE_TIMEOUT`、`BLUEZ_TEMP_OBJECT_TIMEOUT`、`BAND_PULSE_PERIOD`、`SMP_SETTLE_DELAY`、`link_standby_budget()` | R1/R3/R4/R7 |
| `bluez_support.py` | 新增 `wait_for_bluez_link()`：单条长驻 `Device1.Connect` + 属性轮询 + abort 后 ~150 ms 重挂，绝不 `Disconnect` | R1/R2/R3 |
| `bluez_support.py` | `scanner_kwargs()` 默认 `DuplicateData=False`，`MIBAND_BLUEZ_DUPLICATE_DATA=1` 可恢复 | R5 |
| `bluez_support.py` | `is_transient_connect_error()` 补入 `failed to discover services`、`device disconnected`、`Not connected`、`Try again` | R9 |
| `bluez_support.py` | `describe_ble_error()` 重写超时 / abort / `-112` 文案；`UnknownObject` 改为 `trust` 指引 | R8 |
| `bluez_support.py` | `active_cached_device()` 标注 legacy；`disconnect_device()` 增加“禁止用于挂起连接”说明 | R2/R6 |
| `miband_client.py` | `_open_client()` 分流为 `_open_bluez_link()` / `_open_generic_link()` | R1/R7 |
| `miband_client.py` | `_open_bluez_link()`：`Trusted` 前置 → 长驻待命 → 链接就绪后交给 bleak | R1/R2/R3/R6 |
| `miband_client.py` | `_connect_with_transient_retry()` 去掉嵌套重扫，仅原地重试 | R7 |
| `miband_client.py` | 新增 `_settle_after_link()`、`_start_chunked_listener()`（6 s × 2 有界重试） | R4 |
| `miband_client.py` | `_discover_device(deadline=...)` + 心跳统计；连续 25 s 零包时告警并给出 `usbreset` 指引 | R2/R8 |
| `miband_client.py` | `DEFAULT_CONNECT_TIMEOUT = 75.0`；`--connect-timeout` 帮助文本说明 70 s 脉冲周期 | R1 |
| `miband_client.py` | 模块 docstring 更正“亮屏才广播”的错误描述 | R8 |
| `doctor.py` | 未配对/未信任提示改为 `trust` 优先；新增“单脉冲广播”说明行 | R8 |
| `tests/` | 新增 `wait_for_bluez_link` 就绪转交、超时不 `Disconnect`、`DuplicateData` 默认值、abort 文案等用例 | — |
| `docs/` | 本文 + `linux_validation.md` §8 + `cross_platform.md` / `README.md` 更正 | R8 |

环境变量速查：

| 变量 | 默认 | 作用 |
|---|---|---|
| `MIBAND_BLUEZ_TRUST` | `1` | `0` 时不设置 `Trusted=True`（A/B 实验用） |
| `MIBAND_BLUEZ_DUPLICATE_DATA` | `0` | `1` 恢复 `DuplicateData=True` |
| `MIBAND_SMP_SETTLE_DELAY` | `1.5` | `ServicesResolved` 后的结算等待秒数 |
| `CONNECT_TIMEOUT` / `--connect-timeout` | `75` | 单次连接预算（Linux 上至少 70 s） |
| `SCAN_TIMEOUT` / `--scan-timeout` | `90` | 等待首个脉冲的时间（脉冲周期 40–60 s） |

## 6. 现场处置手册（Runbook）

1. **确认物理前提**：手机蓝牙/飞行模式关闭；手环近期连过一次 Zepp Life
   （公共广播是由 App 下发并保持的易失状态，手环重启会丢）。
2. **先自检**：`python3 miband_client.py --doctor` 看适配器 `powered`、设备
   `trusted/connected`、`.env` 权限。
3. **判断适配器是否假死**：跑一次只扫探针（例如
   `python3 scan_live.py`，或直接用主程序观察
   `hci_air_events` / 心跳中的 `other BLE` 计数）。
   - 若 25–35 s 内**连别的设备都没有**一个包：适配器大概率已聋 →
     `sudo usbreset 33fa:0012 && sudo systemctl restart bluetooth`
     （`Powered=false/true` **不行**，实测无效）；
   - 若能看到其他 BLE 设备但看不到手环：手环侧广播未使能或不在范围内。
4. **正常采集**：`python3 miband_client.py 60 --imu --log-level DEBUG`。
   首个脉冲 40–60 s 才出现属正常，程序会把 `Connect` 一直挂着等它。
5. **判读日志**：
   | 日志 | 含义 | 处理 |
   |---|---|---|
   | `BlueZ link to ... is up and services are resolved` | 建链成功 | 正常继续 |
   | `le-connection-abort-by-local` | 本轮脉冲没撞上，已自动重挂 | 等下一轮，无需干预 |
   | `failed to discover services, device disconnected` | 手环 ~9 s 看门狗踢断（枚举没跑完） | 自动重试；让手环亮屏可提高成功率 |
   | `-112` / `host is down` | 适配器状态机卡死 | USB 复位 + 重启 bluetooth |
   | `No BLE packet from ANY device` | 射频层面无上报 | 同上一行 |
6. **首次连接失败是正常的**：未配对时手环只给 ~9–9.8 s 枚举窗口，
   若当时处于深休眠连接间隔就必然被踢；`Trusted=True` 后 BlueZ 缓存服务表，
   第二次连接会快得多。

## 7. 仍未解决的问题（下一步验证）

1. **为什么 2A-8 中 `Trusted=True` + 单次 95 s `Connect` 完全 `acl=0`，而
   06:12 的一次普通 `Connect` 5.8 s 就成功？** 可能与该次适配器刚复位后的
   广播簇相位、或 `Device1.Connect` 与内核 auto-connect 的冲突有关，需要 `btmon`
   空口层证据（抓 `LE Create Connection` / `LE Connection Complete` 的精确时刻）。
2. **`1-B` 的 0 包究竟是“手环没发”还是“适配器又聋了”**：本轮 `air_events=0`
   只能证明“没有上报”，无法区分两者。下一步应在只扫不连探针里同时抓 `btmon`，
   或在探针前后各加一次“其他 BLE 设备可见性”对照。
3. **Zepp Life 的“运动心率广播”开关是否只在特定模式（如手环运动模式）下生效**：
   本轮 1-A/1-B 已证明表盘/心率页都不会加速广播，但手环固件菜单里没有该开关，
   需要一次“开启自由训练”的对照（测试 1-C）来确认。
4. **能否让 BlueZ 缓存持久化后彻底免扫描**：按 06:12–06:19 的证据，`Trusted=True`
   + 已缓存 GATT 表时内核 auto-connect 每 ~61 s 成功一次；需要验证在
   “进程退出 → 再启动”之间该缓存是否仍然有效。
5. **`-112` 的确切触发面**：本轮只确认了“扫停 + 电源切换”与“取消挂起 `Connect`”
   两类，是否需要更广的“禁止在扫描活跃期做任何电源/连接取消操作”的硬约束，
   待空口层证据。

## 8. 复现实验最小脚本骨架

```python
# 只扫不连：验证广播规律，永不改变适配器状态
import asyncio, time
from bleak import BleakScanner

async def main(duration=35.0):
    t0 = time.monotonic()
    def cb(dev, adv):
        if dev.address.upper() == "C0:FF:EE:C0:FF:EE":
            print(f"+{time.monotonic()-t0:.3f}s rssi={adv.rssi} svc={adv.service_data}")
    scanner = BleakScanner(detection_callback=cb,
                           bluez={"filters": {"DuplicateData": False, "Transport": "le"}})
    await scanner.start()
    await asyncio.sleep(duration)
    await scanner.stop()

asyncio.run(main())
```

`hciconfig` 差值检查：

```bash
hciconfig hci0 | grep -E "RX bytes|TX bytes"   # 前后各取一次，算 Δevents-Δcommands
```
