**English** · [简体中文](architecture.zh-CN.md)

# Architecture

This document describes the layering, dependency direction, data flow of a session, compatibility
facades, third-party code exemptions and overall project limitations of `miband_monitor/`.
Module-level details are in [modules/](modules/).

## 1. Design goals

1. **One command end to end**: `python miband_client.py` handles discovery, authentication,
   collection, persistence and an optional dashboard;
2. **Testable without hardware**: the simulated band implements the same wire protocol, so CI never
   touches real Bluetooth;
3. **Replaceable boundaries**: the BLE backend, ECDH backend, storage backend and dashboard data
   source are all injected through parameters;
4. **Traceable protocol evidence**: every constant, timeout and field layout related to the real
   device after reverse engineering keeps its provenance in code comments and
   [validation/](validation/);
5. **Privacy first**: credentials and health data land only locally; permissions are tightened and
   git-ignored by default.

## 2. Layering

```
                         ┌────────────────────────────────────────────┐
   Entry / orchestration │ cli        diagnostics   auth     tools    │
                         └───────┬────────────┬──────────┬────────────┘
                                 │            │          │
                         ┌───────v────────────v──────────v────────────┐
   Domain services       │ ble   history   storage   dashboard       │
                         │ sleep offline_dashboard reports simulator  │
                         └───────┬────────────┬──────────┬────────────┘
                                 │            │          │
                         ┌───────v────────────v──────────v────────────┐
   Infrastructure        │ bluez        crypto          config       │
                         └────────────────────────────────────────────┘
```

| Layer | Package | Rule |
|---|---|---|
| Infrastructure | [config](../miband_monitor/config/), [crypto](../miband_monitor/crypto/), [bluez](../miband_monitor/bluez/) | Does not import domain packages; config uses only the standard library; crypto/bluez can stay independent of each other |
| Domain services | [ble](../miband_monitor/ble/), [history](../miband_monitor/history/), [storage](../miband_monitor/storage/), [dashboard](../miband_monitor/dashboard/), [sleep](../miband_monitor/sleep/), [offline_dashboard](../miband_monitor/offline_dashboard/), [reports](../miband_monitor/reports/), [simulator](../miband_monitor/simulator/) | Depends only downward on infrastructure; the analysis packages (sleep / offline_dashboard) do not start threads or use the network |
| Orchestration layer | [cli](../miband_monitor/cli/), [diagnostics](../miband_monitor/diagnostics/), [auth](../miband_monitor/auth/) plus the root `tools/` scripts | May depend on any domain package; responsible for arguments, interaction, lifecycle and exit codes |

**The dependency direction must be one-way**: `cli → {ble, history, storage, dashboard, simulator, diagnostics}`,
`ble → {bluez, crypto, config}`, `history → config`, `simulator → {ble, history}`.
Domain packages are forbidden to import `cli` in reverse, and `config` is forbidden to import other
project packages.

## 3. Runtime data flow

### 3.1 Live collection

1. [cli/app](../miband_monitor/cli/app.py) parses arguments, loads `.env` and configures logging;
2. [cli/runner](../miband_monitor/cli/runner.py) creates [ble.MiBand6Client](../miband_monitor/ble/)
   and calls `connect_and_authenticate()`;
3. Discovery and link setup: on Linux it goes through the standby `Connect` path of
   [bluez](../miband_monitor/bluez/), while Windows/macOS use a bleak scan; authentication uses the
   ECDH backend from [crypto](../miband_monitor/crypto/);
4. After successful authentication, start the IMU (optional), heart-rate and step-count
   notifications in that order;
5. [cli/callbacks](../miband_monitor/cli/callbacks.py) forwards every sample to
   [storage.TelemetryStore](../miband_monitor/storage/) and optionally to
   [dashboard.TelemetryHub](../miband_monitor/dashboard/);
6. On exit, `store.close()` drains the write queue, and `--export-csv` then exports SQLite.

### 3.2 History sync

`--sync-history` runs **before** the live stream starts: `history.sync_history()` repeatedly calls
`BandHistoryFetcher`, hands the activity / SpO2 / sleep SpO2 payloads to the parsers described in
[modules/history.md](modules/history.md), and callbacks then write them into the three never-mixed
destinations `activity_history`, `spo2` and `spo2_sleep`. Failures are only logged and do not
block the subsequent live collection.

### 3.3 Offline analysis

SQLite is the shared data source for analysis and presentation:

```
data/mi_band.db ──> reports.history      → text / JSON summary
               ├──> sleep.analyze        → sleep window, stages, report
               ├──> offline_dashboard    → single-file HTML (embedded SVG/Canvas data)
               └──> dashboard's source=db → live page refresh backfill
```

## 4. Package and module inventory

