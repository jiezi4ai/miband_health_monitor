**English** · [简体中文](history-hardware.zh-CN.md)

# Real-Device Validation Checklist: ⑦ Experimental SpO₂ and Band History Readout

> **Data redaction note**: All dates in this document are placeholder dates (uniformly mapped to January 2020) and are used only to distinguish nights and their relative order; they do not represent actual collection times. The listed values are aggregate statistics and contain no device identifiers, account details, or per-minute raw samples.


> Applies to: versions that include `band_history.py` and support `--sync-history` (git ≥ `28080a9`).
> Code involved: [miband_monitor/history/](../../miband_monitor/history/),
> [miband_client.py](../../miband_client.py),
> [tools/capture_history_payload.py](../../tools/capture_history_payload.py).
> Everything has already passed on the simulator side (`tests/test_history.py`); **the purpose of this checklist is precisely to turn "simulator-only validation" into "real-device validation"**.

---

## 0. What This Validation Must Answer

| # | Question | Corresponding unverified hypothesis |
|---|---|---|
| Q1 | Do the `0x0004`/`0x0005` fetch characteristics actually exist on the Mi Band 6, and do they have notify/write capabilities? | A1 |
| Q2 | Is the time encoding of the "start fetch" command (local time 6B + timezone 1B) correct? | A2/A3 |
| Q3 | Are the position, unit, and start-time parsing of `expected_len` in the start-date response correct? | A4/A5 |
| Q4 | Does the data chunk counter start at 0 and increase contiguously? | A6 |
| Q5 | Is the completion frame `10 02 01`, or the 7-byte version with CRC32? Are the CRC algorithm and byte order correct? | A7/A8 |
| Q6 | Is `[0x03]` alone sufficient for the ACK, and is the reply `10 03`? Does the band delete the transferred data after the ACK? | A9/A10 |
| Q7 | Are the data type codes `0x01` (activity) / `0x25` (SpO₂) correct? | A11 |
| Q8 | Are the field offsets correct for activity (8 bytes/minute) and SpO₂ (65 bytes/record)? | A12/A13 |
| Q9 | Do the parsed times match the records in the Zepp App (timezone/truncation error)? | A2/A3/A14 |

---

## 0.1 Validation Result (2020-01-08, Mi Band 6 / Windows WinRT / MTU 247)

**Conclusion: both activity data and SpO₂ were obtained from the real device; Q1–Q7 and Q9 all pass; Q8 partially passes.**
Two behaviors that differed from "simulator-only validation" have been fixed in the code, and real-device byte-level regression cases were added.

| Observation | Actual real-device behavior | Handling |
|---|---|---|
| Activity data length | The u32 in `10 01 01` is the **number of minutes** for `ACTIVITY` (960 reported for a 16-hour window), yet 7680 bytes were actually received | No longer truncate by this value; instead read until the completion frame `10 02 01`, then trim to whole records |
| Empty-window response | `10 01 01 00 00 00 00 b2 07 01 01 00 00 00 00`, with the time being **1970-01-01**; calling `fromtimestamp()` directly raises `OSError [Errno 22]` on Windows | Treat anything before the year 2000 as invalid and fall back to the requested window; log "no new data" instead of raising an error |
| Chunk counter | **Does not reset** within the same session; the first chunk may start at a value other than 0 (4 and 11 were observed) | Accept any starting value for the first chunk, but still validate continuity thereafter |
| Completion frame | This firmware uses the 3-byte `10 02 01` and **does not carry CRC32** | Keep the optional CRC verification branch and skip it when no CRC is present |
| Data after ACK | The same batch of data can still be fetched again using an earlier window (window semantics, not "delete on ACK") | The sync loop advances the window minute by minute to avoid writing the same record twice |

Measured data (`--sync-history 2`): 1920 activity records, 2020-01-06 22:03 → 01-08 14:02
(local time), zero duplicates, monotonically increasing times, 10675 steps in total; 1 SpO₂ record (100%, not an automatic measurement).
`--sync-history 1` correctly returned empty and confirmed it (`10 03 01`), no longer raising an exception.

