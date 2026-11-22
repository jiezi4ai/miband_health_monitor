# 阶段 4 实施记录：验证驱动的双向能力（P2–P3）（2026-11-20）

> 性质：执行 [gadgetbridge-benchmark.zh-CN.md](../gadgetbridge-benchmark.zh-CN.md) §8「阶段 4：验证驱动的双向能力」的
> 实施登记。B-10 校时、B-12 运动总结**均已落地并完成真机验证**；B-13 复测 `0x2c` 仍为空，**继续挂起**；
> B-15 按 §8「仅用户明确提出时」继续暂缓。前置记录：[阶段 0 闸门](gadgetbridge-gate0.zh-CN.md)、
> [阶段 1](gadgetbridge-phase1.zh-CN.md)、[阶段 2](gadgetbridge-phase2.zh-CN.md)、[阶段 3](gadgetbridge-phase3.zh-CN.md)。

## 总览

| 项 | 内容 | 状态 | 关键文件 |
|---|---|---|---|
| B-10 | 连接后校时下行（CTS `0x2A2B`，读漂移 + 写入） | ✅ 完成 + 真机验证 | `ble/time_sync.py`、`cli/time_args.py`、`cli/runner.py` |
| B-12 | 运动总结 `0x05` 抓取/解析/存储/看板 | ✅ 完成 + 真机验证 | `history/summary_parser.py`、`history/sync.py`、`storage/summary_schema.py` |
| B-13 | stress/PAI/呼吸率/最大心率（`0x2c`） | ⛔ **仍挂起** | 复测 `0x2c` 仍 `declares 0` |
| B-15 | 通知/天气下行 | ⏸ 暂缓 | 未排期、未改动 |

---

## B-10 · 校时下行

- 新增 `miband_monitor/ble/time_sync.py`：
  - `encode_current_time()` 实现 GB `HuamiSupport.getTimeBytes(TimeUnit.SECONDS)` 的 **Mi Band 11 字节变体**：
    `年 LE16, 月, 日, 时, 分, 秒, 星期(周一=1…周日=7), fractions=0, reason=0, 时区刻钟`；
    标准 CTS 记录只有 10 字节，末尾时区字节是小米扩展。
  - `decode_current_time()` 读取后解析本地墙上时间；`TimeSyncMixin.read_current_time()` /
    `sync_current_time(dry_run=)` 以 `_gatt_lock` 串行访问 `0x2A2B`，写入先 `response=True`，
    失败再降级 `response=False`；任何异常都返回诊断 dict，**不中断会话**。
  - `maybe_sync_time()` 是 runner 的唯一挂点，统一日志。
- `MiBand6Client` 组合 `TimeSyncMixin`；CLI 新增互斥的 `--sync-time` / `--sync-time-dry-run`
  （放在 `cli/time_args.py`，守住 `args.py` 300 行预算），`runner.run_monitor` 在认证成功后、
  历史抓取/实时流之前执行。
- 单测：`tests/ble/test_time_sync.py`（10 项）——11 字节精确编码、周日=7、往返解码、
  非法记录、漂移计算、dry-run 不写、写入后复读、写失败降级且不抛、无 mixin 兼容、CLI 互斥。

### 真机证据（2026-11-20，Mi Smart Band 6）

| 动作 | 命令 | 结果 |
|---|---|---|
| 只读漂移 | `miband_client.py 5 --sync-time-dry-run --storage none` | 认证成功；`Band clock drift -0.3s (dry-run; nothing written)` |
| 写入校时 | `miband_client.py 5 --sync-time --storage none` | `Band clock aligned (drift was -0.1s)`；无降级、无错误，会话继续到结束 |
| 设备版本 | 标准 DIS 只读 | 软件版本 `V1.0.6.20`，硬件版本 `V0.82.135.3`；`0x2A26` 固件特征不存在 |

