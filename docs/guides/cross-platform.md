**English** · [简体中文](cross-platform.zh-CN.md)

# Cross-Platform Running and Validation Guide (Linux / Windows / macOS)

This project was originally developed on Linux (BlueZ) and has now been refactored to be cross-platform at the code level. BLE access is
uniformly wrapped by [`bleak`](https://github.com/hbldh/bleak) (Linux/BlueZ, Windows/WinRT,
macOS/CoreBluetooth), so there is no need to maintain a separate Bluetooth stack per system; cross-platform differences are concentrated in
**native ECDH library loading**, **device identifier format** and **ATT MTU reporting**, all of which are handled.

> Documentation navigation: [Documentation hub](../README.md) · [Installation](installation.md) · [Configuration](configuration.md) ·
> [Usage](usage.md) · [Testing](testing.md)
>
> This guide also serves as the operational checklist for real-device validation on Windows/Linux; for test results, collect
> [§7 Feedback information](#7-information-to-include-in-a-bug-report).

---

## 1. Platform support matrix

| Item | Linux | Windows 10/11 | macOS 12+ |
|---|---|---|---|
| BLE backend | BlueZ (`dbus-fast`) | WinRT (`winrt-*`) | CoreBluetooth (`pyobjc`) |
| Device identifier | Bluetooth MAC | Bluetooth MAC | **CoreBluetooth UUID** (MAC is not exposed) |
| Name matching `DEVICE_NAME` | Supported | Supported | Supported (recommended) |
| ECDH backend | native `libecdh.so` (auto-compiled) | pure Python (optionally place `libecdh.dll` manually) | pure Python (optionally compile a `.dylib` manually) |
| Status | Verified (software path + real device, pairing required first) | **Pending real-device validation** | Code-compatible, pending validation |

ECDH backend selection rules (implementation in `miband_monitor/crypto/`):

1. The library specified by `MIBAND_ECDH_LIB` → 2. The current platform's library file under the project root
(`libecdh.so` / `libecdh.dll` / `libecdh.dylib`) → 3. Try to compile on the spot with `gcc`/`clang` →
4. Pure-Python fallback (`vendor/tiny_ecdh/`).

The startup log prints which backend is actually in use:

```
[INFO] MiBand6Client: ECDH backend: native      # common on Linux
[INFO] MiBand6Client: ECDH backend: python      # common on Windows/macOS
```

You can force a switch for troubleshooting with the environment variable: `MIBAND_ECDH_BACKEND=auto|native|python`.
The two backends have been cross-checked byte for byte (`tests/test_ecdh_backends.py`) and are safely interchangeable.

---

## 2. Linux

### 2.1 Dependencies

```bash
# Debian/Ubuntu example
sudo apt-get install -y python3-venv python3-pip bluez
sudo systemctl enable --now bluetooth
```

### 2.2 Installation and smoke test

```bash
cd miband_health_monitor
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# Environment self-check: adapter / pairing state / ECDH backend / .env permissions, all at once
.venv/bin/python miband_client.py --doctor

# No hardware: unit tests + full-path demo
.venv/bin/python -m pytest -q
.venv/bin/python miband_client.py --demo 2 --imu --output data/demo --export-csv
```

### 2.3 Real device (distinguish "first pairing without cache" from "daily use with existing cache")

Linux/BlueZ differs from Windows: the system does not complete SMP pairing automatically without an agent; and **when the first connection has no GATT cache yet,
the band only provides an unauthenticated enumeration window of about 9–9.8 seconds** (about 150 handles must be read one by one), so if the band is in a sleepy connection interval at that time it will be kicked off,
and the log shows `failed to discover services, device disconnected` or
`UnknownObject: Method "WriteValue" ... doesn't exist`.

#### Scenario A: First pairing / host with no BlueZ device cache

When `--doctor` has just reported `device not known to BlueZ yet` (new host, or you just ran `bluetoothctl remove` to clear the cache):

```bash
# 0) Self-check: confirm the adapter is powered=yes and the phone's Bluetooth is off
.venv/bin/python miband_client.py --doctor

# 1) Fill in the configuration (at least DEVICE_ID and AUTH_KEY)
cp .env.example .env

# 2) Recommended: enable the in-process pairing agent and go straight to first scan + automatic trust + SMP pairing
#    (keep the band within 1 meter and try to keep the screen on/worn, so the first GATT enumeration completes within the ~9s watchdog)
MIBAND_BLUEZ_AGENT=1 .venv/bin/python miband_client.py 60 --log-level INFO
```

**First cacheless pairing mechanism and caveats:**
- **No need to type `bluetoothctl pair` manually**: when running with `MIBAND_BLUEZ_AGENT=1`, after the scan captures a 40–60s pulse and before issuing `Device1.Connect`, the client automatically sets the adapter `Pairable=on` and the device `Trusted=True`, and uses the built-in `NoInputNoOutput` agent to let the target band's SMP requests through; if the link happens to come up right at the timeout edge, it also triggers a 10-second `SERVICE_RESOLVE_GRACE` grace period to ensure the first enumeration completes.
- **Do not manually `pair` in advance**: if the phone is still connected or holds a mutually exclusive bond, a manual `bluetoothctl pair` is easily rejected outright by the band (`AuthenticationCanceled`).
- **`.env` credentials that must be kept**: deleting the host's BlueZ cache does not affect `.env`; but if you also **factory-reset the band or unbind/rebind it in Zepp Life**, the band's built-in `AUTH_KEY` is updated, and you must re-extract it and update `.env` to pass application-layer ECDH authentication.
- **Public advertising prerequisite**: after a band reboot the volatile "public advertising" state may be lost; if no pulse is found within 120s, connect once to the band with the phone's Zepp Life and then turn off the phone's Bluetooth.

#### Scenario B: Existing device cache / normal daily reconnection (do not blindly delete the pairing)

When `--doctor` shows the device is already `paired=yes trusted=yes` (written persistently to BlueZ once first pairing completes):

```bash
# For daily use just run it directly; do not add MIBAND_BLUEZ_AGENT=1, and do not run bluetoothctl remove before every connection
.venv/bin/python miband_client.py 60
```

**Important principles when a cache exists:**
1. **Never clear the BlueZ cache before every connection**: every `remove` destroys the GATT service-table cache and the `direct connect` scan-free fast path, exposing you again to the ~9s unauthenticated watchdog; and if the phone is not fully disconnected it also increases the chance of `AuthenticationCanceled`.
2. **A normal Zepp Life sync on the phone does not break the existing pairing**: measurement shows that after the phone completes a sync and turns Bluetooth off, the existing `Paired / Bonded / Trusted` keys on the Linux side remain intact, and the default command connects directly on the first attempt (`0 WARNING / 0 ERROR`).
3. **When you actually need to clear the cache and re-pair (and automatic self-healing)**: only when the band has been re-bound to another host, making the `LTK` held by BlueZ stale (typical symptom: disconnection about 5 seconds after the link is established with `ServicesResolved=False`). When the client hits 2 consecutive unresolved disconnects and confirms the device is `Paired=yes`, it automatically calls `remove_device()` to clear the cache and starts the agent to self-heal; for manual recovery, run:
   ```bash
   bluetoothctl remove AA:BB:CC:DD:EE:FF
   MIBAND_BLUEZ_AGENT=1 .venv/bin/python miband_client.py 60
   ```
4. **If a previous force-kill left a `Connected=yes` residue**: the client automatically cleans up ghost connections (`Connected=True, ServicesResolved=False`); if the handshake fails when reusing a half-warm connection (`Connected=True, ServicesResolved=True`), it also actively calls `disconnect_device()` to fall back to a clean initial state and reconnect.

(If you want to perform the old manual steps of only trusting without pairing, you can run `bluetoothctl scan on` to capture a pulse and then `bluetoothctl trust AA:BB:CC:DD:EE:FF`.)

About the advertising frequency (**measured, contrary to older documentation**): after the phone's Bluetooth is turned off, the Mi Band 6
**only emits 1 isolated connectable advertising pulse every 40–60 seconds, and emits none at all when the screen is off**;
waking or swiping the screen does **not** make it advertise faster, it only affects the connection interval after the link is established.
Therefore the Linux path was changed to: after scanning the first pulse, **keep one `Device1.Connect` pending**
(for up to 70 seconds, covering the entire pulse cycle), instead of "fail after 15 seconds then go back to scanning".

After `trust` / first-pairing persistence:

- BlueZ keeps the device object and GATT cache; subsequent connections no longer need to re-enumerate 150 handles,
  and the kernel can also auto-reconnect when the band appears (measured 2026-11-12: 6 consecutive auto-reconnects, interval about 61 seconds);
- Connection no longer depends on "pressing Enter exactly during advertising" — the pending `Connect` waits for the pulse;
- ATT MTU is negotiated explicitly (previously always 23 bytes).

For detailed evidence and measurement reports, see [Linux connection troubleshooting chronicle](../validation/linux-ble-connect-findings.md) and
[Linux BLE controlled retest and stale LTK report](../validation/linux-ble-test-report.md).

### 2.4 Common problems

> **Preferred first troubleshooting step (first action when Linux suddenly stops connecting)**:
> ```bash
> .venv/bin/python tools/reset_bt_adapter.py   # auto-detects USB vid:pid -> confirms -> usbreset + restart bluetooth -> --doctor
> # Or run manually:
> sudo usbreset 33fa:0012 && sudo systemctl restart bluetooth   # check lsusb for vid:pid if not 33fa:0012
> .venv/bin/python miband_client.py --doctor
> ```
> **Why try this first (before toggling `power off/on` or deleting pairing)**:
> 1. **Clears hardware radio hangs directly**: USB adapters such as BARROT `33fa:0012` can lock their internal BLE scan/radio state machine so HCI still responds while `air_events == 0` (`other BLE=0`); `bluetoothctl power off/on` cannot fix this, whereas `usbreset` cold-resets the dongle firmware;
> 2. **Non-destructive to your bond**: `systemctl restart bluetooth` cleanly rebinds `bluetoothd` to `hci0` and clears stale D-Bus state while **keeping** your cached `Paired / Bonded / Trusted` keys and GATT table intact;
> 3. **Immediate readiness confirmation via `--doctor`**: verifies `powered=yes`, `paired=yes trusted=yes`, and `connected=no` before reconnecting (note that other Bluetooth peripherals on the host will briefly disconnect).

| Symptom | Handling |
|---|---|
| `org.bluez was not provided` / `No Bluetooth adapters found` | The `bluetooth` service is not running or there is no adapter; WSL2 does not support Bluetooth, use native Linux |
| Cannot scan | Phone Bluetooth is off; confirm the band's public advertising is still enabled (connect once with Zepp Life, then turn off phone Bluetooth). The band only emits one pulse every 40–60 seconds; set `--scan-timeout` to 120. If **no packets from any device** are received, see the next row |
| Scanner is running, `hciconfig` counters increase, but within 25 seconds **not a single BLE packet arrives** | Adapter radio hang (BARROT `33fa:0012` exhibits this after cancelling a pending connection): `sudo usbreset <vid:pid>` or unplug/replug USB, then `sudo systemctl restart bluetooth`. **D-Bus `Powered=false/true` has no effect** |
| Insufficient permissions | Normal users can usually do this; if restricted, check polkit/the `bluetooth` group or use a desktop session |
| Dropped 9–10 seconds after the link is established, log `failed to discover services, device disconnected` | The band's unauthenticated connection watchdog expires (the first connection must enumerate ~150 GATT handles). The client retries automatically; one `trust` lets BlueZ cache the service table and avoids it |
| Disconnects after about 40 seconds, log `UnknownObject ... doesn't exist` | Not `trust`ed. Let `bluetoothctl trust <MAC>` take effect first; only `pair` when Bond is really needed (a band still bound to the phone gives `AuthenticationCanceled`) |
| BlueZ log shows `No agent available for request type 2` while connecting | The band initiated SMP authentication but the system has no agent. `MIBAND_BLUEZ_AGENT=1` makes the client register a `NoInputNoOutput` agent to let it through automatically |
| Log shows `le-connection-abort-by-local` | The kernel initiated within its 40-second cycle without a band pulse; the client re-arms automatically, no intervention needed |
| Startup log says `MTU=23` with a `Using default MTU value` warning | Old-version behavior; current versions negotiate explicitly. If it still appears, add `--log-level DEBUG` to see why `_acquire_mtu` failed |
| Every connection takes tens of seconds | Normal: a band with no phone link only emits one pulse every 40–60 seconds. After one `trust`, BlueZ caches the GATT table and reconnects automatically, usually within seconds from the second time on |

### 2.5 Linux-specific behavior notes

| Behavior | Description |
|---|---|
| Direct-connect priority | Genuinely bonded devices are connected directly from the BlueZ object tree; connections with `Connected+ServicesResolved` are reused directly; cached objects are no longer trusted merely because they have an RSSI |
| Pending link establishment | After a pulse is scanned, one long-lived `Device1.Connect` covers the entire 70-second advertising cycle, and after the kernel's 40-second abort it re-arms automatically in about 150 ms; **no `Disconnect` is ever sent** (cancelling a pending connection makes some adapters' scanning hang) |
| Built-in pairing agent | With `MIBAND_BLUEZ_AGENT=1`, registers `org.bluez.Agent1` (`NoInputNoOutput`) on the system D-Bus and automatically lets the target band's SMP requests through; recommended for first cacheless pairing, not needed once a healthy pairing exists |
| Service-resolution grace | If the physical link happens to come up (`Connected=True`) just before the 70 s pending budget expires, `wait_for_bluez_link()` grants an extra 10 s `SERVICE_RESOLVE_GRACE` to avoid interrupting the first GATT enumeration |
| Stale-connection self-healing | When a ghost residue `Connected=True, ServicesResolved=False` is found, clear it before connecting; when reusing an already-connected object but link establishment/authentication fails, actively call `disconnect_device()` to fall back to a clean state |
| Stale-LTK self-healing | If a paired device hits `dropped_unresolved >= 2` consecutively (disconnect after about 5 s of encryption timeout), automatically `remove_device()` and temporarily start the pairing agent to rebuild a clean bond (at most once per run) |
| Scan parameters | `DuplicateData=False` (on BT 5/6, `True` makes BlueZ restart extended scanning every ~5 seconds); `MIBAND_BLUEZ_DUPLICATE_DATA=1` restores it |
| SMP settlement wait | Wait 1.5 seconds after `ServicesResolved` before sending the first GATT write, to avoid queueing behind BlueZ's `new_auth` + HID/device-info probing |
| Fast Retry | On `le-connection-abort-by-local`, `InProgress`, `failed to discover services`, retry in place without nested rescans |
| GATT write lock | Introduces a Gadgetbridge-like `BtLEQueue` mechanism: writes are globally serialized, and `InProgress` retries automatically |
| Fast reconnect | After session authentication succeeds the backoff delay is reset; after an unexpected disconnect it reconnects within 0.3s to catch the high-frequency advertising window right at disconnect |
| `--no-direct-connect` | Forces the scan path, useful for debugging issues such as "direct connect got a stale object" |
| MTU negotiation | After connecting, calls bleak's `_acquire_mtu()`; on WinRT the system does this automatically |
| Pairing state | `Trusted: yes` is the prerequisite for kernel auto-reconnect and GATT caching; `Paired: yes` is only necessary when an encrypted link/Bond is needed |
| Adapter reset | BARROT `33fa:0012` showing `-112`/zero advertising can only be reset at the USB level; D-Bus power cycling has no effect; both `--doctor` and the scan heartbeat give this hint |