> 2020-01-08 addendum: sleep SpO₂ `0x26` was also separately captured and passed—12901 B / 430 records,
> the 30B layout and SpO₂ field offsets were confirmed; see Appendix A.1 for details.

---

## 1. Acceptance Criteria (read this first)

### Must Pass (Must)

- [ ] A start-date response beginning with `10 01 01` appears, with `expected_len > 0` (when the band actually has history data).
- [ ] The data chunk counter starts at **0** and increases contiguously with no gaps (see the `History chunk seq=…` log).
- [ ] A completion frame appears and is `10 02 01` (or the 7-byte variant with a 4-byte CRC32).
- [ ] A `10 03` reply follows the ACK (or only the warning "No ack response received … (continuing)" appears).
- [ ] The parsed SpO₂ value is between **50–100** (normal measurements are usually 90–100), and the `auto_measure` flag is reasonable.
- [ ] Activity timestamps increase strictly in **60-second** steps; steps are 0–255; heart rate is 0 or 30–220.
- [ ] Persisted row count == parsed sample count: JSONL, SQLite, and CSV agree (see §3).
- [ ] After the history sync, live heart rate/steps are still normal (the history sync does not break subsequent sessions).
- [ ] Repeated syncing (same window) either returns 0 new records or has an explainable behavior (see §4).

### Should Verify (Should)

- [ ] Run once each with `--days 1` / `--days 7` / `--days 30`; behavior should change reasonably with the window.
- [ ] Multiple fetch rounds (e.g. `rounds=activity:2`) work normally.
- [ ] Parsed times differ from the corresponding Zepp App records by ≤ 2 minutes (due to minute truncation).
- [ ] Capture one `btmon` trace or nRF Connect GATT table to confirm the characteristic properties and frame sequence.

> If any Must item fails, consider "⑦ failed"; please collect materials per §6 and report back.

---

## 2. Prerequisites (all required)

### Environment

- Linux + BlueZ (WSL2 requires USB Bluetooth passthrough; `bluetoothctl` must be available); on Windows use the native system (WinRT), not WSL2 Bluetooth.
- Project dependencies installed (`.venv` or system environment); `python -m pytest -q` should report **200 passed** without hardware.
- A compiler is not required: native ECDH is used when `gcc`/`clang` is available, otherwise it automatically falls back to pure Python (the log prints `ECDH backend`).
- The computer timezone matches the band timezone (the protocol encodes "local wall-clock time" as described below):
  ```bash
  timedatectl    # Confirm Time zone; if necessary: sudo timedatectl set-timezone Asia/Shanghai
  ```

### Band and Account

- Band battery ≥ 30%, worn, screen can be woken; **phone Bluetooth off / airplane mode**.
- The band really has history data: recent activity/SpO₂ records are visible in Zepp Life / Zepp App.
- `DEVICE_ID` (or legacy `DEVICE_MAC`) and `AUTH_KEY` are configured in `.env` and a live connection can be established.
- Run a baseline once (not involving ⑦):
  ```bash
  .venv/bin/python miband_client.py 20 --storage none
  ```
  You must see `Chunked ECDH authentication SUCCEEDED. Session is ready.` and at least one heart-rate log line;
  **do not proceed to ⑦ if the baseline fails**; resolve the connection/authentication issue per the README FAQ first.

---

## 3. Collection Procedure

### 3.1 Standard Collection (recommended: one full run)

```bash
RUN="validation/history-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN"

# Environment snapshot (very useful when troubleshooting)
{
  uname -a
  .venv/bin/python -V
  .venv/bin/python -m pip freeze | grep -iE "bleak|cryptography|pytest|dotenv"
  bluetoothctl --version
} > "$RUN/env.txt" 2>&1
git rev-parse HEAD > "$RUN/commit.txt"
.venv/bin/python -m pytest -q > "$RUN/pytest.txt" 2>&1

# Collection: 60-second live stream + sync the last 7 days of history right after connecting; DEBUG logging
.venv/bin/python miband_client.py 60 \
    --sync-history 7 \
    --output "$RUN/data" \
    --export-csv \
    --log-level DEBUG 2>&1 | tee "$RUN/run.log"

# Local history report
.venv/bin/python history_report.py --db "$RUN/data/mi_band.db" --hours 168 \
    > "$RUN/report.txt" 2>&1
.venv/bin/python history_report.py --db "$RUN/data/mi_band.db" --hours 168 --json \
    > "$RUN/report.json" 2>&1
```

