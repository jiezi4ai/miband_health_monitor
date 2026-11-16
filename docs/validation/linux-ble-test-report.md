**English** · [简体中文](linux-ble-test-report.zh-CN.md)

# Linux BLE Controlled Retest and Stale-LTK Root Cause Report (Tests 1–4 & Control Verification)

> Building on [linux-ble-connect-findings.md](linux-ble-connect-findings.md) (2026-11-12), this document records the follow-up
> controlled real-device experiments (Test 1–4, Test 4 v2, Test 0, Test B) covering
> **"BlueZ disconnects after about 5 seconds with `ServicesResolved=False`"**, **"does normal syncing break pairing"**,
> **"the impact of residual `Connected=True` connections"**, and **"3-day history calibration and timezone alignment"**,
> and distills the hardened self-healing mechanisms and a reusable Debug troubleshooting workflow.
>
> Device addresses are uniformly redacted to the placeholder `C0:FF:EE:C0:FF:EE`.

---

## 1. Key Conclusions (TL;DR)

| # | Key conclusion | Evidence source | Guidance for usage and implementation |
|---|---|---|---|
| 1 | **The 5-second repeated disconnects in Tests 1–3 = a stale BlueZ `LTK` (Long Term Key) causing an over-the-air encryption timeout (HCI error code `0x08`)** | Test 1–3 logs + `btmon` `.btsnoop` | The `LTK` cached in the old BlueZ `Device1` object does not match the band; after the kernel sends `HCI LE Start Encryption`, the firmware times out and drops the link after 5000 ms; at this point `ServicesResolved=False` and `RX/TX acl=0/0` |
| 2 | **Test 4's success was not because of clearing the cache itself, but because it removed the invalid pairing and rebuilt a valid `LTK` with `MIBAND_BLUEZ_AGENT=1`** | Test 4 v1 (`Paired=yes, Bonded=yes, Trusted=yes`) | `bluetoothctl remove` + pairing-agent rebuild is needed only when the `LTK` is already out of sync; never unconditionally delete the pairing every time in a normal state |
| 3 | **A healthy pairing remains fully usable after the phone's Zepp Life syncs normally and then turns Bluetooth off; there is no need to clear the cache or enable `MIBAND_BLUEZ_AGENT=1` every time** | Pre-check + Test 0 + Test B | Keep `Paired=yes / Bonded=yes / Trusted=yes / Connected=no` and run directly: 1 `direct connect` (13.5–18 s), **0 WARNING / 0 ERROR**, stable 60 s run + `--imu` |
| 4 | **Unconditionally running `remove` first every time is actually harmful** | Control experiments and BlueZ mechanism analysis | Clearing the cache every time loses the GATT service table cache and the `direct connect` scan-free fast path, re-exposing the link to the ~9–9.8 s unauthenticated enumeration watchdog; if the phone is not fully disconnected yet, it can also trigger `AuthenticationCanceled` |
| 5 | **Multiple `Connect`s or reconnects in one collection log come from two stacked layers**: ① the kernel period of waiting 40–60 s for a single pulse during standby; ② the supervisor automatically reconnecting after a session drops | Test 4 v2 vs Test B comparison | `le-connection-abort-by-local` is a normal log from re-arming on the kernel's 40 s initiation period; mid-session drops are mostly caused by the link being preempted by the phone, power-saving timeouts, or reuse of a residual half-open `Connected=True` state |
| 6 | **3-day history data aligns exactly with Zepp Life** | Test 4 v2 (`--sync-history 3 --band-tz Asia/Shanghai`) | 4318 minutes synced with no gaps; same-day steps `8353` vs `8353` exactly identical; after `detect_sessions()`'s boundary-extension logic + `--band-tz` fixed the double offset, the sleep interval `22:15 -> 06:28` closely matches Zepp's `22:24 -> 06:27` |

---

## 2. Controlled Experiment Summary (Tests 1–4 and Control Verification)

Common conditions: band-to-Linux-host distance < 1 m; before testing, the phone is confirmed to have finished syncing and phone Bluetooth is turned off (unless otherwise noted in the table).

