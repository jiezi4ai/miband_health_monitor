**English** · [简体中文](linux-validation.zh-CN.md)

# Linux Validation Report (Ubuntu 24.04 / BlueZ)

> Validation date: 2026-11-08 (two rounds: software path + real device) · Commit under test: `4f4d63b` (`main`)
> Environment: Ubuntu 24.04.5 LTS, kernel 6.8.0-147, x86-64; Python 3.13.13 (conda and `python3 -m venv`);
> BlueZ 5.72, USB adapter `hci0`, systemd `bluetooth` service active.
> Device: Mi Smart Band 6 (address redacted).
> **This round only performs validation and recording; no code was modified.** The diagnostic BlueZ agent script was placed in `/tmp` and is not part of the repository.

## 1. Conclusions at a Glance

| Layer | Result |
|---|---|
| Unit/integration tests (no hardware) | ✅ 216 passed / 4 skipped (run once each with the native and pure-Python ECDH backends) |
| demo end-to-end path (collection→storage→CSV→dashboard) | ✅ Passed, artifacts complete |
| Real BLE scanning | ✅ Available (non-root, no `bluetooth` group needed) |
| Real-device connection + Chunked ECDH authentication | ✅ Success (authentication completes both when unpaired and when paired) |
| Real-device heart rate / steps / IMU streams | ⚠️ Steps and IMU ✅; heart rate produced **0 notifications** in the paired round (to be retested) |
| Real-device history sync | ✅ 1188 activity samples + 1 SpO2 (`--sync-history 1`) |
| Real-device long-session stability | ⚠️ Unpaired: disconnect at about 36 s; **after pairing: full 300 s** |
| Live dashboard with real-device data | ✅ `/api/snapshot`, `/api/history`, `/events` all have real data |
| Recorded issues | 10 (L1–L10) + 5 notes (N1–N5); of which **L9/L10 were fixed in P0 (§7)** |

**In one sentence**: the software layer works on Linux; the real device works, provided that **pairing is completed on the BlueZ side first**,
otherwise the connection is dropped by the band after about 36 seconds (L9). This corresponds exactly to the L7 risk in the original report.

## 2. Passed Validation Items (software path, first round)

| # | Item | Command / method | Result |
|---|---|---|---|
| 1 | Test suite (native ECDH) | `python3 -m pytest -q` | 216 passed / 4 skipped |
| 2 | Test suite (pure Python ECDH) | `MIBAND_ECDH_BACKEND=python python3 -m pytest -q` | 216 passed |
| 3 | venv installation per the docs | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` | Installation succeeded; pytest/demo both passed |
| 4 | CI end-to-end path | `miband_client.py --demo 2 --imu --sync-history 1 --sync-sleep-spo2 --storage both --export-csv` | All 7 required artifacts non-empty |
| 5 | Real BLE scanning | `scan_ble.py` / `scan_live.py` | Available; the band is discoverable while advertising |
| 6 | Scan timeout | `--device-id C0:FF:EE:C0:FF:EE --scan-timeout 3` | Clear error, exit 1 |
| 7 | Ctrl+C | Send SIGINT during a demo run / during scanning | Graceful exit, `Storage summary` normal |
| 8 | Storage backends | `--storage jsonl / sqlite / both / none` | All four correct |
| 9 | Non-ASCII + spaces in path | `--output "/tmp/数据 目录"` | Writes normally |
| 10 | Dashboard HTTP | `/`, `/api/snapshot`, `/api/history` (including `source=db`), `/events`(SSE), `/healthz` | All 200 |
| 11 | Port in use | Bind `18080` twice | Clear error, no crash |
| 12 | Offline dashboard/report/export | `history_dashboard.py`, `history_report.py`, `export_csv.py`, `sleep_analysis.py` | Normal |
| 13 | 0x26 payload import | `tools/import_spo2_sleep.py` (synthetic 91B payload) | 3 samples written to JSONL+SQLite |
| 14 | ECDH three-level fallback | native → on-the-fly `gcc` build → pure Python | All three levels work; shared secret consistent |
| 15 | Environment variables | `SCAN_TIMEOUT`, `BLE_MTU`, `LOG_LEVEL`, `STORAGE_BACKEND`, `DEMO_MODE` | All effective |
| 16 | Argument validation | `--sync-sleep-spo2` without `--sync-history` | argparse rejects, exit 2 |
| 17 | Backward-compatibility check | No POSIX-only dependencies such as `fcntl/termios/resource`; CSV uses `newline=""` | Does not block Windows |

## 3. Real-Device Validation (second round)

### 3.1 What Succeeded

| Item | Observation |
|---|---|
| Band discovery | `Band detected! Establishing BLE link`; advertising appeared intermittently and was captured within the 95 s scan window |
| Connection | `BLE link established` (the MTU log was always 23, see L10) |
| Chunked ECDH authentication | `Chunked ECDH authentication SUCCEEDED. Session is ready.` |
| Heart-rate stream | Unpaired round: 70–72 BPM reported normally (9–16 records) |
| Step stream | Normal: `Steps: 8666 | Distance: 5877 m | Calories: 213 kcal` |
| IMU stream | Normal: 689 samples collected in one round |
| History sync | `1188 activity sample(s), 1 SpO2 sample(s), 0 sleep SpO2` |
| Live dashboard | `/api/snapshot` returns real spo2/imu; `/events` SSE pushes real data |
| CSV export | All 6 tables generated (heart_rate 16, imu 689, activity_history 1188, etc.) |
| Long session | After pairing, **full 300 s**: `Collection window (300s) elapsed` |

### 3.2 Locating the Disconnect

The two unpaired sessions both terminated about **36 seconds after collection began**:

```
12:40:28 [ERROR] Heart-rate keep-alive failed; treating link as lost:
  [org.freedesktop.DBus.Error.UnknownObject] Method "WriteValue" ... doesn't exist
