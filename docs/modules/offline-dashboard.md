**English** · [简体中文](offline-dashboard.zh-CN.md)

# offline-dashboard — Offline single-file history dashboard

## Responsibilities

**Bake** the activity history, heart rate, spot-check SpO2 and overnight sleep SpO2 from SQLite **into a self-contained HTML file**:

- No CDN, no fonts, no external images, no network requests; it can be opened by double-clicking, emailed or archived long-term;
- Server-side rendered SVG sleep-stage chart + embedded Canvas curves;
- Data-source tolerance: missing tables, old databases, or only forensic JSONL — all yield an explainable result.

Source: [miband_monitor/offline_dashboard/](../../miband_monitor/offline_dashboard/)

## Module breakdown

| File | Contents |
|---|---|
| `constants.py` | Time windows, stage order/labels, data-source markers, `SPO2_SLEEP_JSONL` |
| `strings.py` | KPI labels and page wording (historical output strings are kept unchanged) |
| `sources.py` | Probes/reads the SQLite tables and `spo2_sleep.jsonl`, column names come from the storage schema |
| `collect.py` | Assembles the activity/heart-rate/SpO2/sleep series and applies time-window filtering |
| `packaging.py` | Packages template variables such as `DATA` and stage styles |
| `kpis.py` | KPI computation (latest night, deep-sleep share, sleep efficiency, steps, heart-rate zones, minimum SpO2) |
| `svg.py` | Sleep-stage chart (run-length compression, positioned by real timestamps) |
| `render.py` | Reads the HTML template and injects the data |
| `cli.py` | `main` (the `history_dashboard.py` entry point) |
| `assets/` | `history_dashboard.html`, `history_dashboard.css`, `history_dashboard.js`, `history_charts.js`, `history_dashboard_tables.js` |

## Public API

| Name | Description |
|---|---|
| `collect(db_path, *, days=7, spo2_sleep_path=None)` | Returns the series and metadata needed for rendering |
| `render(payload)` / `build(...)` | Produces the full HTML string |
| `hypnogram_svg(stages, height=44, lane_gap=1.0)` | Stage chart SVG |
| `main(argv)` | CLI: `--db`, `-o/--output`, `--days`, `--spo2-sleep-jsonl` |

## Data flow

```
data/mi_band.db ──sources.collect()──> activity / heart_rate / spo2 / spo2_sleep
   │(when the spo2_sleep table is empty, fall back to the JSONL in the same directory or given by --spo2-sleep-jsonl)
   v
collect ──> kpis + svg ──> packaging ──> render(template) ──> a single .html
```

## Dependencies

- `miband_monitor.sleep` (session detection and staging), `storage.schema` (table/column names), `config.health`;
- Standard library `sqlite3`, `json`, `statistics`, `pathlib`;
- Does not depend on BLE, starts no threads, makes no network requests.

## Configuration and constants

| Item | Default | Description |
|---|---|---|
| `--db` | `data/mi_band.db` | Input database |
| `-o/--output` | `dashboard_history.html` | Output file |
| `--days` | 7 | Time window shown |
| `--spo2-sleep-jsonl` | Automatic fallback | Reads the forensic JSONL when the table is empty |

KPI labels and stage colors are part of the output contract and are centralized in `strings.py` / `constants.py`.

## Failure modes

| Situation | Behavior |
|---|---|
| Database does not exist | Earlier versions generated an empty dashboard and exited 0 (L4, see the Linux validation report); the current implementation should error, so confirm the database exists before use |
| Missing table/old database | `sources` probes table by table, missing tables are treated as empty series, no crash |
| Overnight SpO2 table empty | Falls back to `spo2_sleep.jsonl` in the same directory; if still absent only spot-check SpO2 is shown |
| Heart rate missing | A gray in-bed band is drawn at the chart position instead of four empty lanes pretending to have data |
| Activity history discontinuous | Bars are positioned by real timestamps, avoiding global misalignment caused by missing minutes |
| SpO2 gaps longer than 5 minutes | The curve breaks, no continuous line segment is fabricated |
| Output directory not writable | CLI reports an error and returns non-zero |

## Tests

- `tests/test_history_dashboard.py` (after the refactor `tests/offline_dashboard/{test_collect,test_render}.py`):
  empty database/missing-table tolerance, time-window filtering, the 255 sentinel excluded from averages, activity bars at real timestamps
  colored by session, SVG coverage and lane order, overnight SpO2 table/JSONL fallback, template injection with no leftover placeholders,
  single-file self-containment, CLI.
- Hardware dashboard output and KPIs see the appendix of [validation/history-hardware.md](../validation/history-hardware.md).

## Related documentation

- [guides/usage.md](../guides/usage.md)
- [guides/data-formats.md](../guides/data-formats.md)
- [modules/sleep.md](sleep.md), [modules/dashboard.md](dashboard.md)