> `--sync-history` runs **before the live stream starts**; the log order should be:
> authentication succeeded → `Fetching up to 7 day(s) …` → history sync → `Streaming session 1 started`.

### 3.2 Raw Payload Capture (strongly recommended, almost mandatory on failure)

```bash
.venv/bin/python tools/capture_history_payload.py \
    --days 7 --output "$RUN/payloads" 2>&1 | tee "$RUN/payload_capture.log"
```

Each payload is saved as `history_<type>_<time>.bin` plus a same-named `.json` (type, since, start time,
length, SHA-256). **These bin files are the only hard evidence for diagnosing "field offset/version/CRC" problems.**

### 3.3 Optional: HCI / GATT Capture

```bash
# Terminal A (requires root; start it before running Python, Ctrl+C when done)
sudo btmon -w "$RUN/btmon.btsnoop"
```

Also prepare a screenshot of the GATT table from nRF Connect (phone) or `bluetoothctl`, focusing on
under service `0000fee0-0000-1000-8000-00805f9b34fb`:

- `00000004-0000-3512-2118-0009af100700`: **notify + write**;
- `00000005-0000-3512-2118-0009af100700`: **notify**.

---

## 4. Staged Checks (tick against the log)

### Stage 0: Connection and Authentication (baseline)

| Expected log (DEBUG/INFO) | Record |
|---|---|
| `Waiting for Mi Band broadcast at …` | Scan duration |
| `Band detected! Establishing BLE link …` | RSSI |
| `BLE link established. Initializing chunked transfer listener...` | — |
| `Chunked ECDH authentication SUCCEEDED. Session is ready.` | Authentication duration |

### Stage 1: History Sync Start

| Expected log | Record |
|---|---|
| `Fetching up to 7 day(s) of band-side history (experimental)...` | Whether it appears |

### Stage 2: Activity Data (type `0x01`, before SpO₂)

| # | Expected log | Record/Verdict |
|---|---|---|
| 2.1 | `Fetching history type 0x01 since <iso>` | Is `since` 7 days ago, and is the timezone local |
| 2.2 | `Start-date response: <hex>` | Copy down the hex; it should begin with `10 01 01` |
| 2.3 | `Band reports <N> byte(s) of history starting at <iso>` | Is N a multiple of 8; is the start time ≤ now |
| 2.4 | `History chunk seq=0 (…)`, `seq=1` … | Does the sequence start at 0 and run contiguously; does the max seq roughly match N/19 |
| 2.5 | `Fetch completion response: <hex>` | Copy down the hex; is it `10 02 01` (3B) or 7B (with CRC) |
| 2.6 | `Ack response: <hex>` | Is it `10 03`; record a warning if missing |
| 2.7 | `Fetched payload OK: N bytes, crc=verified|absent` | Is CRC verified |
| 2.8 | `Fetched <K> activity sample(s) up to <iso>` | Does K == N/8 |

### Stage 3: SpO₂ Data (type `0x25`)

| # | Expected log | Record/Verdict |
|---|---|---|
| 3.1 | `Fetching history type 0x25 since <iso>` | — |
| 3.2 | `Start-date response: <hex>` | Begins with `10 01 01` |
| 3.3 | `Band reports <N> byte(s) …` | Is N `1 + 65×K` |
| 3.4 | `History chunk seq=…` | Continuity |
| 3.5 | `Fetch completion response: <hex>` | Copy down the hex |
| 3.6 | `Ack response: <hex>` | Copy down the hex |
| 3.7 | `Fetched payload OK: N bytes, crc=…` | — |
| 3.8 | `Fetched <M> spo2 sample(s) up to <iso>` | Does M == (N−1)/65 |

