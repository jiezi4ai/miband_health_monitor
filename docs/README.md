**English** · [简体中文](README.zh-CN.md)

# Documentation center

This is the entry point for all Mi Band 6 Health Monitor documentation. The repository root
[README](../README.md) only keeps the feature overview, quick start and navigation; details are
organized under the categories below.

> **Languages:** every document is available in English and Simplified Chinese. The Chinese
> counterpart is the same path with `.zh-CN` before `.md` (for example
> [architecture.zh-CN.md](architecture.zh-CN.md)); use the language bar at the top of each
> document to switch.

## Reading paths

| Your goal | Start here |
|---|---|
| Install and run for the first time | [guides/installation.md](guides/installation.md) → [guides/configuration.md](guides/configuration.md) → [guides/usage.md](guides/usage.md) |
| The band just will not connect | [guides/cross-platform.md](guides/cross-platform.md) → [guides/faq.md](guides/faq.md) → [validation/linux-ble-connect-findings.md](validation/linux-ble-connect-findings.md) |
| Understand the code structure | [architecture.md](architecture.md) → [modules/](modules/) one module at a time |
| Change the protocol / add a data stream | [architecture.md](architecture.md) + [modules/ble.md](modules/ble.md) + [modules/history.md](modules/history.md) |
| Process data / run analysis | [guides/data-formats.md](guides/data-formats.md) + [modules/storage.md](modules/storage.md) + [modules/sleep.md](modules/sleep.md) |
| Learn what the sleep fields mean | [investigations/sleep-fields.md](investigations/sleep-fields.md) |
| Contribute code / write tests | [guides/testing.md](guides/testing.md) + [guides/privacy.md](guides/privacy.md) |

## Architecture and modules

| Document | Contents |
|---|---|
| [architecture.md](architecture.md) | Layered architecture, dependency direction, runtime data flow, third-party code exemptions, compatibility facades and global limitations |
| [modules/config.md](modules/config.md) | Defaults, environment variables, paths, privacy and permissions |
| [modules/crypto.md](modules/crypto.md) | ECDH native / pure-Python dual backends and library-load fallback |
| [modules/bluez.md](modules/bluez.md) | Linux D-Bus device discovery, standby link establishment, pairing agent, MTU |
| [modules/ble.md](modules/ble.md) | GATT protocol, chunked authentication, real-time data streams and client lifecycle |
| [modules/history.md](modules/history.md) | Band-side history fetch protocol, three payload parsers and sync loop |
| [modules/storage.md](modules/storage.md) | JSONL/SQLite schema, background writer thread, CSV export |
| [modules/dashboard.md](modules/dashboard.md) | Live dashboard hub, HTTP/SSE API and frontend assets |
| [modules/sleep.md](modules/sleep.md) | Sleep window detection, deep/light sleep derivation and reports |
| [modules/offline-dashboard.md](modules/offline-dashboard.md) | Offline single-file HTML history dashboard |
| [modules/simulator.md](modules/simulator.md) | In-memory simulated band and fake bleak backend |
| [modules/cli.md](modules/cli.md) | Command-line arguments, session supervision, callback wiring |
| [modules/diagnostics.md](modules/diagnostics.md) | `--doctor` environment self-check and scan troubleshooting |
| [modules/reports.md](modules/reports.md) | Local SQLite summary reports |
| [modules/auth.md](modules/auth.md) | Interactive flow for retrieving an auth_key from an account |
| [modules/tools.md](modules/tools.md) | `tools/` diagnostic, forensic and check scripts |

## User guides

| Document | Contents |
|---|---|
| [guides/installation.md](guides/installation.md) | Linux / Windows / macOS installation, dependencies, optional ECDH compilation |
| [guides/configuration.md](guides/configuration.md) | Full `.env` variables, CLI arguments, precedence and self-checks |
| [guides/usage.md](guides/usage.md) | Live capture, dashboard, history sync, export, reports, sleep, offline dashboard |
| [guides/data-formats.md](guides/data-formats.md) | Data directory, JSONL/SQLite/CSV fields, timestamp semantics |
| [guides/cross-platform.md](guides/cross-platform.md) | Three-platform differences, Linux pairing/trust, Windows/macOS verification checklist |
| [guides/testing.md](guides/testing.md) | Test layout, CI matrix, demo smoke test, documentation/privacy/size checks |
| [guides/faq.md](guides/faq.md) | Common errors and scan/connect/auth/history/dashboard troubleshooting |
| [guides/privacy.md](guides/privacy.md) | Data classification, 0600/ignore rules, redaction when reporting, cleanup |

## Validation and investigations (evidence archive)

These documents preserve the original experiment records, log excerpts and conclusions. In the
English versions only the prose is translated: quoted command output, logs and payload dumps stay
verbatim in their original language, and no number, date or reading is changed.

