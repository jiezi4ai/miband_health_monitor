**English** · [简体中文](linux-ble-connect-findings.zh-CN.md)

# Linux "Band Often Fails to Connect" Investigation and Root-Cause List (2026-11-12)

> This document records a set of controlled real-device experiments on 2026-11-12 on Ubuntu 24.04 / BlueZ 5.72 / kernel 6.8
> targeting "the band often cannot connect on Linux", together with the resulting code changes.
> The goal is to **turn a black box into reproducible facts**: every conclusion comes with an observation method and measured data,
> so that future regressions can be compared directly.
>
> See `docs/validation/linux-validation.md` for the previous round (2026-11-08, L1–L10 issue list).

## 0. TL;DR

| # | Conclusion | Impact |
|---|---|---|
| 1 | **With the phone's Bluetooth off, the Mi Band 6 emits only 1 isolated advertising pulse every 40–60 seconds**; with the screen off it emits nothing at all, and **waking/swiping the screen does not make it advertise faster** | Any "short-window connect + rescan" strategy falls into leapfrog misalignment and never catches a pulse |
| 2 | **Cancelling a "pending" `LE Create Connection` (`Disconnect` / timeout cancel) makes the BARROT `33fa:0012` adapter's scan silently stall**: HCI commands are still acknowledged, but over-the-air advertising events stay at 0 forever | In the field this looks like "the scanner starts normally but not a single packet is received"; only a USB-level reset recovers it |
| 3 | `bleak` **3.0.2** mistakes `le-connection-abort-by-local` for "it once connected" and waits for a `Connected=false` that never arrives, **hanging for 41 seconds** | A single `connect()` cannot span the kernel's 40-second initiation period, so it must re-arm the connection itself |
| 4 | After `ServicesResolved`, BlueZ still runs SMP (`new_auth`) and built-in HID/device-info probing; during this time **the first GATT write/`start_notify` gets stuck behind the single ATT queue** (measured 56.8 seconds) | The first authentication step must not be sent immediately after `ServicesResolved`; leave a settling window and add a timeout |
| 5 | `DuplicateData=True` makes BlueZ **restart extended scanning every ~5 seconds** on BT 5.x/6.x (31 `0x2041/0x2042` events in 75 seconds) | One of the triggers for this adapter's silent stall; the default has been changed to `False` |
| 6 | Historically (11-09), 9 consecutive successful sessions **were all completed with `Trusted=True`**; the `hog-lib` error is only settled and printed when the link drops at the end of the session, **and is not the blocking root cause** | Do not disable `Trusted` just to avoid the HID plugin; `Trusted` is actually a prerequisite for kernel auto-reconnect and GATT caching |
| 7 | "Scan hit → immediately `Connect`" works (delivered within 10 ms it can still hit the tail frame of the same advertising burst), **but only if the connection is not cancelled midway** | This revision hardens it into the `wait_for_bluez_link()` standby loop |

## 1. Environment

| Item | Value |
|---|---|
| Host | Ubuntu 24.04.5 LTS, kernel `6.8.0-147`, x86-64 |
| Bluetooth stack | BlueZ `5.72`, `bluetooth.service` active |
| Adapter | `hci0`, USB `33fa:0012`, **BARROT Bluetooth 6.0 Adapter** (vendor ID 2279) |
| Adapter power | `/sys/bus/usb/devices/6-4/power/control = auto`, `autosuspend_delay_ms = 2000` |
| Python | 3.13 (conda), `bleak 3.0.2`, `dbus-fast` |
| Band | Mi Smart Band 6, MAC `C0:FF:EE:C0:FF:EE` (public address, not RPA) |
| Paired devices | AirPods, LIFT mouse, Huazai speaker, etc. (they compete for the controller during BLE scanning) |

## 2. Observation Methods (reusable)

