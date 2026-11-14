**English** · [简体中文](tools.zh-CN.md)

# tools — Diagnostics, forensics and validation scripts

## Responsibilities

The optional scripts under `tools/` do not take part in normal collection; they are used for hardware forensics, protocol probing, data import and CI validation.
The scripts keep only argument parsing and hardware-facing diagnostic flows, importing shared logic directly from the domain packages
(e.g. `history.parsers.parse_spo2_sleep`, `storage.TelemetryStore`, `sleep.calibration`); there is no separate `miband_monitor.tools` implementation package.

Source: [tools/](../../tools/) (script list and usage in [tools/README.md](../../tools/README.md))

## Script list

| Script | Purpose | Touches the band |
|---|---|---|
| `capture_history_payload.py` | Captures raw history payloads (`.bin` + SHA-256 metadata) for offline review | Yes |
| `import_spo2_sleep.py` | Decodes a 0x26 `.bin` and writes it to `spo2_sleep` JSONL + SQLite (deduplicated by timestamp) | No |
| `probe_declared.py` | Only asks the band "how many minutes are left from time X", fetches no data and sends no ACK | Yes |
| `probe_fetch_types.py` | Queries the start-date reply for an arbitrary history type code | Yes |
| `probe_sleep_session.py` | Probes the Huami `SLEEP_SESSION` (0x48) type | Yes |
| `calibrate_sleep.py` | Compares the four sleep-byte interpretations side by side; refuses to fit when usable nights are insufficient | No |
| `check_file_sizes.py` | CI: first-party code/asset files ≤300 lines | No |
| `check_privacy.py` | CI: Git-tracked files must not contain real MACs/keys/home paths | No |
| `check_docs_links.py` | CI: relative Markdown links must resolve | No |

## Public API

The root `tools/*.py` scripts use the main implementation through `sys.path` or package imports (for example
`history.parsers.parse_spo2_sleep`, `storage.TelemetryStore`, `sleep.calibration`).

## Data flow

```
real band ──capture_history_payload.py──> validation/payloads/history_*.bin + .json
                                              │
                       import_spo2_sleep.py ──┴──> spo2_sleep.jsonl + mi_band.db
probe_*.py ──> read-only queries (no ACK, does not disturb the band's buffer)
calibrate_sleep.py ──> data/zepp_nights.json + SQLite → comparison table (no automatic parameter tuning)
check_*.py ──> CI fail/pass (file size, privacy, documentation links)
```

## Dependencies

- `miband_monitor.ble/history/storage/sleep` and `config`; `bleak`, `cryptography`;
- The forensic scripts write to `validation/`, a directory ignored by `.gitignore`.

## Configuration and constants

- Scripts read device identifiers and keys from `.env`/the environment, never hard-coded; `--scan-timeout` 90–120 recommended;
- `calibrate_sleep.py` uses `data/zepp_nights.json` (personal data, already ignored);
- The exclusion list of `check_file_sizes.py` is exactly the third-party list in [architecture.md](../architecture.md#6-third-party-and-compatibility-exemptions).

## Failure modes

| Situation | Behavior |
|---|---|
| No hardware/credentials not configured | The probe script errors out and modifies no data |
| payload version/length mismatch | `import_spo2_sleep.py` rejects it and explains why |
| Duplicate import | Deduplicated by timestamp, idempotent |
| Forensic data contains real MACs/health data | The output directory is ignored; documentation and issues must be redacted |
| Documentation link broken | `check_docs_links.py` returns non-zero |
| File over 300 lines | `check_file_sizes.py` returns non-zero |

## Tests

- `tests/test_import_spo2_sleep.py`: dual-write of 0x26 `.bin` import, idempotency, dry-run, invalid payloads;
- `tests/test_calibrate.py`: the four interpretations and "refuse to fit when usable nights are insufficient";
- `tests/test_probe_declared.py`: only the start command is written, never fetches data/sends a receipt, zero-filled calendars are not misjudged;
- CI directly runs the three `check_*.py` scripts.

## Related documentation

- [tools/README.md](../../tools/README.md)
- [guides/testing.md](../guides/testing.md), [guides/privacy.md](../guides/privacy.md)
- [validation/history-hardware.md](../validation/history-hardware.md)