| Package | Module split | Documentation |
|---|---|---|
| config | defaults / env / paths / privacy / security / health / demo | [modules/config.md](modules/config.md) |
| crypto | constants / native / pure_python / facade | [modules/crypto.md](modules/crypto.md) |
| bluez | constants / platform / dbus / devices / admin / link / pairing / mtu / scanner / errors | [modules/bluez.md](modules/bluez.md) |
| ble | protocol / parsers / identity / crypto / chunked / backends / discovery / link / mtu / listener / auth_* / notifications / streams / client | [modules/ble.md](modules/ble.md) |
| history | protocol / models / parsers / fetcher / sync | [modules/history.md](modules/history.md) |
| storage | schema / store / writer / sqlite / readers / export_csv | [modules/storage.md](modules/storage.md) |
| dashboard | constants / history / hub / http / page / server + assets | [modules/dashboard.md](modules/dashboard.md) |
| sleep | constants / samples / scoring / detection / classification / session / report / cli / calibration | [modules/sleep.md](modules/sleep.md) |
| offline_dashboard | constants / strings / sources / collect / packaging / kpis / svg / render / cli + assets | [modules/offline-dashboard.md](modules/offline-dashboard.md) |
| simulator | constants / payloads / devices / band / history / auth / streams / fake_bleak / factory | [modules/simulator.md](modules/simulator.md) |
| cli | args / app / callbacks / logging / runner | [modules/cli.md](modules/cli.md) |
| diagnostics | report / checks / doctor / scanning / live_scan | [modules/diagnostics.md](modules/diagnostics.md) |
| reports | history | [modules/reports.md](modules/reports.md) |
| auth | constants / extractor / token | [modules/auth.md](modules/auth.md) |

## 5. Compatibility facades (root shims)

After the refactor, the repository root still keeps the following files; their only responsibility
is "forward + preserve the public names":

| File | Forwarding target |
|---|---|
| `miband_client.py` | `miband_monitor.cli.app.main` (CLI arguments and behavior unchanged) |
| `storage.py` | `miband_monitor.storage` (`TelemetryStore`, schema, readers) |
| `dashboard.py` | `miband_monitor.dashboard` |
| `band_history.py` | `miband_monitor.history` |
| `sleep_analysis.py` | `miband_monitor.sleep` |
| `history_dashboard.py` | `miband_monitor.offline_dashboard` |
| `history_report.py` | `miband_monitor.reports` |
| `export_csv.py` | `miband_monitor.storage.export_csv` |
| `sim_band.py` | `miband_monitor.simulator` |
| `ecdh_wrapper.py` | `miband_monitor.crypto` |
| `bluez_support.py` | `miband_monitor.bluez` |
| `doctor.py` / `scan_ble.py` / `scan_live.py` | `miband_monitor.diagnostics` |
| `get_auth_key.py` / `fetch_by_token.py` | `miband_monitor.auth` |

Old documents, old scripts and third-party examples that write `from storage import TelemetryStore`
and the like continue to work; new code should import `miband_monitor.<domain>` directly.

## 6. Third-party and compatibility exemptions

`tools/check_file_sizes.py` requires every **first-party** code/resource file to be ≤300 lines.
The following content stays as upstream, is intentionally exempt, and does not participate in the
refactor:

| Content | Location | License | Exemption reason |
|---|---|---|---|
| tiny-ECDH (C) | `ecdh.c` / `ecdh.h` | upstream tiny-ECDH-c | Byte-for-byte wire-format dependency; any change breaks compatibility with the band; the compiled artifact `libecdh.so` is a Linux x86-64 prebuild |
| tiny-ECDH-python | [vendor/tiny_ecdh/](../vendor/tiny_ecdh/) | MIT © 2023 Daniel Oliveira | Pure-Python fallback for platforms without the native library (Windows/macOS/ARM/CI), which must match upstream |
| huami-token | [huami_token/](../huami_token/) | MIT © 2025 Kirill Snezhko | Huami/Zepp cloud API client used to obtain auth_key; read-only use |
| Prebuilt library | `libecdh.so` | compiled from the C sources above | Binary artifact, not reviewed by line count; automatically compiled or falls back to pure Python when the library is absent |

**A protocol reference is not code copying**: the chunked-ECDH and history-fetch flows reference
Gadgetbridge's (AGPL-3.0) public reverse-engineering findings; this project is an independent Python
implementation and has not imported its source code or linked its libraries. When adding third-party
code, you must update this table, the exclusion list in `tools/check_file_sizes.py` and the license
note in [guides/privacy.md](guides/privacy.md) at the same time.

## 7. Data contract

- Timestamps: the live stream records **computer receive time**, history sync records **band sampling
  time**, uniformly Unix seconds + UTC ISO-8601;
- Queues/threads: BLE callbacks never do disk I/O directly; they only enqueue;
- The on-disk format is defined by a single source of truth in
  [miband_monitor/storage/schema.py](../miband_monitor/storage/schema.py); changes must consider
  migration of existing data;
- `spo2_sleep` and spot-check `spo2` are two separate datasets and must not be merged; parts whose
  field semantics are undetermined are preserved as-is.

Field-level details are in [guides/data-formats.md](guides/data-formats.md).

## 8. Global limitations and design trade-offs

- **The band is not a general-purpose sensor platform**: only the verified heart rate / step count /
  IMU / history SpO2 / activity are implemented; other services are not guessed;
- **No EEG at the wrist**: sleep staging is heuristic derivation, its output carries `derived: true`
  semantics, and no medical claims are made;
- **The band's buffer holds only about 40 hours**: syncing is "rescuing data", not long-term storage;
- **BLE behavior varies by platform**: BlueZ needs trust/pairing and dedicated standby connection
  logic, while Windows/macOS are handled by the system stack;
- **Single machine, no authentication**: the live dashboard listens on loopback only by default and
  provides no multi-user or remote deployment;
- **Zero web-framework dependencies**: HTTP/SSE/charts are all standard library and a hand-written
  frontend, trading for the smallest dependency surface.
