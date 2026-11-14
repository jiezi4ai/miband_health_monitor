**English** · [简体中文](usage.zh-CN.md)

# Usage

All commands are run from the repository root; the examples use `.venv/bin/python`; on Windows write
`.venv\Scripts\python.exe`. See [configuration.md](configuration.md) for the meaning of the configuration options.

## 1. Start with the hardware-free full path

```bash
.venv/bin/python miband_client.py --demo 2 --imu --sync-history 1 \
    --output data/demo --export-csv
```

This single command covers authentication, the three live streams, history sync, JSONL/SQLite persistence
and CSV export. Outputs: `data/demo/heart_rate.jsonl` etc., `mi_band.db`, `data/demo/csv/`.
No Bluetooth hardware is needed, so it also works as a smoke test on Windows/macOS.

## 2. Real-device collection

```bash
# Environment self-check (adapter, pairing, ECDH, .env permissions; does not connect to the band)
.venv/bin/python miband_client.py --doctor

# Collect 60 seconds of heart rate + steps
.venv/bin/python miband_client.py 60

# Collect 60 seconds and add 25Hz IMU
.venv/bin/python miband_client.py 60 --imu

# Collect until Ctrl+C, write SQLite as well, export CSV at the end
.venv/bin/python miband_client.py --export-csv

# Logs only, nothing persisted
.venv/bin/python miband_client.py --storage none
```

Real-device essentials:

- **Turn off phone Bluetooth / enable airplane mode**, otherwise the band stays connected to the phone and does not advertise;
- The band only emits one isolated connectable advertising pulse every **40–60 seconds**, and sends none at all with the screen off;
  **waking or swiping the screen does not make it advertise faster** (measured 2026-11-12); it only affects the connection interval after the link is established,
  hence `--scan-timeout 120`;
- Linux: with **no BlueZ cache on first use**, we recommend `MIBAND_BLUEZ_AGENT=1 .venv/bin/python miband_client.py 60` to automatically perform trust and first pairing; once a **`paired/trusted` cache exists**, just run the default command for scan-free direct connection (no need to clear the cache after a normal phone sync either; see [cross-platform.md](cross-platform.md) for details);
- The heart-rate sensor turns itself back on automatically after an automatic reconnect;
- Please include the first two lines of the startup log (`ECDH backend`, `Discovery target`) when reporting a problem.

## 3. Live dashboard (HTTP API + SSE)

```bash
.venv/bin/python miband_client.py --web-port 8080             # real device
.venv/bin/python miband_client.py --demo 30 --web-port 8080   # hardware-free demo
```

Open `http://127.0.0.1:8080` in a browser (`--web-host 0.0.0.0` allows LAN access; mind the security implications).
The page draws heart rate/SpO2/steps/IMU resultant acceleration trends on a Canvas, pushed live over SSE, with no refresh needed.

| Endpoint | Description |
|---|---|
| `GET /` | single-page dashboard |
| `GET /api/snapshot` | latest values + recent series + counts (JSON) |
| `GET /api/history?kind=heart_rate&limit=600` | in-memory series for one metric; add `&source=db` to read SQLite |
| `GET /events` | SSE event stream (sends a snapshot first, then keeps pushing samples) |
| `GET /healthz` | liveness probe |

History backfill: when the page loads it requests four `?source=db` series in parallel, then opens the SSE stream; every snapshot
(including the first SSE frame) merges persisted points with live points by timestamp and de-duplicates them. When the database is missing, a table is
missing, or `--storage jsonl|none` is used, it silently degrades to a pure live view. DB queries run in a thread pool and do not block BLE.

## 4. History sync (experimental)

The Mi Band 6's SpO2 is not a real-time notification but a history record; activity data is stored per minute:

```bash
# After connecting, first fetch the last 7 days of history, then enter live collection
.venv/bin/python miband_client.py 60 --sync-history 7

# History sync only (end with Ctrl+C)
.venv/bin/python miband_client.py --sync-history 3

# Also fetch 0x26 overnight SpO2 (writes the separate spo2_sleep table + JSONL)
.venv/bin/python miband_client.py 60 --sync-history 7 --sync-sleep-spo2
```

