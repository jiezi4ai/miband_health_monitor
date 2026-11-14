**English** · [简体中文](diagnostics.zh-CN.md)

# diagnostics — Environment self-check and scan troubleshooting

## Responsibilities

Turn "why can't it connect" from log guesswork into copyable check steps:

- `miband_client.py --doctor`: read-only check of the configuration, ECDH backend, output directory and (on Linux) the BlueZ
  adapter/device state; does not connect to the band or modify system settings; on failure prints copyable repair commands.
- `scan_ble.py`: one-shot scan listing addresses and RSSI grouped as "band / other devices".
- `scan_live.py`: continuous scanning that prints every packet, used to catch the isolated advertising pulse that only appears every 40–60 s.

Source: [miband_monitor/diagnostics/](../../miband_monitor/diagnostics/)

## Module breakdown

| File | Contents |
|---|---|
| `report.py` | `_Report`, `OK/INFO/WARN/FAIL` levels and the unified output format |
| `checks.py` | Individual checks: `.env` permissions, dependency versions, ECDH backend, output directory writability, device identifier format |
| `doctor.py` | `run_doctor(device_id, auth_key, output)` orchestration, returns 0/1 |
| `scanning.py` | `scan_devices()` (the implementation of `scan_ble.py`) |
| `live_scan.py` | Continuous scan main loop (the implementation of `scan_live.py`), reuses `bluez.scanner_kwargs()` on Linux |

## Public API

| Name | Description |
|---|---|
| `run_doctor(device_id, auth_key, output) -> int` | Async self-check; 0 = all passed, 1 = some FAIL |
| `_Report` | Collects check results and formats output (for test assertions) |
| `scan_devices(duration_seconds=90)` | bleak scan, distinguishes the band from other BLE devices |
| `main()` (live scan) | Continuously prints `[FOUND] address | name | rssi` |

## Data flow

```
cli.args --doctor ──> cli.app.main ──> diagnostics.doctor.run_doctor
                                         ├─ config.env / config.privacy (redaction)
                                         ├─ crypto.facade.backend_name()
                                         ├─ storage.secure_path / output directory probe
                                         └─ bluez.list_adapters()/find_device()
scan_ble.py / scan_live.py ──> diagnostics.scanning / live_scan ──> bleak
```

## Dependencies

- `miband_monitor.config`, `crypto`, `bluez`; the scan scripts also depend on `bleak`.
- Does not depend on `ble.client`, so the self-check does not need the authentication code path.

## Configuration and constants

- Scanning defaults to 90 s (`SCAN_TIMEOUT`); without a phone link the band only emits a pulse every 40–60 s,
  so a short window will almost certainly miss it;
- `--doctor` uses `--output`, `DEVICE_ID`/`DEVICE_MAC`, `AUTH_KEY` (format checked only, never printed in plaintext);
- On Linux it checks trusted/paired/connected, adapter powered, and the actual `.env` permissions.

## Failure modes

| Situation | Output/behavior |
|---|---|
| Device identifier or key not configured | `[FAIL]` + hint pointing at `.env.example`, exit code 1 |
| `.env` permissions too open | `[WARN]` (or FAIL, depending on platform) and a `chmod 600` command |
| Adapter not powered/no adapter | `[FAIL]`, hint to start the `bluetooth` service |
| Device not trusted/paired | `[WARN]`, with `bluetoothctl trust/pair` commands |
| Output directory not writable | `[FAIL]`, hint to change `--output` |
| Non-Linux platform | BlueZ checks skipped, everything else proceeds as usual |
| Scan finds nothing in 90 s | Prints "the band may not be advertising" plus phone Bluetooth/pulse-period hints, non-zero exit code |

## Tests

- `tests/test_bluez_support.py::test_doctor_*` (after the refactor `tests/bluez/test_doctor.py`):
  report levels, redaction, output-directory failure, mocks of the BlueZ checks.
- `tests/test_probe_declared.py` covers the arguments and safety behavior of the `tools/` probes (no ACK sent).
- Hardware troubleshooting record: [validation/linux-validation.md](../validation/linux-validation.md) (L1–L10, P0 re-verification).

## Related documentation

- [guides/faq.md](../guides/faq.md)
- [guides/cross-platform.md](../guides/cross-platform.md)
- [modules/bluez.md](bluez.md)
