[English](auth.md) · **简体中文**

# auth — 账号获取 auth_key

## 职责

把"如何得到 `AUTH_KEY`"封装成两条交互式流程，并安全写回本地 `.env`：

- `fetch_by_token.py`（**主推路径**）：已有浏览器网页登录态时，用 `user_id` + `app_token`
  直接查设备——不走密码登录，不受小米 2FA 影响；
- `get_auth_key.py`（**兜底路径**，成功率不稳定）：小米账号或 Zepp/Amazfit 账号登录 →
  列出绑定设备 → 取 key。小米路径自 2026-04 起被小米对脚本登录的 2FA/风控拦断
  （[huami-token#119](https://codeberg.org/argrento/huami-token/issues/119)）；
  Zepp 路径 2026-04 时仍可用，但 Zepp 在 2025 年内改过两次登录流程。

云协议实现位于第三方 [huami_token/](../../huami_token/)（MIT；以上游 v0.8.0 源码
原样 vendoring，溯源与同步步骤见 [huami_token/VENDORED.md](../../huami_token/VENDORED.md)）；
本包只包含交互流程、端点常量与安全写文件逻辑。

源码：[miband_monitor/auth/](../../miband_monitor/auth/)

## 模块拆分

| 文件 | 内容 |
|---|---|
| `constants.py` | `.env` 路径、目标设备（从环境读取，绝无硬编码）、Zepp Web 端点/头/超时 |
| `extractor.py` | 小米/Zepp 账号交互流程；只显示"找到并写入"，不打印完整密钥 |
| `token.py` | `fetch_devices(user_id, app_token)`、`main`；按区域依次尝试端点 |

## 公开 API

`ENV_PATH`、`TARGET_MAC`（`DEVICE_ID` 优先，兼容 `DEVICE_MAC`）、`run_extractor() -> int`、
`fetch_devices(user_id, app_token) -> bool`、`token_main() -> int`。

## 数据流

```
用户输入账号/密码（getpass，不落盘）或 user_id/app_token
        │
        ├─ huami_token 客户端 ──> 云 API ──> 设备列表 + auth_key
        └─ config.env.update_env_file() ──> .env（chmod 0600；仅写 AUTH_KEY 等键）
终端只输出掩码后的设备地址/密钥状态
```

## 依赖

- 第三方 `huami_token`、`requests`、`loguru`、`pycryptodome`（见 requirements.txt）；
- `miband_monitor.config`（路径、`.env` 写入、脱敏）；
- 不依赖 BLE 或存储。

## 配置与常量

- 输出键：`DEVICE_ID`/`DEVICE_MAC` 与 `AUTH_KEY`，写入项目根 `.env`；
- `TARGET_MAC` 从环境读取，仓库内没有真实 MAC；
- Zepp Web 端点按 CN / CN2 / Global / US3 顺序尝试，超时 10 s；
- 账号密码通过 `getpass` 读取，不写入 shell 历史或日志。

## 失败模式

| 情况 | 行为 |
|---|---|
| 账号密码错误/需要验证码 | 打印服务端错误，返回非 0，不写 `.env` |
| 触发小米 2FA（2026-04 起） | 小米方法以 "Missing ssecurity or location" 中断；错误提示会推荐 `fetch_by_token.py` 与 Mi Fitness App 日志兜底（见 [configuration §3](../guides/configuration.zh-CN.md)） |
| 该账号记录中没有密钥（设备绑在 Mi Fitness 后端） | 明确提示并给出兜底建议（浏览器 token 路线 / App 日志）；不写 key |
| 账号下没有设备 | 明确提示，不写 key |
| `app_token` 过期 | 提示重新从浏览器获取 |
| 网络不可达 | 捕获请求异常并给出端点/网络提示 |
| `.env` 不可写 | 报错；不会静默丢 key |
| 终端不支持 `getpass` | 给出错误，不把密码回显到屏幕 |

## 测试

- 云 API 流程默认**不在 CI 中跑**（需要真实账号）；线下按
  [guides/usage.md](../guides/usage.zh-CN.md) 的步骤验证。
- `tests/test_device_matching.py` 覆盖 `DEVICE_ID`/`DEVICE_MAC` 优先级与占位符处理
  （与写回逻辑共享 config.env）。
- 隐私约束由 `tools/check_privacy.py` 在 CI 中检查（仓库不得出现 token/真实 MAC）。

## 相关文档

- [guides/configuration.md](../guides/configuration.zh-CN.md)（获取 auth_key 三种方式）
- [guides/privacy.md](../guides/privacy.zh-CN.md)
- [modules/config.md](config.zh-CN.md)
