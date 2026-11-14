**English** · [简体中文](reports.zh-CN.md)

# reports — Local history summary

## Responsibilities

Read the heart-rate/SpO2/activity data of the last N hours from SQLite and output a human-readable summary (text or JSON):

- Heart-rate record count, min/max/mean;
- SpO2 record count, mean, automatic-measurement count;
- Active minutes, total steps;
- Explainable output when tables are missing or the database is empty.

Source: [miband_monitor/reports/](../../miband_monitor/reports/)

## Module breakdown

| File | Contents |
|---|---|
| `history.py` | `summarize`, `format_report`, `main`, `DEFAULT_DB`; table probing and scalar query helpers |

## Public API

| Name | Description |
|---|---|
| `summarize(db_path, hours=24.0, now=None) -> dict` | Aggregated result; raises `FileNotFoundError` if the database does not exist |
| `format_report(summary) -> str` | Text report |
| `main(argv=None) -> int` | CLI: `--db`, `--hours`, `--json` |
| `DEFAULT_DB` | `data/mi_band.db` (from config.paths) |

## Data flow

```
data/mi_band.db ──summarize()──> dict ──format_report()──> text
                                     └─ json.dumps() ──> --json
```

## Dependencies

- `miband_monitor.config.paths`; standard library `sqlite3`, `json`;
- Read-only, writes no database and starts no threads; the root entry point `history_report.py` is a compatibility facade.

## Configuration and constants

- The default window is 24 hours; `--hours 168` means 7 days;
- The time window is based on UTC timestamps, displayed in local time in the report;
- The 255 heart-rate sentinel and out-of-range values are excluded from statistics (consistent with the dashboard/sleep definitions).

## Failure modes

| Situation | Behavior |
|---|---|
| Database does not exist | `FileNotFoundError` → CLI error message + exit code 1 |
| A table is missing | The corresponding metric shows "no data", the rest proceeds normally |
| No records within the time window | Outputs 0 records plus a note, no error |
| Database corrupt/locked | The sqlite exception propagates, CLI prints the error |

## Tests

- `tests/test_history.py` (after the refactor `tests/history/test_report.py`): summary fields, empty database/missing table,
  JSON output, CLI exit code.
- Real-hardware report samples see [validation/linux-validation.md](../validation/linux-validation.md).

## Related documentation

- [guides/usage.md](../guides/usage.md)
- [guides/data-formats.md](../guides/data-formats.md)
- [modules/storage.md](storage.md)