---

## 3. Windows 10/11

### 3.1 Python and dependencies

Python 3.10+ from [python.org](https://www.python.org/downloads/) is recommended (check
"Add python.exe to PATH"); the Microsoft Store Python still works for BLE development,
but the python.org build is easier to troubleshoot.

```powershell
cd miband_health_monitor
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`bleak` installs the WinRT-related dependencies automatically (`winrt-runtime`, `winrt-windows-devices-bluetooth`, etc.),
so no manual handling is needed, and neither Visual Studio nor gcc is required.

### 3.2 Smoke test (no band needed)

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe miband_client.py --demo 2 --imu --output data\demo --export-csv
```

Expected: all pass (currently 390+ tests; the skipped cases need real capture data);
the demo produces `data\demo\*.jsonl`, `mi_band.db` and `csv\`.
If these two steps pass, Python, dependencies, the pure-Python ECDH backend, storage, the dashboard and the export path are all working on
Windows, leaving only the real BLE link.

### 3.3 Bluetooth environment check

1. "Settings → Bluetooth & other devices": the Bluetooth switch is on and the band's history entry is visible;
2. In Device Manager, confirm the Bluetooth adapter has no yellow exclamation mark and uses a vendor/WinRT-compatible driver;
3. If the band was previously connected to this computer: **remove the device** under "Bluetooth & other devices" and retry
   (Windows' BLE device cache sometimes causes connection failures);
4. Turn off phone Bluetooth / enable airplane mode, to avoid the band staying connected to the phone;
5. No need to keep swiping the screen: the band only emits one advertising pulse every 40–60 seconds (none with the screen off, and swiping does not speed it up),
   so set `--scan-timeout` to 120 and just wait for it to appear.

### 3.4 Running

```powershell
copy .env.example .env      # fill in DEVICE_ID (Bluetooth MAC) and AUTH_KEY
.venv\Scripts\python.exe scan_ble.py
.venv\Scripts\python.exe miband_client.py 60 --log-level DEBUG
.venv\Scripts\python.exe miband_client.py --demo 30 --web-port 8080   # dashboard self-test
```

### 3.5 Windows common problems

| Symptom | Cause / handling |
|---|---|
| `OSError: [WinError 193]` / loading `libecdh.so` fails | Old-version issue; the current version falls back to pure Python automatically; confirm the startup log says `ECDH backend: python` |
| `BleakError: ... was not found` | Wrong address or the band is not advertising: verify with `scan_ble.py`; confirm the band is not occupied by the phone |
| `BleakError: ... Unreachable` / connection timeout | Delete the old device record in Windows and retry; try another USB Bluetooth adapter (some cheap adapters have incomplete BLE support) |
| Scan list is empty | Windows Bluetooth switch/adapter issue; use the system's "Add device" page to confirm the band can be discovered |
| Disconnects soon after connecting | The band's screen is off / it is off the wrist; keep it worn and the screen active, or increase `SCAN_TIMEOUT` |
| Authentication timeout | Use `--log-level DEBUG` to watch chunked notifications; keep `--mtu` at the default, and for special adapters try `--mtu 185` / `--mtu 247` |
| Company computer cannot enable Bluetooth | Group policy/driver restriction; requires an administrator, unrelated to this project |

> Tip: `--mtu` is a "manual override", not automatic negotiation. If the configured value is larger than the actually negotiated MTU,
> chunked writes fail (authentication timeout/characteristic write errors). Without a clear basis, keep the default (do not pass `--mtu`).

### 3.6 Native ECDH acceleration (optional)

It works fine without a compiler. If you want the native implementation on Windows:

- With MinGW-w64 gcc: `gcc -O3 -shared -DECDH_BUILD_DLL ecdh.c -o libecdh.dll`,
  and put `libecdh.dll` in the project root; or
- With an MSVC developer command prompt:
  `cl /nologo /O2 /LD /DECDH_BUILD_DLL ecdh.c /Fe:libecdh.dll` (this produces
  `.obj` files in the current directory, which you can clean up manually), and likewise put it in the project root; or
- Use `MIBAND_ECDH_LIB=C:\path\to\libecdh.dll` to point at any location.

The startup log showing `ECDH backend: native` means it is in effect; on failure it still silently falls back to pure Python, without affecting functionality.

---

## 4. macOS (code-compatible, pending real-device validation)

- For privacy, CoreBluetooth does not provide MAC addresses, and scan results are **UUIDs**:
  `scan_ble.py` prints the UUID as the `Address`; put it into `DEVICE_ID`;
- Or match directly with `DEVICE_NAME` (advertising-name substring, e.g. `Mi Smart Band`), which is more robust across systems;
- On first run the system pops up a Bluetooth permission request; you must allow the terminal/IDE to access Bluetooth
  (System Settings → Privacy & Security → Bluetooth);
- Without a native `libecdh.dylib` it automatically uses pure Python; with Xcode command-line tools you can also
  `clang -O3 -dynamiclib ecdh.c -o libecdh.dylib` to enable the native backend.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scan_ble.py
.venv/bin/python miband_client.py 60 --device-name "Mi Smart Band" --log-level DEBUG
```

