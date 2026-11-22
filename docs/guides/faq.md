**English** · [简体中文](faq.zh-CN.md)

# Frequently Asked Questions (FAQ)

Look up by symptom; see [cross-platform.md](cross-platform.md) for platform details and [configuration.md](configuration.md) for configuration.

## Connection and scanning

> **First troubleshooting step when Linux fails to connect (recommended first try)**:
> If phone Bluetooth is already off yet Linux still cannot connect (especially when scan heartbeats show `other BLE=0` or `-112`), reset the USB adapter at the bus level, restart `bluetoothd`, and verify readiness with `--doctor`:
> ```bash
> .venv/bin/python tools/reset_bt_adapter.py
> # Or run manually (check `lsusb` for <vid:pid> if not BARROT 33fa:0012):
> sudo usbreset 33fa:0012 && sudo systemctl restart bluetooth
> .venv/bin/python miband_client.py --doctor
> ```
> (`tools/reset_bt_adapter.py` auto-detects `<vid:pid>` from `/sys/class/bluetooth/hci0`, prompts before invoking `sudo`, and runs `--doctor` afterwards; supports `--dry-run` and `-y`.)
> **Why this works**: `usbreset` cold-resets the adapter's stalled BLE radio/scanning state machine (D-Bus `bluetoothctl power off/on` cannot clear firmware state), `systemctl restart bluetooth` rebinds `bluetoothd` to the re-enumerated `hci0` and clears stale D-Bus state while **preserving** your existing on-disk `Paired / Trusted` bond and GATT cache, and `--doctor` confirms `powered=yes`, intact pairing, and no stuck `connected=yes`. (Note: other connected Bluetooth peripherals on the host will briefly disconnect.)

| Symptom | Cause / handling |
|---|---|
| `No Bluetooth adapters found` / `org.bluez was not provided` | No Bluetooth stack on the machine (e.g. WSL2 without passthrough, `bluetooth` service not started). Install/start BlueZ, or pass through a USB adapter. |
| Cannot find the band within 90 seconds | Turn off phone Bluetooth; connect once with Zepp Life to restore the band's volatile "public advertising" state; confirm the MAC/UUID; the band only emits a pulse every 40–60 seconds, so use `--scan-timeout 120`. |
| Scanner is running and hardware counters increase, but within 25 seconds **not a single packet arrives even from other BLE devices** | USB adapter radio hang (common with BARROT `33fa:0012`): `sudo usbreset <vid:pid>` or unplug/replug USB, then `sudo systemctl restart bluetooth`. D-Bus power cycling has been measured to have no effect. See [validation/linux-ble-connect-findings.md](../validation/linux-ble-connect-findings.md). |
| Linux: dropped 9–10 seconds after the link is established, with `failed to discover services, device disconnected` | The band's unauthenticated connection watchdog (the first connection must enumerate ~150 GATT handles). The client retries automatically; first run `bluetoothctl trust <MAC>`. |
| Dropped after about 40 seconds, with `UnknownObject ... doesn't exist` | Not trusted: BlueZ removes the device object after disconnect. Run `bluetoothctl trust <MAC>`, and pair if necessary. |
| BlueZ log shows `No agent available for request type 2` while connecting | The band initiated SMP but the system has no agent: set `MIBAND_BLUEZ_AGENT=1` or run `bluetoothctl pair` manually. |
| Linux: drops about **5 seconds** after every connection, `ServicesResolved=False` (`RX/TX acl=0`) | BlueZ stores a stale `LTK`, causing an over-the-air `LE Start Encryption` timeout (`0x08`). When it happens twice in a row, the client automatically clears the cache and starts the agent to re-establish pairing; you can also manually `bluetoothctl remove <MAC>` + `MIBAND_BLUEZ_AGENT=1`. Note that after a normal Zepp Life sync there is no need to clear the cache. See [validation/linux-ble-test-report.md](../validation/linux-ble-test-report.md). |
| After the log shows `already connected in BlueZ; reusing connection`, the link drops shortly afterwards | A half-warm/stale `Connected=True` state left by the previous session. If reuse fails, the client automatically calls `disconnect_device()` to reset and rebuild; you can also run `bluetoothctl disconnect <MAC>` first and then connect. |
| Every connection takes tens of seconds | Normal: a band with no phone link only emits a pulse every 40–60 seconds. After trusting once, BlueZ caches the GATT table and reconnects automatically. |
| Windows: `BleakError ... not found` / connection refused | Use "Settings → Bluetooth & other devices" to confirm the adapter; delete the old device record; turn off phone Bluetooth; verify the address with `scan_ble.py`. |
| Windows: `OSError: [WinError 193]` / failing to load `libecdh.so` | The current version falls back to pure Python automatically; confirm the startup log says `ECDH backend: python`. |
| macOS: cannot scan / address does not match | No MAC is exposed: use the UUID printed by `scan_ble.py` as `DEVICE_ID`, or configure `DEVICE_NAME`; allow the terminal to access Bluetooth in System Settings. |