### Stage 4: Summary and Subsequent Live Stream

| Expected log | Verdict |
|---|---|
| `Band history sync finished: <K> activity sample(s), <M> SpO2 sample(s), rounds=activity:x,spo2:y` | K/M consistent with stages 2/3 |
| If no new data: `Band history sync finished: no new history data` | Normal (just synced / no data) |
| `Streaming session 1 started (duration=60s, imu=False).` | History sync did not block the live stream |
| `Current Heart Rate: … BPM`, `Steps: …` | Live stream still normal |

### Stage 5: Persistence and Display

```bash
ls "$RUN/data"                         # should contain heart_rate/steps/imu/spo2/activity_history .jsonl + mi_band.db
ls "$RUN/data/csv"                     # should contain 5 CSV files
cat "$RUN/report.txt"
```

| Check | Command | Expected |
|---|---|---|
| SpO₂ table | `sqlite3 "$RUN/data/mi_band.db" "select count(*),min(spo2),max(spo2),sum(auto_measure) from spo2;"` | rows = M; values 50–100 |
| Activity table | `sqlite3 "$RUN/data/mi_band.db" "select count(*),sum(steps),avg(heart_rate) from activity_history;"` | rows = K; reasonable steps |
| JSONL | `wc -l "$RUN/data/spo2.jsonl" "$RUN/data/activity_history.jsonl"` | Matches table row counts |
| Time interval | see the script below | Adjacent activity samples strictly +60s |
| Dashboard | open `http://127.0.0.1:8080` when `--web-port 8080` is added | SpO₂ card/chart has data |

Time-interval self-check:

```bash
.venv/bin/python - "$RUN/data/activity_history.jsonl" <<'EOF'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
rows.sort(key=lambda r: r["ts"])
gaps = [round(b["ts"] - a["ts"], 3) for a, b in zip(rows, rows[1:])]
print("samples:", len(rows), "gaps:", gaps[:10], "unique gaps:", sorted(set(gaps))[:5])
print("first:", rows[0]["iso_time"], "last:", rows[-1]["iso_time"])
EOF
```

Expected: `unique gaps` is basically only `[60.0]`; the last timestamp ≤ current time and not earlier than the window start.

---

## 5. Cross-Check Against the Zepp App (timezone/truncation validation)

1. Find data for the same day under "SpO₂" and "Activity/Sleep" records in Zepp Life / Zepp App.
2. Compare the times in the local `spo2.jsonl` / `activity_history.jsonl`:
   - deviation ≤ 2 minutes is allowed (the protocol itself has minute precision);
   - a whole-hour offset → timezone encoding problem (focus on recording A2/A3);
   - completely scrambled dates/times → time field offset problem (record the payload hex).

---

## 6. Repeated Sync / Idempotency Validation

```bash
RUN2="$RUN/repeat"; mkdir -p "$RUN2"
# Immediately run the same window again
.venv/bin/python miband_client.py 20 --sync-history 7 \
    --output "$RUN2/data" --log-level DEBUG 2>&1 | tee "$RUN2/run.log"
grep -E "Band history sync finished|no new history data" "$RUN2/run.log"
```

Verdicts:

- If the second run reports `no new history data` / 0 records → this indicates that **the band deletes the transferred data after the ACK**, which matches expectations;
- If the second run still returns the same samples → record the "duplicate return" phenomenon (the firmware may retain data, or the ACK may not actually take effect);
  this is not a crash, but must be noted in the report;
- If the second run errors/times out → record the error log (the fetch state may not have been reset).

---

## 7. Known Unverified Hypotheses (tick each one; most important)

> The table below is exactly what this checklist aims to disprove/confirm. Tick each one that passes; attach the corresponding log for failures.