1. **HCI over-the-air event delta method** (the most important tool this round). The `events` counter of `hciconfig hci0`
   counts "received HCI events", including `Command Complete` and `LE Meta`.
   Within one sampling window:

   ```
   air_events = Δevents − Δcommands
   ```

   - `air_events > 0`: the controller really did report over-the-air packets to the host (the radio is working);
   - `Δevents == Δcommands` (i.e. `air_events == 0`): **every command sent by the host only got back a
     `Command Complete`, with no advertising reports at all** — in this state, "the band is not advertising" and
     "the adapter has gone deaf" cannot be distinguished at the application layer; you must also consider "is any other device advertising" and whether it recovers after a USB reset.

2. **`journalctl -u bluetooth` / `journalctl -k`**: capture `new_auth()`, `hog-lib.c`,
   `Opcode 0x2041/0x2042 failed: -112`, `start background scanning failed: -112`.

3. **Scan-only probe** (the only measurement that does not change hardware state): scan continuously for N seconds,
   **never call `Connect`/`Disconnect`**, and record the arrival timestamp, `Δt`, RSSI, `ManufacturerData`,
   and `ServiceData` of every packet. After this probe the adapter stays healthy and can be retested repeatedly.

4. **Persistence cross-validation**: the `iso_time` values in `data/heart_rate.jsonl` and `data/steps.jsonl`
   are hard evidence of "authentication really succeeded and data was actually collected" and can be used to cross-reference the
   `journalctl` records from that time (this round used them to correct the misjudgment that "11-09 succeeded because `Trusted=False`").

## 3. Controlled Experiment Timeline

All times are local UTC (`TZ=Etc/UTC`).

| ID | Time | Operation/condition | Key observation | Conclusion |
|---|---|---|---|---|
| 2A-2 | 06:33:07–06:34:16 | `Trusted=False`, screen on with swiping | Caught a pulse and linked in 5.8 s; exchanged `acl_tx=+166 / acl_rx=+165` within 8.7 s, then `failed to discover services, device disconnected`; **0** `hog-lib.c` errors | Both the physical link and GATT enumeration were proceeding; the band kicked the link after ~9 s without authentication |
| 2A-3 | 06:38:06, 06:38:11 | 1 ms after the pre-check scan `stop()`, `Powered=false` | `Opcode 0x2041 failed: -112`, `start background scanning failed: -112`, then 75 s with zero advertising | The race between stopping the scan and switching power directly corrupts the extended-scan state machine |
| 2A-4 | 06:43–06:47 | D-Bus `Powered=false/true` reset only | Within 75 s `commands=+31 / events=+31`, `air_events=+0` | **A D-Bus soft reset cannot recover the radio**; a USB-level reset is required |
| 2A-5 | 06:49:24 / 06:50:05 / 06:50:57 | After the USB reset, `DuplicateData=False` | Three pulse intervals **40.5 s / 52.2 s**; every `Connect(15~20 s)` yielded `acl=0` | Pulse period > connection window, producing "leapfrog misalignment": every pulse is consumed by the scanner |
| 2A-6 | 07:54:44 → 07:55:59 | `Connect` within 10 ms after catching a pulse; segmented re-arm | Link established with `acl_tx=+7 / acl_rx=+6`, kicked after 9.76 s; re-armed on the spot 0.15 s later; `le-connection-abort-by-local` at 07:55:02; **bleak waited idly for 41.11 s**; the BlueZ object was still alive 59.6 s after scanning stopped | ① "connect on packet capture" works; ② bleak 3.0.2 has an abort deadlock; ③ a pending `Connect` prevents the object from being reclaimed |
| 2A-7 | 08:05:57 → 08:07:22 | After a 35 s slice timeout, bleak automatically `Disconnect`ed | After cancelling the pending connection and rescanning, `air_events=+0` for 50 s | **Cancelling a pending `Connect` makes the adapter deaf** (same root as 2A-3) |
| 2A-8 | 08:23:00 → 08:24:56 | After the USB reset, `Trusted=True` + a single `Connect(95 s)` | `acl=0` for 115 s, covering two complete 41 s kernel initiation periods with zero system errors; the object's `UUIDs` contained only `0xfee0` (no `0x1812`) | `Trusted` cannot trigger anything over the air before the first link is established; a real pulse hit is still required |
| **1-A** | 08:31:21–08:31:56 | Band left on the **"Heart rate" measurement page**; scan-only for 35 s | **Only 1 packet** (`t=+21.7 s`, RSSI −54, `ServiceData 0x1074 = 4212 steps`), `air_events=0` the rest of the time | The heart-rate page does **not** produce dense advertising |
| **1-B** | 08:35:17–08:35:52 | Main watch face/menu **swiped continuously up and down**; scan-only for 35 s | **0 packets** (`air_events=0`) | **Screen swiping does not trigger advertising**, contrary to the old documentation |
| Historical comparison | 11-09 23:25–23:41 | Old code (`c220a97e`, `Trusted=True`) | **9 sessions all authenticated successfully**: 50 heart-rate records (79–101 bpm), 93 step records, 929 IMU records, and 1188 history records; during the same period `bluetoothd` printed `hog-lib.c ... unlikely error` at **23:26:10 / 23:31:33 / 23:34:28** | The HID error is printed when **the link drops and accounts are settled**, not the blocking root cause; `Trusted=True` is the success path |
| Historical comparison | 06:12–06:19 | Uncommitted code (`Trusted=True`) | 6 automatic reconnects at about 61 s intervals, each reaching `new_auth()` | As long as the GATT table is cached, kernel auto-reconnect is reliable |

