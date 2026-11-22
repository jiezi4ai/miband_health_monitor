# 阶段 1 实施记录：快赢（P1）（2026-11-20）

> 性质：执行 [gadgetbridge-benchmark.zh-CN.md](../gadgetbridge-benchmark.zh-CN.md) §8「阶段 1：快赢」的
> 实施登记。四项 B-2 / B-9 / B-1 / B-11 全部落地，零真机依赖，基线全绿。阶段 0 闸门结论见
> [gadgetbridge-gate0.zh-CN.md](gadgetbridge-gate0.zh-CN.md)。

## 总览

| 项 | 内容 | 状态 | 关键文件 |
|---|---|---|---|
| B-2 | `schema_version` + 显式迁移函数 | ✅ 完成 | `storage/schema.py`、`storage/sqlite.py` |
| B-9 | kind→band 单点统一 | ✅ 完成 | `sleep/samples.py`、`offline_dashboard/` |
| B-1 | 带日期能力闸门白名单 | ✅ 完成 | `history/capabilities.py`、`history/sync.py` |
| B-11 | 整库备份 + 校验 + 轮换 | ✅ 完成 | `storage/backup.py`、`tools/backup_db.py`、CLI `--backup` |

---

## B-2 · schema_version + migrate()

- `storage/schema.py` 新增 `SCHEMA_VERSION = 1`、`SchemaVersionError`、`get_schema_version(conn)`、
  `MIGRATIONS` 有序步骤表与 `migrate(conn)`；模块保持「无 I/O」（连接由调用方传入，`sqlite3` 仅在
  `TYPE_CHECKING` 下导入）。
- `storage/sqlite.py::open_database` 在应用幂等 `_SCHEMA` 后调用 `migrate()`：
  - **旧库（user_version=0）就地收养**，不丢数据、不重写行；
  - **新库**建好即打戳到 v1；
  - **更高版本库**（由更新代码写入）被拒绝打开，避免旧版静默降级。
- `storage/__init__.py` 导出新符号；根 `storage` façade 因 `import *` 自动继承。
- 单测：`tests/storage/test_schema_version.py`（5 项）——版本戳、幂等重开、旧库收养保数据、未来版本拒绝、
  迁移步骤连续性。

## B-9 · kind→band 收敛到单点

- `sleep/samples.py` 成为**唯一编码源**：定义 `BAND_REST/ACTIVE/SLEEP/NONWEAR = 0/1/2/3`、
  `BAND_CODES`（随 payload 下发）与单一分类函数 `activity_band(sample, in_sleep=)`；未佩戴优先于睡眠，
  与 `is_nonwear` 同源。
- `offline_dashboard/constants.py` 的 `BAND_*` 改为从 `sleep.samples` **再导出**（不再各写一套常量）；
  `packaging.py` 用 `activity_band()` 取代重复的 if/elif 链，并在 `activity` payload 中携带 `bands` 码表。
- `history_charts.js` 改为读取 `DATA.activity.bands`，用 `code === bands.NONWEAR` 判定斜纹，
  **移除硬编码 `code === 3`**；颜色表按码表键控。旧 HTML 保留兜底码表。
- `sleep/__init__.py` / `offline_dashboard/__init__.py` 导出相应符号；历史 façade 兼容。
- 单测：`tests/offline_dashboard/test_band_codes.py`（5 项）——三层同源、分类优先级、payload 码表、
  渲染 HTML 无硬编码 3、码表可 JSON 序列化。

## B-1 · 能力闸门白名单

- `history/protocol.py::FetchDataType` 补 `SPORTS_SUMMARIES(0x05)` / `SPORTS_DETAILS(0x06)` /
  `STATISTICS(0x2c)`，注释记录阶段 0 探测事实。
- 新增 `history/capabilities.py`（独立模块，让协议模块守住 300 行预算）：`CapabilityStatus`、
  `FetchCapability`、`CAPABILITIES` 带日期白名单、`is_known_empty()`、`is_skippable()`。
  每个状态都来自**真机探测**（2026-11-20），不照抄 GB 能力矩阵。
- `history/sync.py` 把候选任务过一遍闸门：`is_skippable()` 为真（EMPTY / NEEDS_ID）的类型直接跳过并记录日志，
  `sync_history` 不再反复试探已知空类型（0x2c / 0x48）。
- `history/__init__.py` 导出新符号。
- 单测：`tests/history/test_capabilities.py`（5 项）——全类型覆盖、空类型判定、跳过判定、探测来源、
  sync 确实过闸门（把 ACTIVITY 临时标记 skippable 验证其 fetch 不运行）。

## B-11 · 整库备份 + 校验 + 轮换

- `storage/backup.py`：`backup_database()` 用 SQLite **在线备份 API**（`Connection.backup`，WAL 安全，
  不是裸 `shutil.copy`）；备份后用 `PRAGMA integrity_check` + 逐表行数比对 `verify_backup()` 才判成功。
  - 目标为**目录** → 微秒时间戳快照 + `--keep N` 轮换（默认 5）；
  - 目标为**`*.db` 文件** → 单次校验副本，不轮换。
  - 全程走 0600/0700 权限助手。
- `tools/backup_db.py`：`run` / `verify` 两个子命令（README 双语文案已更新）。
- 主客户端新增 `--backup PATH` / `--backup-keep N`：会话结束、`store.close()` 后执行，
  失败只记日志不吞掉会话（经 `cli/backup_cli.py` 共享，保持 cli 模块 ≤300 行）。
- 单测：`tests/storage/test_backup.py`（7 项）——显式文件校验、目录轮换保 N、篡改副本被拒、缺源报错、
  CLI 工具往返、`--backup` 走 demo 会话集成、默认 keep。

---

## 阶段 1 全链路基线（2026-11-20，全绿）

| 检查 | 命令 | 结果 |
|---|---|---|
| 单测 | `python -m pytest -q` | **415 passed, 11 skipped**（35.6s；阶段 0 为 393 passed，新增 22 项） |
| 仿真手环 demo + 备份 | `miband_client.py --demo 2 --imu --sync-history 1 --sync-sleep-spo2 --storage both --export-csv --backup ...` | 退出码 0；6 类产物非空；`--backup` 副本经 `integrity_check` + 行数校验通过 |
| 预检 | `miband_client.py --doctor` | **0 error / 0 warning**，4 项检查通过 |
| 文件预算 | `tools/check_file_sizes.py` | OK：260 个首方文件全部 ≤300 行 |
| 文档链接 | `tools/check_docs_links.py` | OK：738 条本地链接全部可解析 |
| 测试数量声明 | `tools/check_test_baseline.py` | OK：4 处声明与收集用例数一致 |
| 隐私门禁 | `tools/check_privacy.py` | OK：349 个跟踪文件无真实凭据 |

演示产物与备份落在 `data/phase1-demo/`、`data/phase1-backup.db`（均 gitignored）。

## 备注与边界

- 本阶段四项均为**无真机依赖**改动；阶段 0 已用真机确认 `0x05` 有数据、`0x2c` 为空，故 B-1 白名单直接采用该事实。
- B-12（运动总结解析）/ B-13（衍生指标抓取）仍挂起：前者依赖 B-5→B-6 架构链，后者 `0x2c` 探测为空。
- B-2 的迁移框架已就位，当前版本 v1 的 v0→v1 步骤仅打戳（不重写行）；未来改动 `_SCHEMA` 时须追加迁移步骤并递增 `SCHEMA_VERSION`。
- 未触碰工作区既有未提交内容；所有改动均限于本阶段涉及文件。