- [x] **A1** `0x0004`/`0x0005` exist in Mi Band 6 firmware, with properties notify+write / notify.
- [x] **A2** Start command time encoding = `year(LE16),month,day,hour,minute` + `reason(0x00)` + `timezone(15-min units)`.
- [x] **A3** The band truncates `since` to **minute** precision (if the firmware used second precision, duplicates/missing records would appear).
- [x] **A4** start-date response structure = `10 01 01 | expected_len(u32 LE) | start time(≥6B)`.
- [ ] **A5** ~~`expected_len` is the payload byte count~~ —— **only true for SpO₂** (66 = version byte + 65);
      for activity data it is the **number of minutes** (960 reported for a 16-hour window, 7680 bytes actually received). Now changed to rely on the completion frame.
- [ ] **A6** ~~counter starts at 0~~ —— **does not reset within the same session**; the first chunk may start at any value (see 4, 11).
      The first chunk is accepted; `+1` continuity is still validated thereafter.
- [x] **A7** The completion frame is `10 02 01` (this firmware is 3 bytes, with no CRC segment).
- [ ] **A8** This firmware does not return CRC32, so the algorithm cannot be validated; the code retains the optional verification branch.
- [x] **A9** The ACK command is only `[0x03]`, reply `10 03 01`.
- [ ] **A10** ~~the band deletes transferred history after the ACK~~ —— **does not hold**: fetching the same window again still returns the same data;
      idempotency is ensured by the client advancing the window minute by minute.
- [x] **A11** Type codes `0x01`=activity, `0x25`=normal SpO₂.
- [x] **A12** Activity sample 8B: `kind,intensity,steps,heart_rate,unknown1,sleep,deep_sleep,rem_sleep`
      (fields can be decoded; only the semantics of `steps`/`heart_rate` are confirmed).
- [x] **A13** SpO₂ record 65B: `int32 LE unix_ts, int8 spo2(negative=automatic, value+128), 60B reserved`; version byte=2.
      Real-device record decoded to 100% (2020-01-07 07:42:07 local).
- [x] **A14** Running the history sync before the live stream has no side effects (sync first, then start the stream; heart rate/steps normal).

---

## 8. Failure Quick Reference

| Symptom / log keyword | Possible cause | Next step | Materials to attach |
|---|---|---|---|
| `timed out waiting for start-date response` | `0x0004` has no notify or writes are rejected; the firmware uses a different characteristic | Export the GATT table with nRF Connect; try `--days 1`; reconnect and retry | GATT screenshot, `run.log`, btmon |
| `band rejected fetch type 0x25 (status 0x02)` | The firmware does not support this type / type code differs / no data | Confirm SpO₂ records exist in the App; validate activity only first (temporarily use a small `--days` window) | status value, type code, App screenshot |
| `Start-date response: …` prefix is not `10 01` | Response format/characteristic differs | Save the full hex; compare against `payload_capture` | Full response hex, response length |
| Repeated `Band reports 0 byte(s)` | No new data; or `since` is encoded as a future time | Check the computer timezone; try `--days 30`; look at the `since` log | `since` log, `timedatectl` |
| `packet counter mismatch: got X, expected Y` | BLE packet loss / counter does not start at 0 / chunk length assumption wrong | Retry closer to the band; capture btmon; record the first seq | 10 lines of log before/after the counter message, btmon |
| `timed out waiting for activity data chunk` | Chunks did not start (timing/need to enable some notify first) | Retry; confirm the band state after `10 02 01` is sent | Complete log up to the timeout |
| `unexpected completion response` | Completion frame format differs | Save the hex; use the payload tool to confirm the data itself is complete | Completion frame hex |
| `payload CRC32 mismatch (expected …, got …)` | CRC algorithm/byte order differs, or data is corrupted | Save the payload bin; try big-endian/little-endian and zlib/crc32c computations separately | payload bin + JSON, completion frame hex |
| `No ack response received from band (continuing)` | Firmware does not reply to the ACK or needs a variant ACK | Record it; watch for duplicate data | Subsequent sync results |
| `unsupported SpO2 payload version X` | Version byte differs (not 2) | Save the payload; record the version and the first 32 bytes | payload bin, first 32B hex |
| `SpO2 payload length … not a multiple of 65` | Record length differs (more/fewer fields) | Save the payload; record the length and `(len-1) % 65` | payload bin/JSON |
| Absurd values (SpO₂ < 50 or > 100; steps > 255) | Field offset/encryption/version differs | Save the payload; stop parsing | payload bin, parse results |
| No live heart rate after history sync | Band busy / notify conflict | Retest without `--sync-history`; record the session log | Both run.log files |
| `--web-port` port in use | Port already occupied | Use `--web-port 0` or a different port | Error log |

