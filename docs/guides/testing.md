**English** · [简体中文](testing.zh-CN.md)

# Testing and Validation

## 1. Hardware-free tests

```bash
.venv/bin/python -m pytest -q
```

No Bluetooth hardware is needed: the simulated band implements the same wire protocol for authentication, live streams and history fetch. The baseline changes as the refactor progresses; trust the actual output (baseline before the refactor: 270 collected / 266 passed / 4 skipped; the skipped cases need real capture data). CI runs the same test suite on Linux / Windows / macOS × Python 3.10/3.12/3.13.

## 2. Test layout

Current and post-refactor layout (root-level test files remain usable during the refactor):

| Area | Current files | Post-refactor directory |
|---|---|---|
| BLE protocol | `tests/test_chunked_protocol.py`, `tests/test_device_matching.py` | Keep/merge into `tests/simulator` |
| BlueZ | `tests/test_bluez_support.py` | `tests/bluez/{test_platform,test_devices,test_link,test_pairing,test_errors,test_client_integration,test_doctor}.py` |
| ECDH | `tests/test_ecdh_backends.py` | Keep |
| History | `tests/test_history.py` | `tests/history/{test_codecs,test_parsers,test_fetcher,test_sync,test_report}.py` |
| Sleep | `tests/test_sleep.py` | `tests/sleep/{test_detection,test_classification,test_session,test_cli}.py` |
| Simulated band | `tests/test_simulated_band.py` | `tests/simulator/{test_auth,test_streams,test_monitor}.py` |
| Offline dashboard | `tests/test_history_dashboard.py` | `tests/offline_dashboard/{test_collect,test_render}.py` |
| Live dashboard | `tests/test_dashboard.py` | `tests/dashboard/{test_hub,test_server,test_cli}.py` |
| Storage | `tests/test_storage.py` | Keep |
| Tools | `tests/test_import_spo2_sleep.py`, `test_calibrate.py`, `test_probe_declared.py` | Keep |
| Crypto/parsing basics | `test_miband.py` | `tests/test_crypto_parsers.py` |

The "Tests" section of each module's documentation lists the most important behavioral assertions for that area.

## 3. CI pipeline

Steps in [.github/workflows/ci.yml](../../.github/workflows/ci.yml):

1. Install dependencies;
2. `compileall` for `miband_monitor`, root modules, `tests`, `tools`;
3. `tools/check_file_sizes.py`: first-party code/assets ≤300 lines;
4. `tools/check_privacy.py`: git-tracked files must not contain real MACs/keys/paths;
5. `tools/check_docs_links.py`: relative Markdown links must resolve;
6. `tools/check_test_baseline.py`: test-count claims in the READMEs / cross-platform guide must not drift from the collected suite;
7. `pytest -q`;
8. ECDH round-trip smoke with `MIBAND_ECDH_BACKEND=python`;
9. demo full path: `--demo 2 --imu --sync-history 1 --sync-sleep-spo2 --storage both --export-csv`;
10. Verify that demo artifacts are non-empty (JSONL, `mi_band.db`, CSV).

You can run these commands locally one by one; a link-check failure prints `FAIL <file> -> <target>` directly.

## 4. Demo smoke (recommended cross-platform)

```bash
.venv/bin/python miband_client.py --demo 2 --imu --sync-history 1 \
    --sync-sleep-spo2 --output data/ci-demo --storage both --export-csv
```

It should produce `heart_rate/steps/imu/spo2/spo2_sleep.jsonl`, `mi_band.db` and 6 CSVs.
It does not depend on Bluetooth and is the fastest way to verify a successful installation on Windows/macOS.

## 5. Real-device validation

Real-device behavior cannot be covered by CI; validate it manually with the following checklists:

- History protocol (activity/SpO2/0x26): [validation/history-hardware.md](../validation/history-hardware.md);
- Linux software link and real device: [validation/linux-validation.md](../validation/linux-validation.md);
- Linux connection-stability root cause and validation: [validation/linux-ble-connect-findings.md](../validation/linux-ble-connect-findings.md);
- Three-platform validation checklist: [cross-platform.md](cross-platform.md).

## 6. Forensics and calibration tools

```bash
# Keep the raw payload as hard evidence
.venv/bin/python tools/capture_history_payload.py --days 7 --output validation/payloads

# Import 0x26 forensic data (idempotent)
.venv/bin/python tools/import_spo2_sleep.py --output data validation/payloads/history_26_*.bin

# Compare sleep interpretations (refuses to fit when there are too few usable nights)
.venv/bin/python tools/calibrate_sleep.py --zepp data/zepp_nights.json
```

The tests for these scripts are in `tests/test_import_spo2_sleep.py`, `tests/test_calibrate.py`,
`tests/test_probe_declared.py`. Forensic artifacts contain personal data; `validation/` is ignored,
but they must be redacted before external feedback (see [privacy.md](privacy.md)).

## 7. Test-writing conventions

- Do not touch real Bluetooth: use the `simulator` fake backend or monkeypatch the backend;
- Do not depend on the network or real accounts;
- For time-related cases, use an injected `now`/fixed timestamps to avoid flakiness;
- Assert public behavior and data formats, not internal implementation details;
- When adding/changing a data format, you must also update [data-formats.md](data-formats.md) and the relevant module documentation.