```

- The BlueZ log gives the root cause: `src/device.c:new_auth() No agent available for request type 2`
  and `device_confirm_passkey: Operation not permitted` — the band initiated pairing and the system had no agent.
- After the disconnect, BlueZ removed the device object (`bluetoothctl info` → `not available`),
  so subsequent characteristic writes hit `UnknownObject`; the application treats this as a lost link — the behavior is correct, but the error wording is misleading.
- Control experiment: after registering a `NoInputNoOutput` agent via D-Bus and reconnecting,
  the agent received `RequestAuthorization ... -> accept`, the device became `Paired: yes`,
  and the same command ran **300 seconds without dropping**.

Conclusion: **L9 holds**—on Linux, without pairing first, the connection is dropped by the band after about 36 seconds.

### 3.3 To Be Retested

In the paired round (300 s), heart-rate notifications were **0 records**, while steps were reported normally every 60 s;
the two earlier unpaired rounds had normal heart rate. The difference may come from the band's wearing state (optical heart rate stops when off-wrist),
or from characteristic permissions after pairing; **it cannot be attributed at present** and needs to be retested while worn.

## 4. Issue List (recorded, **not fixed**)

### L1 · `.env` actual permissions are 0644, not the documented 0600
- **Symptom**: `ls -l .env` → `-rw-r--r--`; README line 805 promises "ignored, permissions 0600".
- **Cause**: the code only `chmod 0600`s `.env` when **writing** it (`get_auth_key.py:67`, `fetch_by_token.py:49`); it neither checks nor tightens on read.
- **Impact**: on multi-user Linux hosts, `AUTH_KEY` can be read by other users on the same machine.
- **Platform relevance**: yes (under Windows ACLs "0600" does not apply, so it is not visible on Windows).

### L2 · Telemetry artifacts have overly broad permissions (0664 / 0644)
- **Symptom**: `heart_rate.jsonl` is `-rw-rw-r--`, `mi_band.db` is `-rw-r--r--`.
- **Impact**: personal health data is readable in shared directories, inconsistent with the repository's privacy stance.
- **Platform relevance**: yes (Windows uses per-user ACLs by default).

### L3 · Unwritable output directory / occupied by a same-named file → uncaught exception + raw traceback
- **Symptom**: read-only directory → `PermissionError`; `--output` pointing at a file → `FileExistsError`;
  both print the raw Python stack and exit 1.
- **Platform relevance**: cross-platform, easier to trigger on Linux.
- **Suggested direction**: catch `OSError` and provide actionable guidance.

### L4 · `history_dashboard.py` silently succeeds for a nonexistent DB
- **Symptom**: generates a 22 KB empty dashboard, exits 0, and creates a 0-byte DB; inconsistent with `history_report.py`/`export_csv.py` (exit 1).

### L5 · Cross-platform documentation does not match the facts
- `docs/guides/cross-platform.md:3` says "originally developed on Linux (BlueZ)"; `:21` says Linux "has been used long-term".
- `:106` says the Windows smoke test "expected: 88 passed"; the current figure is **216 passed**.
- **Note**: this round confirms that the Linux software path works, but "used long-term" still does not hold; the docs should be changed to "software path validated + real device requires pairing first (see L9)".

### L6 · Usage examples in three `tools/` scripts hard-code the Windows venv path
- `tools/probe_fetch_types.py:9`, `probe_sleep_session.py:29`, `calibrate_sleep.py:22` all use `./.venv/Scripts/python.exe`.

### L7 · Missing pairing (bonding) step on Linux → **this round confirmed on the real device that the link drops** (see 3.2)
- Neither the code nor the docs include a BlueZ agent / pairing bootstrap; on Windows, the system "Add a device" may have completed the pairing, masking the difference.
- **Impact**: without pairing, the connection drops after about 36 s; with pairing it is stable for 300 s.
- **Suggested direction**: add the `bluetoothctl` pairing steps to the docs (lowest cost), or ship a built-in agent (requires weighing permissions and security).

### L8 · Inconsistent timeout parameters across probe scripts
- `probe_fetch_types.py` has no `--scan-timeout`; with no band present, after the default 90 s scan it may still reconnect, and it was measured not exiting after 60 s.

### L9 · **[High] When unpaired, the band drops the link after about 36 seconds and triggers a misleading D-Bus error** — ✅ Fixed (see §7)
- **Symptom**: both unpaired sessions ended at ~36 s; the log showed `UnknownObject: Method "WriteValue" ... doesn't exist`.
- **Root cause**: BlueZ `No agent available for request type 2` → `device_confirm_passkey: Operation not permitted`;
  after the link dropped, BlueZ removed the device object, and subsequent characteristic writes hit the vanished object.