---

## 9. Packaging and Redaction (mandatory before submitting)

```bash
cd validation
tar -czf "history-validate-$(date +%Y%m%d-%H%M%S).tar.gz" history-*/
```

Before sharing:

```bash
# 1) Redact MAC addresses in logs
sed -E 's/([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/XX:XX:XX:XX:XX:XX/g' run.log > run.redacted.log

# 2) Confirm there is no auth_key leakage (normal code does not print it; still check)
grep -inE "auth_key|AUTH_KEY" run.log || echo "no auth key in log"

# 3) Never package/screenshot .env
```

- DEBUG logs contain the ECDH salt and public key (not private credentials, but the two lines
  `Received random challenge salt` / `Received band ECDH public key` can be removed if needed).
- `btmon.btsnoop` contains BLE addresses and over-the-air data; provide it only when necessary.
- Business data (heart rate/SpO₂/activity) is itself personal health data; when providing external feedback, **attach only the necessary excerpts**.

---

## 10. Feedback Template (copy and fill in)

```markdown
## ⑦ Real-Device Validation Report

### Environment
- Band model / firmware version:
- Host / distro / BlueZ / bleak versions:
- Code commit (git rev-parse HEAD):
- Computer timezone (timedatectl):
- Band timezone consistent: yes / no

### Conclusion
- [ ] Activity data (0x01): PASS / FAIL
- [ ] SpO₂ data (0x25): PASS / FAIL
- [ ] Repeated sync: PASS / FAIL / observation:
- [ ] Live stream unaffected: PASS / FAIL

### Key logs (DEBUG)
Start-date response (activity):
Start-date response (spo2):
Fetch completion response:
Ack response:
Fetched summary lines:

### Data statistics
activity samples:   spo2 samples:   rounds:
sqlite rows: spo2=   activity_history=
Deviation vs Zepp App:

### Attachments
- [ ] run.log (redacted)
- [ ] payloads/*.bin + *.json
- [ ] report.json
- [ ] GATT table screenshot
- [ ] btmon.btsnoop (optional)

### Anomalies and hypotheses
```

---

## 11. Acceptance Sign-off

| Date | Band model/firmware | Activity | SpO₂ | Repeated sync | Notes |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

---

## Appendix A: Protocol Constants Quick Reference

| Item | Value |
|---|---|
| fetch control/metadata characteristic | `00000004-0000-3512-2118-0009af100700` (notify+write) |
| activity data characteristic | `00000005-0000-3512-2118-0009af100700` (notify) |
| commands | start `0x01`, fetch `0x02`, ACK `0x03` |
| response/success | `0x10` / `0x01` |
| type codes | activity `0x01`, normal SpO₂ `0x25`, sleep SpO₂ `0x26` |
| start time encoding | 6B short calendar (year LE16/month/day/hour/minute) + `0x00` + timezone (15 min) |
| SpO₂ payload | version `2` + N×65B |
| sleep SpO₂ payload | version `2` + N×30B (**real-device validated on 2020-01-08, see Appendix A.1**)<br>`int32 LE ts` + `u8 spo2` + `u8 duration` + 6B high + 6B low + 8B signal + 4B spare |
| activity payload | N×8B (Mi Band 6) |
| default timeout/rounds | 30s / 5 rounds |

### Appendix A.1: Sleep SpO₂ `0x26` Real-Device Validation Result (2020-01-08, PASS)