---

## 5. Design notes: what the cross-platform compatibility layer does

| Difference | Handling | Related code |
|---|---|---|
| ECDH needs a platform-native library | Two backends: native load/compile + pure-Python fallback, with a unified byte format | `miband_monitor/crypto/`, `vendor/tiny_ecdh/` |
| Windows/macOS lack Linux's `.so` | Select according to `sys.platform` between `.dll` / `.dylib`; a load failure is not fatal | `miband_monitor.crypto.native_library_candidates()` |
| macOS has no MAC | Dual device matching by identifier and name, with UUID format support | `miband_monitor.ble.identity.device_matches()` |
| Windows legacy configuration | `DEVICE_MAC` remains usable; if both are present, `DEVICE_ID` wins (placeholders are ignored) | `miband_monitor.ble.identity._env_device_id()` |
| ATT MTU differs per platform | Parse once after connecting and pass it to all chunked writes; supports `--mtu`/`BLE_MTU` overrides | `miband_monitor.ble.mtu` / `MiBand6Client._session_mtu` |
| Path / encoding differences | Everything uses `pathlib`; JSONL/CSV/.env explicitly UTF-8 | `miband_monitor/storage/`, `miband_monitor/auth/` |
| Signals/event loop | No POSIX signals, only asyncio; Ctrl+C is handled by `asyncio.run` | `miband_monitor/cli/` |
| Windows has no gcc | Pure-Python fallback; installing `requirements.txt` is enough | `miband_monitor.crypto.PurePythonEcdhBackend` |