| ID | Initial BlueZ state | Operation variable (cache / agent) | CLI target | Measured result | Key metrics and log signatures |
|---|---|---|---|---|---|
| **Test 1** | Old bond exists (`Connected=no`) | No cache clearing, no `MIBAND_BLUEZ_AGENT` | 60 s basic collection | **Failure** (`EXIT_CODE=1`) | Disconnect after about `5.15–5.18 s` following several `Connected=True`; `ServicesResolved=False`, `hciconfig RX/TX acl = 0/0` |
| **Test 2** | Old bond exists (same as Test 1) | Runs right after Test 1 under the same conditions | 60 s basic collection | **Failure** (`EXIT_CODE=1`) | Exactly reproduces the `~5.16 s` disconnect + `ServicesResolved=False` |
| **Test 3** | Old bond exists + `btmon -w` enabled | Simultaneously capture HCI `.btsnoop` | 60 s capture reproduction | **Failure** (`EXIT_CODE=1`) | `btmon` confirms: `LE Connection Complete` → `LE Data Length Change (251B)` → `HCI LE Start Encryption` → **`Encryption Change / Disconnect Complete: Connection Timeout (0x08)` after 5000 ms** |
| **Test 4 v1** | `bluetoothctl remove` first to clear the old object | `MIBAND_BLUEZ_AGENT=1` enabled | 60 s + `--imu` + `--sync-history 1` | **Success** (`EXIT_CODE=0`) | Triggers a brand-new SMP pairing and writes back `Paired/Bonded/Trusted=True`; 1440 history records + 1548 IMU records; 4 `[0x16]` keep-alives over the full 60 s |
| **Test 4 v2** | Starts with residual **`Connected=yes`** | No cache clearing (reuses the Test 4 v1 bond), `--band-tz Asia/Shanghai` | `--sync-history 3` + 60 s | **Success but reconnected midway** (`EXIT_CODE=0`) | Phase 1 reused the residual connection and synced 4318 history records, but the link dropped at ~39 s; phase 2 scan timed out; steps `8353 = 8353`, sleep `22:15–06:28` aligned with Zepp `22:24–06:27` |
| **Pre-check** | Phone's Zepp Life has just completed a normal sync, then Bluetooth off | Observation only via `bluetoothctl info`, **no changes to the band or cache** | State verification | **State intact** | `Paired=yes, Bonded=yes, Trusted=yes, Connected=no` |
| **Test 0** | Immediately after Pre-check (`Connected=no`) | **No cache clearing, no `MIBAND_BLUEZ_AGENT`** | 20 s smoke test | **Success** (`EXIT_CODE=0`) | 1 `direct connect` (18 s) directly; **0 WARNING / 0 ERROR** |
| **Test B** | Immediately after Test 0 (`Connected=no`) | **No cache clearing, no `MIBAND_BLUEZ_AGENT`** | 60 s + `--imu` stress test | **Success** (`EXIT_CODE=0`) | 1 `direct connect` (13.5 s); 4 `[0x16]` keep-alives; IMU reached `Seq 91`; **0 WARNING / 0 ERROR** |
| **Post-reboot** | After a system reboot (`Paired/Bonded/Trusted=yes, Connected=no`) | **No cache clearing, no `MIBAND_BLUEZ_AGENT`** | `--imu --sync-history 1 --band-tz Asia/Shanghai --export-csv` 60 s | **Success** (`EXIT_CODE=0`) | 1 `direct connect` (30.9 s); 1440 history + 44 HR + 1548 IMU with zero drops; **0 WARNING / 0 ERROR** |
| **Fresh Pair 1** | `remove_device()` first to fully clear the BlueZ object (`not known to BlueZ yet`) | Simulate a new device's first use: `MIBAND_BLUEZ_AGENT=1` | `--imu --sync-history 1 --band-tz Asia/Shanghai --export-csv` 60 s | **Success** (`EXIT_CODE=0`) | Pulse found in 10.7 s; triggered the `SERVICE_RESOLVE_GRACE` 10 s grace period and resolution succeeded +1.8 s later; the agent automatically authorized SMP; 1440 history + 45 HR + 1548 IMU; **0 WARNING / 0 ERROR** |
| **Fresh Pair 2** | Immediately after Fresh Pair 1 (the new pairing is already persisted) | **No longer enables `MIBAND_BLUEZ_AGENT`** | Default 20 s reconnect verification | **Success** (`EXIT_CODE=0`) | `--doctor` shows `paired=yes trusted=yes`; the default command establishes the link in 1 attempt (15 HR + 1 steps); **0 WARNING / 0 ERROR** |