## Authentication and data streams

| Symptom | Cause / handling |
|---|---|
| Authentication timeout | Chunked notifications lost or firmware differences; check with `--log-level DEBUG`; the client retries on the next session automatically. |
| Authentication succeeds but heart rate does not move | The band must be worn snugly; the `0x2A39` control sequence may be rejected by the firmware; reconnect or reboot the band. |
| No IMU data | Some firmware requires entering a specific workout mode first; `--imu` is an experimental feature. |
| Duplicate data (steps) | The step stream first reads the current value and then subscribes to notifications, so the first entry may be duplicated; this is expected. |
| Meaning of timestamps | Live streams use computer receive time; history sync uses band sample time (see [data-formats.md](data-formats.md)). |

## History sync

| Symptom | Cause / handling |
|---|---|
| `--sync-history` reports `band rejected fetch type` | That firmware/model does not support the corresponding history type; the failure does not affect live collection. |
| `--sync-history` times out / checksum fails | Chunks lost or firmware differences; reconnection retries; on a real device please attach DEBUG logs. |
| `--sync-history 7` only retrieves 40 hours | Normal. The parameter only means "I ask for at most this long"; the band's ring buffer holds about 2400 minutes; the start point moves forward 1:1. |
| Zepp has data, but the band returns none | Three reasons: (1) already consumed by the app (permanent holes or out-of-window outside 40 hours); (2) the band never produces this kind of data (deep sleep/REM/score are computed by the app); (3) the band was not worn that night (`0xF3`), and the app showed another device on the same account. See [investigations/sleep-fields.md](../investigations/sleep-fields.md). |
| Want to confirm how far back the band still has data | `python tools/probe_declared.py 168 24`: query only, no fetch, no ACK, does not disturb the buffer. |
| 0x26 sleep SpO2 imported but not visible | Confirm it was written to the separate `spo2_sleep` table; the offline dashboard prefers the table and falls back to JSONL when it is empty. |
| The spot-check `spo2` table stays empty | Expected: spot-check records only exist when a single measurement was taken on the band; otherwise the round "declares 0 records" (visible in the INFO log). For an overnight curve use `--sync-sleep-spo2` (separate `spo2_sleep` table). |

## Dashboard and reports

| Symptom | Cause / handling |
|---|---|
| Dashboard will not open / port already in use | Use `--web-port 0` for a random port; it binds locally by default, so remote access needs `--web-host 0.0.0.0` and attention to the firewall. |
| Dashboard has data but the curves do not move | SSE disconnects reconnect automatically; confirm the page is not suspended or refresh it to pull a new snapshot. |
| History is empty after a dashboard refresh | Requires `--storage sqlite/both` and data in the database; `source=db` silently degrades when the database or table is missing. |
| `history_report.py` reports the database does not exist | Generate data first: `miband_client.py 60` or `--demo`. |
| A sleep report shows `unknown` for one night | That night has no heart rate: only the sleep duration can be given, and staging cannot be guessed. |
| A whole night of not wearing the band is counted as sleep | The current version uses `kind & 0x0F == 3` to detect non-wear and does not create a sleep segment; if it is still abnormal, please attach the data. |

## Exit and stability

| Symptom | Cause / handling |
|---|---|
| Disconnects after a while | Band power saving / taken off / phone contention; exponential backoff reconnects automatically by default. |
| No summary after Ctrl+C | The current version prints a `Storage summary`; if it does not, the process was probably force-killed or the log was redirected. |
| Collection window ends but there is no "Reconnecting" log | Expected: after `duration` is exhausted, the program returns normally; reconnection has not failed. |

## Historical issue status (Linux, recorded 2026-11-08)

Among L1–L10 in [validation/linux-validation.md](../validation/linux-validation.md):

- **L9 (about 36-second disconnect without pairing + misleading D-Bus errors) is fixed**: the documentation adds pairing/trust steps,
  and D-Bus errors are translated into actionable hints;
- **L10 (ATT MTU never negotiated) is fixed**: `_acquire_mtu()` is called explicitly after connecting, and the measured MTU goes from 23 → 247;
- The rest are documentation/script usability/silent-behavior issues, handled in the corresponding sections.

## Still unresolved / to be verified

- Real-device behavior on Windows/macOS still needs verification on those systems (code-level compatibility is complete);
- The mapping between the band's three-byte "stage scores" and Zepp durations is not settled; sleep staging is a derived value;
- The semantics of 0x26 `duration/signal/extend` are not settled and remain marked `[experimental]`.
