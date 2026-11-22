# 阶段 0 事实基线闸门记录（2026-11-20）

> **性质**：执行 [gadgetbridge-benchmark.zh-CN.md](../gadgetbridge-benchmark.zh-CN.md) §8「阶段 0：先修正事实基线」的
> 原始证据与结论登记。本阶段**零代码改动**；本记录是后续 B-3 / B-12 / B-13 能否进入排期的唯一闸门依据。
> **证据纪律**：探测项来自真机 `Mi Smart Band 6`，原始字节与解码并列，可复现；不凭 Gadgetbridge 能力矩阵推断。

## 闸门结论速览

| 项 | 判定输入 | 实测结果 | 闸门结论 |
|---|---|---|---|
| B-3 睡眠算法（=R-4 第 2 步） | `data/zepp_nights.json` 夜数 | 文件不存在，可用夜 = **0** | ⛔ **挂起**（< 3 夜，不满足 A/B 前提） |
| B-12 运动总结抓取 | `0x05 SPORTS_SUMMARIES` 探测 | 状态成功、`declares 320`、真实时间戳 `2026-11-17 16:09` | ✅ **解锁**（证实手环产出总结数据） |
| B-13 衍生指标抓取 | `0x2c STATISTICS` 探测 | 状态成功但 `declares 0`、时间戳归零 `1970-01-01` | ⛔ **挂起**（探测为空，不凭 GB 矩阵推进） |

> **重要修正**：基准文档 §7.4 / §8 曾把 B-12 归入「证据弱/暂缓」，理由是「Band 6 运动总结产出未确证」。
> 本次真机探测**确证产出存在**（`0x05` 非 0 条）——这是探测事实，而非能力矩阵推断——故 B-12 满足
> §8 阶段 4 的前置「probe 证实有数据」。但注意：**B-12 实现仍依赖 B-5 → B-6 架构链先稳固**，
> 本阶段只解锁「可进入后续排期」，非立即施工。

---

## 动作 1 · 落点纠错核实

按 §7.2 / §7.3 核对三处落点修正是否已就地写入文档且与源码一致：

| 编号 | 修正后落点（文档） | 源码核实 | 结论 |
|---|---|---|---|
| B-5 | `ble/client.py`（锁所在）+ `streams.py`/`chunked.py` 之上，非 `link.py` | `_gatt_lock` 定义于 `miband_monitor/ble/client.py:151`；`link.py` 无锁 | ✅ 一致 |
| B-6 | 在 `fetch_payload` 现有模板上补进度/错误恢复 | `BandHistoryFetcher.fetch_payload`（`history/fetcher.py:201`）已是统一 init→metadata→chunk→CRC→ack→close 模板，三种类型共用 | ✅ 一致 |
| B-14 | workout 电量路径提升为通用 series + 覆盖默认会话 | `workout_runner.py:80` 已有 `run_battery_probe()` → `record_battery()` → `hub.publish_workout()` | ✅ 一致 |

正文被证伪描述（§7.2：指数退避、连接不入队、rawKind 无低四位掩码等）已在基准文档 §3.1/§3.6 的复核
blockquote 与 §7 中就地登记。**动作 1 无需再改文档，本阶段未触碰源码。**

---

## 动作 2 · zepp_nights.json 夜数清单

- 目标路径：`data/zepp_nights.json`（`data/` 已被 `.gitignore` 忽略，属个人数据）。
- 全仓搜索（含 `data/`、`scratch/`、`temp/`、仓库根）确认：**该文件当前不存在**。
- 测试侧对应行为：`tests/test_calibrate.py::test_report_refuses_to_fit_on_a_single_usable_night`
  在 DB 或 zepp 文件缺失时 `pytest.skip`，不会因缺文件而误判可用夜。

**夜数清单**：可用夜 = 0，`device` 字段完备的夜 = 0。

**闸门结论（B-3）**：0 夜 < 3 夜 → **保持挂起**。改进计划 R-4 明确「算法升级待 ≥3 夜数据」，
且 Band 6 无 REM 数据源（GB 比例闭环的 REM 部分不适用）。解锁条件：攒到 ≥3 个含 `device` 字段的
Zepp 对照夜（戴 → 当天同步 → 当天记录，见 `guides/usage.zh-CN.md` §5.4）。手环为 40 小时滑动窗口，
隔天同步即丢夜，收集动作不可拖延。

---

## 动作 3 · 带日期的探测记录（真机）

**方法**：`tools/probe_fetch_types.py`；设备 `Mi Smart Band 6`（`.env` 中 DEVICE_ID/AUTH_KEY，日志已脱敏）；
`--scan-timeout 60`；`since ≈ 2026-11-13 07:52`（默认 7 天窗口）。探测只写 start-date 命令并读一条元数据回复，
**不发送 `0x03` ACK**，故不清除手环侧已上传数据（非破坏性）。
类型码取自 GB 的 `HuamiFetchDataType`（AGPL-3.0，**仅协议事实参考、未复制代码**）：
`0x2c`=STATISTICS、`0x05`=SPORTS_SUMMARIES、`0x06`=SPORTS_DETAILS，另以 `0x01`=ACTIVITY、`0x48`=SLEEP_SESSION 作对照。