---

## 3. Mechanism Analysis: Why "Multiple Errors/Warnings and Multiple Connections" Occur

### 3.1 The truth behind the ~5-second disconnect recovered by `btmon` (Tests 1–3)

When BlueZ holds an old pairing record but the band's pairing key has been refreshed by another host/App or the bond has been cleared, the handshake sequence between Linux and the band is as follows:

1. The kernel receives a pulse (or initiates `Device1.Connect`), and the physical link is established successfully (`LE Connection Complete`);
2. The controller completes parameter negotiation: `LE Data Length Change` (251 bytes) and `LE Read Remote Used Features` both return normally;
3. Because BlueZ considers the device `Paired=True`, the Linux kernel proactively sends `HCI LE Start Encryption` to the controller, passing in the **stale `LTK`** from BlueZ's on-disk store;
4. The band firmware cannot decrypt/authenticate this link-encryption request with its current key, so it neither triggers upper-layer GATT service discovery (hence `ServicesResolved` stays `False` and `acl` packet traffic is `0`) nor responds, and it simply times out and drops the link after about **5000 ms** (`Encryption Change: Connection Timeout (0x08)`).

> Distinguishing point: **stale-LTK disconnect ≈ 5.1 s with `RX/TX acl = 0/0`**; whereas **the first-connection unauthenticated watchdog ≈ 9.0–9.8 s and is accompanied by heavy GATT enumeration `acl > 0` (log `failed to discover services`)**.

### 3.2 Why the Log Shows Multiple `Connect`s and Reconnects

When running the main program (`run_monitor()` in [cli/runner.py](../../miband_monitor/cli/runner.py)), "multiple rounds of logs in one execution" come from two normal layers:

1. **Pulse waiting within a single link-establishment window (normal)**:
   A band with no phone connection emits only 1 connectable pulse every **40–60 seconds**. One Linux-kernel `LE Create Connection` times out after about 40 seconds and reports `le-connection-abort-by-local`. `wait_for_bluez_link()` re-arms on the spot after ~150 ms to wait for the next pulse, and enters `scan` (≥ 70 s) when `direct` (49.5 s) fails to hit. The INFO/WARNING retries during these periods are by design and do not indicate failure.