Protocol highlights (independently implemented based on Gadgetbridge's public reverse-engineering results):

- control/metadata characteristic `0x0004`, data chunks `0x0005`;
- write `[0x01, data type] + local time(6B) + [reason, timezone]` to start; activity `0x01`, SpO2 `0x25`;
- the band first replies `10 01 01 <count u32> <start time>`, then the client writes `[0x02]` to request data;
- chunks carry an incrementing counter (**not reset** per fetch); when done the band replies `10 02 01` and the client replies `[0x03]` to acknowledge;
- SpO2 records: version 2 + 65 bytes each (int32 LE time, 1-byte SpO₂, 60 bytes reserved),
  a negative value means automatic measurement (real value = raw value + 128);
- activity records: 8 bytes per minute `kind,intensity,steps,heart_rate,unknown1,sleep,deep_sleep,rem_sleep`.

### Two protocol pitfalls exposed by the real device

1. **`<count u32>` for activity data is a "minute count", not a byte count**: a 16-hour window reports 960,
   but actually transfers 7680 bytes. The client now reads until the completion frame `10 02 01`, then trims to whole records.
2. **When there is no new data in the window, the band backfills 1970-01-01**: calling `fromtimestamp()` directly raises
   `OSError [Errno 22]` on Windows. The client treats anything before 2000 as invalid and falls back to the requested window.

> ✅ Real-device validation (Mi Band 6 / Windows WinRT / MTU 247): a 2-day window returned 1920 activity records
> in one go (zero duplicates, monotonic timestamps, 10675 steps in total) and 1 SpO2 record; a 1-day window correctly
> returned empty and acknowledged normally. See [validation/history-hardware.md](../validation/history-hardware.md) for the item-by-item checklist.

### The band only keeps about 40 hours

The band's minute data is a sliding window of **2400 minutes (40 hours)**; each minute written evicts the oldest row.
Periods already fetched and acknowledged by the app leave **permanent holes**. Therefore `--sync-history 7` can in practice
only retrieve 40 hours. To keep a particular night, you must sync within 40 hours after that night ends (the safe approach: sync daily).

A probe that only asks, does not fetch, and does not disturb the buffer:

```bash
.venv/bin/python tools/probe_declared.py 168 24
```

### Sleep SpO2 0x26 (separate table)

```bash
# Forensics: save the raw payload as .bin + .json (including SHA-256)
.venv/bin/python tools/capture_history_payload.py --days 7 --spo2-sleep --output validation/payloads

# Import forensic .bin files into the real data path (the band may clear data after an ACK; this is often the only way to get them back)
.venv/bin/python tools/import_spo2_sleep.py --output data validation/payloads/history_26_*.bin
```

Layout: version 2 + N×30B (`int32 LE ts / u8 spo2 / u8 duration / 6B high / 6B low /
8B signal / 4B spare`). Real-device validation: 12901 B = 1 + 430×30, SpO₂ 80–100, mean 95.5.
The semantics of `duration`, `signal` and `extend` are not settled, so it remains marked `[experimental]` and is not requested
by default; samples go into the separate `spo2_sleep` table/JSONL/CSV and are never mixed into spot-check `spo2`.

## 5. Local reports and sleep derivation

```bash
.venv/bin/python history_report.py --hours 24       # text report for the last 24 hours
.venv/bin/python history_report.py --hours 168 --json

.venv/bin/python sleep_analysis.py --db data/mi_band.db            # sleep text report
.venv/bin/python sleep_analysis.py --db data/mi_band.db --json     # structured output
.venv/bin/python sleep_analysis.py --db data/mi_band.db --night 2020-01-07

# Comparison tool: four candidate interpretations side by side; refuses to fit when usable nights < 2
.venv/bin/python tools/calibrate_sleep.py --zepp data/zepp_nights.json
```

### 5.1 The three bytes are scores, not stage durations

The `sleep` / `deep_sleep` / `rem_sleep` values in activity history are **not minutes per stage**. All three candidate
interpretations were checked against real Zepp numbers (01-06 night: deep sleep **44 minutes = 8%**):

| Interpretation | Deep sleep | Conclusion |
| --- | --- | --- |
| `score / 128` integration | 96 minutes (27%) | off by 52 minutes, and counts REM as 82 minutes (the app reported 0 that night) |
| Gadgetbridge thresholds (REM>55 / deep sleep>42) | 128 minutes (35%) | off by 84 minutes |
| Heart-rate ranking heuristic | 50 minutes (11%) | closest; adopted |

The evidence is **inverted**: on the 01-06 night, when the app reported REM 0 minutes, `rem_sleep` was nonzero for 458/485 minutes;
on the 01-07 night, when the app reported REM 87 minutes, `rem_sleep` was all zero for 396/396 minutes. No monotonic scaling
can make both columns hold at once — their meaning is "a discriminant score computed within the sleep window when heart rate is present".
Whole-database statistics also support this: all 463 minutes with nonzero `rem_sleep` have heart rate; the 755 minutes
with heart rate but a zero byte all fall in daytime non-sleep segments. Therefore this project **does not output REM**, and keeps
all three columns in the database as evidence.

### 5.2 Six-night Zepp comparison (raw records in data/zepp_nights.json)

| Date | Score | Time in bed | Sleep | Deep sleep | Light sleep | REM | Awake | Band has this night |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01-01 | 75 (beats 38%) | 23:06 → 07:36 | 7h57 | 1h02 (13%) | 6h55 (87%) | No such column | 33 | No |
| 01-02 | 86 (beats 71%) | 22:07 → 06:35 | 8h27 | 58 (11%) | 7h29 (89%) | No such column | 1 | No |
| 01-03 | 88 (beats 78%) | 21:45 → 06:34 | 8h40 | 1h08 (13%) | 7h32 (87%) | No such column | 9 | No |
| 01-05 | 75 (beats 38%) | 21:16 → 05:42 | 8h05 | 44 (9%) | 7h21 (91%) | No such column | 21 | No |
| 01-06 | 73 (beats 34%) | 21:06 → 06:06 | 8h40 | 44 (8%) | 7h56 (92%) | No such column | 20 | **Yes** (missing one hour) |
| 01-07 | 92 (beats 90%) | 22:44 → 05:11 | 6h27 | 1h14 (19%) | 3h46 (58%) | **1h27 (23%)** | 0 | No (not worn) |

Three conclusions:

1. **REM only appears on the night that is "not the band"**: all five nights worn on the band have no REM column; the 01-07 page
   comes from another device on the same account (band: 679 minutes of `0xF3`, 0 heart-rate records).
2. **"A constant deep-sleep ratio" is ruled out**: deep sleep was 62/58/68/44/44/74 minutes across six nights, 8%–19% of sleep,
   neither a constant nor a fixed percentage.
3. **The score mainly penalizes wakefulness**: against awake minutes `r = -0.87`, against sleep efficiency `+0.86`, against sleep
   duration `-0.47`. The score cannot be used as a validation baseline.

Aligning by overlapping intervals (01-06): our time in bed 470 minutes/sleep 453/awake 17/deep sleep 50 (11%);
Zepp converted to the same interval is about 480/460/20/44 (8%). The three rules reverse-engineered from this are exactly the implementation:
**awake by steps, window by anchor + stillness extension, no REM output**; the two deep-sleep thresholds have only one night of samples
and are provisional values, to converge once more Zepp nights are available.

### 5.3 Cross-check with Gadgetbridge

| Question | Conclusion |
| --- | --- |
| 8-byte layout | `FetchActivityOperation.createExtendedSample()` has the same fields in the same order under the same names; the sample size for the Mi Band 6 is exactly 8 |
| Are the three bytes durations? | Gadgetbridge also does **not** treat them as durations: it takes the score with `& 127` and compares it with thresholds (REM > 55, deep sleep > 42); the author notes "thresholds are arbitrary … not accurate" |
| Where do Zepp's durations come from? | Another command, `SLEEP_SESSION (0x48)`, 594 bytes per record, containing the stage-segment list and sleep score |
| Can the Mi Band 6 obtain them? | **No.** `supportsSleepScore()` defaults to false and is not overridden by `MiBand6Coordinator`; on a real device, `0x48` reports success but 0 records |

For the complete evidence, the original Zepp page-by-page text and the process of correcting the conclusions, see
[investigations/sleep-fields.md](../investigations/sleep-fields.md).

### 5.4 Non-wear and adding samples

Only the low four bits of `kind` are the activity code, and `3` = **not worn** (Gadgetbridge `TYPE_NONWEAR`).
On the real device, none of the 679 minutes of `0xF3` has **a single heart-rate record** (the other kinds have heart rate about 100% of the time),
and all of them have zero intensity and zero steps — so 01-07 is not "11.3 hours in bed", but the band not being worn. Non-wear nights
generate no sleep segment and do not enter the dashboard's "latest night".

Adding samples takes only three steps: **wear it to sleep → sync the same day → record the Zepp numbers in `data/zepp_nights.json` that day**.
The second step is a hard prerequisite: after receiving the `03` ack, the band clears the minutes already uploaded. When there are fewer than
two usable nights, `tools/calibrate_sleep.py` refuses to fit and only lists the differences.

## 6. Offline history dashboard (single-file HTML)

```bash
.venv/bin/python history_dashboard.py --db data/mi_band.db \
    -o dashboard_history.html --days 7

# When you only have JSONL and it has not been imported into the database, you can specify the overnight SpO2 source explicitly
.venv/bin/python history_dashboard.py --db data/mi_band.db \
    -o dashboard_history.html --spo2-sleep-jsonl validation/payloads-26/spo2_sleep.jsonl
```

Contents: KPIs (latest night, deep-sleep share, sleep efficiency, steps, heart-rate range, lowest SpO2), sleep-structure SVG,
heart-rate curve, per-day activity rhythm, daily steps, overnight sleep SpO2 curve, spot-check SpO2 table. No CDN/fonts/images,
so it can be opened by double-clicking, emailed or archived directly.

Three deliberate design choices: the activity rhythm bars are positioned by real timestamps (band history is not a continuous grid);
nights with missing heart rate draw a grey time-in-bed band instead of an empty lane; overnight SpO2 (0x26) and spot-check SpO2 (0x25)
are split into two sections, with lines broken across gaps longer than 5 minutes.

## 7. CSV export

```bash
.venv/bin/python export_csv.py --db data/mi_band.db --output data/csv
```

`--export-csv` does the same thing automatically at the end of a session; it exports the six tables `heart_rate`, `steps`, `imu`,
`spo2`, `activity_history` and `spo2_sleep`, UTF-8 encoded with column names as the header.
See [data-formats.md](data-formats.md) for the fields and directory layout.

## 8. Troubleshooting scripts

```bash
.venv/bin/python scan_ble.py      # 8–90 second scan list (prints UUIDs on macOS)
.venv/bin/python scan_live.py     # continuous event scan (catches isolated advertising pulses)
```

More diagnostic tools are described in [../tools/README.md](../../tools/README.md); see [faq.md](faq.md) for common errors.

## 9. Windows examples

```powershell
.venv\Scripts\python.exe miband_client.py --demo 2 --imu --output data\demo --export-csv
.venv\Scripts\python.exe miband_client.py 60
.venv\Scripts\python.exe miband_client.py --web-port 8080
.venv\Scripts\python.exe history_report.py --hours 24
.venv\Scripts\python.exe scan_ble.py
```

## 10. Workout keep-alive mode (`--workout`) and the watchdog

A closed-loop capture and disconnect-recovery flow for sustained workouts of 10–60+ minutes:

```bash
# Real-device workout mode (1 Hz live heart rate + 0x0007 incremental steps/calories + Z1-Z5 zones + live dashboard)
.venv/bin/python miband_client.py --workout --age 28 --weight 68 --sex male --web-port 8080 --export-csv

# 4-second simulator end-to-end demo (no hardware)
.venv/bin/python miband_client.py --demo 4 --workout --web-port 0 --output /tmp/miband-workout-demo --export-csv
```

Key features:
- **Dual-layer HR watchdog (enabled by default)**: in addition to the `0x16` keep-alive sent every 12 seconds, it watches for `0x2A37` notification silence (parseable frames such as `bpm=0`/`255` also refresh the heartbeat timestamp); after 24 seconds of silence it sends a Tier-1 soft re-arm `0x15 0x01 0x01` (at most 2 times), and beyond 48 seconds it triggers a Tier-2 link drop and fast reconnect (0.3 s). The thresholds can be tuned with `--hr-silence-soft` / `--hr-silence-hard`.
- **Disconnect recovery and targeted gap fill**: when the reconnect outage exceeds `--gap-fill-min` (default 60 s), the client incrementally fetches the `ACTIVITY (0x01)` minute data for that window **before** starting the live streams and writes it into the de-duplicated `activity_history` (never into the raw `heart_rate` table); it is then merged seamlessly into the in-memory and dashboard timeline.
- **Net increments and physiological estimates**: using the first `0x0007` frame as the workout-start baseline, it computes net steps, net distance and band net calories (including midnight-reset detection), and additionally provides a Keytel (2005) heart-rate calorie estimate plus the Z1–Z5 heart-rate zone time distribution from age/weight/sex; at the end it generates `workout_summary.json`.
- **Optional battery and host sleep-prevention diagnostics**: with `--workout` enabled, it conservatively reads the standard `0x2A19` battery level every `--battery-interval` (default 300 s; automatically skipped when unsupported); on Linux, `--doctor` also performs a read-only check of the Bluetooth USB controller's `autosuspend` state.