### 原始回复与解码（2026-11-20）

| 类型 | 原始字节 | status | declares | 回显时间戳 | 判读 |
|---|---|---|---|---|---|
| `0x2c` STATISTICS | `10 01 01 00 00 00 00 b2 07 01 01 00 00 00 00` | 0x01 成功 | **0** | 1970-01-01（归零） | 空 |
| `0x48` SLEEP_SESSION（对照） | `10 01 01 00 00 00 00 b2 07 01 01 00 00 00 00` | 0x01 成功 | **0** | 1970-01-01（归零） | 空（与既有结论一致） |
| `0x01` ACTIVITY（对照） | `10 01 01 9b 15 00 00 ea 07 0b 0d 07 33 00 20` | 0x01 成功 | **5531** | 2026-11-13 07:51 | 有数据（探针有效） |
| `0x05` SPORTS_SUMMARIES | `10 01 01 40 01 00 00 ea 07 0b 11 10 09 0b 20` | 0x01 成功 | **320** | 2026-11-17 16:09 | **有数据** |
| `0x06` SPORTS_DETAILS | `10 01 02` | 0x02 失败 | — | — | 需先给定具体 summary ID（预期行为） |

- 解码规则：字节 `[3:7]` 为小端 u32 声明数；`[7:]` 起为年(LE16)/月/日/时/分。`count==0` 时手环把时间戳
  清零为 1970（见 `history/protocol.py` 文档），是「固件认识该类型但没有数据」的标志；`count>0` 且时间戳
  非归零即为有数据。
- **稳定性**：`0x05` 与 `0x2c` 各复测一次，两次结果逐字节一致（`0x05` 恒定 320 / 2026-11-17 16:09，
  `0x2c` 恒定空），排除队列串包或偶发回复。

### 闸门结论

- **B-13（衍生指标：stress/PAI/呼吸率/最大心率）→ ⛔ 挂起**。`0x2c` 探测为空，符合 §8「探测为空就挂起，
  不凭 GB 能力矩阵推进」。既有 `0x2c` 返回 0 条的结论被本次真机复测再次确认。
- **B-12（运动总结抓取）→ ✅ 解锁**。`0x05` 探测非 0 条且回显真实时间戳，满足 §8 阶段 4 前置条件。
  Band 6 无 GPS 硬件、不含轨迹这一结论不变；实现应延续 `offline_dashboard` 的自绘 SVG 零依赖路线。
  实际抓取/解析仍按依赖链在 B-5 → B-6 稳固之后的阶段 4 进行。

### 并入 B-1 能力白名单的候选（供阶段 1 落实）

阶段 1 将下列带探测日期的事实升级为 `history/protocol.py` 结构化白名单，`sync.py` 显式读取跳过：

| 类型码 | 名称 | 状态 | 探测日期 | 证据 |
|---|---|---|---|---|
| `0x01` | ACTIVITY | 有数据 | 2026-11-20 | 本记录 |
| `0x25` / `0x26` | SPO2_NORMAL / SPO2_SLEEP | 有数据 | 既有真机验证 | `validation/history-hardware.zh-CN.md` |
| `0x05` | SPORTS_SUMMARIES | 有数据（待解析） | 2026-11-20 | 本记录 |
| `0x2c` | STATISTICS | 探测为空 | 2026-11-20 | 本记录 |
| `0x48` | SLEEP_SESSION | 探测为空 | 2026-11-20 | 本记录 + `investigations/sleep-fields.zh-CN.md` §6.4 |
| `0x06` | SPORTS_DETAILS | 需 summary ID（不可独立探测） | 2026-11-20 | 本记录 |

---

## 复现命令

```bash
# 夜数（预期：文件不存在）
ls -l data/zepp_nights.json

# 真机探测（需佩戴亮屏、1 米内、关手机蓝牙；无手机时每 40-60s 一个广播脉冲）
.venv/Scripts/python.exe tools/probe_fetch_types.py 2c 05 48 01 06 --scan-timeout 60
# Windows 用 .venv/Scripts/python.exe，Linux 用 .venv/bin/python
```

## 阶段 0 基线检查（2026-11-20，全绿）

| 检查 | 命令 | 结果 |
|---|---|---|
| 单测 | `python -m pytest -q` | **393 passed, 11 skipped**（31.65s） |
| 仿真手环全链路 | `miband_client.py --demo 2 --imu --sync-history 1 --sync-sleep-spo2 --storage both --export-csv` | 退出码 0；6 类产物非空，0 丢失 |
| 预检 | `miband_client.py --doctor` | **0 error / 0 warning**，4 项检查通过 |

产物落在 `data/ci-demo-gate0/`（gitignored）：`csv/` 下 `heart_rate/steps/imu/spo2/activity_history/spo2_sleep` 六张表均非空。
本阶段零代码改动，基线全绿即视为闸门检查通过。