```bash
python tools/capture_history_payload.py --days 7 --spo2-sleep \
    --scan-timeout 90 --output validation/payloads-26
```

Environment: Mi Band 6 / Windows 11 / WinRT. A single connection retrieved 3 ACTIVITY segments (8640 records),
1 SPO2_NORMAL record (66 B), and 1 SPO2_SLEEP segment (12901 B), with `errors: []` and exit code 0.

| Check | Result |
|---|---|
| Firmware accepts `0x26` | Yes, returns a success status rather than ignored / rejected |
| payload length | **12901 B = 1 + 430×30**, `(len - 1) % 30 == 0` |
| version byte | `2` |
| timestamps | strictly increasing, 21:39 → 05:39 next day (local); main interval 60 s (371 times), plus 59/61/120/180/360 s gaps |
| SpO₂ values | 80–100, mean 95.48, **0 records** outside 50–100 → offset 4 and the "unsigned" reading hold |
| `high` / `low` | both groups are sampled values of 99–100, matching Gadgetbridge naming |
| `duration` | clustered at 16/32/48/64, **semantics undetermined** |
| `signal` / `extend` | nonzero but without a fixed interpretation; `extend` is nonzero on only 137/430 rows |
| vs `0x25` | 66 B = 1 + 65, 1 spot-measurement record (100%, 07:42) |

Conclusion: **the 30B layout and field offsets passed real-device validation**; the first two real-device records have been locked in as
the byte-level regression `tests/test_history.py::test_parse_spo2_sleep_real_hardware_prefix`.
However, the semantics of `duration` and the three trailing byte groups are undetermined, and upstream Gadgetbridge still marks them `TODO save`,
so the `[experimental]` tag and the default-off behavior are retained.

**Promoted the same day (visualization first, then a dedicated table)**: `history_dashboard.py` gained an overnight SpO₂ curve
(preferring the table, falling back to `spo2_sleep.jsonl` when the table is empty); `storage.py` gained a **dedicated** `spo2_sleep`
SQLite table; `export_csv.py` gained an export of the same name; `tools/import_spo2_sleep.py` imports the `.bin` evidence from this appendix
into both pipelines, deduplicating by timestamp (the band may clear data after the ACK, so this step is often the only way to get it back).
After importing 430 records, the dashboard showed min 80 / max 100 / avg 95.5, with source `sqlite`,
and the KPI "lowest SpO₂" correctly took the combined minimum of spot measurements and overnight data.

The raw evidence `validation/payloads-26/history_26_*.bin` (SHA-256 `9cd65d3759948167…`)
contains personal health data; the directory is ignored by `.gitignore`; redact per §9 before external feedback, and do not package `.env`.

## Appendix B: Simulator Baseline (for comparison)

```bash
.venv/bin/python miband_client.py --demo 3 --sync-history 1 --output data/demo --export-csv
```

Expected (simulator fixed data):

- `Fetched 4 activity sample(s)`, `Fetched 3 spo2 sample(s)`
- `rounds=activity:1,spo2:1`
- DB: `spo2=3`, `activity_history=4`; 5 CSV files
- `history_report.py`: `SpO2 min 96 / max 98 / avg 97.0 / auto 1`, `activity 4 minutes, 71 steps`

Real-device results should match the simulator in **structure**; different values and times are normal.

## Appendix C: Log Message Index (for grep)

| Keyword | Meaning |
|---|---|
| `Fetching up to .* day\(s\)` | History sync entry point |
| `Fetching history type` | Start of each type (including since) |
| `Start-date response` | Start response hex (key) |
| `Band reports .* byte\(s\)` | expected_len and start time |
| `History chunk seq=` | Chunk counter continuity |
| `Fetch completion response` | Completion frame hex (key) |
| `Ack response` | ACK reply hex |
| `Fetched payload OK` | Verification result |
| `Fetched .* sample\(s\)` | Number of parsed samples |
| `Band history sync finished` | Summary |
| `no new history data` | No new data (normal) |
