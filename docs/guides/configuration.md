**English** · [简体中文](configuration.zh-CN.md)

# Configuration

Configuration source priority: **command-line arguments > process environment variables > `.env` > built-in defaults**.
Defaults are centralized in `miband_monitor/config/defaults.py`; the `.env` template is
[.env.example](../../.env.example).

## 1. Prepare .env

```bash
cp .env.example .env
```

`.env` is ignored by `.gitignore`; on startup the program tries to tighten it to 0600.
**Do not commit a real auth_key.**

## 2. Variable table

| Variable | Required | Default | Description |
|---|---|---|---|
| `DEVICE_ID` | Yes | — | Band identifier: on Linux/Windows use the MAC (e.g. `C0:FF:EE:C0:FF:EE`); on macOS use the CoreBluetooth UUID |
| `DEVICE_MAC` | No | — | Legacy alias, still supported; when both are set, `DEVICE_ID` takes priority (placeholder values are ignored) |
| `DEVICE_NAME` | No | — | Advertising-name substring match (case-insensitive), e.g. `Mi Smart Band`; useful on macOS/with multiple devices |
| `AUTH_KEY` | Yes | — | 32-character hexadecimal authentication key (16 bytes) |
| `BLE_MTU` | No | auto | Manually override the ATT MTU (23–517); usually leave empty for auto-detection |
| `OUTPUT_DIR` | No | `data` | Output directory for JSONL and `mi_band.db` |
| `STORAGE_BACKEND` | No | `both` | `jsonl` / `sqlite` / `both` / `none` |
| `SCAN_TIMEOUT` | No | `90` | Seconds to wait for advertising; a band with no phone link only emits a pulse every 40–60 seconds, so ≥120 is recommended |
| `CONNECT_TIMEOUT` | No | `75` | Single-connection budget; on Linux it is raised to at least 70 seconds (covering one advertising cycle) |
| `LOG_LEVEL` | No | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `DEMO_MODE` | No | `0` | Set to `1` to be equivalent to `--demo` |
| `WEB_PORT` | No | — | Live dashboard port; leave empty to disable, `0` means a random free port |
| `WEB_HOST` | No | `127.0.0.1` | Dashboard bind address; by default only reachable from the local machine |
| `HISTORY_DAYS` | No | — | Set to N to be equivalent to `--sync-history N` |
| `MIBAND_ECDH_BACKEND` | No | `auto` | Diagnostic use: `auto` / `native` / `python` |
| `MIBAND_ECDH_LIB` | No | — | Explicit path to the native ECDH library |
| `MIBAND_BLUEZ_TRUST` | No | `1` | Linux: mark the device as `Trusted` before connecting; `0` only for A/B experiments |
| `MIBAND_BLUEZ_DUPLICATE_DATA` | No | `0` | Linux: `1` restores `DuplicateData=True` (on BT 5/6 this easily wedges the adapter's scanning) |
| `MIBAND_SMP_SETTLE_DELAY` | No | `1.5` | Linux: seconds to wait after `ServicesResolved` for SMP/profile settlement |
| `MIBAND_BLUEZ_AGENT` | No | `0` | Linux: `1` registers an in-process `NoInputNoOutput` pairing agent |

## 3. Obtain auth_key

Choose one of three:

1. **Xiaomi account** (interactive, password is never written to disk):

   ```bash
   .venv/bin/python get_auth_key.py     # choose 1
   ```

2. **Zepp/Amazfit account**:

   ```bash
   .venv/bin/python get_auth_key.py     # choose 2
   ```

3. **Browser app_token** (existing web login session):

   ```bash
   .venv/bin/python fetch_by_token.py   # enter user_id and app_token
   ```

If you already have output from the third-party `huami-token`, you can fill it into `.env` directly.
`AUTH_KEY` is equivalent to the band's pairing credential; treat it like a password; see [privacy.md](privacy.md) for details.

## 4. Command-line arguments

```
python miband_client.py [duration] [options]

duration              collection seconds; if omitted, run until Ctrl+C
--imu                 also collect raw IMU acceleration (about 25Hz; starts before the heart-rate stream)
--sync-history [DAYS] after connecting, fetch the band history for the last DAYS days (default 7; experimental)
--sync-sleep-spo2     additionally fetch 0x26 overnight SpO2 (requires --sync-history)
--demo                use an in-memory simulated band (no Bluetooth hardware needed)
--device-id ID        override DEVICE_ID (MAC; UUID on macOS)
--device-name NAME    advertising-name substring match (additional discovery condition)
--mtu BYTES           manually override the ATT MTU (23–517; auto-detected by default)
--web-port PORT       start the live dashboard/HTTP API (0 = random free port)
--web-host HOST       dashboard bind address (default 127.0.0.1)
--output DIR          output directory (default $OUTPUT_DIR or data)
--storage MODE        jsonl | sqlite | both | none (default both)
--export-csv          export SQLite to CSV after the session ends
--scan-timeout SEC    scan wait seconds (default 90)
--connect-timeout SEC single-connection budget (default 75)
--log-level LEVEL     DEBUG | INFO | WARNING | ERROR
--no-reconnect        do not automatically reconnect after errors/disconnects
--doctor              run environment self-checks only, do not connect to the band
--no-direct-connect   Linux: force the scan path (to debug stale direct-connect issues)
```

## 5. Common combinations

```bash
# Hardware-free demo (including history sync/sleep SpO2/CSV)
python miband_client.py --demo 2 --imu --sync-history 1 --sync-sleep-spo2 \
    --output data/demo --export-csv

# Long collection + dashboard + export afterwards
python miband_client.py --web-port 8080 --export-csv

# Sync history only, no live streams
python miband_client.py 1 --sync-history 3 --storage both

# Investigate native ECDH backend issues
MIBAND_ECDH_BACKEND=native python miband_client.py --doctor
```

## 6. Validation and troubleshooting

- The first two lines of the startup log print `ECDH backend` and `Discovery target`; please include them when reporting a problem;
- Configuration errors are usually caught explicitly: unconfigured device/key, `--mtu` out of range, `--sync-sleep-spo2` missing its prerequisite argument;
- For permission/environment issues, run `--doctor` first;
- See [cross-platform.md](cross-platform.md) for platform-specific notes and [faq.md](faq.md) for an error lookup.
