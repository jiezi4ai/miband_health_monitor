**English** · [简体中文](README.zh-CN.md)

# Mi Band 6 Health Monitor

Connect to a Mi Band 6 directly over **BLE**, bypass the phone app, and stream heart rate,
live step count and raw IMU acceleration data to your computer in real time. Every record
is timestamped and persisted as JSONL / SQLite, with one-command CSV export for later
analysis and further development.

Runs on Linux / Windows / macOS; without hardware, the built-in simulated band exercises
the whole pipeline; the code is split by domain inside the `miband_monitor/` package, and
the historical scripts remain as compatibility entry points.

> **Languages:** documentation is provided in English (this file) and Simplified Chinese
> ([README.zh-CN.md](README.zh-CN.md)); every document has a language switcher at the top,
> and its Chinese counterpart is the same path with `.zh-CN` before `.md` (for example
> [docs/architecture.zh-CN.md](docs/architecture.zh-CN.md)). Code, comments and docstrings
> are English. The dashboards' on-screen labels are currently Simplified Chinese; the
> English documentation gives the English gloss wherever it describes them.

---

## 1. Feature overview

| Capability | Description |
|---|---|
| Direct band connection | Scan, connect and auto-reconnect on link loss via [`bleak`](https://github.com/hbldh/bleak) (Linux/BlueZ, Windows/WinRT, macOS/CoreBluetooth) |
| Cross-platform | Linux / Windows 10+ / macOS; automatically falls back to pure Python when the native ECDH library is unavailable (no compiler needed) |
| Secure authentication | Huami Chunked Transfer + NIST B-163 ECDH + AES-CBC challenge/response; chunk reassembly with sequence validation, bounds protection and duplicate handling |
| Heart rate | Standard BLE SIG Heart Rate service (`0x2A37` / `0x2A39`), continuous measurement + 12 s keep-alive |
| Live steps | Private characteristic `0x0007`: steps / distance / calories |
| Raw IMU | Private characteristics `0x0001`/`0x0002`, about 25 Hz three-axis acceleration (requires `--imu`); only `0x00`-type frames are acceleration (int16, 4096 LSB/g), `0x01`/`0x07` frames on the same characteristic are ignored |
| Live dashboard | `--web-port` starts an embedded HTTP server: SSE push + single-page charts (heart rate / SpO₂ / steps / IMU), **no third-party dependencies**; a page refresh backfills history from SQLite |
| SpO₂ | Fetched from band-side history (requires `--sync-history`, verified on real hardware) |
| Historical activity | Per-minute activity intensity / steps / heart rate / sleep flags (requires `--sync-history`, verified on real hardware) |
| Sleep SpO₂ 0x26 | `--sync-sleep-spo2` fetches whole-night SpO₂ (30 B layout **verified on real hardware**, 430 records in one night), written to a **separate** `spo2_sleep` table + JSONL + CSV; the offline dashboard draws the whole-night curve, fully isolated from spot-check `0x25` |
| Local history report | `history_report.py` summarizes heart rate / SpO₂ / activity data from SQLite, as text or JSON |
| Sleep derivation | `sleep_analysis.py`: a `kind` state machine detects sleep windows, then heart-rate level and heart-rate variability ranks distinguish deep / light sleep (**derived values**, no REM output; the band does not report stages directly) |
| Offline history dashboard | `history_dashboard.py` generates a **single-file HTML**: KPIs, sleep structure chart, heart rate, activity rhythm, steps, whole-night SpO₂ curve, spot-check SpO₂ table; no external resources, opens offline and can be shared as-is |
| Timestamps / persistence | Every record carries Unix seconds + UTC ISO-8601 milliseconds; JSONL append writes + SQLite WAL, either or both |
| CSV export | Export 6 CSV tables from SQLite |
| Auto-reconnect | Exponential-backoff reconnect after a session failure or link loss; a failed heart-rate keep-alive also triggers reconnect |
| No-hardware demo | `--demo` runs the complete pipeline against the built-in simulated band (authentication, data streams, history sync, persistence, export) |
| Tests | 270+ unit/integration tests, including a simulated BLE backend, **no real band needed**; CI covers Linux/Windows/macOS |

---

## 2. How it works

```text
┌────────────────┐  1. account login (optional, first run)   ┌────────────────────────────┐
│ Xiaomi/Zepp    │ ─────────────────────────────────────────> │ miband_monitor.auth        │
│ account        │    get_auth_key.py / fetch_by_token.py    │ → AUTH_KEY written to .env │
└────────────────┘                                            └──────────────┬─────────────┘
                                                                             v
┌────────────────┐  2. BLE scan / connect / authenticate  ┌──────────────────────────────┐
│ Mi Band 6      │ <─────────────────────────────────────> │ miband_monitor.ble          │
│                │  3. three real-time GATT notifications  │ ├─ bluez (Linux compat)     │
│                │ ──────────────────────────────────────> │ ├─ crypto (ECDH backends)   │
└────────────────┘                                         │ └─ HR/steps/IMU parsers     │
                                                           └──────┬───────────────┬──────┘
                                                                  │ timestamps    │ history fetch
                                                       ┌──────────v───────┐  ┌────v──────────────────┐
                                                       │ storage          │  │ history (0x0004/5)    │
                                                       │ JSONL + SQLite   │  │ parsers + sync        │
                                                       │ single writer    │  └────┬──────────────────┘
                                                       └──────┬─────┬─────┘       │
                                                              │     │             │
                                                 ┌────────────v─┐ ┌─v──────────┐  │
                                                 │ export_csv   │ │ dashboard  │  │
                                                 │ → CSV        │ │ HTTP + SSE │  │
                                                 └──────────────┘ └────────────┘  │
                                                                                 v
                                                                   sleep / offline_dashboard
                                                                   reports (SQLite → report / HTML)
```

Authentication flow (simplified):

1. The client sends its own B-163 public key (inner message `04 02 00 02 + pubkey`, sent in chunks).
2. The band returns `16-byte random salt + 48-byte public key` (chunked notifications with sequence
   numbers; the client validates continuity and reassembles).
3. Both sides compute the 48-byte ECDH shared secret; `shared[8:24] XOR auth_key` yields the session
   AES key.
4. The client sends back `0x05 + AES-CBC(auth_key, salt) + AES-CBC(session_key, salt)`; the band
   confirms and authentication succeeds.

History data (`--sync-history`) is fetched through the band's private `0x0004`/`0x0005`
characteristics: activity is stored per minute, SpO₂ per reading, then both enter the same
storage/dashboard/export pipeline described above. Protocol details and real-hardware evidence
are in [docs/validation/history-hardware.md](docs/validation/history-hardware.md).

---

## 3. Project structure

```text
miband_health_monitor/
├── miband_monitor/             # first-party implementation (domain packages, see docs/modules/)
│   ├── config/                 # defaults, environment variables, paths, privacy and permissions
│   ├── crypto/                 # ECDH native + pure-Python dual backends
│   ├── bluez/                  # Linux/BlueZ D-Bus compatibility layer
│   ├── ble/                    # BLE client, protocol codecs, authentication, data streams
│   ├── history/                # band-side history fetch, parsing, sync
│   ├── storage/                # JSONL/SQLite schema, writer thread, CSV export
│   ├── dashboard/              # live dashboard (HTTP + SSE + frontend assets)
│   ├── sleep/                  # sleep window / stage derivation
│   ├── offline_dashboard/      # offline single-file HTML history dashboard
│   ├── simulator/              # in-memory simulated band + fake bleak backend
│   ├── cli/                    # command-line entry points and session supervision
│   ├── diagnostics/            # --doctor and scan troubleshooting
│   ├── reports/                # local history summary reports
│   └── auth/                   # account-based auth_key retrieval
├── miband_client.py            # compatibility entry point: forwards to miband_monitor.cli
├── storage.py / dashboard.py / band_history.py / sleep_analysis.py / ...
│                               # compatibility shims: old import paths keep working
├── ecdh.c / ecdh.h / libecdh.so              # third-party tiny-ECDH (C / prebuilt)
├── vendor/tiny_ecdh/           # third-party pure-Python ECDH fallback (MIT)
├── huami_token/                # third-party Huami cloud API client (MIT)
├── tools/                      # diagnostic / forensic / doc-check scripts
├── tests/                      # hardware-free test suite (split by domain)
├── docs/                       # documentation center, entry point docs/README.md
├── .github/workflows/ci.yml    # Linux/Windows/macOS test matrix
├── requirements.txt / pytest.ini / .env.example
└── README.md
```

> The old scripts (`miband_client.py`, `storage.py`, `history_report.py`, etc.) remain as
> **compatibility facades**: behaviour and CLI arguments are unchanged; the real implementation
> lives in `miband_monitor/<domain>/`.

---

## 4. Quick start

### 4.1 Installation

```bash
cd miband_health_monitor
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

On Windows use `.venv\Scripts\python.exe`; per-platform steps are in
[docs/guides/installation.md](docs/guides/installation.md).

### 4.2 Configuration

```bash
cp .env.example .env          # fill in DEVICE_ID (MAC or macOS UUID) and AUTH_KEY
```

`.env` is git-ignored and will be tightened to 0600. The full variable table is in
[docs/guides/configuration.md](docs/guides/configuration.md); if you do not have an
`AUTH_KEY` yet, obtain one with `get_auth_key.py` / `fetch_by_token.py`.

### 4.3 Self-check and no-hardware demo

```bash
# Environment self-check: adapter, pairing state, ECDH backend, .env permissions (read-only, does not connect)
.venv/bin/python miband_client.py --doctor

# Exercise the whole pipeline without hardware (simulated band, IMU, history sync and CSV export)
.venv/bin/python miband_client.py --demo 2 --imu --sync-history 1 \
    --output data/demo --export-csv
```

### 4.4 Real-device capture

```bash
.venv/bin/python miband_client.py 60                 # 60 s of heart rate + steps
.venv/bin/python miband_client.py 60 --imu           # additionally 25 Hz IMU
.venv/bin/python miband_client.py --export-csv       # capture until Ctrl+C, then export CSV
.venv/bin/python miband_client.py --storage none     # log only, no persistence
.venv/bin/python miband_client.py 60 --sync-history 7 --sync-sleep-spo2
```

Real-device essentials: **turn off phone Bluetooth**; with no phone link the band only emits one
advertising pulse every 40–60 seconds, so `--scan-timeout 120` is recommended; on Linux, for the
first pairing without a cache, add `MIBAND_BLUEZ_AGENT=1` to complete pairing and trust; once a
cache exists you can run directly and connect without scanning (and after a normal phone sync no
cache clearing is needed). See [docs/guides/cross-platform.md](docs/guides/cross-platform.md) and
[docs/guides/faq.md](docs/guides/faq.md).

### 4.5 Dashboards, history and reports

```bash
.venv/bin/python miband_client.py --web-port 8080            # live dashboard/API
.venv/bin/python history_report.py --hours 24                # text summary
.venv/bin/python sleep_analysis.py --db data/mi_band.db      # sleep derivation
.venv/bin/python history_dashboard.py -o history.html --days 7   # offline single-file dashboard
.venv/bin/python export_csv.py --db data/mi_band.db --output data/csv
```

Full commands and arguments are in [docs/guides/usage.md](docs/guides/usage.md).

### 4.6 Compatibility with old commands and imports

The refactor only moved implementations; user-facing interfaces are unchanged:

- every historical command (`miband_client.py`, `history_report.py`, `export_csv.py`,
  `sleep_analysis.py`, `history_dashboard.py`, `scan_ble.py`, ...) keeps its arguments and
  output format;
- old import paths (`from storage import TelemetryStore`, `import sleep_analysis`, etc.) keep
  working through the root compatibility facades;
- CI checks first-party files are ≤300 lines, runs the privacy scan, validates local
  documentation links and runs the full test suite.

---

## 5. Documentation navigation

| Entry | Contents |
|---|---|
| [docs/README.md](docs/README.md) | Documentation index and reading paths |
| [docs/architecture.md](docs/architecture.md) | Layered architecture, dependency direction, data flow, third-party exemptions and limitations |
| [docs/modules/](docs/modules/) | Responsibilities, public API, data flow, failure modes and tests for the 15 domain modules |
| [docs/guides/installation.md](docs/guides/installation.md) | Installation and dependency notes for the three platforms |
| [docs/guides/configuration.md](docs/guides/configuration.md) | Full `.env` variable table, CLI arguments, precedence |
| [docs/guides/usage.md](docs/guides/usage.md) | Capture, dashboard, history sync, reports, sleep, offline dashboard |
| [docs/guides/data-formats.md](docs/guides/data-formats.md) | Data directory, JSONL/SQLite/CSV fields and time semantics |
| [docs/guides/cross-platform.md](docs/guides/cross-platform.md) | Linux/Windows/macOS differences and verification checklist |
| [docs/guides/testing.md](docs/guides/testing.md) | Test layout, CI, demo smoke test, documentation/privacy checks |
| [docs/guides/faq.md](docs/guides/faq.md) | Common questions and troubleshooting |
| [docs/guides/privacy.md](docs/guides/privacy.md) | Data classification, permissions, cleanup, pre-submission checks |
| [docs/validation/](docs/validation/) | Real-hardware evidence: history protocol, Linux connection |
| [docs/investigations/sleep-fields.md](docs/investigations/sleep-fields.md) | Sleep three-byte forensics and comparison with Zepp |

Each English document has a Simplified Chinese counterpart: same path with `.zh-CN` before
`.md` (for example `docs/guides/usage.zh-CN.md`). Use the language bar at the top of any
document to switch.

---

## 6. Privacy and security summary

- `AUTH_KEY` is equivalent to the band's Bluetooth pairing credential; treat it as a password.
  `.env` is git-ignored by default and tightened to 0600.
- Heart rate, SpO₂, activity, IMU and sleep results are **personal health data** and are all
  written under `data/` (git-ignored by default).
- Device addresses in code and documentation are always placeholders (such as
  `C0:FF:EE:C0:FF:EE`); the repository contains no real MAC addresses, keys or home paths.
- The dashboard/HTTP API binds only to `127.0.0.1` by default and has no authentication; do not
  expose it directly to the public internet.
- Sanitize before reporting issues: see [docs/guides/privacy.md](docs/guides/privacy.md) and
  `tools/check_privacy.py`.

---

## 7. License and third party

This project is released under the [MIT License](LICENSE), Copyright © 2026 alex-j-zhang.

| Third party | Location | License / notes |
|---|---|---|
| `bleak` | dependency (requirements.txt) | MIT, cross-platform BLE wrapper |
| `huami_token` | `huami_token/` | MIT, © 2025 Kirill Snezhko, Huami/Zepp cloud API client |
| `tiny-ECDH` (C) | `ecdh.c` / `ecdh.h` | upstream C implementation, compiled to `libecdh.so` as an accelerator |
| `tiny-ECDH-python` | `vendor/tiny_ecdh/` | MIT, © 2023 Daniel Oliveira, pure-Python fallback |
| Gadgetbridge (protocol reference) | no code copied | AGPL-3.0, used only as reference for publicly reverse-engineered protocol facts |

Third-party code is kept verbatim and is exempt from the 300-line budget; the complete exemption
table and rationale are in
[docs/architecture.md](docs/architecture.md#6-third-party-and-compatibility-exemptions).

### 7.1 Development and checks

```bash
.venv/bin/python -m pytest -q                    # hardware-free tests (including simulated band)
.venv/bin/python tools/check_file_sizes.py       # first-party files ≤300 lines
.venv/bin/python tools/check_privacy.py          # no real MAC/key/path in the repository
.venv/bin/python tools/check_docs_links.py       # relative Markdown links resolve
```

See [docs/guides/testing.md](docs/guides/testing.md) for the test layout, the three-platform CI
matrix and the real-hardware verification checklist.

---

## 8. Status and known limitations

- The SpO₂/activity history and the sleep SpO₂ `0x26` 30 B layout are both verified on real
  Mi Band 6 hardware; the `duration` / `signal` / `extend` semantics of `0x26` are undecided,
  so it remains marked `[experimental]` and is not requested by default.
- Only heart rate / steps / IMU / SpO₂ (history) / activity (history) are covered; stress,
  workout details, battery level and others are not implemented yet.
- Sleep staging is a **derived value** (there is no EEG at the wrist); it is meant for trends and
  structure, not minute-by-minute medical interpretation.
- The band keeps only the last ~40 hours of minute data; parts already consumed by the phone app
  leave permanent gaps. Sync promptly to keep a given night.
- Windows/macOS are code-compatible; real-hardware verification status is tracked in
  [docs/guides/cross-platform.md](docs/guides/cross-platform.md).
- Dashboard and offline-dashboard on-screen labels are currently Simplified Chinese; the English
  documentation translates the labels it references.

---

## 9. Feedback and contributions

When reporting an issue, please include:

1. OS and version, Python version, `bleak` version, Bluetooth adapter model;
2. the first lines of the startup log (`ECDH backend`, `Discovery target`, MTU);
3. the full `--log-level DEBUG` log (**redact MAC and auth_key first**);
4. which step failed and whether it reproduces reliably.

Do not submit `.env`, `data/`, `validation/` or packet captures; see
[docs/guides/privacy.md](docs/guides/privacy.md) for sanitizing and cleanup. Protocol and
hardware evidence is best organized under [docs/validation/](docs/validation/) or
[docs/investigations/](docs/investigations/).
