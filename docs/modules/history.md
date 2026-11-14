**English** · [简体中文](history.zh-CN.md)

# history — Band-side history data

## Responsibilities

Read the minute-level activity records and SpO2 records stored inside the band and parse them into timestamped samples:

- Private fetch protocol (`0x0004` control/metadata, `0x0005` data chunks);
- Three payloads: normal SpO2 `0x25` (65B/record), activity `0x01` (8B/minute), sleep SpO2 `0x26` (30B/record);
- High-level sync loop: window advancement per data type, failure isolation, result summarization.

Source: [miband_monitor/history/](../../miband_monitor/history/)

## Module breakdown

| File | Contents |
|---|---|
| `protocol.py` | UUIDs, command/response bytes, record sizes, `FetchDataType`, short calendar and fetch time codecs, log formatting |
| `models.py` | `HistoryFetchError`, `HistoryParseError`, `HistorySyncResult` |
| `parsers.py` | `parse_spo2_normal`, `parse_spo2_sleep`, `parse_activity`, `_trim_to_records`, `_parse_payload` |
| `fetcher.py` | `BandHistoryFetcher`: one fetch round, GATT subscription, chunk reassembly, completion frame/ACK |
| `sync.py` | `sync_history`, `summarize_history_result`, `_extend_*` |

## Public API

| Name | Description |
|---|---|
| `FetchDataType` | `ACTIVITY=0x01`, `SPO2_NORMAL=0x25`, `SPO2_SLEEP=0x26` |
| `encode_fetch_time` / `decode_fetch_time` | 6B local calendar + reason + timezone (15 min units) |
| `encode_short_calendar` / `decode_short_calendar` | Short calendar encode/decode |
| `parse_activity(payload, start_ts)` | 8B/minute → `kind,intensity,steps,heart_rate,unknown1,sleep,deep_sleep,rem_sleep` |
| `parse_spo2_normal(payload)` | version 2 + N×65B; negative value = automatic measurement, real value +128 |
| `parse_spo2_sleep(payload)` | version 2 + N×30B; includes duration/high/low/signal/extend |
| `BandHistoryFetcher` | `fetch(start, data_type, ...)` returns the raw payload |
| `sync_history(client, days, on_spo2, on_activity, include_spo2_sleep=False, on_spo2_sleep=None)` | High-level loop, returns `HistorySyncResult` |
| `summarize_history_result(result)` | One-line summary (sample count, rounds, errors) |

## Data flow

```
cli.runner._sync_band_history → history.sync_history
   │  for each type (activity, spo2, [spo2_sleep]):
   │    BandHistoryFetcher.fetch() ──> 0x0004 start-date → 0x0005 chunks
   │                              └──> 10 02 01 completion frame → 0x03 ACK
   │    parsers._parse_payload    ──> list[dict(ts, ...)]
   └──> callbacks ──> storage: activity_history / spo2 / spo2_sleep (three isolated tables)
```

## Dependencies

- Depends only on `miband_monitor.config` and the standard library; `protocol/parsers` do not import a BLE backend,
  so the simulator can reuse the same codecs directly;
- `fetcher` accepts any object with `client`/GATT write/notification capabilities (a real client or the simulated band).

## Configuration and constants

- `DEFAULT_TIMEOUT=30 s`, `DEFAULT_MAX_ROUNDS=12`, `MAX_PAYLOAD_BYTES=65536`;
- `SPO2_RECORD_SIZE=65`, `SPO2_SLEEP_RECORD_SIZE=30`, `ACTIVITY_SAMPLE_SIZE=8`, `SPO2_VERSION=2`;
- `--sync-history DAYS` only says "how far back to ask at most": the band's ring buffer holds about 2400 minutes (40 hours),
  so at most ~40 hours are actually available, and whatever the App has already taken leaves permanent holes;
- 0x26 is off by default (enabled by `--sync-sleep-spo2`), and the semantics of the trailing fields are undetermined.

## Failure modes

| Situation | Behavior |
|---|---|
| Band does not support a type | Logs `band rejected fetch type ...`, continues with other types |
| No start-date / data chunks within 30 s | `HistoryFetchError`, this type fails for this round, retried after reconnecting |
| Chunk sequence gap | Logs `packet counter mismatch` and fails, avoiding misaligned splicing |
| Completion frame is not `10 02 01` | Logs the hex and fails; the optional CRC32 check branch is retained |
| Empty window returns 1970-01-01 | Treated as "no new data", backs off the request window, no error |
| Payload length is not a whole number of records | `_trim_to_records` trims by data type (activity reads until the completion frame) |
| Parsed value out of range (SpO₂<50 etc.) | `HistoryParseError` / sample dropped and logged, never writes garbage data |
| History sync fails | Logs an error only, real-time collection continues |

## Tests

- `tests/test_history.py` (after the refactor split into `tests/history/test_codecs.py`, `test_parsers.py`,
  `test_fetcher.py`, `test_sync.py`, `test_report.py`): time encoding, the three parsers,
  the 0x26 30B layout, byte-level regression of the first two records from real hardware, simulated fetch packet loss, persistence, CLI.
- `tests/test_import_spo2_sleep.py`: dual-write and idempotent deduplication for 0x26 `.bin` import.
- Hardware evidence: [validation/history-hardware.md](../validation/history-hardware.md),
  [investigations/sleep-fields.md](../investigations/sleep-fields.md).

## Related documentation

- [modules/storage.md](storage.md), [modules/sleep.md](sleep.md)
- [guides/data-formats.md](../guides/data-formats.md)
- [guides/usage.md](../guides/usage.md) (history sync command)