结论：Band 6 的 `0x2A2B` 可读可写，11 字节格式与 GB 事实一致；本次漂移仅 0.1–0.3 s，
写入通道已实测成功。日志：`data/phase4-time-dryrun.log`、`data/phase4-time-write.log`（gitignored）。

## B-12 · 运动总结抓取

- 新增 `history/summary_parser.py`：解析 `0x05` 单条总结，支持 `version >= 512` 布局
  （519 跳过 1 字节 + `minHR` + 定位 `0x8C`；516 跳过 4 字节）。输出类型、起止、时长、
  步数、活动秒、卡路里、距离、平均/最大/最小心率、配速、步频/步幅、海拔、`has_gps`。
  哨兵值不发布：`minHR=-256`、`minPace>60 s/m`、海拔 `±100000`。
- `history/parsers.py::_parse_payload` 增加 0x05 分派；`HistorySyncResult` 增加 `sports`，
  `sync_history(include_sports=, on_sports=)` 把 0x05 加入候选与消费者。
  **游标按 `end_ts + 1s` 推进**——真机实测发现按 `start+1s` 会让手环反复返回同一条；
  这与 GB 在 `FetchSportsDetailsOperation` 保存 `endTime` 的做法一致。重复总结由既有
  "no forward progress" 检查兜底。
- 存储：新增 `storage/summary_schema.py`（`activity_summary` 表、唯一索引 `(ts,end_ts)`、
  `INSERT OR REPLACE`、v1→v2 迁移），`schema.py` 升到 **v2** 并合并 DDL；
  `TelemetryStore.record_activity_summary()`、`sqlite.insert_record()`、JSONL、
  CSV 导出、`--sync-sports`（要求 `--sync-history`）全部接通。
- 离线看板新增「运动记录」表（类型/时长/步数/距离/消耗/心率），无 GPS 不画轨迹；
  空表给出 `--sync-sports` 提示。
- 能力闸门：`SPORTS_SUMMARIES` 从 `PENDING` 升为 **`AVAILABLE`**（探测日期 2026-11-20，
  附本机真机抓取证据）。
- 单测：`tests/history/test_summary_parser.py`（8 项，GB Mi Band 6 v519 真机夹具回归）、
  `tests/history/test_sports_sync.py`（4 项，逐条抓取/游标/重复/解析失败隔离）、
  `tests/offline_dashboard/test_sports_panel.py`（3 项）、存储/迁移测试 2 项。
- **与 GB 的口径差异（2026-11-22 逐行复核）**：字节布局、版本分派（≥512 / 519 跳 1 字节 +
  `0x8C` / 516 跳 4）与 GB `HuamiActivitySummaryParser` 逐字段一致；但哨兵策略**比 GB 更严**——
  GB 无条件发布 maxPace 与可为 0 的 averageHR/maxHR，且对五种活动豁免 minPace 过滤，本项目统一
  按哨兵不发布。与 GB 双轨采集对账时两侧统计会有系统性小差（本项目口径更合理），**非 GB 同口径**。
  另：version<512 的 legacy 记录本项目直接报错、GB 会按旧布局继续解析（Band 6 实测 ≥512，不触发）。

### 真机证据（2026-11-20，Mi Smart Band 6）

命令：`miband_client.py 30 --sync-history 7 --sync-sports --storage both --output data/phase4-sports2`

| 字段 | 实测值 |
|---|---|
| 总结版本 | **519** |
| 运动类型 | code 2 `treadmill` |
| 起止 | `2026-11-17 16:09:11` → `16:12:44`（213 s） |
| 步数 / 活动秒 | 493 / 207 |
| 距离 / 卡路里 | 578.6 m / 29.2 kcal |
| 平均 / 最大心率 | 119 / 143 BPM |
| `has_gps` | false（Band 6 无 GPS） |

- 首轮抓到 1 条并正确解析入库；第二轮以 `end+1s`（16:12:45）请求，手环回
  `Band reports no new SPORTS_SUMMARIES records`——证明游标推进正确、不会重复消费。
