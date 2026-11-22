# 阶段 3 实施记录：数据理解与可视化（P2）（2026-11-20）

> 性质：执行 [gadgetbridge-benchmark.zh-CN.md](../gadgetbridge-benchmark.zh-CN.md) §8「阶段 3：数据理解与可视化」的
> 实施登记。B-7 / B-8 / B-14 三项落地；**B-3 因闸门未开保持挂起**（0 夜 < 3 夜），本阶段未实现睡眠算法升级。
> 前置阶段记录：[阶段 0 闸门](gadgetbridge-gate0.zh-CN.md)、[阶段 1 快赢](gadgetbridge-phase1.zh-CN.md)、
> [阶段 2 架构安全网](gadgetbridge-phase2.zh-CN.md)。

## 总览

| 项 | 内容 | 状态 | 关键文件 |
|---|---|---|---|
| B-7 | `day/week/month/all` 粒度 + 同轴视图 + 三种状态显式着色 | ✅ 完成 | `offline_dashboard/ranges.py`、`combined.py`、`assets/history_coaxis.js`、`svg.py` |
| B-8 | KPI 时间范围（`day`=昨晚 / `week` / `month` / `all`=全库） | ✅ 完成 | `offline_dashboard/kpis.py`、`cli.py`、`strings.py` |
| B-14 | 电池提升为 hub 独立 series，覆盖带看板的默认会话；显示链路状态 | ✅ 完成 | `dashboard/hub.py`、`cli/workout_runner.py`、`assets/dashboard.{html,js}` |
| B-3 | 滚动基线 + 深睡占比闭环 | ⛔ **挂起** | 闸门复核：`data/zepp_nights.json` 仍不存在（0 夜） |

---

## B-7 · 多粒度 + 同轴 + 不佩戴着色

- 新增 `offline_dashboard/ranges.py`：`RANGE_DAYS`（day=1 / week=7 / month=30 / all=None）、
  `RANGE_LABELS`、`normalize_range()`、`resolve_ranges()`。`--range` 决定取数窗口与图表粒度，
  `--kpi-range` 独立决定卡片口径；更宽的 KPI 档位会同时放宽取数窗口，避免"全库 KPI 只看 7 天"。
  未指定两者时 `--days N` 的历史行为与昨晚 KPI 逐字不变。
- 新增 `offline_dashboard/combined.py`：同轴分桶。`day` 用 10 分钟桶、`week` 用 1 小时桶、
  `month`/`all` 用自然日桶；桶起点按**本地时钟**对齐（日桶落在本地午夜，不是 UTC 午夜）。
  每个桶产出 `[ts, steps|null, bpm|null, band|null]`：**无记录的桶步数为 null**，
  不做零值柱、不连心率线、不涂睡眠色；band 取自 B-9 单点码表，桶内混合时用最高优先级
  （未佩戴 > 睡眠 > 活动 > 静止）。
- 新增 `assets/history_coaxis.js`：左轴步数柱 + 右轴心率线 + 底部睡眠/未佩戴色带共用一条时间轴；
  心率遇到缺值或连续空桶即断线。`assets/history_dashboard.html` 增「同轴视图」节，`render.py` 内联新脚本。
- `svg.py::hypnogram_svg()` 增加 `nonwear=` / `show_unknown=` 可选参数（默认输出与旧测试逐字一致）：
  底部 6px 斜纹 = 手环实测未佩戴（`kind=0xF3`），底泳道灰块 = 有记录但无心率，
  **留空 = 该分钟没有记录**——三者不再混为一谈。`collect()` 从 `session.samples` 生成逐分钟 flags。
- 单测：`tests/offline_dashboard/test_ranges_and_coaxis.py`（14 项）——档位映射/校验、窗口解析、
  KPI 反 widened 窗口、分桶宽度、缺口 null 纪律、SVG 三种状态、渲染产物与 payload 元数据。

## B-8 · KPI 时间范围

- `_kpis()` 增加 keyword-only `range=` 参数（默认 `day`），拆为 `_last_night_cards()`（原语义）、
  `_averaged_cards()`（周/月/全库对睡眠取均值、步数取日均）与 `_common_cards()`（未佩戴/心率/血氧三档通用）。
  `week/month/all` 每卡 hint 都带档位标签，避免数字脱离口径被误读。
- `collect()` 把 `kpi_range`、`kpi_label` 写进 `meta`，页眉显示"窗口 + KPI 口径"；
  CLI 增 `--kpi-range`，`history_dashboard.py --range week --kpi-range week` 可复现。
- 单测覆盖两夜均值、独立 KPI 档位（全库窗口 + 昨晚 KPI）、空库占位与三档切换。

## B-14 · 电池通用 series 与链路状态

- `dashboard/constants.py` 新增 `BATTERY_KIND` / `EVENT_SERIES_KINDS`；**`METRIC_KINDS` 不变**，
  电量不进入由 storage schema 推导的 `/api/history?source=db` 列集合，也不伪造 SQLite 表。
