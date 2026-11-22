**English** · [简体中文](cli.zh-CN.md)

# cli — Command line and session supervision

## Responsibilities

The orchestration layer for every user-visible entry point:

- Argument parsing (**byte-for-byte compatible** with the pre-refactor version: same flags, defaults, help, validation and exit codes);
- `.env` loading and permission tightening, logging configuration;
- Validating the device identifier/key and deciding between real hardware and demo;
- Assembling `TelemetryStore`, the optional `TelemetryHub/DashboardServer` and callbacks;
- Connecting, syncing history, starting data streams, waiting for the duration, reconnecting on disconnect, cleanup on exit and CSV export.

Source: [miband_monitor/cli/](../../miband_monitor/cli/)

## Module breakdown

| File | Contents |
|---|---|
| `args.py` | `build_parser`, `parse_args`, `demo_requested`, historical private helpers `_env_float/_env_optional_int/_secure_env_file` |
| `app.py` | `main(argv)`: the lifecycle and exit codes of the whole command |
| `callbacks.py` | `build_callbacks(store, hub=None)` → `StreamCallbacks` |
| `logging.py` | `configure_logging`, `LOG_FORMAT` (tolerant of legacy Windows code pages) |
| `runner.py` | `run_monitor` (reconnect supervision), `run_demo`, `_sync_band_history` |

## Public API

`main(argv) -> int` (exported at the `miband_monitor.cli` package level); `build_parser()`, `parse_args()`,
`demo_requested(args)`; `run_monitor(device_id, auth_key_hex, *, duration, imu, callbacks,
scan_timeout, connect_timeout, reconnect, reconnect_initial_delay, reconnect_max_delay,
sync_history_days, sync_sleep_spo2, device_name, mtu, direct_connect, client_factory)`;
`run_demo(...)`; `build_callbacks(store, hub=None)`; `configure_logging(level)`.

## Data flow

```
main()
 ├─ parse_args() (load_env + secure_env_file)
 ├─ --doctor ──> diagnostics.run_doctor (does not connect to the band)
 ├─ validate DEVICE_ID/AUTH_KEY (placeholders allowed in demo)
 ├─ TelemetryStore + optional DashboardServer
 ├─ build_callbacks()
 ├─ run_monitor() / run_demo()
 │    ├─ connect_and_authenticate()
 │    ├─ first session: _sync_band_history() (failure does not affect real-time streams)
 │    ├─ start_raw_sensor_stream? → start_heart_rate_stream → start_steps_stream
 │    └─ wait for duration/disconnect → backoff or 0.3s ultra-fast reconnect
 └─ finally: stop dashboard → store.close() → --export-csv
```

## Dependencies

- Domain packages: `ble`, `history`, `storage`, `dashboard`, `simulator` (demo only),
  `diagnostics` (`--doctor` only);
- `miband_monitor.config`, `bluez.errors.describe_ble_error`;
- The root entry point `miband_client.py` is only a compatibility facade doing `from miband_monitor.cli import main`.

## Configuration and constants

CLI arguments (full description in [guides/configuration.md](../guides/configuration.md)):
`duration`, `--imu`, `--device-id`, `--device-name`, `--mtu`, `--sync-history [DAYS]`,
`--sync-sleep-spo2`, `--sync-sports`, `--sync-time` / `--sync-time-dry-run`, `--demo`,
`--output`, `--storage`, `--export-csv`,
`--scan-timeout`, `--connect-timeout`, `--log-level`, `--web-port`, `--web-host`,
`--no-reconnect`, `--doctor`, `--no-direct-connect`.
Reconnect policy: disconnect after successful authentication → 0.3 s fast reconnect (to catch the band's
advertising window after a disconnect); repeated failures → exponential backoff starting at 1 s, capped at 30 s.

## Failure modes

| Situation | Behavior |
|---|---|
| DEVICE_ID/AUTH_KEY not configured | Error and exit code 1, hint to configure `.env` or use `--demo` |
| `--mtu` out of range | Explicit error + valid range, exit code 1 |
| `--sync-sleep-spo2` / `--sync-sports` without `--sync-history` | Rejected by argparse, exit code 2 |
| `--sync-time` together with `--sync-time-dry-run` | Rejected as mutually exclusive, exit code 2 |
| Dashboard port in use | Logs an error, continues collecting without the dashboard |
| History sync fails | Logs an error only, real-time collection continues |
| Session exception | Logs `Monitoring stopped after error`, exit code 1; no reconnect with `--no-reconnect` |
| Ctrl+C | Graceful exit, `Storage summary` prints normally |
| `--export-csv` with `--storage jsonl/none` | warning, export skipped |

## Tests

- `tests/test_device_matching.py`: CLI arguments, environment-variable precedence, macOS name matching;
- `tests/test_dashboard.py`: CLI wiring and dashboard start/stop;
- `tests/test_history.py`: `--sync-history` argument and summary;
- `tests/test_simulated_band.py`: reconnect and timeout behavior of `run_monitor/run_demo`.
- The CI demo smoke command directly covers most branches of `main()`.

## Related documentation

- [guides/configuration.md](../guides/configuration.md), [guides/usage.md](../guides/usage.md)
- [modules/ble.md](ble.md), [modules/diagnostics.md](diagnostics.md)