### 3.1 What a Single-Pulse Advertisement Actually Looks Like

The only sample caught by `1-A`:

```
mfg  = 343: 02ffff...ff02 f229feea46be   # Huami manufacturer data, trailing 0x02 = connectable flag
svc  = 0000fee0...: 74100000             # 0x1074 = 4212 steps (little-endian)
rssi = -54 dBm
```

That is: **the pulse itself carries live data and is a connectable advertisement (`ADV_IND`)**; it just appears very infrequently.
Another already-bonded device's `ServiceData` changed with the step count across multiple samplings, showing that the payload is live.

## 4. Root-Cause List

### R1 · Single-pulse advertising + short connection window = leapfrog misalignment (P0)
- **Symptom**: "scanning sees it, connecting fails" occurring repeatedly, or success only every other pulse.
- **Evidence**: the three pulses in 2A-5 were `40.5 s / 52.2 s` apart; each `Connect` waited only 15–20 s before timing out and falling back to scanning.
- **Mechanism**: pulse arrives → scanner consumes it → enter `Connect` and wait 20 s (missing the next pulse) → fall back to scanning →
  the next pulse is consumed by the scanner again……the phase is permanently offset.
- **Fix**: `bluez_support.link_standby_budget()` guarantees a budget ≥ `BAND_PULSE_PERIOD` (70 s);
  `_open_bluez_link()` no longer falls back to scanning during retries.

### R2 · Cancelling a pending connection → adapter scan silent stall (P0, most insidious)
- **Symptom**: the scanner starts normally and the `hciconfig` counters increase, but `air_events` stays 0 and not a single packet is received.
- **Evidence**: 2A-3 (power switch 1 ms after scan stop → `-112`), 2A-7 (after a 35 s timeout `Disconnect`, zero advertising for 50 s),
  2A-4 (`Powered=false/true` cannot recover; `commands=+31 / events=+31`).
- **Conclusion**: `-112 = -EHOSTDOWN`, requiring a **USB port-level reset** (`usbreset` or unplug/replug).
- **Fix**: the standby loop **never actively `Disconnect`s**; `disconnect_device()` gains a documented constraint
  "only for cleaning up ghost connections"; the scan heartbeat prints explicit reset instructions after "25 consecutive seconds with zero packets".

### R3 · bleak 3.0.2 deadlocks for 41 s on `le-connection-abort-by-local` (P1)
- **Evidence**: 2A-6 `07:55:02.691 → 07:55:43.802`; in the source this branch unconditionally
  `await local_disconnect_monitor_event.wait()`, but BlueZ never emits `Connected=false` when the kernel never connected.
