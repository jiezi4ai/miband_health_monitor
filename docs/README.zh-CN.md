[English](README.md) · **简体中文**

# 文档中心

这里是 Mi Band 6 Health Monitor 的全部文档入口。仓库根目录的
[README](../README.zh-CN.md) 只保留功能概览、快速开始与导航；具体细节按下面的分类查阅。

## 阅读路线

| 你的目标 | 从这里开始 |
|---|---|
| 第一次安装并跑起来 | [guides/installation.md](guides/installation.zh-CN.md) → [guides/configuration.md](guides/configuration.zh-CN.md) → [guides/usage.md](guides/usage.zh-CN.md) |
| 只是连不上手环 | [guides/cross-platform.md](guides/cross-platform.zh-CN.md) → [guides/faq.md](guides/faq.zh-CN.md) → [validation/linux-ble-connect-findings.md](validation/linux-ble-connect-findings.zh-CN.md) |
| 想理解代码结构 | [architecture.md](architecture.zh-CN.md) → [modules/](modules/) 逐个模块 |
| 要改协议 / 加新数据流 | [architecture.md](architecture.zh-CN.md) + [modules/ble.md](modules/ble.zh-CN.md) + [modules/history.md](modules/history.zh-CN.md) |
| 处理数据 / 做分析 | [guides/data-formats.md](guides/data-formats.zh-CN.md) + [modules/storage.md](modules/storage.zh-CN.md) + [modules/sleep.md](modules/sleep.zh-CN.md) |
| 想知道睡眠字段结论 | [investigations/sleep-fields.md](investigations/sleep-fields.zh-CN.md) |
| 提交代码 / 写测试 | [guides/testing.md](guides/testing.zh-CN.md) + [guides/privacy.md](guides/privacy.zh-CN.md) |

## 架构与模块

| 文档 | 内容 |
|---|---|
| [architecture.md](architecture.zh-CN.md) | 分层架构、依赖方向、运行时数据流、第三方代码豁免、兼容门面与全局限制 |
| [modules/config.md](modules/config.zh-CN.md) | 默认值、环境变量、路径、隐私与权限 |
| [modules/crypto.md](modules/crypto.zh-CN.md) | ECDH 原生 / 纯 Python 双后端与库加载回退 |
| [modules/bluez.md](modules/bluez.zh-CN.md) | Linux D-Bus 设备发现、待命建链、配对 agent、MTU |
| [modules/ble.md](modules/ble.zh-CN.md) | GATT 协议、chunked 认证、实时数据流与客户端生命周期 |
| [modules/history.md](modules/history.zh-CN.md) | 手环历史 fetch 协议、三种 payload 解析与同步循环 |
| [modules/storage.md](modules/storage.zh-CN.md) | JSONL/SQLite schema、后台写线程、CSV 导出 |
| [modules/dashboard.md](modules/dashboard.zh-CN.md) | 实时看板 hub、HTTP/SSE API 与前端资源 |
| [modules/sleep.md](modules/sleep.zh-CN.md) | 睡眠窗口检测、深睡/浅睡推导与报告 |
| [modules/offline-dashboard.md](modules/offline-dashboard.zh-CN.md) | 离线单文件 HTML 历史看板 |
| [modules/simulator.md](modules/simulator.zh-CN.md) | 内存模拟手环与假 bleak 后端 |
| [modules/cli.md](modules/cli.zh-CN.md) | 命令行参数、会话监督、回调接线 |
| [modules/diagnostics.md](modules/diagnostics.zh-CN.md) | `--doctor` 环境自检与扫描排障 |
| [modules/reports.md](modules/reports.zh-CN.md) | 本地 SQLite 汇总报告 |
| [modules/auth.md](modules/auth.zh-CN.md) | 账号获取 auth_key 的交互流程 |
| [modules/tools.md](modules/tools.zh-CN.md) | `tools/` 诊断、取证与校验脚本 |

## 使用指南

| 文档 | 内容 |
|---|---|
| [guides/installation.md](guides/installation.zh-CN.md) | Linux / Windows / macOS 安装、依赖、ECDH 编译（可选） |
| [guides/configuration.md](guides/configuration.zh-CN.md) | `.env` 全量变量、CLI 参数、优先级与自检 |
| [guides/usage.md](guides/usage.zh-CN.md) | 实时采集、看板、历史同步、导出、报告、睡眠、离线看板 |
| [guides/data-formats.md](guides/data-formats.zh-CN.md) | 数据目录、JSONL/SQLite/CSV 字段、时间戳语义 |
| [guides/cross-platform.md](guides/cross-platform.zh-CN.md) | 三平台差异、Linux 配对/trust、Windows/macOS 验证清单 |
| [guides/testing.md](guides/testing.zh-CN.md) | 测试布局、CI 矩阵、demo 冒烟、文档/隐私/体积校验 |
| [guides/faq.md](guides/faq.zh-CN.md) | 常见报错、扫描/连接/认证/历史/看板问题 |
| [guides/privacy.md](guides/privacy.zh-CN.md) | 数据分级、0600/忽略规则、对外反馈脱敏、清理 |