| Document | Contents |
|---|---|
| [validation/history-hardware.md](validation/history-hardware.md) | Real-hardware verification checklist and results for SpO₂ / activity / sleep SpO₂ `0x26` |
| [validation/linux-validation.md](validation/linux-validation.md) | Ubuntu/BlueZ software stack + real-hardware verification report (L1–L10) |
| [validation/linux-ble-connect-findings.md](validation/linux-ble-connect-findings.md) | 2026-11-12 investigation of unstable Linux connections and root-cause list |
| [validation/linux-ble-test-report.md](validation/linux-ble-test-report.md) | Test 1–4 re-test conclusions, stale LTK root cause, self-healing logic and debug manual |
| [validation/wsl2-usbipd-verification.zh-CN.md](validation/wsl2-usbipd-verification.zh-CN.md) | WSL2 + usbipd Bluetooth passthrough and real-device verification, 2026-11-17~18 (Chinese only for now) |
| [validation/issue-register.zh-CN.md](validation/issue-register.zh-CN.md) | L1–L14 issue register: symptom, status and closing evidence (Chinese only for now) |
| [validation/gadgetbridge-gate0.zh-CN.md](validation/gadgetbridge-gate0.zh-CN.md) | GB benchmark roadmap stage-0 fact-baseline gate: night count, `0x2c`/`0x05` real-device probe records, and B-3/B-12/B-13 unlock decisions (2026-11-20, Chinese only) |
| [validation/gadgetbridge-phase1.zh-CN.md](validation/gadgetbridge-phase1.zh-CN.md) | GB benchmark roadmap stage-1 quick wins: B-2 schema version, B-9 kind single source, B-1 capability gate, B-11 whole-DB backup + baseline (2026-11-20, Chinese only) |
| [validation/gadgetbridge-phase2.zh-CN.md](validation/gadgetbridge-phase2.zh-CN.md) | GB benchmark roadmap stage-2 architecture safety net: B-5 GATT transactions, B-6 FetchSession enhancement, B-4 device state machine + baseline (2026-11-20, Chinese only) |
| [validation/gadgetbridge-phase3.zh-CN.md](validation/gadgetbridge-phase3.zh-CN.md) | GB benchmark roadmap stage-3 data understanding: B-7 multi-granularity co-axis view, B-8 KPI ranges, B-14 battery series + baseline; B-3 stays gated at 0 nights (2026-11-20, Chinese only) |
| [validation/gadgetbridge-phase4.zh-CN.md](validation/gadgetbridge-phase4.zh-CN.md) | GB benchmark roadmap stage-4 verification-driven work: B-10 clock sync and B-12 workout summaries (both hardware-verified); B-13 `0x2c` still empty and suspended, B-15 deferred (2026-11-20, Chinese only) |
| [validation/sleep-calibration-2026-11.zh-CN.md](validation/sleep-calibration-2026-11.zh-CN.md) | Sleep-staging calibration against seven Zepp Life nights (2026-11): corrected page-date convention, nap-vs-night matching bug, duplicate-minute de-duplication, per-reading errors and threshold sweep (2026-11-20, Chinese only) |
| [validation/derived-metrics-probe-2026-11.zh-CN.md](validation/derived-metrics-probe-2026-11.zh-CN.md) | Derived-metric type-code probe (2026-11): six codes answered `0x02`, only `0x0d` PAI carries data and matches five Zepp values; includes the 102-byte layout and its 7-day series (2026-11-20, Chinese only) |
| [investigations/sleep-fields.md](investigations/sleep-fields.md) | Sleep three-byte field forensics and comparison with Zepp Life / Gadgetbridge |

## Risk register

| Document | Contents |
|---|---|
| [improvement-plan.zh-CN.md](improvement-plan.zh-CN.md) | Known risks R-1…R-8 with measured evidence, root-cause analysis and proposed solutions (Chinese only for now) |

## Benchmarking

| Document | Contents |
|---|---|
| [gadgetbridge-benchmark.zh-CN.md](gadgetbridge-benchmark.zh-CN.md) | Gadgetbridge comparative analysis: feature gaps, data-link patterns, UI/data-visualization and engineering borrowables, with a prioritized adoption table, line-by-line source verification (§7) and an implementation roadmap (§8) (Chinese only for now) |

## Tools and conventions

- Tool documentation and script list: [../tools/README.md](../tools/README.md)
- Configuration template: [../.env.example](../.env.example)
- License and third parties: [../LICENSE](../LICENSE),
  [architecture.md#6-third-party-and-compatibility-exemptions](architecture.md#6-third-party-and-compatibility-exemptions)

> Device addresses in the documentation are always placeholders (for example
> `C0:FF:EE:C0:FF:EE`), and dates use placeholder dates. If you find a broken link or stale
> content, run `python tools/check_docs_links.py` first and then open an issue.