- **Control**: after registering an agent and completing pairing, the same command ran 300 s without dropping (see 3.2).
- **Impact**: new Linux users following the docs would repeatedly encounter "collection stops after a few dozen seconds", and the error message points at a nonexistent method, making self-diagnosis difficult.
- **Fix**: docs add pairing/trust steps; D-Bus errors are translated into actionable guidance (§7).

### L10 · **[Medium] ATT MTU is never actually negotiated on Linux** — ✅ Fixed (see §7)
- **Symptom**: every connection prints
  `UserWarning: Using default MTU value. Call _acquire_mtu() or set _mtu_size first`,
  and the startup log always shows `MTU=23`.
- **Cause**: `miband_client._resolve_mtu()` only reads `client.mtu_size`; the BlueZ backend of bleak 3.0.2
  only populates that value when `_acquire_mtu()` is called explicitly, otherwise it returns 23. The WinRT/macOS backends populate it automatically on connection.
- **Impact**: chunked writes are sent with 20-byte payloads, multiplying the number of chunks for authentication and history sync (this round's 1188 history records still synced, but more slowly,
  and weak-signal conditions are more likely to trigger authentication timeouts).
- **Platform relevance**: yes, and it is a typical "Windows normal, Linux silently degraded" difference.
- **Fix**: call `_acquire_mtu()` explicitly after connecting; measured MTU 23 → **247** (§7).

## 5. Notes (not defects; avoid misjudgment)

- **N1 · Prebuilt library covers only x86-64/glibc**: `libecdh.so` is an ELF x86-64 binary; on ARM/musl it first builds on the fly with `gcc`, then falls back to pure Python if that fails. The fallback chain has been verified.
- **N2 · Log times are UTC**: the host uses `TZ=Etc/UTC`.
- **N3 · `scan_live.py` produces no output when piped**: Python buffering; it works normally with `-u` or under a TTY.
- **N4 · No "Reconnecting" log after a failure**: when `duration` is already exhausted, `run_monitor` silently `return`s (deadline check).
  This is expected behavior, but the lack of a "collection window finished" wrap-up log makes it easy to misread as a reconnect failure.
- **N5 · Band advertising is intermittent**: after the screen goes off it basically stops advertising; `scan_ble.py`'s default 8 s window often misses it,
  so a longer `--scan-timeout` or continuous scanning with `scan_live.py` is needed.

## 6. Reproduction Command Summary

```bash
# Software path
python3 -m pytest -q
python3 miband_client.py --demo 2 --imu --sync-history 1 --sync-sleep-spo2 \
  --output /tmp/ci-demo --storage both --export-csv

# Real device (pair first, see L9)
bluetoothctl pairable on
python3 /tmp/bt_agent.py 900 &          # diagnostic agent (not part of the repository)
python3 miband_client.py 300 --scan-timeout 180 --storage both --imu

# Dashboard
python3 miband_client.py --demo 15 --web-port 0
curl -s http://127.0.0.1:<port>/healthz
```

> In this report all device addresses are placeholders; `data/`, `.venv/`, and `.cache/` are all covered by `.gitignore`.
> This round paired once for the control experiment; to undo: `bluetoothctl remove <MAC>`.

---

## 7. P0 Fixes and Re-Verification (2026-11-09)

For L9/L10 and the perceived experience of "Linux connections are hard", four changes were made, all effective only on the Linux path;
Windows/macOS behavior is unchanged.

