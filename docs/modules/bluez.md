**English** · [简体中文](bluez.zh-CN.md)

# bluez — Linux / BlueZ compatibility layer

## Responsibilities

Under Linux, BlueZ differs from WinRT/CoreBluetooth in three key ways; this module wraps those differences into testable helpers:

1. **D-Bus device objects are transient**: an unpaired/untrusted device disappears from the object tree after disconnect,
   and subsequent GATT writes fail with `UnknownObject: Method "WriteValue" ... doesn't exist`; an unbound band also
   disconnects after about 40 s.
2. **bleak rescans before connecting with a MAC**: a paired device can be connected directly through the BlueZ cached
   object without waiting for an advertisement.
3. **The ATT MTU is not acquired automatically**: without calling `_acquire_mtu()`, `mtu_size` is always 23.

All helpers degrade gracefully to no-ops on non-BlueZ platforms, so Windows/macOS can safely import them.

Source: [miband_monitor/bluez/](../../miband_monitor/bluez/)

## Module breakdown

| File | Contents |
|---|---|
| `constants.py` | Service/interface/object paths, default adapter, SMP settlement and timeouts |
| `platform.py` | `is_bluez_platform`, address normalization / MAC detection |
| `dbus.py` | `_managed_objects` and basic D-Bus calls |
| `devices.py` | `list_known_devices`, `find_device`, `make_ble_device`, `connected_device`, `paired_device`, `active_cached_device` |
| `admin.py` | `set_adapter_pairable`, `set_device_trusted`, `disconnect_device`, `remove_device` |
| `link.py` | `link_standby_budget`, `wait_for_bluez_link` (standby Connect loop) |
| `pairing.py` | `BlueZPairingAgent` (`NoInputNoOutput` in-process agent) |
| `mtu.py` | `try_acquire_mtu` |
| `scanner.py` | `scanner_kwargs` (`DuplicateData=False` etc.) |
| `errors.py` | Transient-error detection (`le-connection-abort-by-local`, `InProgress`) and `describe_ble_error` |

## Public API

`link_standby_budget(connect_timeout)`, `is_bluez_platform()`, `normalize_address()`,
`looks_like_mac()`, `device_path_for_address()`, `list_known_devices()`,
`find_device(address)`, `list_adapters()`, `make_ble_device(info)`,
`connected_device(address)`, `paired_device(address)`, `active_cached_device(...)`,
`is_transient_connect_error()`, `is_in_progress_error()`, `scanner_kwargs()`,
`set_adapter_pairable()`, `set_device_trusted()`, `disconnect_device()`, `remove_device()`,
`wait_for_bluez_link()`, `BlueZPairingAgent`, `try_acquire_mtu(client)`,
`describe_ble_error(exc)`.

## Data flow

```
ble.discovery
  ├─ paired/cached? ──paired_device()/active_cached_device()──> make_ble_device()
  │                                      │
  └─ no ── scanner_kwargs() + bleak scan ─┘
                                          v
                              wait_for_bluez_link() standby Device1.Connect
                                          │ success
                                          v
                              try_acquire_mtu() ──> MTU 247 (measured)
```

Pairing: when `MIBAND_BLUEZ_AGENT=1`, `BlueZPairingAgent` registers `org.bluez.Agent1` on the system D-Bus and
automatically accepts SMP requests from the target band; otherwise the user runs `bluetoothctl pair`.

## Dependencies

- Runtime: Linux + BlueZ + `dbus-fast` (installed with `bleak`); everything degrades on non-Linux.
- In-project: depends only on `miband_monitor.config` and does not import `ble` (to avoid a cycle).
- `ble` imports this package through its public functions; `diagnostics` uses `list_adapters/find_device` for self-checks.

## Configuration and constants

| Variable | Default | Description |
|---|---|---|
| `MIBAND_BLUEZ_TRUST` | `1` | Set the device to `Trusted` before connecting, buying GATT cache and kernel auto-reconnect |
| `MIBAND_BLUEZ_AGENT` | `0` | `1` registers the in-process pairing agent |
| `MIBAND_BLUEZ_DUPLICATE_DATA` | `0` | `True` restarts extended scanning every ~5 s on BT 5/6, easily killing the adapter |
| `MIBAND_SMP_SETTLE_DELAY` | `1.5` | Seconds to wait for SMP/profile discovery to settle after `ServicesResolved` |

Key constants: `BAND_PULSE_PERIOD ≈ 70 s` (lower bound of the standby connect budget), `DBUS_TIMEOUT`,
`AGENT_MANAGER_*`.

## Failure modes

| Symptom | Cause | Handling |
|---|---|---|
| `failed to discover services, device disconnected` (about 9–10 s) | GATT cache not complete; the band's unauthenticated-connection watchdog expires (needs ~150 handles enumerated) | Automatic retry; for the first pairing without a cache use `MIBAND_BLUEZ_AGENT=1` and keep the screen on at close range if possible |
| `dropped-unresolved` (drops after about 5 s, `ServicesResolved=False`) | BlueZ stored a stale `LTK`, causing an over-the-air `LE Start Encryption` timeout (`0x08`) | `wait_for_bluez_link` stops early after 2 drops; a paired device automatically triggers `remove_device()` + pairing-agent self-healing |
| `UnknownObject ... doesn't exist` | BlueZ removes the device object when unpaired/after disconnect | `describe_ble_error` translates it into an actionable hint; reconnect |
| `le-connection-abort-by-local` | The kernel's 40 s initiation cycle saw no pulse | `wait_for_bluez_link` re-arms in place after about 150 ms and does **not** actively Disconnect |
| `-112 / host is down`, zero advertisements | Adapter RF is wedged on BARROT `33fa:0012` and similar | USB reset only: `usbreset` or unplug/replug + `systemctl restart bluetooth`; a D-Bus power cycle does not help |
| `No agent available for request type 2` | The band initiates SMP but the system has no agent | `MIBAND_BLUEZ_AGENT=1` or manual pairing with `bluetoothctl` |
| MTU always 23 | `_acquire_mtu()` was not called | The current version negotiates proactively; if it still occurs, inspect the `try_acquire_mtu` logs |

## Tests

- `tests/bluez/` (`test_platform.py`, `test_devices.py`, `test_link.py`, `test_pairing.py`,
  `test_errors.py`, `test_client_integration.py`, `test_doctor.py`, `test_standby_backoff.py`,
  `test_self_healing.py`): D-Bus property parsing, addresses/object paths, standby budget and grace period, agent lifecycle,
  residual-connection and stale-LTK self-healing, error translation and client integration paths.
- Hardware evidence: [validation/linux-validation.md](../validation/linux-validation.md),
  [validation/linux-ble-connect-findings.md](../validation/linux-ble-connect-findings.md),
  [validation/linux-ble-test-report.md](../validation/linux-ble-test-report.md).

## Related documentation

- [guides/cross-platform.md](../guides/cross-platform.md)
- [modules/ble.md](ble.md) (who calls these helpers)
- [modules/diagnostics.md](diagnostics.md) (how `--doctor` shows adapter state)