2. **Session supervisor reconnect on link loss (normal fault tolerance)**:
   If a session drops mid-run (e.g. Test 4 v2 phase 1 reused a residual `Connected=True` state and dropped at ~39 s, or the band's power saving/phone interference causes a drop), `run_monitor()` starts the next session after exponential backoff (or a `0.3 s` fast reconnect window immediately after the drop) to continue completing `--duration`.

### 3.3 Why You Should Not "Unconditionally Clear the BlueZ Cache Before Every Start"

1. **Normal phone syncing does not break the Linux bond**: Test 0 and Test B have verified conclusively that after Zepp Life finishes a normal sync and phone Bluetooth is turned off, the existing `Paired/Bonded/Trusted` keys on the Linux side remain valid and no re-pairing is needed.
2. **Keeping the cache provides two key benefits**: `direct connect` can initiate a link to an already-bonded device directly without relying on catching a pulse; and BlueZ has ~150 GATT handles cached, avoiding a full service discovery every time and the ~9 s watchdog.
3. **The cost of mistakenly deleting it**: if the band still has a valid bond with the phone and the phone's Bluetooth is not disconnected, deleting the BlueZ cache and forcing a pairing will instead be rejected over the air by the band (`AuthenticationCanceled`).

---

## 4. Self-Healing and Protection Logic Hardened in Code

In response to the two types of abnormal precursor states exposed by Tests 1–4 and Test 4 v2, the [bluez/](../../miband_monitor/bluez/__init__.py) and [ble/](../../miband_monitor/ble/client.py) layers have built in the following tiered self-healing mechanisms (**triggered only by confirmed failure evidence and never interfering with healthy pairings**):

| Trigger condition | Code location | Automatic action | Protection boundary |
|---|---|---|---|
| At startup direct-connect detection, **`Connected=True` and `ServicesResolved=False`** is found (ghost residue) | [ble/discovery.py](../../miband_monitor/ble/discovery.py) `_direct_connect_target()` | Calls `bluez.disconnect_device()` to clean up the ghost link, prints `WARNING`, waits 0.3 s, then continues connecting from a clean state | **Only cleans up existing objects confirmed `Connected=True`**; never sends `Disconnect` to a "pending `Connect`", preventing the BARROT adapter from stalling |
| When reusing a residual **`Connected=True` and `ServicesResolved=True`" connection, the Bleak handover fails or the first GATT/ECDH handshake fails | [ble/link.py](../../miband_monitor/ble/link.py) / [ble/auth_connect.py](../../miband_monitor/ble/auth_connect.py) | Prints `WARNING` and calls `bluez.disconnect_device()` to clear the stale half-open/invalid old connection; the next round rebuilds from a clean `Connected=no` | Executed only when `_reused_bluez_link=True`; does not affect new connection pulses |
| A single round or retries across `run_monitor` **hit `dropped_unresolved >= 2` consecutively** (drop at about 5 s before `ServicesResolved=True`), and the device is confirmed currently `Paired=True` | [bluez/link.py](../../miband_monitor/bluez/link.py) + [ble/link.py](../../miband_monitor/ble/link.py) `_recover_from_stale_bond()` + [cli/runner.py](../../miband_monitor/cli/runner.py) | ① `wait_for_bluez_link()` returns `"dropped-unresolved"` early after the 2nd unresolved drop, avoiding a pointless wait; ② calls `bluez.remove_device()` to remove the stale `Device1` object; ③ automatically launches `BlueZPairingAgent` and resets `_trusted_paths` to complete a clean re-pairing within the remaining budget or the next retry | ① **`paired_device()` must be non-empty** (unpaired devices are not mistakenly deleted); ② `_stale_bond_reset_attempted` **triggers only once** per run, preventing an infinite loop of cache deletion while the phone competes for the link |

---

## 5. Future FAQ and Systematic Debug Approach

### 5.1 "Preferred Reset & State Baseline Check" Before Every Investigation

When connections suddenly stall, scan heartbeats report `other BLE=0`, or retries keep failing, **make hardware USB reset + `bluetoothd` restart + `--doctor` your first troubleshooting step** (it cold-resets stalled adapter firmware while preserving your cached pairing keys and GATT table, making it safer and more effective than `power off/on` or deleting the bond):

```bash
# 0. Preferred quick reset & check (briefly disconnects other Bluetooth peripherals; use lsusb if not 33fa:0012)
sudo usbreset 33fa:0012 && sudo systemctl restart bluetooth
.venv/bin/python miband_client.py --doctor

# 1. Read-only baseline check: confirm phone Bluetooth is off / Zepp Life is not holding the link
python3 miband_client.py --doctor

# 2. View the four BlueZ object states (focus on Paired / Bonded / Trusted / Connected)
bluetoothctl info C0:FF:EE:C0:FF:EE | grep -E "Paired|Bonded|Trusted|Connected|ServicesResolved"

# 3. Check the USB adapter power/controller online state and the HCI counter baseline
hciconfig hci0
```

Expected output for a healthy standby state:
- `Paired: yes`, `Bonded: yes`, `Trusted: yes`, `Connected: no` (if a previous process was force-killed and left `Connected: yes`, first see whether the reconnect self-heals, or run `bluetoothctl disconnect C0:FF:EE:C0:FF:EE`).

### 5.2 Rapid Triage by Symptom and Troubleshooting Path

| Symptom / log keyword | Root-cause judgment | How to confirm | Action |
|---|---|---|---|
| Frequent `dropped-unresolved-after-5.xs`, `ServicesResolved=False`, `RX/TX acl=0/0` | **Stale BlueZ LTK** (key out of sync with the band) | Whether the self-healing log triggers `clearing cached BlueZ bond`; or check with `btmon` whether `0x08` is returned after `LE Start Encryption` | **If self-healing did not take effect or only tried once**: manually run `bluetoothctl remove C0:FF:EE:C0:FF:EE`, then `MIBAND_BLUEZ_AGENT=1 python3 miband_client.py 30` to rebuild the pairing |
| ~9–9.8 s disconnect after link establishment, `failed to discover services, device disconnected` (`acl > 0`) | **First full GATT enumeration timeout**, triggering the band's unauthenticated watchdog | `Paired: no` or the first enumeration right after clearing the cache | Move closer to the adapter and keep the band screen on, then rerun once; recovery follows once `Trusted=yes` and the cache are established |
| Scan for 25 s with **no** surrounding BLE device reported, `Opcode 0x2041/0x2042 failed: -112`, `Δevents == Δcommands` | **USB adapter radio scan state machine stalled** (common on BARROT `33fa:0012`) | Compare two `hciconfig hci0` samples: `events - commands == 0`, and the phone cannot scan any other device either | A physical/USB-level reset is required: `sudo usbreset 33fa:0012 && sudo systemctl restart bluetooth` (`bluetoothctl power off/on` is ineffective) |
| Can scan surrounding other BLE devices, but the band cannot be scanned within 90 s | ① The phone is still connected to the band; ② the band lost the "public advertising" state set by Zepp after a reboot | Open the phone and confirm the band's Bluetooth icon state, or check with Zepp Life whether it is directly connected | Run a full sync once with Zepp Life on the phone, make sure to exit and then **turn off phone Bluetooth** and retry |
| Link-establishment error `AuthenticationCanceled` (`0x05`) while `MIBAND_BLUEZ_AGENT=1` | The band is still locked to the phone/original binding, or the pairing timing conflicts | `btmon` / `journalctl -u bluetooth` shows `AuthenticationCanceled` | Confirm phone Bluetooth is fully off; restart the band's Bluetooth or unbind/rebind in Zepp Life if necessary |
| Link drops or authentication hangs right after `already connected in BlueZ; reusing connection` | A previous process was force-killed or hung and left a half-open `Connected=True` | `bluetoothctl info C0:FF:EE:C0:FF:EE` already shows `Connected: yes` before startup | The code automatically falls back to `disconnect_device()` after a failed reuse; you can also run `bluetoothctl disconnect C0:FF:EE:C0:FF:EE` first to reset before testing |
| History report / sleep times are off by 8 hours overall, or the day's step count is split incorrectly across midnight | `BAND_TZ` does not match the band's local timezone | `--sync-history` / `sleep_analysis.py` did not receive `--band-tz` | Pass `--band-tz Asia/Shanghai` (or set `BAND_TZ=Asia/Shanghai` in `.env`) so that storage and reporting use the same timezone convention |

### 5.3 Standard Procedure for In-Depth Packet-Capture Forensics

For new firmware or unknown D-Bus/HCI anomalies, collect complete evidence with the following non-intrusive procedure (avoid sending raw `.btsnoop` files or real addresses externally):

1. **Terminal 1 starts the kernel/HCI capture** (starting from a clean `Connected=no` state):
   ```bash
   sudo btmon -w /tmp/miband_btmon.btsnoop
   ```
2. **Terminal 2 runs the reproduction**:
   ```bash
   python3 miband_client.py 30 --log-level DEBUG 2>&1 | tee /tmp/miband_run.log
   ```
3. **Extract key HCI events offline and compare timestamps**:
   ```bash
   btmon -r /tmp/miband_btmon.btsnoop | grep -E "LE Connection|Start Encryption|Encryption Change|Disconnect Complete|Pairing|LTK"
   ```
4. **Run the repository redaction check before submitting or archiving**:
   ```bash
   python3 tools/check_privacy.py
   ```
