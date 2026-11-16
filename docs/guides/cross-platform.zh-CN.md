[English](cross-platform.md) · **简体中文**

# 跨平台运行与验证指南（Linux / Windows / macOS）

本项目最初在 Linux（BlueZ）上开发，现已做代码层跨平台改造。BLE 访问由
[`bleak`](https://github.com/hbldh/bleak) 统一封装（Linux/BlueZ、Windows/WinRT、
macOS/CoreBluetooth），因此不需要为每个系统维护一套蓝牙代码；跨平台差异集中在
**ECDH 原生库加载**、**设备标识格式** 和 **ATT MTU 上报** 三处，均已处理。

> 文档导航：[文档中心](../README.zh-CN.md) · [安装](installation.zh-CN.md) · [配置](configuration.zh-CN.md) ·
> [使用](usage.zh-CN.md) · [测试](testing.zh-CN.md)
>
> 本指南同时是 Windows/Linux 真机验证的操作清单；测试结果请按
> [§7 反馈信息](#7-提交问题或验证结果时需要的信息) 收集。

---

## 1. 平台支持矩阵

| 项目 | Linux | Windows 10/11 | macOS 12+ |
|---|---|---|---|
| BLE 后端 | BlueZ（`dbus-fast`） | WinRT（`winrt-*`） | CoreBluetooth（`pyobjc`） |
| 设备标识 | 蓝牙 MAC | 蓝牙 MAC | **CoreBluetooth UUID**（不暴露 MAC） |
| 名称匹配 `DEVICE_NAME` | 支持 | 支持 | 支持（推荐） |
| ECDH 后端 | 原生 `libecdh.so`（自动编译） | 纯 Python（可选手动放 `libecdh.dll`） | 纯 Python（可选手动编译 `.dylib`） |
| 状态 | 已验证（软件链路 + 真机，需先配对） | **待真机验证** | 代码兼容，待验证 |

ECDH 后端选择规则（实现见 `miband_monitor/crypto/`）：

1. `MIBAND_ECDH_LIB` 指定的库 → 2. 项目根目录下当前平台的库文件
（`libecdh.so` / `libecdh.dll` / `libecdh.dylib`）→ 3. 尝试用 `gcc`/`clang` 现场编译 →
4. 纯 Python 回退（`vendor/tiny_ecdh/`）。

启动日志会打印实际使用哪个后端：

```
[INFO] MiBand6Client: ECDH backend: native      # Linux 常见
[INFO] MiBand6Client: ECDH backend: python      # Windows/macOS 常见
```

可用环境变量强制切换以便排查：`MIBAND_ECDH_BACKEND=auto|native|python`。
两种后端已做逐字节交叉校验（`tests/test_ecdh_backends.py`），可安全互换。

---

## 2. Linux

### 2.1 依赖

```bash
# Debian/Ubuntu 示例
sudo apt-get install -y python3-venv python3-pip bluez
sudo systemctl enable --now bluetooth
```

### 2.2 安装与冒烟测试

```bash
cd miband_health_monitor
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 环境自检：适配器 / 配对状态 / ECDH 后端 / .env 权限，一次看全
.venv/bin/python miband_client.py --doctor

# 无硬件：单元测试 + 全链路 demo
.venv/bin/python -m pytest -q
.venv/bin/python miband_client.py --demo 2 --imu --output data/demo --export-csv
```

### 2.3 真机（区分“首次无缓存配对”与“已有缓存日常使用”）

Linux/BlueZ 与 Windows 不同：系统不会在无 agent 时自动完成 SMP 配对；且**首次连接尚无 GATT 缓存时，
手环只给约 9–9.8 秒的未认证枚举窗口**（需逐个读取 ~150 个句柄），若当时手环处于休眠连接间隔会被踢断，
日志表现为 `failed to discover services, device disconnected` 或
`UnknownObject: Method "WriteValue" ... doesn't exist`。

#### 场景 A：首次配对 / 主机无 BlueZ 设备缓存

当你刚在 `--doctor` 看到 `device not known to BlueZ yet`（新主机，或刚执行过 `bluetoothctl remove` 清空缓存）时：

```bash
# 0) 自检：确认适配器 powered=yes 且手机蓝牙已关闭
.venv/bin/python miband_client.py --doctor

# 1) 填好配置（至少 DEVICE_ID 与 AUTH_KEY）
cp .env.example .env

# 2) 推荐方式：开启进程内配对 agent，直接走首次扫描 + 自动信任 + SMP 配对
#    （保持手环在 1 米内并尽量亮屏/佩戴，便于 ~9s 看门狗内完成首次 GATT 枚举）
MIBAND_BLUEZ_AGENT=1 .venv/bin/python miband_client.py 60 --log-level INFO
```

**首次无缓存配对机制与注意事项：**
- **无需手敲 `bluetoothctl pair`**：带 `MIBAND_BLUEZ_AGENT=1` 运行时，客户端会在扫描捕获 40–60s 脉冲后、发起 `Device1.Connect` 之前自动设置适配器 `Pairable=on` 与设备 `Trusted=True`，并用内置 `NoInputNoOutput` agent 放行目标手环的 SMP 请求；若刚好卡在超时边缘连上，还会触发 10 秒 `SERVICE_RESOLVE_GRACE` 宽限确保首次枚举完成。
- **不建议直接手工提前 `pair`**：若手机端仍未断开或持有互斥绑定，手工 `bluetoothctl pair` 容易直接被手环拒绝（`AuthenticationCanceled`）。
- **必须保留的 `.env` 凭证**：删除主机 BlueZ 缓存不影响 `.env`；但如果你还对手环做了**恢复出厂设置或 Zepp Life 解绑重绑**，手环内置 `AUTH_KEY` 会更新，必须重新提取并更新 `.env` 才能通过应用层 ECDH 认证。
- **公共广播前提**：手环重启后可能丢失易失“公共广播”状态；若 120s 仍扫不到脉冲，先用手机 Zepp Life 连一次手环再关掉手机蓝牙。

#### 场景 B：已有设备缓存 / 正常日常复连（勿盲目删配对）

当你用 `--doctor` 看到设备已处于 `paired=yes trusted=yes`（首次配对完成后就会持久写入 BlueZ）：

```bash
# 日常直接运行即可，不要再加 MIBAND_BLUEZ_AGENT=1，也不要每次先 bluetoothctl remove
.venv/bin/python miband_client.py 60
```

**有缓存情况下的重要原则：**
1. **切勿每次连接前都清空 BlueZ 缓存**：每次 `remove` 都会销毁 GATT 服务表缓存与 `direct connect` 免扫描快路径，重新暴露在 ~9s 未认证看门狗下；若手机端未彻底断连还会增加 `AuthenticationCanceled` 概率。
2. **手机 Zepp Life 正常同步不会破坏现有配对**：实测证明手机端完成同步并关闭蓝牙后，Linux 侧已有 `Paired / Bonded / Trusted` 密钥依然完好，直接默认命令即可 1 次直连成功（`0 WARNING / 0 ERROR`）。
3. **何时才需要清缓存重配（与自动自愈）**：仅当手环换绑其他主控导致 BlueZ 持有的 `LTK` 陈旧失效（典型症状为建链后约 5 秒且 `ServicesResolved=False` 掉线）时才需要重配。客户端在连续命中 2 次未解析断链且确认设备为 `Paired=yes` 时会自动调用 `remove_device()` 清缓存并拉起 agent 自愈；如需手动恢复，可执行：
   ```bash
   bluetoothctl remove AA:BB:CC:DD:EE:FF
   MIBAND_BLUEZ_AGENT=1 .venv/bin/python miband_client.py 60
   ```
4. **若上次强杀留下 `Connected=yes` 残留**：客户端会自动清理幽灵连接（`Connected=True, ServicesResolved=False`）；若复用半温连接（`Connected=True, ServicesResolved=True`）时握手失败，也会主动 `disconnect_device()` 回退到干净初态重连。

（如需手工执行传统只 trust 不 pair 的旧步骤，可执行 `bluetoothctl scan on` 捕捉脉冲后 `bluetoothctl trust AA:BB:CC:DD:EE:FF`。）

关于广播频率（**已实测，与旧文档相反**）：手机蓝牙关闭后，小米手环 6
**每 40–60 秒才发出 1 个孤立的可连接广播脉冲，屏幕熄灭时完全不发**；
点亮或滑动屏幕**不会**让它发得更快，只影响建链后的连接间隔。
因此 Linux 路径改为：扫到第一个脉冲后**把一个 `Device1.Connect` 一直挂着**
（最长 70 秒，覆盖整个脉冲周期），而不是"连 15 秒失败就回去重扫"。

`trust` / 首次配对持久化之后：

- BlueZ 会保留设备对象与 GATT 缓存；后续连接不再需要重新枚举 150 个句柄，
  内核还能在手环出现时自动回连（实测 2026-11-12：连续 6 次自动回连，间隔约 61 秒）；
- 连接不再依赖"恰好扫到广播期间按下回车"——待命中的 `Connect` 会等到脉冲；
- ATT MTU 会显式协商（此前恒为 23 字节）。

详细证据与实测报告见 [Linux 连接排查纪实](../validation/linux-ble-connect-findings.zh-CN.md) 与
[Linux BLE 受控复测与陈旧 LTK 报告](../validation/linux-ble-test-report.zh-CN.md)。

### 2.4 常见问题

> **排查首选（Linux 突然连不上/扫不到时第一步执行）**：
> ```bash
> sudo usbreset 33fa:0012 && sudo systemctl restart bluetooth   # 若非 33fa:0012 请先用 lsusb 查 vid:pid
> .venv/bin/python miband_client.py --doctor
> ```
> **为什么将其作为首选（优于重启程序、`power off/on` 或删配对）**：
> 1. **直接解除射频假死**：BARROT `33fa:0012` 等 USB 适配器在扫描竞态或异常断链后会出现“HCI 命令仍回复，但空口广播完全聋掉（`other BLE=0`）”的硬件状态机卡死，D-Bus `Powered=false/true` 实测无效，只有 `usbreset` 能冷清零芯片寄存器；
> 2. **零破坏且保留现有配对**：`systemctl restart bluetooth` 让 `bluetoothd` 重新接管 `hci0` 并清除 D-Bus 僵死状态，同时**不会删除**磁盘上现有的 `Paired / Bonded / Trusted` 密钥与 GATT 缓存；
> 3. **`--doctor` 立刻确认就绪**：确认 `powered=yes`、`paired=yes trusted=yes`、`connected=no` 后即可直接开跑（注意操作会短暂断开主机其他蓝牙外设）。

| 现象 | 处理 |
|---|---|
| `org.bluez was not provided` / `No Bluetooth adapters found` | `bluetooth` 服务未运行或无适配器；WSL2 不支持蓝牙，请用原生 Linux |
| 扫描不到 | 手机蓝牙关闭；确认手环的公共广播仍被使能（用 Zepp Life 连一次，再关手机蓝牙）。手环每 40–60 秒才发一个脉冲，`--scan-timeout` 用 120。若**任何设备的包都收不到**，见下一行 |
| 扫描器在跑、`hciconfig` 计数在涨，但 25 秒内**一个 BLE 包都没有** | 适配器射频假死（BARROT `33fa:0012` 在取消挂起连接后会出现）：`sudo usbreset <vid:pid>` 或拔插 USB，再 `sudo systemctl restart bluetooth`。**D-Bus 的 `Powered=false/true` 无效** |
| 权限不足 | 普通用户通常可用；若受限，检查 polkit/`bluetooth` 组或使用桌面会话 |
| 建链后 9–10 秒被断，日志 `failed to discover services, device disconnected` | 手环的未认证连接看门狗到期（首次连接要枚举 ~150 个 GATT 句柄）。客户端会自动重试；`trust` 一次后 BlueZ 缓存服务表即可避免 |
| 连上 40 秒左右就断，日志 `UnknownObject ... doesn't exist` | 未 `trust`。先让 `bluetoothctl trust <MAC>` 生效；确需 Bond 时才 `pair`（仍绑定手机的手环会 `AuthenticationCanceled`） |
| 连接时 BlueZ 日志出现 `No agent available for request type 2` | 手环发起了 SMP 认证而系统没有 agent。`MIBAND_BLUEZ_AGENT=1` 让客户端注册 `NoInputNoOutput` agent 自动放行 |
| 日志出现 `le-connection-abort-by-local` | 内核 40 秒发起周期内没等到手环脉冲；客户端会自动重挂，无需干预 |
| 启动日志 `MTU=23` 并伴随 `Using default MTU value` 警告 | 旧版本行为；当前版本会主动协商。若仍出现，加 `--log-level DEBUG` 查看 `_acquire_mtu` 失败原因 |
| 每次都要等几十秒才连上 | 正常：无手机链路的手环每 40–60 秒才发一个脉冲。`trust` 一次后 BlueZ 会缓存 GATT 表并自动回连，第二次开始通常几秒内完成 |

### 2.5 Linux 专属行为说明

| 行为 | 说明 |
|---|---|
| 直连优先 | 已真正绑定（bonded）设备从 BlueZ 对象树直接连接；`Connected+ServicesResolved` 的连接直接复用；不再信任"有 RSSI 就算新鲜"的缓存对象 |
| 待命建链 | 扫到脉冲后由一个长驻 `Device1.Connect` 覆盖整个 70 秒广播周期，内核 40 秒 abort 后约 150 ms 自动重挂；**全程不发 `Disconnect`**（取消挂起连接会让部分适配器扫描假死） |
| 内置配对 Agent | `MIBAND_BLUEZ_AGENT=1` 时在系统 D-Bus 注册 `org.bluez.Agent1`（`NoInputNoOutput`），自动放行目标手环 SMP 请求；首次无缓存配对建议开启，已有健康配对后无需开启 |
| 服务解析宽限 | 若在 70 s 待命预算截止前恰好物理建链（`Connected=True`），`wait_for_bluez_link()` 额外授予 10 s `SERVICE_RESOLVE_GRACE` 避免打断首次 GATT 枚举 |
| 残留连接自愈 | 发现 `Connected=True, ServicesResolved=False` 幽灵残留时先清再连；复用已连接对象却建链/认证失败时主动 `disconnect_device()` 回退干净状态 |
| 陈旧 LTK 自愈 | 若已配对设备连续命中 `dropped_unresolved >= 2`（约 5 s 加密超时掉线），自动 `remove_device()` 并临时拉起配对 agent 重建干净绑定（每次运行至多一次） |
| 扫描参数 | `DuplicateData=False`（BT 5/6 上 `True` 会让 BlueZ 每 ~5 秒重启扩展扫描）；`MIBAND_BLUEZ_DUPLICATE_DATA=1` 可恢复 |
| SMP 结算等待 | `ServicesResolved` 后等 1.5 秒再发第一条 GATT 写，避免堵在 BlueZ 的 `new_auth` + HID/device-info 探测后面 |
| Fast Retry | 遇 `le-connection-abort-by-local`、`InProgress`、`failed to discover services` 原地重试，不再嵌套重扫 |
| GATT 写锁 | 引入类 Gadgetbridge `BtLEQueue` 机制，写操作全局串行化，遇 `InProgress` 自动重试 |
| 极速重连 | 会话认证成功后重置退避延迟，意外断连后以 0.3s 极速重连，抓住断开瞬间高频广播窗口 |
| `--no-direct-connect` | 强制走扫描路径，便于排查"直连拿到的是旧对象"这类问题 |
| MTU 协商 | 连接后调用 bleak 的 `_acquire_mtu()`；WinRT 由系统自动完成 |
| 配对状态 | `Trusted: yes` 是内核自动回连与 GATT 缓存的前提；`Paired: yes` 仅在需要加密链路/Bond 时必要 |
| 适配器复位 | BARROT `33fa:0012` 出现 `-112`/零广播后只能 USB 级复位，D-Bus 电源循环无效；`--doctor` 与扫描心跳都会给出该提示 |

---

## 3. Windows 10/11

### 3.1 Python 与依赖

推荐从 [python.org](https://www.python.org/downloads/) 安装 Python 3.10+（勾选
“Add python.exe to PATH”），不要用 Microsoft Store 的 Python 做 BLE 开发时仍可用，
但 python.org 版本排查更方便。

```powershell
cd miband_health_monitor
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`bleak` 会自动安装 WinRT 相关依赖（`winrt-runtime`、`winrt-windows-devices-bluetooth` 等），
无需手工处理，也不需要 Visual Studio / gcc。

### 3.2 冒烟测试（不需要手环）

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe miband_client.py --demo 2 --imu --output data\demo --export-csv
```

预期：全部通过（当前 `241 passed, 4 skipped`，跳过项需要真实抓包数据）；
demo 生成 `data\demo\*.jsonl`、`mi_band.db` 与 `csv\`。
这两步通过说明 Python、依赖、ECDH 纯 Python 后端、存储、看板、导出链路在
Windows 上都正常，剩下的只有真实 BLE 链路。

### 3.3 蓝牙环境检查

1. “设置 → 蓝牙和其他设备”：蓝牙开关为开，能看到手环历史记录；
2. 设备管理器确认蓝牙适配器无黄色感叹号，驱动为厂商/WinRT 兼容驱动；
3. 若手环此前被这台电脑连接过：在“蓝牙和其他设备”里**删除设备**再重试
   （Windows 的 BLE 设备缓存有时会导致连接失败）；
4. 手机蓝牙关闭 / 飞行模式，避免手环被手机占连；
5. 不需要一直滑屏：手环每 40–60 秒才发一个广播脉冲（熄屏时不发，滑屏也不会加快），
   因此 `--scan-timeout` 用 120，等它自己出现即可。

### 3.4 运行

```powershell
copy .env.example .env      # 填 DEVICE_ID（蓝牙 MAC）与 AUTH_KEY
.venv\Scripts\python.exe scan_ble.py
.venv\Scripts\python.exe miband_client.py 60 --log-level DEBUG
.venv\Scripts\python.exe miband_client.py --demo 30 --web-port 8080   # 看板自测
```

### 3.5 Windows 常见问题

| 现象 | 原因/处理 |
|---|---|
| `OSError: [WinError 193]` / 加载 `libecdh.so` 失败 | 老版本问题，当前版本会自动回退纯 Python；确认启动日志是 `ECDH backend: python` |
| `BleakError: ... was not found` | 地址不对或手环未广播：用 `scan_ble.py` 核对；确认手环未被手机占用 |
| `BleakError: ... Unreachable` / 连接超时 | 删除 Windows 里的旧设备记录后重试；换 USB 蓝牙适配器（部分廉价适配器 BLE 支持不完整） |
| 扫描列表为空 | Windows 蓝牙开关/适配器问题；用系统“添加设备”页面确认能发现手环 |
| 连接后很快断开 | 手环息屏/离体；保持佩戴与屏幕活动，或提高 `SCAN_TIMEOUT` |
| 认证超时 | 用 `--log-level DEBUG` 观察分块通知；`--mtu` 保持默认，特殊适配器可尝试 `--mtu 185` / `--mtu 247` |
| 公司电脑无法开启蓝牙 | 组策略/驱动限制，需要管理员处理，与本项目无关 |

> 提示：`--mtu` 是“手动覆盖”，并非自动协商。设置值大于实际协商 MTU 时，
> 分块写会失败（认证超时/写特征报错）。没有明确依据时请保持默认（不传 `--mtu`）。

### 3.6 ECDH 原生加速（可选）

不需要编译器也能正常使用。若想在 Windows 上用原生实现：

- 用 MinGW-w64 的 gcc：`gcc -O3 -shared -DECDH_BUILD_DLL ecdh.c -o libecdh.dll`，
  把 `libecdh.dll` 放在项目根目录；或
- 用 MSVC 开发者命令行：
  `cl /nologo /O2 /LD /DECDH_BUILD_DLL ecdh.c /Fe:libecdh.dll`（会在当前目录产生
  `.obj` 文件，可手动清理），同样放到项目根目录；或
- 用 `MIBAND_ECDH_LIB=C:\path\to\libecdh.dll` 指定任意位置。

启动日志显示 `ECDH backend: native` 即生效；失败时仍会静默回退纯 Python，不影响功能。

---

## 4. macOS（代码兼容，待真机验证）

- CoreBluetooth 出于隐私不提供 MAC 地址，扫描结果是 **UUID**：
  `scan_ble.py` 输出中的 `Address` 即 UUID，填到 `DEVICE_ID`；
- 或直接用 `DEVICE_NAME`（广播名子串，如 `Mi Smart Band`）匹配，跨系统更稳；
- 首次运行时系统会弹窗请求蓝牙权限，需允许终端/IDE 访问蓝牙
  （系统设置 → 隐私与安全性 → 蓝牙）；
- 没有原生 `libecdh.dylib` 时自动使用纯 Python；有 Xcode 命令行工具时也可
  `clang -O3 -dynamiclib ecdh.c -o libecdh.dylib` 启用原生后端。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scan_ble.py
.venv/bin/python miband_client.py 60 --device-name "Mi Smart Band" --log-level DEBUG
```

---

## 5. 设计说明：跨平台兼容层做了什么

| 差异点 | 处理方式 | 相关代码 |
|---|---|---|
| ECDH 需要平台原生库 | 双后端：原生加载/编译 + 纯 Python 回退，字节格式统一 | `miband_monitor/crypto/`、`vendor/tiny_ecdh/` |
| Windows/macOS 缺少 Linux 的 `.so` | 按 `sys.platform` 选择 `.dll` / `.dylib`，加载失败不致命 | `miband_monitor.crypto.native_library_candidates()` |
| macOS 没有 MAC | 设备标识与名称双匹配，支持 UUID 格式 | `miband_monitor.ble.identity.device_matches()` |
| Windows 旧配置 | `DEVICE_MAC` 继续可用，若同时存在则优先 `DEVICE_ID`（忽略占位符） | `miband_monitor.ble.identity._env_device_id()` |
| ATT MTU 各平台不同 | 连接后解析一次并透传给所有分块写；支持 `--mtu`/`BLE_MTU` 覆盖 | `miband_monitor.ble.mtu` / `MiBand6Client._session_mtu` |
| 路径 / 编码差异 | 全部使用 `pathlib`，JSONL/CSV/.env 显式 UTF-8 | `miband_monitor/storage/`、`miband_monitor/auth/` |
| 信号/事件循环 | 不使用 POSIX signal，只用 asyncio；Ctrl+C 由 `asyncio.run` 处理 | `miband_monitor/cli/` |
| Windows 无 gcc | 纯 Python 回退，安装 `requirements.txt` 即可 | `miband_monitor.crypto.PurePythonEcdhBackend` |

---

## 6. 真机验证清单（Linux / Windows 各跑一遍）

准备：手环电量 ≥ 30%，佩戴中；手机蓝牙关闭；`.env` 已配置 `DEVICE_ID` + `AUTH_KEY`；
先用 `--demo` 确认软件链路。

| # | 验证项 | 命令 / 判据 |
|---|---|---|
| 1 | 扫描到设备 | `scan_ble.py` 列表出现手环，地址/UUID 与 `DEVICE_ID` 一致 |
| 2 | 连接 + 认证 | 日志出现 `Chunked ECDH authentication SUCCEEDED` |
| 3 | 心率流 | 日志出现 `Current Heart Rate: N BPM`，`heart_rate.jsonl` 有数据 |
| 4 | 步数流 | 日志出现 `Steps: ...`，`steps.jsonl` 有数据 |
| 5 | IMU（可选） | `--imu` 时 `imu.jsonl` 约 25Hz 增长 |
| 6 | 看板（可选） | `--web-port 8080`，浏览器曲线实时刷新，`/healthz` 返回 ok |
| 7 | 历史同步（可选） | `--sync-history 1` 出现 `Band history sync finished`，`spo2.jsonl`/`activity_history.jsonl` 有数据 |
| 8 | 主动断开重连 | 关闭手环蓝牙/走远再回来，日志出现 `Reconnecting in ...` 并恢复采集 |
| 9 | 退出与落盘 | Ctrl+C 后 `Storage summary` 计数 > 0，`--export-csv` 生成 5 张 CSV |

建议把第 2、3、7 项作为核心通过标准；其余失败请记录现象与日志。

---

## 7. 提交问题或验证结果时需要的信息

1. 操作系统与版本（如 Windows 11 23H2 / Ubuntu 24.04）；
2. Python 版本、`python -m pip list | grep -i bleak`（Windows 用 `findstr`）；
3. 蓝牙适配器型号（设备管理器 → 蓝牙）；
4. 启动日志前几行（`ECDH backend`、`Discovery target`、`BLE link established ... MTU`）；
5. `--log-level DEBUG` 的完整日志（**务必先脱敏 MAC 与 auth_key**）；
6. 失败发生在清单第几步，是否能稳定复现。

> 日志脱敏：`sed -E 's/([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/XX:XX:XX:XX:XX:XX/g'`。
> 永远不要提交 `.env`、`data/`、抓包文件。
