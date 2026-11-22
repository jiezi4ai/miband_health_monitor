# 风险与改进计划

> **来源**：2026-11-19 对全项目（代码 / 文档 / 数据链路 / 测试 / 真机验证材料）的一次完整分析。
> **性质**：本文是「已知风险 + 解决方案」的登记簿，不改变任何现有行为承诺；每条给出实测证据、
> 根因分析、可选方案（含推荐项）、验收标准与优先级。完成一条就更新状态列，避免变成
> 「被遗忘的已知问题」。
> **约定**：本文中的设备地址一律为占位符（真实地址见运行日志，不入库）。

## 0. 总览

| 编号 | 风险 | 优先级 | 状态 |
|---|---|---|---|
| [R-1](#r-1-测试基线数字在文档间漂移) | 测试基线数字在文档间漂移 | P1 | ✅ 已闭环 |
| [R-2](#r-2-windows-本机-14-个平台性失败无-skip-标记) | Windows 本机 14 个平台性失败无 skip 标记 | P1 | ✅ 已闭环 |
| [R-3](#r-3-temp-含真实标识符导致-check_privacy-37-项-fail) | `temp/` 含真实标识符导致 `check_privacy` 37 项 FAIL | **P0** | ✅ 已闭环 |
| [R-4](#r-4-睡眠分期阈值按单夜校准校准流程未固化) | 睡眠分期阈值按单夜校准，校准流程未固化 | P2 | ◐ 流程已固化；算法升级待 ≥3 夜数据 |
| [R-5](#r-5-点测-spo2-表为空属预期但缺少用户侧解释) | 点测 `spo2` 表为空：属预期，但缺少用户侧解释 | P3 | ✅ 已闭环 |
| [R-6](#r-6-activity_history-同刻去重在-windows-上丢数据真缺陷) | `activity_history` 同刻去重在 Windows 上丢数据（真缺陷） | P1 | ✅ 已闭环 |
| [R-7](#r-7-看板无鉴权边界l1l8-问题缺少闭环登记) | 看板无鉴权边界；L1–L8 问题缺少闭环登记 | P3 | ✅ 已闭环 |
| [R-8](#r-8-工作区卫生未提交与未跟踪内容) | 工作区卫生：未提交与未跟踪内容 | P2 | ✅ 已闭环 |

建议执行顺序：**R-3 → R-2/R-6（同一次测试整改）→ R-1 → R-8 → R-4 → R-5/R-7**。

## 执行记录（2026-11-19）

按上表顺序全部执行完毕，验证基线如下：

| 验证项 | 结果 |
|---|---|
| Windows 本机 `pytest -q`（免沙箱） | **393 passed / 11 skipped / 0 failed**（collected 404；14 个原失败：13 个修复转绿、1 个转显式 skip） |
| `check_test_baseline.py`（新门禁） | collected 404，4 处声明全部在容差内 |
| `check_file_sizes.py` | 251 个第一方文件全部 ≤300 行 |
| `check_docs_links.py` | 729 个本地链接全部可解析 |
| `check_privacy.py` | 37 → **0 项** finding |
| `miband_client.py --doctor`（免沙箱） | **0 error / 0 warning / 4 checks passed** |

要点摘记（细节见各节）：

- **R-2 的实际做法优于原方案**：13 个"Linux 专属失败"里有 **9 个是测试自身的补丁错位**
  （`monkeypatch` 打在 `bluez` 包转发名上、而 `link.py` 读 `platform.is_bluez_platform`），
  修正补丁指向后全平台通过；4 个是伪造 sysfs 树用了含冒号的目录名（Windows 非法），
  改用平台中立命名后同样全平台通过；1 个是**生产缺陷**
  （[playbook_privileged.py](../miband_monitor/diagnostics/playbook_privileged.py) 用 `pathlib`
  拼接 Linux shell 命令 → Windows 上反斜杠），改为纯字符串拼接。真正需要 skip 的只有
  `dbus_fast` 依赖的配对测试（`pytest.importorskip`）。
- **R-6** 按方案 c 落地：`_enqueue` 对无时间戳样本单调推进 ts；复现脚本从 1 行恢复为 5 行，
  原 Windows 失败测试转绿，Linux 去重回归测试不受影响。
- **R-7** 落地 `WEB_TOKEN`（服务端 Bearer/`?token=` 双通道、`/healthz` 豁免、前端自动透传、
  doctor 对 LAN 绑定无 token 出 WARN）；[issue-register.zh-CN.md](validation/issue-register.zh-CN.md)
  闭环了 L1–L14（其中 L6/L8 本次顺手修复：探针用法平台中立化 + 补 `--scan-timeout`）。
- **R-3** 落地：脱敏证据存档 [wsl2-usbipd-verification.zh-CN.md](validation/wsl2-usbipd-verification.zh-CN.md)；
  `temp/` 与生成的根目录看板产物入 `.gitignore`；`history_dashboard.html` 移入 `data/`。
- **R-8** 落地后新增发现：`libecdh.so` 与 `tools/reset_bt_adapter.py` 的"改动"**均只是
  可执行模式位差异**（`git config core.filemode false` 后消失），无需验证重编译。

### 验收复核补充（同日二次审查）

上线前对全部变更做了逐项复核（代码 diff、测试等价性、JS/Python 语法、功能冒烟、
文档事实核对），发现并修复了两处自身缺陷：

1. **L3 的修复不完整**：`TelemetryStore` 构造位于 CLI 的 `try` 之外，输出目录不可写时
   仍会抛原始 traceback。已在 [cli/app.py](../miband_monitor/cli/app.py) 捕获 `OSError`，
   输出可操作错误日志并返回退出码 1（实测：`exit=1`，无堆栈）。issue-register 的
   L3 关闭证据同步修正。
2. **看板暴露缺少运行期提示**：原实现只在 doctor（读环境变量）里提示，`--web-host 0.0.0.0`
   但未设 `WEB_TOKEN` 时服务启动无任何警告。已在
   [dashboard/server.py](../miband_monitor/dashboard/server.py) 的 `start()` 加 WARN。

同时补齐了 `WEB_TOKEN` 的**自动化回归测试**（[tests/dashboard/test_server.py](../tests/dashboard/test_server.py)：
未带 token 401、错 token 401、`?token=` 与 `Authorization: Bearer` 均 200、
`/healthz` 豁免、未配置 token 时保持开放），并用独立冒烟脚本验证了 9 个端点的实际行为。

---

## R-1 测试基线数字在文档间漂移

### 现状（实测，2026-11-19）

| 出处 | 声称的基线 |
|---|---|
| [README.zh-CN.md](../README.zh-CN.md) §1 | “270+ 单元/集成测试” |
| [guides/cross-platform.zh-CN.md](guides/cross-platform.zh-CN.md) §3.2 | "241 passed" |
| [guides/testing.zh-CN.md](guides/testing.zh-CN.md) | “基线随重构推进以实际输出为准” |
| WSL (Ubuntu 22.04) 实测，11-18 | **392 passed / 4 skipped** |
| Windows 本机实测，11-19 | **372 passed / 10 skipped / 14 failed**（失败见 R-2/R-6） |
| 干净 checkout 的 CI（三平台矩阵） | 全绿（docs 声称） |

### 根因分析

测试文件随重构拆分（如 `test_history.py` → `tests/history/` 5 个文件）后，各文档中的精确数字靠手工同步，必然漂移。「以实际输出为准」是自我声明式的缓解，但它把核对成本转嫁给每一位读者，也让 PR 审阅无法快速判断“这个文档数字过期了吗”。

### 解决方案（推荐 A + B 同时做）

- **A. 让数字自动生成**：CI 增加一步
  `python -m pytest --collect-only -q | tail -n 2`，把收集到的用例数写进 job summary；
  再加一个小脚本 `tools/check_test_baseline.py`：扫描 README / guides 里的
  `NNN+ tests` 字样，与 `--collect-only` 的数量比对，偏差超过 10% 即 FAIL。
  这与现有 `check_file_sizes / check_privacy / check_docs_links` 三个守门工具同一风格。
- **B. 改写文档语义**：把精确数（“241 passed”）改成**下限语义**（“390+ tests”）。
  下限只在测试减少时才需要更新，天然抗漂移。
- ~~C. 只靠人工同步~~：现状已证明不可靠，不推荐。

### 验收

`tools/check_test_baseline.py` 进 CI 且三平台通过；README 与 guides 中不再出现互相矛盾的精确数字。

---

## R-2 Windows 本机 14 个平台性失败无 skip 标记

### 现状（实测，2026-11-19，Windows 11 + Python 3.12.10）

`372 passed / 10 skipped / 14 failed`。14 个失败分两类：

1. **13 个 Linux 专属测试**（bluez 9、cli/workout 的 USB autosuspend 3、gui playbooks 1）：
   断言 `/sys/class/bluetooth` 等 sysfs 路径、`sudo usbreset` 命令文案或 udev 提示。
   Windows 上路径无法构造（`WinError 267`：路径含冒号），于是 **fail 而不是 skip**。
2. **1 个真实缺陷**：`tests/history/test_report.py::test_activity_average_ignores_unavailable_heart_rate`
   ——见 [R-6](#r-6-activity_history-同刻去重在-windows-上丢数据真缺陷)。

### 根因分析

这些测试的**意图**是 Linux-only（守卫 Linux 兼容层的平台分支），但没有携带平台标记，
于是 Windows 上它们以“失败”呈现。后果有两个：

- 本机基线永远是红的，开发者无法用“全绿”作为 Windows 回归信号——
  11-18 的环境日志记录的 “18 failed 均为平台兼容” 就是这个问题的实际成本；
- 真失败（R-6 这类）会淹没在平台噪声里，**这次它正是被 13 个平台失败掩盖着**。

另外 `requirements.txt` 缺 `tzdata` 声明：Windows 的 `zoneinfo` 无 IANA 数据库，
`Asia/Shanghai` 解析失败（11-18 已手工补装；CI 的 Windows 镜像自带所以未暴露）。
这属于依赖声明缺口，不是代码问题。

### 解决方案

1. **平台守卫**：为 13 个 Linux 专属测试加
   `@pytest.mark.skipif(sys.platform != "linux", reason="asserts Linux sysfs/sudo behaviour")`。
   CI 的 Linux 仍然全覆盖；Windows/macos 显示 skip 而非 fail，基线变为可解释的
   `372 passed / 23 skipped / 1 failed`，真失败立刻可见。
   具体落在：[tests/bluez/](../tests/bluez/) 9 处、
   [tests/test_cli_preflight_and_sigterm.py](../tests/test_cli_preflight_and_sigterm.py)
   与 [tests/test_workout_storage_and_doctor.py](../tests/test_workout_storage_and_doctor.py)
   的 usb-autosuspend 各 1–2 处、[tests/gui/test_playbooks.py](../tests/gui/test_playbooks.py) 1 处。
2. **依赖声明**：`requirements.txt` 追加
   `tzdata; sys_platform == "win32"`（一行，与本文件 ≤300 行预算兼容）。
3. **可选增强**：`pytest.ini` 注册 `linux` marker 并在文档 testing.md 说明
   “Linux-only 测试必须带 marker”，防止未来新增测试重蹈覆辙。

> 环境备注（非项目缺陷）：在受限沙箱里跑 pytest 会因临时目录创建模式（0700）被拒，
> 产生大量与项目无关的 `PermissionError`；判断 Windows 基线时应以普通终端为准。

### 验收

普通终端 `pytest -q` 在 Windows 上 0 failed（Linux 专属项全部 skip）；
`pytest -q` 在 WSL 上仍 392 passed；CI 三平台全绿。

---

## R-3 `temp/` 含真实标识符导致 `check_privacy` 37 项 FAIL

### 现状（实测，2026-11-19）

`tools/check_privacy.py` 报 **37 项 FAIL**，全部来自未跟踪、未忽略的
`temp/wsl_test/`（本地工作目录，刻意不入库）：

- 真实设备地址（手环、外接 dongle，以及扫描时撞见的邻居 BLE 设备）；
- 个人家目录路径（`.setup-env.sh`、进度报告、验证脚本）。

`check_privacy.py` 的扫描范围是 `git ls-files --cached --others --exclude-standard`——
**未跟踪但不被忽略的文件同样在扫描范围内**，所以这些工作笔记使本地隐私门禁持续红着，
一旦有人顺手 `git add .` 就会把真实 MAC 与个人路径提交进仓库历史。

### 根因分析

`temp/wsl_test/` 里的 P0 真机验证报告有**长期证据价值**（它记录了 usbipd 直通、
内核兼容性、脉冲建链时序的完整实测），但写笔记时用了真实标识符，没有走项目文档
一贯的占位符纪律。P5 报告自己已建议把 `temp/` 加入 `.gitignore`——那只是止血，
证据本身仍留不在版本库里。

### 解决方案（推荐 a，辅以 b 作为过渡）

- **a. 迁移 + 脱敏入 docs/validation/**（符合项目「证据存档」惯例）：
  1. 把 P0 真机验证与 WSL2 直通结论整理为
     `docs/validation/wsl2-usbipd-verification.zh-CN.md`（按现有 validation 文档体例：
     环境表、时间线、命令、结论），设备地址一律换成占位符（如 `C0:FF:EE:C0:FF:EE`、
     `XX:XX:**:**:XX:XX`），个人路径写成 `~/Works/...`；
  2. 纯环境脚本（`.setup-env.sh`、kinect 相关）不迁移——它们与本项目无关；
  3. 迁移完成后将 `temp/` 移出仓库（或至少入 `.gitignore`）。
- **b. 过渡动作（立刻可做）**：`.gitignore` 追加 `temp/` 与 `history_dashboard.html`，
  让 `git status` 噪声与误提交风险先归零，再从容执行 a。
  注意：`.gitignore` **只解决 git 层面的问题**——`check_file_sizes.py` 不读 gitignore，
  生成产物必须移动到 `data/`（其排除目录）或删除，见 [R-8](#r-8-工作区卫生未提交与未跟踪内容)。
- ~~c. 让 `check_privacy.py` 跳过 temp/~~：削弱门禁语义，等于把“这批文件含敏感信息”的
  警报关掉，不推荐。

### 验收

`tools/check_privacy.py` 0 finding；若执行 a，`tools/check_docs_links.py` 仍通过、
`temp/` 不再出现在 `git status`。

---

## R-4 睡眠分期阈值按单夜校准，校准流程未固化

### 现状

- [miband_monitor/sleep/classification.py](../miband_monitor/sleep/classification.py)
  的 `DEEP_HR_RANK=0.20 / DEEP_SD_RANK=0.45` 是按**一个**可用夜晚调出的；
  [investigations/sleep-fields.zh-CN.md](investigations/sleep-fields.zh-CN.md) §7.2
  自己写明“只有一夜样本，属于临时值”；
- 六夜 Zepp 对照只换来一个先验（手环佩戴夜深睡占睡眠 8%–13%，中位 11%）；
- [tools/calibrate_sleep.py](../tools/calibrate_sleep.py) 已设防（可用夜 <2 拒绝拟合），
  但“每天同步 + 当天把 Zepp 数字记进 `data/zepp_nights.json`”这个**数据收集流程
  没有固化到使用文档**，样本一直攒不起来。

### 根因分析

腕部无 EEG，分期本来就是启发式；问题不在“阈值是拟合的”，而在**拟合的证据流是断的**：
校准工具已就位，收集动作却依赖人 remembering。项目文档（§6.5）也指出与
Gadgetbridge `SleepStageEstimator` 的差距：它用滚动基线偏移 + 深睡占比闭环自适应，
而本项目用全局分位——这正是本项目深睡 12% 偏低于先验中位的原因。

### 解决方案

1. **固化收集流程**（零代码）：在 [guides/usage.zh-CN.md](guides/usage.zh-CN.md)
   睡眠一节加“攒校准夜”小节——戴 → 当天同步 → 当天把 Zepp 睡眠页数字记进
   `data/zepp_nights.json`（必须含 `device` 字段，工具已有两道闸防别的设备的夜混入）；
   配一句 cron/提醒建议（手环 40 小时窗口，隔天就丢夜，见
   [investigations/sleep-fields.zh-CN.md](investigations/sleep-fields.zh-CN.md) §10）。
2. **算法升级（有数据后再做）**：在 `sleep/classification.py` 增加“滚动基线”模式
   （心率相对滑动基线的偏移代替全局排名），用 `zepp_nights.json` ≥3 夜做 A/B；
   达标（各夜深睡占比落在 8%–13% 先验内且 Zepp 深睡分钟误差 <15 分钟）后切换默认，
   并保留 `derived: true` 语义不变。
3. ~~为对上某一页数字而硬调阈值~~：investigations §8.6 已论证这是前几轮犯过的错。

### 验收

`zepp_nights.json` 攒到 ≥3 个 `device` 字段完备的夜晚；`calibrate_sleep.py` 能给出
“哪种读法误差最小 + 阈值跨夜是否一致”两个结论。

---

## R-5 点测 `spo2` 表为空：属预期，但缺少用户侧解释

### 现状（实测）

`data/mi_band.db` 的 `spo2` 表 0 行（时间范围 NULL），而 `spo2_sleep` 有整夜数据。
`--sync-history` 时 0x25 轮次常“声明 0 条”，摘要行里只体现为没有 spo2 样本。

### 根因分析

点测血氧只在**手环侧发生过手动/自动单次测量**时才有记录（用户不主动测就没有），
这由固件行为决定，不是同步链路故障。但 `summarize_history_result` 对“声明 0 条”与
“类型被拒”不区分，用户容易把空表误读为 bug，浪费排障时间（FAQ 已有零散解释，
但数据格式文档未覆盖“为什么我的 spo2 是空的”）。

### 解决方案

1. （文档，P3）在 [guides/data-formats.zh-CN.md](guides/data-formats.zh-CN.md) 与
   FAQ 的 spo2 条目补一句：“点测 `spo2` 只在手环侧做过单次测量时非空；
   想要整夜连续血氧用 `--sync-sleep-spo2`（`spo2_sleep` 表）”。
2. （可选，小改动）`sync_history` 摘要中把 “declared 0 records” 显式化
   （一行日志），让“没有数据”与“取失败”在日志里可区分。

### 验收

用户按文档操作后不会再为空 `spo2` 表提 issue；sync 日志能区分三类结果
（有样本 / 声明 0 条 / fetch 失败）。

---

## R-6 `activity_history` 同刻去重在 Windows 上丢数据（真缺陷）

### 现状（已复现，2026-11-19）

`tests/history/test_report.py::test_activity_average_ignores_unavailable_heart_rate`
在 Windows 失败：连发 5 条**不带时间戳**的活动样本，库里只剩 1 行。
最小复现（同线程连发）：

```text
enqueued ts: [t, t, t, t, t]      # 5 次 time.time() 完全相同
distinct enqueued ts: 1
rows in db: 1
```

### 根因分析

两个事实叠加：

1. Windows 上紧密循环内的 `time.time()` 可连续返回**同一值**（时钟粒度），
   5 次入队拿到同一个 ts；
2. [miband_monitor/storage/sqlite.py](../miband_monitor/storage/sqlite.py) 的
   `insert_record` 对 `activity_history` 做 **ts 完全相等去重**
   （`SELECT 1 FROM activity_history WHERE ts = ?`，为跨轮次重复同步设计），
   于是后 4 条被当作重复静默丢弃。

Linux 上 `time.time()` 粒度更细，5 次 ts 几乎必然不同，所以 CI 绿、
WSL 392 全绿——**这是一个只在 Windows 显形的静默数据丢失路径**。

**影响面评估**：生产路径的 `activity_history` 全部带手环分钟时间戳
（[miband_monitor/cli/callbacks.py](../miband_monitor/cli/callbacks.py) 总是传
`sample.get("ts")`），一分钟一条、互不相等，**不触发**。触发条件是“无时间戳的
活动样本在同一时钟 tick 内连发”——目前只有测试这么做；但 `TelemetryStore.record_activity_history`
是公开 API，任何第三方调用方都可能踩中。危害等级：低概率、静默、难发现——
值得修，不值得恐慌。

### 解决方案（推荐 c，改动最小且语义最诚实）

- **c. 无 timestamp 的入队保证 ts 唯一**：`TelemetryStore._enqueue` 在
  `timestamp is None` 时若 `event_ts <= 上一条 enqueued ts`，则取
  `上一条 ts + 1e-6` 单调推进（毫秒级抖动，不影响任何按窗口/按分钟的聚合）。
  对“真实重复”的去重（跨轮次同步，ts 来自手环、彼此相等）**语义不变**。
- a. 去重键改为“分钟取整 ts + payload 摘要”：能同时解决，但改变去重语义
  （同分钟内两条**真实**不同样本会被误杀——历史同步不存在这种数据，但 API 语义变窄）。
- b. 删掉 SQLite 端去重、只留 JSONL 端去重：会让“重抓不污染库”的保证失效，
  与 workout gap-fill 幂等测试冲突。

修复后把该测试的断言保持不变（它写的是真实数据契约：255 哨兵不入均值），
Windows 上自然转绿。

### 验收

复现脚本在 Windows 上得到 5 行；R-2 完成后 Windows 基线 0 failed；
Linux/CI 全套件不受影响（去重回归测试 `test_activity_history_dedup_across_sqlite_and_jsonl_reopen`
继续通过）。

---

## R-7 看板无鉴权边界；L1–L8 问题缺少闭环登记

### 现状

- 实时看板/GUI 默认只绑 `127.0.0.1` 但**无鉴权**，SSE/API 响应头带
  `Access-Control-Allow-Origin: *`；`--web-host 0.0.0.0` 即暴露到 LAN
  （[miband_monitor/dashboard/http.py](../miband_monitor/dashboard/http.py)、
  [server.py](../miband_monitor/dashboard/server.py)）。文档已警示“不要暴露公网”，
  但没有任何技术护栏。
- [validation/linux-validation.zh-CN.md](validation/linux-validation.zh-CN.md)
  的 L1–L10 中，L9/L10 已修复复验，**L1–L8 没有逐条的闭环记录**（修复了、
  won't-fix、还是仍开放，无从追查）。

### 根因分析

单机隐私工具选择零鉴权换取零依赖，取舍本身合理；缺的是**纵深防御的一环**
（防误配）与**问题登记制度**（防遗忘）。“已知问题”若没有状态跟踪，
下一位维护者只能重读全部验证文档自己拼图。

### 解决方案

1. **可选令牌（小改动，~30 行，守住误配后果）**：新增 `WEB_TOKEN` 环境变量——
   设置后 `/api/*`、`/events`、GUI POST 均要求 `Authorization: Bearer <token>`
   或 `?token=`，未设置时行为与现状完全一致（不破坏“一条命令跑通”）；
   `--doctor` 在 `WEB_HOST` 非 127.0.0.1 且未设 token 时输出 WARN。
2. **问题登记簿**：`docs/validation/issue-register.md`，一表五列
   （编号 / 症状 / 根因与证据 / 状态 / 关闭条件），把 L1–L8 与本文件各条目统一登记；
   修复即改状态，不再散落在叙事文档里。
3. GUI 的 `/api/gui/` POST 面已有加固提交（路由白名单、会话互斥），保持现状即可。

### 验收

设 `WEB_TOKEN` 后未带令牌的请求 401；doctor 对“LAN 绑定无鉴权”给出 WARN；
issue-register 覆盖 L1–L8 各一条状态。

---

## R-8 工作区卫生：未提交与未跟踪内容

### 现状（git status，2026-11-19）

| 内容 | 状态 | 判断与建议 |
|---|---|---|
| `libecdh.so` | 已修改（二进制变化） | Linux x86-64 预编译产物；疑为 WSL 侧重编后同步。**先验证**（`.cache/ecdh/libecdh.so` 是本地自动编译缓存）：重跑一次认证冒烟确认可用后再决定提交与否；不要盲目提交二进制 |
| [tools/reset_bt_adapter.py](../tools/reset_bt_adapter.py) | 已修改 | 仅文件模式位变化（可执行位丢失，Windows checkout 常见）。建议 `git config core.filemode false` 或提交前恢复 `100755`，避免无意义的 mode-only diff |
| `history_dashboard.html` | 未跟踪 | 生成产物（311KB / 508 行，含个人健康数据）。**实测使 `check_file_sizes.py` 本机 FAIL**（工具不读 `.gitignore`）。不要提交；用 `history_dashboard.py -o data/history_dashboard.html` 重新生成到 `data/`（工具排除目录），删除仓库根副本；可选把默认输出改为 `data/` 防复发 |
| `temp/` | 未跟踪 | 见 R-3：迁移脱敏后移出仓库 |
| `.pytest_cache/` | 已忽略 | 正常缓存，无需处理 |
| `.env` | 已忽略 | 含真实凭据，保持 0600、永不提交（现状正确） |

**本机三门禁实测（2026-11-19，修订前）**：`check_docs_links` 通过（655 链接）；
`check_privacy` 37 项 FAIL（全部来自 `temp/`，见 R-3）；
`check_file_sizes` 1 项 FAIL（`history_dashboard.html`，见上表）。
干净 checkout 上三者全绿——两个红项都是**工作区内容**问题，不是代码问题。
（本次修订执行后三个门禁已全部回绿，见文首执行记录。）

### 根因分析

跨机器镜像（rsync 服务器 ↔ WSL ↔ Windows）+ 二进制产物 + 生成文件共同造成；
`.gitignore` 未覆盖“生成的 HTML 看板”与“工作笔记”两类新文件形态。

### 验收

`git status` 干净（或只剩有意的改动）；`check_privacy` / `check_file_sizes` /
`check_docs_links` 三门禁全绿。

---

## 附：本次分析使用的方法

- 通读 `miband_monitor/` 15 个包的代表性源码（认证、链路、存储、历史、睡眠、
  workout、看板、GUI、模拟器、配置、BlueZ 层）与全部 31 篇 docs 文档；
- 实库检查（SQLite 只读）与 JSONL/会话日志抽样；
- 实跑三门禁工具与完整测试套件（Windows 本机、免沙箱）；
- 对唯一一个非平台性失败做了独立最小复现，定位到
  [miband_monitor/storage/sqlite.py](../miband_monitor/storage/sqlite.py) 的
  同刻去重 + Windows 时钟粒度叠加（R-6）。