- **Fix**: a single `bleak.connect()` no longer takes on cross-period work; instead
  `bluez_support.wait_for_bluez_link()` uses D-Bus directly to hold one `Device1.Connect`,
  re-arming ~150 ms after an abort, and hands the established connection to `bleak` once successful.

### R4 · SMP / built-in profile probing starves the ATT queue (P1)
- **Evidence**: `06:12:11.767` `ServicesResolved` → `start_notify(0x0017)` sent 1 ms later →
  `06:12:13` `new_auth() No agent available` → stuck for 56.8 s.
  Also in 2A-2, `hog-lib.c`'s `unlikely error` was settled in a burst at the moment the link dropped.
- **Fix**: `_settle_after_link()` waits `SMP_SETTLE_DELAY` (default 1.5 s, overridable via `MIBAND_SMP_SETTLE_DELAY`)
  after `ServicesResolved`; `_start_chunked_listener()` uses a bounded retry of 6 s × 2
  instead of a bare `await`.

### R5 · The 5-second restart storm of `DuplicateData=True` (P1)
- **Evidence**: during a 75 s scan, `commands=+31`, exactly 15 periods ×2 +1.
- **Fix**: `scanner_kwargs()` defaults to `DuplicateData=False`; `MIBAND_BLUEZ_DUPLICATE_DATA=1`
  is kept for experiments.

### R6 · Stale RSSI causing a false direct connect (P1)
- **Evidence/mechanism**: objects with `Trusted=True` retain the last `RSSI` for a long time,
  so "having an RSSI means fresh" does not hold.
- **Fix**: `_direct_connect_target()` accepts only **bonded** devices or a genuinely `Connected+ServicesResolved`
  connection; `active_cached_device()` is marked legacy and is no longer called.

### R7 · Nested retries blowing up the total budget (P1)
- **Evidence**: the old `_connect_with_transient_retry` nested `_discover_device(45 s)` after each 15 s timeout,
  worst case `10 + 90 + 3×(15+45) + 15 ≈ 295 s`, making `duration` meaningless.
- **Fix**: the budget is uniformly governed by `connect_timeout` (default 75 s, with `link_standby_budget()` guaranteeing 70 s);
  retries no longer nest scanning.

### R8 · Misleading documentation and hints (P2)
- "Wake and swipe the screen and it will advertise" → measured as ineffective;
- "run `bluetoothctl pair` first" → a band still bound to the phone often returns `AuthenticationCanceled` and triggers cache deletion;
  the correct single step is `trust` (`pair` is optional only in built-in-agent scenarios);
- `--doctor` claims that "not paired" inevitably means a 40 s disconnect, which does not match the measurements (~9 s enumeration watchdog, `Trusted` alone enables auto-reconnect).
- **Fix**: `doctor.py` wording, `describe_ble_error()`, this document, `docs/guides/cross-platform.md`, and `README.md` were updated together.

### R9 · Unauthenticated watchdog (~9–9.8 s) and first full enumeration (P1, hardware constraint)
- **Evidence**: 3.7 s enumeration in the active screen-on state = success; 331 packets exchanged in 8.7 s right after the screen turned off, then kicked; deep sleep 9.76 s with only 6 rounds.
- **Conclusion**: the first connection (BlueZ has no GATT cache yet) requires the band to be at a "just woken" fast connection interval at the moment the link is established;
  once BlueZ has cached the service table, later connections no longer need a full enumeration.
- **Countermeasure**: this revision is responsible for "making the connection window long enough + catching the first usable pulse";
  "the physical state at the moment of link establishment" still depends on whether the band was just woken (see the items to verify in §7).

## 5. Code Change Cross-Reference