- 7 天窗口内本机只有 1 条总结，因此"多条连续抓取"由单测（两条记录 + 空轮）覆盖；
  真机负责确认版本、字段与游标语义。日志：`data/phase4-sports2.log`（gitignored）。

## B-13 · 闸门复测（保持挂起）

`tools/probe_fetch_types.py 2c --scan-timeout 60`（非破坏性，不回 ACK）原始回复：

```
type 0x2c: reply 10010100000000b207010100000000
           accepted, declares 0
```

按 §8「探测为空就挂起，不凭 GB 能力矩阵推进」，B-13 **不实现**；`history/capabilities.py`
中 `STATISTICS` 仍为 `EMPTY`，`sync_history` 不会请求它。

> **后置更新（2026-11-20 晚间，本记录冻结后）**：B-13 **重划范围后部分落地**——不再纠缠
> `0x2c`（透明文件仓，GB 亦不解析），按类型码逐个探测。`0x13` 自动压力全链路落地
> （`stress_parser.py`、schema **v3** 新增 `stress` 表、`--sync-stress`）；`0x0d` PAI 仅解析器
> 与能力登记落地（手环只存 App 下发的滞后镜像，未接同步链路）。本记录上方基线表（488 passed）
> 为第一轮快照；第二轮后全量为 **517 passed / 11 skipped**（2026-11-22 复核）。
> 详见 [derived-metrics-probe-2026-11.zh-CN.md](derived-metrics-probe-2026-11.zh-CN.md)。

## B-15 · 暂缓

未新增通知/天气下行通道；按 §8 仅在用户明确提出时评估。

---

## 阶段 4 基线（2026-11-20，全绿）

| 检查 | 命令 | 结果 |
|---|---|---|
| 单测 | `python -m pytest -q` | **488 passed, 11 skipped**（阶段 3 为 461；新增 27 项，收集 499） |
| 仿真手环 demo + 备份 | `miband_client.py --demo 2 --imu --sync-history 1 --sync-sleep-spo2 --storage both --export-csv --backup ...` | 退出码 0；7 张 CSV（含空的 `activity_summary`）、备份校验通过 |
| 预检 | `miband_client.py --doctor` | 0 error / 0 warning，4 项通过 |
| 文件预算 | `tools/check_file_sizes.py` | OK：282 个首方文件 ≤300 行 |
| 文档链接 | `tools/check_docs_links.py` | OK：764 条本地链接可解析 |
| 测试数量 | `tools/check_test_baseline.py` | OK：收集 499，4 处声明在容差内 |
| 隐私 | `tools/check_privacy.py` | OK：375 个跟踪文件无真实凭据 |
| 真机 B-10 | dry-run + write | 漂移 -0.3 s → 写入成功；软件版本 `V1.0.6.20` |
| 真机 B-12 | `--sync-history 7 --sync-sports` | v519 treadmill 1 条，字段正确；第二轮无新记录 |
| 真机 B-13 | `probe_fetch_types.py 2c` | `declares 0` → 保持挂起 |

## 备注与边界

- 校时是**可选下行**：默认关闭，失败只告警；本阶段没有改动 chunked/chunked2021 通道，
  也未新增其他下行消息，故新固件的 chunked2021 迁移不影响本功能。
- 0x05 抓取成功后会回 ACK，手环侧该条总结被清掉（与 GB 非 ZeppOS 行为一致）；
  需要保留手环侧记录时不要运行 `--sync-sports`。
- `activity_summary` 以 `(ts,end_ts)` 唯一并 `OR REPLACE`，重跑不会重复；JSONL 仍为追加写，
  重跑可能追加重复行（与既有 activity_history 的去重策略不同，已在文档注明）。
- 固件 `0x2A26` 特征不存在，版本证据采用 DIS 的 software/hardware revision；
  设备序列号未写入任何跟踪文件。
- 工作区既有未提交内容未被触碰；改动均限于本阶段文件。