## 验证与调查（证据存档）

这些文档保留原始实验记录、日志片段与结论；正文除脱敏与链接外不做改写。

| 文档 | 内容 |
|---|---|
| [validation/history-hardware.md](validation/history-hardware.zh-CN.md) | 血氧 / 活动 / 睡眠血氧 `0x26` 的真机验证清单与结果 |
| [validation/linux-validation.md](validation/linux-validation.zh-CN.md) | Ubuntu/BlueZ 软件链路 + 真机验证报告（L1–L10） |
| [validation/linux-ble-connect-findings.md](validation/linux-ble-connect-findings.zh-CN.md) | 2026-11-12 Linux 连接不稳定专项排查与根因清单 |
| [validation/linux-ble-test-report.md](validation/linux-ble-test-report.zh-CN.md) | Test 1–4 复测结论、陈旧 LTK 根因、自愈逻辑与 Debug 手册 |
| [validation/wsl2-usbipd-verification.md](validation/wsl2-usbipd-verification.zh-CN.md) | WSL2 + usbipd 蓝牙直通与真机连接验证（2026-11-17~18，已脱敏） |
| [validation/issue-register.md](validation/issue-register.zh-CN.md) | L1–L14 问题闭环登记册：症状、状态与关闭证据 |
| [validation/gadgetbridge-gate0.zh-CN.md](validation/gadgetbridge-gate0.zh-CN.md) | GB 对标路线图阶段 0 事实基线闸门：夜数、`0x2c`/`0x05` 真机探测记录与 B-3/B-12/B-13 解锁判定（2026-11-20） |
| [validation/gadgetbridge-phase1.zh-CN.md](validation/gadgetbridge-phase1.zh-CN.md) | GB 对标路线图阶段 1 快赢实施记录：B-2 schema 版本、B-9 kind 单点、B-1 能力闸门、B-11 整库备份与基线（2026-11-20） |
| [validation/gadgetbridge-phase2.zh-CN.md](validation/gadgetbridge-phase2.zh-CN.md) | GB 对标路线图阶段 2 架构安全网：B-5 GATT 事务队列、B-6 FetchSession 增强、B-4 设备状态机与基线（2026-11-20） |
| [validation/gadgetbridge-phase3.zh-CN.md](validation/gadgetbridge-phase3.zh-CN.md) | GB 对标路线图阶段 3 数据理解与可视化：B-7 多粒度同轴、B-8 KPI 时间范围、B-14 电量 series 与基线；B-3 因 0 夜仍挂起（2026-11-20） |
| [validation/gadgetbridge-phase4.zh-CN.md](validation/gadgetbridge-phase4.zh-CN.md) | GB 对标路线图阶段 4 验证驱动：B-10 校时下行、B-12 运动总结（均真机验证）；B-13 `0x2c` 仍为空保持挂起、B-15 暂缓（2026-11-20） |
| [validation/sleep-calibration-2026-11.zh-CN.md](validation/sleep-calibration-2026-11.zh-CN.md) | 睡眠分期对照校准（2026-11，7 夜）：Zepp 日期口径更正、`find_session` 午睡误配、重复分钟去重，三种读法误差与阈值扫描（2026-11-20） |
| [validation/derived-metrics-probe-2026-11.zh-CN.md](validation/derived-metrics-probe-2026-11.zh-CN.md) | 衍生指标类型码探测（2026-11）：六码固件回 `0x02`，仅 `0x0d` PAI 有数据并与 Zepp 五项核对一致，含 102 字节布局与 7 天序列（2026-11-20） |
| [investigations/sleep-fields.md](investigations/sleep-fields.zh-CN.md) | 睡眠三字节字段取证、与 Zepp Life / Gadgetbridge 的对照 |

## 风险与改进登记

| 文档 | 内容 |
|---|---|
| [improvement-plan.md](improvement-plan.zh-CN.md) | 已知风险 R-1…R-8：每条附实测证据、根因分析与解决方案（暂只有中文版） |

## 对标分析

| 文档 | 内容 |
|---|---|
| [gadgetbridge-benchmark.md](gadgetbridge-benchmark.zh-CN.md) | 与 Gadgetbridge 的对标深度分析：功能差距、数据链路模式、UI / 数据可视化与工程实践借鉴，附优先级建议表、源码逐行核验结果（§7）与实施路线图（§8）（暂只有中文版） |

## 工具与规范

- 工具说明与脚本清单：[../tools/README.md](../tools/README.zh-CN.md)
- 配置模板：[../.env.example](../.env.example)
- 许可与第三方：[../LICENSE](../LICENSE)、[architecture.md#6-第三方与兼容豁免](architecture.zh-CN.md#6-第三方与兼容豁免)

> 文档中的设备地址一律为占位符（例如 `C0:FF:EE:C0:FF:EE`），日期统一为占位日期；
> 若发现链接失效或内容过期，先跑 `python tools/check_docs_links.py` 再提 issue。
