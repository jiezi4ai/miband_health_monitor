**English** · [简体中文](sleep.zh-CN.md)

# sleep — Sleep derivation

## Responsibilities

**Derive** sleep windows and stages from the band's activity history (per-minute `kind / intensity / steps / heart_rate`):

- Sleep window: anchored on the band's own `kind` sleep family, extended on both sides by "stationary and not non-wear";
- Awake: any minute with steps (`steps >= 1`) is awake;
- Deep/light sleep: split within the window by heart-rate level ranking + short-term heart-rate variability ranking; `unknown` without heart rate;
- Non-wear: continuous spans with `kind & 0x0F == 3` (`0xF3`), no sleep segment generated;
- All outputs are `derived` values, strictly separated from the band's raw fields.

Source: [miband_monitor/sleep/](../../miband_monitor/sleep/)

## Module breakdown

| File | Contents |
|---|---|
| `constants.py` | Stage names, `kind` codes, window/staging thresholds (every number carries a real-device or Zepp basis comment) |
| `samples.py` | `kind_code`, `is_nonwear`, `is_sleep_kind`, `is_movement`, `is_awake`, `usable_heart_rate`, `load_samples`, local-time formatting |
| `scoring.py` | Experimental reading of the three-byte "stage score": `score_value`, `samples_have_scores`, `score_estimates` |
| `detection.py` | `detect_sessions`, `detect_nonwear_spans` |
| `classification.py` | `classify_session` + `_rank_within`, `_rolling_sd`, `_smooth` |
| `session.py` | `SleepSession`, `build_session`, `analyze`, awakening/longest-sleep-segment statistics |
| `report.py` | `_format_report` text report |
| `cli.py` | `main` (the `sleep_analysis.py` entry point) |
| `calibration.py` | Comparison of the four candidate sleep-byte interpretations with Zepp Life reference values (called by `tools/calibrate_sleep.py`) |

## Public API

`analyze(samples) -> dict` is the main entry point, returning `sessions`, a per-night summary and a `derived: true` marker;
`build_session(samples)`, `detect_sessions`, `detect_nonwear_spans`, `classify_session`
can be tested individually. Sample utilities: `load_samples(db_path, ...)`, `kind_code`, `is_nonwear`,
`is_sleep_kind`, `is_awake`, `usable_heart_rate`, `local_iso`, `local_date`.
Constants are exported with the package (`STAGE_*`, `SLEEP_KIND_MASK`, `DEEP_HR_RANK=0.20`, `DEEP_SD_RANK=0.45`, etc.);
thresholds are centralized in [constants.py](../../miband_monitor/sleep/constants.py).

## Data flow

```
SQLite activity_history ──load_samples()──> [{ts, kind, intensity, steps, heart_rate, ...}]
      │
      ├─ detect_nonwear_spans() ──> 0xF3 continuous spans (no sleep generated)
      ├─ detect_sessions()      ──> anchor (sleep kind) + stationary extension ±60min, bridges gaps ≤20min
      └─ classify_session()     ──> steps decide awake + heart-rate/HRV ranking splits deep sleep, short segments smoothed
                                   │
                              SleepSession ──> text report / offline dashboard / JSON
```

## Dependencies

- `miband_monitor.config.health` (valid heart-rate range, 255 sentinel);
- `miband_monitor.storage.schema` (read-only table names, starts no writer thread);
- Standard library `sqlite3`, `statistics`;
- Reused by `offline_dashboard` and `tools/calibrate_sleep.py`.

## Configuration and constants

| Constant | Value | Basis |
|---|---|---|
| `SLEEP_KIND_MASK/VALUE` | 0xF0 | Of the 27 real-device kinds, only the 0xF0 family is sleep-related |
| `KIND_NONWEAR` | 0x03 | Gadgetbridge `TYPE_NONWEAR`; 679 minutes with 0 heart rate/0 steps |
| `AWAKE_STEPS` | 1 | Zepp's 20-minute awake ≈ the 17 captured minutes with steps |
| `ANCHOR_MINUTES` | 60 | Anchors extend to each side by at most 60 minutes |
| `MIN_ANCHOR_MINUTES / MIN_SESSION_MINUTES` | 10 / 20 | Discards isolated anchors and short segments |
| `SESSION_GAP_MINUTES` | 20 | Bridges brief awakenings during the night |
| `HR_WINDOW_MINUTES` | 7 | Short-term HRV rolling window |
| `DEEP_HR_RANK / DEEP_SD_RANK` | 0.20 / 0.45 | Calibrated on the night of 2020-01-06, **provisional values** |
| `MIN_STAGE_MINUTES` | 3 | Smooths over overly short stage segments |

**No REM is output**: `0x48` declares 0 records in this firmware; the three-byte `rem_sleep` runs in the opposite direction
from the App's REM minutes (when the App reports 0, 458/485 minutes are non-zero; when the App reports 87 minutes, 396/396 are 0),
so treating it as duration would be invention rather than measurement.
Full evidence in [investigations/sleep-fields.md](../investigations/sleep-fields.md).

## Failure modes

| Situation | Behavior |
|---|---|
| Database does not exist/no `activity_history` table | Error or empty result; CLI exit code non-zero |
| Target night has no samples | Reports "no data", does not guess sleep |
| All `kind` values are `0xF3` for the night | Determined to be non-wear, no sleep segment generated and not included in the "latest night" |
| Sleep segment present but no heart rate all night | Deep/light sleep are `unknown`, sleep duration is still reported |
| Three-byte scores missing | Output only as experimental corroboration, not part of primary staging |
| Thresholds based on a single night | Code comments and docs both mark them as "provisional", pending calibration with more Zepp nights |

## Tests

- `tests/test_sleep.py` (after the refactor `tests/sleep/{test_detection,test_classification,test_session,test_cli}.py`):
  `kind` family classification (including `0xF3`), anchor + stationary extension windows, awake determined by steps, deep-sleep staging,
  all-`unknown` for nights without heart rate, no sleep segment for non-wear nights, regression alignment of real-device data with Zepp,
  score integration, CLI text/JSON/specified night.
- `tests/test_calibrate.py`: the four interpretations of `tools/calibrate_sleep.py` and "refuse to fit when usable nights are insufficient".

## Related documentation

- [investigations/sleep-fields.md](../investigations/sleep-fields.md)
- [guides/usage.md](../guides/usage.md) (sleep commands)
- [modules/offline-dashboard.md](offline-dashboard.md), [modules/history.md](history.md)