---

## 6. Real-device validation checklist (run once on each of Linux / Windows)

Preparation: band battery ≥ 30%, worn; phone Bluetooth off; `.env` configured with `DEVICE_ID` + `AUTH_KEY`;
first confirm the software path with `--demo`.

| # | Item | Command / criterion |
|---|---|---|
| 1 | Device is scanned | The band appears in the `scan_ble.py` list, and the address/UUID matches `DEVICE_ID` |
| 2 | Connect + authenticate | Log shows `Chunked ECDH authentication SUCCEEDED` |
| 3 | Heart-rate stream | Log shows `Current Heart Rate: N BPM`, and `heart_rate.jsonl` has data |
| 4 | Step stream | Log shows `Steps: ...`, and `steps.jsonl` has data |
| 5 | IMU (optional) | With `--imu`, `imu.jsonl` grows at about 25Hz |
| 6 | Dashboard (optional) | `--web-port 8080`, browser curves refresh live, `/healthz` returns ok |
| 7 | History sync (optional) | `--sync-history 1` shows `Band history sync finished`, `spo2.jsonl`/`activity_history.jsonl` have data |
| 8 | Active disconnect and reconnect | Turn off the band's Bluetooth/go away and come back; the log shows `Reconnecting in ...` and collection resumes |
| 9 | Exit and persistence | After Ctrl+C, `Storage summary` counts > 0; `--export-csv` generates 5 CSV files |

We recommend treating items 2, 3 and 7 as the core pass criteria; for other failures, record the symptom and logs.

---

## 7. Information to include in a bug report

1. Operating system and version (e.g. Windows 11 23H2 / Ubuntu 24.04);
2. Python version, `python -m pip list | grep -i bleak` (use `findstr` on Windows);
3. Bluetooth adapter model (Device Manager → Bluetooth);
4. The first few lines of the startup log (`ECDH backend`, `Discovery target`, `BLE link established ... MTU`);
5. The complete `--log-level DEBUG` log (**always redact MACs and auth_key first**);
6. Which checklist step the failure occurred at, and whether it reproduces reliably.

> Log redaction: `sed -E 's/([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/XX:XX:XX:XX:XX:XX/g'`.
> Never submit `.env`, `data/` or capture files.