| File | Change | Corresponding root cause |
|---|---|---|
| `bluez_support.py` | Added `LE_CONN_TIMEOUT`, `CONNECT_SLICE_TIMEOUT`, `BLUEZ_TEMP_OBJECT_TIMEOUT`, `BAND_PULSE_PERIOD`, `SMP_SETTLE_DELAY`, `link_standby_budget()` | R1/R3/R4/R7 |
| `bluez_support.py` | Added `wait_for_bluez_link()`: one long-lived `Device1.Connect` + property polling + re-arm ~150 ms after an abort, never `Disconnect` | R1/R2/R3 |
| `bluez_support.py` | `scanner_kwargs()` defaults to `DuplicateData=False`; `MIBAND_BLUEZ_DUPLICATE_DATA=1` restores it | R5 |
| `bluez_support.py` | `is_transient_connect_error()` now includes `failed to discover services`, `device disconnected`, `Not connected`, `Try again` | R9 |
| `bluez_support.py` | `describe_ble_error()` rewrites the timeout / abort / `-112` wording; `UnknownObject` now points to `trust` | R8 |
| `bluez_support.py` | `active_cached_device()` marked legacy; `disconnect_device()` documents "must not be used for pending connections" | R2/R6 |
| `miband_client.py` | `_open_client()` split into `_open_bluez_link()` / `_open_generic_link()` | R1/R7 |
| `miband_client.py` | `_open_bluez_link()`: `Trusted` first → long standby → hand over to bleak once the link is ready | R1/R2/R3/R6 |
| `miband_client.py` | `_connect_with_transient_retry()` drops nested rescans and retries in place only | R7 |
| `miband_client.py` | Added `_settle_after_link()`, `_start_chunked_listener()` (6 s × 2 bounded retry) | R4 |
| `miband_client.py` | `_discover_device(deadline=...)` + heartbeat statistics; warn and give `usbreset` guidance after 25 consecutive seconds with zero packets | R2/R8 |
| `miband_client.py` | `DEFAULT_CONNECT_TIMEOUT = 75.0`; `--connect-timeout` help text explains the 70 s pulse period | R1 |
| `miband_client.py` | Module docstring corrects the wrong "advertises only with the screen on" description | R8 |
| `doctor.py` | Unpaired/untrusted hints now prefer `trust`; added a "single-pulse advertising" informational line | R8 |
| `tests/` | Added cases for `wait_for_bluez_link` ready handover, no `Disconnect` on timeout, the `DuplicateData` default, abort wording, etc. | — |
| `docs/` | This document + `linux_validation.md` §8 + `cross_platform.md` / `README.md` corrections | R8 |

Environment variable quick reference:

| Variable | Default | Purpose |
|---|---|---|
| `MIBAND_BLUEZ_TRUST` | `1` | When `0`, do not set `Trusted=True` (for A/B experiments) |
| `MIBAND_BLUEZ_DUPLICATE_DATA` | `0` | `1` restores `DuplicateData=True` |
| `MIBAND_SMP_SETTLE_DELAY` | `1.5` | Seconds to wait for settling after `ServicesResolved` |
| `CONNECT_TIMEOUT` / `--connect-timeout` | `75` | Single connection budget (at least 70 s on Linux) |
| `SCAN_TIMEOUT` / `--scan-timeout` | `90` | Time to wait for the first pulse (pulse period 40–60 s) |

## 6. Field Runbook

1. **Confirm the physical preconditions**: phone Bluetooth/airplane mode off; the band has recently connected to Zepp Life once
   (the public advertising state is a volatile state set and maintained by the App; a band reboot loses it).
2. **Self-check first**: `python3 miband_client.py --doctor` to inspect the adapter's `powered`, device
   `trusted/connected`, and `.env` permissions.
3. **Determine whether the adapter has stalled**: run one scan-only probe (e.g.
   `python3 scan_live.py`, or directly observe
   `hci_air_events` / the `other BLE` count in the heartbeat from the main program).
   - If within 25–35 s there is not **a single packet from any other device either**: the adapter is probably deaf →
     `sudo usbreset 33fa:0012 && sudo systemctl restart bluetooth`
     (`Powered=false/true` **does not work**; measured ineffective);
   - If other BLE devices are visible but the band is not: band-side advertising is not enabled or the band is out of range.