- `TelemetryHub`：`publish_battery(level)` 以懒创建的有界 deque 存电量（`level` 0–100 校验），
  `snapshot()` / `history("battery")` 可读取；无电量事件时快照形状与阶段 2 完全一致。
  `publish_event()` 额外记住 `event_latest`，让新打开的页面立刻看到 B-4 的 `device` 状态，
  不必等下一条 SSE。设备与电量仍共用同一 hub 通道，未新建事件总线。
- `cli/workout_runner.py::run_battery_probe()` 的 `workout` 改为可选：先发 `publish_battery`，
  有 workout 时再照旧 `record_battery` + `publish_workout`。`wait_session_with_battery()` 不再以
  `workout is None` 提前返回；**当且仅当有 hub（看板开启）或有 workout 时**才轮询电量——
  无消费者的会话保持原等待路径，避免无谓 BLE 读操作（该约束由既有
  `test_run_monitor_counts_duration_after_first_auth` 捕获并守住）。
- 实时看板 `dashboard.html` 增「手环电量」卡片与趋势图、`deviceState` 徽标；`dashboard.js`
  处理 `battery` series、`device` 事件与快照中的 `event_latest.device`，显示连接阶段、
  busy 任务和重连次数。
- 单测：`tests/dashboard/test_battery_series.py`（7 项）——series 与 METRIC_KINDS 隔离、懒创建、
  设备事件快照、SSE 扇出、无 workout 探测、workout 快照兼容、默认会话轮询、页面资产。

## B-3 · 闸门复核（保持挂起）

- 复核 `data/zepp_nights.json`：**仍不存在，可用夜 = 0**（阶段 0 结论未变）。
  按 §8「< 3 夜则挂起」与改进计划 R-4「升级待 ≥3 夜」，`sleep/classification.py` 本阶段**未改动**，
  `derived: true` 语义不变。
- Band 6 无 REM 数据源，GB 比例闭环的 REM 部分本就不适用；即便将来解锁也只实现深睡占比闭环。

> **后置更新（2026-11-20 晚间，阶段 3 实施完成后）**：本节冻结时的复核结论已被同日后续事件
> 超越——`data/zepp_nights.json` 当晚写入 8 夜 Zepp 参照（7 个带 `device` 的可用夜），
> **B-3 闸门解锁**；随即完成逐夜对照校准，发现现役算法为三种读法中最差（58.5 min 平均误差、
> 恒不产 REM），并给出候选读法（分值字节 `deep>40` + `rem>50`，联合平均误差 29.0 min）。
> **算法切换仍未实施**，`sleep/classification.py` 保持未改动，属下一批工作。
> 详见 [sleep-calibration-2026-11.zh-CN.md](sleep-calibration-2026-11.zh-CN.md)。

---

## 阶段 3 全链路基线（2026-11-20，全绿）

| 检查 | 命令 | 结果 |
|---|---|---|
| 单测 | `python -m pytest -q` | **461 passed, 11 skipped**（41.9s；阶段 2 为 440 passed，新增 21 项；收集 472） |
| 仿真手环 demo + 备份 | `miband_client.py --demo 2 --imu --sync-history 1 --sync-sleep-spo2 --storage both --export-csv --backup ... --output data/phase3-demo` | 退出码 0；6 类 CSV 非空、0 丢失；备份 `integrity_check` + 行数校验通过 |
| 预检 | `miband_client.py --doctor` | **0 error / 0 warning**，4 项检查通过 |
| 文件预算 | `tools/check_file_sizes.py` | OK：273 个首方文件全部 ≤300 行 |
| 文档链接 | `tools/check_docs_links.py` | OK：749 条本地链接可解析 |
| 测试数量 | `tools/check_test_baseline.py` | OK：收集 472，4 处声明在容差内 |
| 隐私门禁 | `tools/check_privacy.py` | OK：364 个跟踪文件无真实凭据 |
| 离线 CLI 冒烟 | `history_dashboard.py --range week --kpi-range week` / `--range all --kpi-range all` | 退出码 0；week 输出 401 KB、10 夜；all 输出 443 KB、12 夜，`meta.days=None` 与全库 KPI 正确 |

演示产物、备份与两份冒烟 HTML 落在 `data/phase3-demo/`、`data/phase3-backup.db`（均 gitignored）。

## 备注与边界

- 阶段 3 全项为**无真机依赖**改动；电量读取仍受 `0x2A19` best-effort 前提约束，Band 6 不支持时只显示 `--`。
- 电池轮询只在"有看板 hub"或"有 workout"时发生；纯无看板会话不增加 BLE 事务。
- B-7 的"未佩戴/无心率/无记录"三态是语义区分，不是补数据：缺口仍是 unset，
  与阶段 1 的 B-9 单点码表、阶段 0 的缺口纪律一致。
- B-12/B-13 仍在阶段 4 挂起（`0x2c` 为空；`0x05` 已解锁但依赖后续抓取实现），本阶段未触碰抓取协议。
- 未触碰工作区既有未提交内容；改动均限于本阶段涉及文件。