| Change | Where | Re-verification result |
|---|---|---|
| Pairing guidance + environment self-check | `docs/guides/cross-platform.md` §2.3/§2.5, `doctor.py`, `--doctor` | The self-check identifies "unpaired/not pairable/.env permissions" and provides copy-pasteable commands |
| Direct-connect fast path (skips scanning) | `bluez_support.paired_device()`, `MiBand6Client._open_client()` | Log `Bonded band ... skipping discovery`, **no scan occurred** |
| ATT MTU negotiation | `bluez_support.try_acquire_mtu()`, `_apply_mtu()` | `MTU=23` → **`MTU=247`**, `UserWarning` gone |
| D-Bus error translation | `bluez_support.describe_ble_error()` | `UnknownObject` translated to "unpaired/disconnected" + fix command |

Real-device re-verification log (excerpt):

```
22:31:17 [INFO] Bonded band C0:FF:EE:C0:FF:EE found in the BlueZ object tree; skipping discovery.
22:31:26 [INFO] BLE link established. Initializing chunked transfer listener (MTU=247)...
22:31:26 [INFO] Negotiated ATT MTU via BlueZ: 247 bytes.
22:31:28 [INFO] Chunked ECDH authentication SUCCEEDED. Session is ready.
```

Additional notes:

- If the direct connection fails (band out of range/asleep), it falls back to scanning within 12 seconds and does not consume the full connection timeout;
- `--no-direct-connect` forces the scan path, useful for investigating "stale cached objects";
- Added test `tests/test_bluez_support.py` (26 items); full suite **242 passed / 4 skipped**;
- L9's "stable for 300 seconds after pairing" and L10's "MTU 247" have both been reproduced and verified on the real device on this machine.

---

## 8. Addendum: 2026-11-12 Connection-Instability Investigation

> This section only indexes and summarizes conclusions; for the full evidence chain, timeline, and root-cause list, see
> [Linux connection troubleshooting findings](linux-ble-connect-findings.md).

### 8.1 New Findings (overturning two old conclusions)

| Old record | 2026-11-12 measurement |
|---|---|
| "Waking and swiping the band screen during scanning makes it advertise" | **Ineffective.** Scan-only for 35 s: the heart-rate measurement page produced only 1 pulse (`+21.7 s`), and continuously swiping up and down on the main watch face produced **0 pulses**. With no phone link, the band emits exactly 1 isolated connectable pulse every **40–60 seconds** |
| "`hog-lib.c` errors clog the ATT queue, so `Trusted=False` should be used" | **Not the root cause.** The 9 consecutive successful sessions on 11-09 were all `Trusted=True` (data in `data/heart_rate.jsonl`, `data/steps.jsonl` at `23:25–23:41`); the `hog-lib` error is only settled and printed **at the moment the link drops** |

### 8.2 New Issues (numbering continues from L10)

| ID | Severity | Issue | Conclusion |
|---|---|---|---|
| L11 | High | When unpaired, the band only allows enumeration within ~9–9.8 s after link establishment; the first full enumeration of 150 GATT handles cannot finish at a deep-sleep connection interval | This is a different mechanism from L9's "36–40 s disconnect"; this round's "catch the pulse → long standby" solved half of the "cannot catch it" problem |
| L12 | High | Cancelling a pending `LE Create Connection` (timeout or active `Disconnect`) makes the BARROT `33fa:0012` scan **silently stall**: HCI commands complete as usual, but over-the-air advertising events stay 0 | Only a USB-level reset (`usbreset`/unplug-replug) works; D-Bus `Powered=false/true` is **ineffective** |
| L13 | Medium | `bleak 3.0.2` deadlocks for 41 s on `le-connection-abort-by-local` (waiting for a `Connected=false` that never appears) | Already handled by `bluez_support.wait_for_bluez_link()` re-arming |
| L14 | Medium | `DuplicateData=True` restarts extended scanning every ~5 s on BT 5/6 controllers (31 `0x2041/0x2042` events in 75 s), a trigger for this adapter's `-112` stall | Default changed to `False` |

### 8.3 Code Changes (see findings document §5 for details)

- `bluez_support.py`: `link_standby_budget()`, `wait_for_bluez_link()`, `scanner_kwargs()` no longer deduplicates by default,
  `is_transient_connect_error()` adds `failed to discover services`, error wording rewritten;
- `miband_client.py`: Linux goes through `_open_bluez_link()` (long-lived `Device1.Connect`, never `Disconnect` midway),
  non-Linux goes through `_open_generic_link()`; after `ServicesResolved`, wait for SMP to settle before writing GATT;
  `start_notify` changed to a 6 s × 2 bounded retry; `--connect-timeout` default 75 s;
- `doctor.py`: `trust` takes priority; added a note about single-pulse advertising.

### 8.4 Regression Results

```
python3 -m pytest -q                            # 266 passed, 4 skipped
MIBAND_ECDH_BACKEND=python python3 -m pytest -q  # 266 passed, 4 skipped
python3 miband_client.py --demo 3 --imu --storage both  # end-to-end path normal
```