4. **Normal collection**: `python3 miband_client.py 60 --imu --log-level DEBUG`.
   The first pulse taking 40–60 s to appear is normal; the program keeps `Connect` pending waiting for it.
5. **Reading the logs**:
   | Log | Meaning | Handling |
   |---|---|---|
   | `BlueZ link to ... is up and services are resolved` | Link established | Continue normally |
   | `le-connection-abort-by-local` | This round's pulse was missed; automatically re-armed | Wait for the next round; no intervention needed |
   | `failed to discover services, device disconnected` | Band's ~9 s watchdog kicked the link (enumeration did not finish) | Automatic retry; keeping the band screen on improves the success rate |
   | `-112` / `host is down` | Adapter state machine is stuck | USB reset + restart bluetooth |
   | `No BLE packet from ANY device` | No reports at the radio level | Same as the previous line |
6. **First-connection failures are normal**: when not paired, the band only allows a ~9–9.8 s enumeration window;
   if it is at a deep-sleep connection interval at that moment, the link will inevitably be kicked. After `Trusted=True`, BlueZ caches the service table,
   and the second connection is much faster.

## 7. Unsolved Problems (next steps)

1. **Why did `Trusted=True` + a single 95 s `Connect` in 2A-8 yield `acl=0` entirely, while
   an ordinary `Connect` at 06:12 succeeded in 5.8 s?** This may be related to the phase of the
   advertising burst right after the adapter reset at that time, or to a conflict between `Device1.Connect` and kernel auto-connect; `btmon`
   over-the-air evidence is needed (capturing the exact moments of `LE Create Connection` / `LE Connection Complete`).
2. **For the 0 packets in `1-B`, was it "the band did not advertise" or "the adapter went deaf again"?** This round's `air_events=0`
   only proves "nothing was reported" and cannot distinguish the two. Next, capture `btmon` simultaneously during the scan-only probe,
   or add a "visibility of other BLE devices" control before and after the probe.
3. **Whether Zepp Life's "sports heart-rate broadcast" switch only takes effect in specific modes (e.g. the band's workout mode)**:
   this round's 1-A/1-B have shown that neither the watch face nor the heart-rate page speeds up advertising, but the band firmware menu has no such switch;
   a control experiment with "free training enabled" (test 1-C) is needed to confirm.
4. **Whether BlueZ caching can be made persistent to eliminate scanning entirely**: per the 06:12–06:19 evidence, with `Trusted=True`
   + a cached GATT table, kernel auto-connect succeeds about every ~61 s; it needs to be verified whether the cache is still valid
   across "process exit → restart".
5. **The exact trigger surface of `-112`**: this round only confirmed two categories, "scan stop + power switch" and "cancel a pending `Connect`".
   Whether a broader hard rule "forbid any power/connection-cancel operation while scanning is active" is needed
   awaits over-the-air evidence.

## 8. Minimal Reproduction Script Skeleton

```python
# Scan-only: verify the advertising pattern without ever changing adapter state
import asyncio, time
from bleak import BleakScanner

async def main(duration=35.0):
    t0 = time.monotonic()
    def cb(dev, adv):
        if dev.address.upper() == "C0:FF:EE:C0:FF:EE":
            print(f"+{time.monotonic()-t0:.3f}s rssi={adv.rssi} svc={adv.service_data}")
    scanner = BleakScanner(detection_callback=cb,
                           bluez={"filters": {"DuplicateData": False, "Transport": "le"}})
    await scanner.start()
    await asyncio.sleep(duration)
    await scanner.stop()

asyncio.run(main())
```

`hciconfig` delta check:

```bash
hciconfig hci0 | grep -E "RX bytes|TX bytes"   # take one sample before and after, then compute Δevents-Δcommands
```
