**English** · [简体中文](storage.zh-CN.md)

# storage — Telemetry persistence

## Responsibilities

Turn every sample from the BLE callbacks into a timestamped persisted row, guaranteeing the BLE thread is never blocked by disk:

- JSONL: one JSON object per line, split into files by stream, appended;
- SQLite: a single `mi_band.db` (WAL), one table per stream, indexed by `ts`;
- Background single writer thread: producers only enqueue, the consumer commits in batches;
- CSV export: exports seven tables from SQLite in a fixed column order;
- Permissions: database/JSONL/directories are tightened to 0600/0700 on POSIX.

Source: [miband_monitor/storage/](../../miband_monitor/storage/)

## Module breakdown

| File | Contents |
|---|---|
| `schema.py` | **Single source of truth**: table/column names, `JSONL_FILENAMES`, `_SCHEMA`, `_INSERT_SQL`, `TABLE_COLUMNS`, `STORAGE_BACKENDS`, `SCHEMA_VERSION`/`MIGRATIONS` |
| `summary_schema.py` | Workout-summary table (0x05, B-12) DDL/columns/INSERT and the v1->v2 migration, keeping `schema.py` under 300 lines |
| `store.py` | `TelemetryStore`: public sink API, timestamps, queue, `stats`, `close` |
| `writer.py` | `run_writer_loop` (batch commits, drains the queue after a failure), `QUEUE_POLL_SECONDS` |
| `sqlite.py` | `open_database` (WAL), `insert_record`, `secure_database_files` |
| `readers.py` | `utc_iso`, `normalize_backend`, `read_jsonl`, `table_exists`, `secure_path` |
| `export_csv.py` | `export_table`, `export_database`, `main` (the `export_csv.py` entry point) |

## Public API

| Name | Description |
|---|---|
| `TelemetryStore(output_dir="data", backend="both")` | backend ∈ `jsonl/sqlite/both/none`; `db_path` attribute |
| `record_heart_rate(bpm, timestamp=None)` | Writes `bpm` |
| `record_steps(info, timestamp=None)` | `steps`, `distance_m`, `calories` |
| `record_imu(info, timestamp=None)` | One row per acceleration sample |
| `record_spo2(spo2, auto_measure, timestamp=None)` | Spot-check SpO2 (the band sampling time can be specified) |
| `record_activity_history(sample, timestamp=None)` | Per-minute activity record |
| `record_spo2_sleep(sample)` | Overnight SpO2, separate table |
| `record_activity_summary(sample)` | Band-side workout summary (0x05), replaced by (start,end) pair |
| `stats()` / `close()` / context manager | Counters, drain the queue, close |
| `export_database(db_path, output_dir)` / `export_table(...)` | CSV export |
| Schema constants (`HEART_RATE_TABLE` etc.) | Imported read-only by sleep/offline_dashboard/reports |

## Data flow

```
BLE/history callbacks ──> TelemetryStore.record_*() ──> queue.Queue
                                                  │
                                   writer thread ───┴─> JSONL append
                                                  └─> SQLite batch commit (WAL)
close() ──> enqueue sentinel ──> join (max 10s) ──> statistics
--export-csv ──> export_database() ──> data/csv/*.csv
```

## Dependencies

- `miband_monitor.config` (`DEFAULT_DB_FILENAME`, `secure_path`);
- Standard library `threading`, `queue`, `sqlite3`, `json`;
- Used by `cli/callbacks`, `dashboard.history`, `reports`, `sleep`, `offline_dashboard`;
- The schema has no I/O, so analysis packages can import it safely without starting threads.

## Configuration and constants

| Item | Default | Description |
|---|---|---|
| `--storage` / `STORAGE_BACKEND` | `both` | `jsonl` / `sqlite` / `both` / `none` |
| `DB_FILENAME` | `mi_band.db` | SQLite file name under the output directory |
| `JSONL_FILENAMES` | Seven stream files | One-to-one with table names |
| `COMMIT_BATCH_SIZE` | 200 | SQLite batch commit size |
| `QUEUE_POLL_SECONDS` | 0.5 | Writer queue polling interval |
| `CLOSE_JOIN_TIMEOUT` | 10.0 s | Upper bound for `close()` waiting for the writer to exit |
| Permissions | 0600 / 0700 | File / directory (POSIX) |

## Tables and destinations

| Table / JSONL | Key fields |
|---|---|
| `heart_rate` | `ts, iso_time, bpm` |
| `steps` | `ts, iso_time, steps, distance_m, calories` |
| `imu` | `sensor_type, sequence, sample_index, x/y/z_raw, a*_g, a*_ms2` |
| `spo2` | `ts, iso_time, spo2, auto_measure` |
| `activity_history` | `kind, intensity, steps, heart_rate, unknown1, sleep, deep_sleep, rem_sleep` |
| `spo2_sleep` | `spo2, duration, spo2_high/low, signal_quality, extend` (trailing bytes as JSON text) |
| `activity_summary` | Workout summary: `end_ts, duration_s, kind_code/name, steps, active_seconds, calories, distance_m, average/max/min_hr, average_pace_s_km, version, has_gps`; unique `(ts,end_ts)` |

Field-level formats see [guides/data-formats.md](../guides/data-formats.md).

## Failure modes

| Situation | Behavior |
|---|---|
| Directory cannot be created/read-only | Raises `OSError` at construction with the path; CLI catches it and exits with code 1 |
| Queue full/disk write failure | The writer logs the exception and continues draining the queue; producers never raise inside the BLE callback |
| Writing after `close()` | Records are dropped and counted (visible in `stats`), no exception |
| SQLite locked by another process | WAL + timeout retries; persistent failures are logged, JSONL still works |
| Database file exists but is corrupt | Opening fails and reports an error; never silently deletes it (protects data) |
| `--storage none` | Creates no files, logs only |
| CSV table missing | `export_table` skips/errors; `--export-csv` requires sqlite/both |

## Tests

- `tests/test_storage.py`: timestamps, JSONL/SQLite writes (including SpO2/activity history/sleep SpO2),
  CSV export, writes dropped after close, permission setting.
- `tests/test_dashboard.py` and `tests/test_history_dashboard.py` cover `source=db`
  and the history dashboard's tolerance when reading the schema.

## Related documentation

- [guides/data-formats.md](../guides/data-formats.md)
- [modules/dashboard.md](dashboard.md), [modules/sleep.md](sleep.md)
- [architecture.md](../architecture.md#7-data-contract)
