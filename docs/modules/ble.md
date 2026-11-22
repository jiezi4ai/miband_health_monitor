**English** · [简体中文](ble.zh-CN.md)

# ble — BLE client and protocol

## Responsibilities

Implement the complete BLE session with the Mi Band 6:

- Device discovery (MAC / CoreBluetooth UUID / advertising-name substring) and the BlueZ direct-connect fast path;
- ECDH + AES-CBC challenge-response over Chunked Transfer authentication (0x0016 write / 0x0017 notify),
  with sequence validation, duplicate-packet handling, out-of-range protection and a reassembly cap;
- Three real-time notification types: standard heart rate `0x2A37`, real-time steps `0x0007`, raw IMU `0x0001/0x0002`;
- Heart-rate keepalive, disconnect events, MTU negotiation and the state resets needed for reconnection.

Source: [miband_monitor/ble/](../../miband_monitor/ble/)

## Module breakdown

| File | Contents |
|---|---|
| `protocol.py` | UUIDs, `CHUNKED_*` header lengths, AUTH sizes, raw sensor commands and type codes |
| `parsers.py` | `parse_heart_rate`, `parse_realtime_steps`, `parse_raw_sensor_data` |
| `identity.py` | `normalize_auth_key`, `is_placeholder_device_id`, `normalize_device_identifier`, `device_matches`, `_env_device_id`, `_secure_env_file` |
| `crypto.py` | `_aes_cbc_encrypt`, `encrypt_challenge` |
| `chunked.py` | `write_chunked_value`, `_write_with_in_progress_retry` (global write lock) |
| `backends.py` | bleak client/scanner factory selection |
| `discovery.py` | scanning, heartbeat, matching by name/MAC/UUID |
| `link.py` | connection budget, transient-error retries, BlueZ standby path |
| `mtu.py` | `_resolve_mtu` / `_apply_mtu` / `_settle_after_link` |
| `listener.py` | chunked notification subscription and dispatch |
| `auth_state.py` / `auth_connect.py` / `auth_handshake.py` | authentication events, connection orchestration, challenge-response state machine |
| `notifications.py` / `streams.py` | heart-rate/steps/IMU notification handling and stream start/stop |
| `time_sync.py` | `TimeSyncMixin`: CTS `0x2A2B` drift read / clock write (Mi Band 11-byte variant, never aborts) |
| `client.py` | `MiBand6Client` composes the mixins above while keeping the public class identity and attributes |

## Public API

- Constants: all `UUID_*` (`0xfee0` service, heart-rate service, `0x0001/2/7/0x0016/17`),
  `CHUNKED_*`, `AUTH_*`, `RAW_SENSOR_*`, `CMD_RAW_SENSOR_*`;
- Parsing: `parse_heart_rate(data) -> int`, `parse_realtime_steps(data) -> dict`,
  `parse_raw_sensor_data(data) -> dict`;
- Auth/utilities: `encrypt_challenge(auth_key, challenge_bytes)`, `normalize_auth_key(hex)`,
  `write_chunked_value(client, char_uuid, data, mtu)`, `device_matches(...)`,
  `_env_device_id()`, `_secure_env_file()`;
- Data type: `StreamCallbacks` (six callbacks: heart_rate/steps/imu/history_*);
- Client: `MiBand6Client(device_id, auth_key_hex, *, device_name, mtu, client_factory,
  scanner_factory, scan_timeout, connect_timeout, auth_timeout, direct_connect)`,
  with main methods `connect_and_authenticate()`, `start_heart_rate_stream()`,
  `start_steps_stream()`, `start_raw_sensor_stream()`,
  `wait_until_disconnected()`, `disconnect()`.

## Data flow

```
connect_and_authenticate()
  ├─ (Linux) paired_device() direct connect → otherwise scan (up to scan_timeout)
  ├─ _apply_mtu() / _settle_after_link() (Linux waits for SMP settlement)
  ├─ _start_chunked_listener() (subscribe to 0x0017)
  ├─ auth: public key → 16B salt + 48B public key → shared[8:24]^auth_key → AES response
  └─ authenticated=True
Then the runner in order: start_raw_sensor_stream (optional) → start_heart_rate_stream()
              → start_steps_stream()
Notification callback ──> StreamCallbacks ──> cli.callbacks ──> storage / dashboard
```

> Order matters: on real hardware, start the raw sensor stream before the heart-rate stream; reversing them
> silently starves the standard heart-rate characteristic (measured: 0 notifications in 20 s vs. normally about 1 per second).

## Dependencies

- `miband_monitor.bluez` (Linux compatibility), `crypto` (ECDH), `config` (defaults and redaction);
- Third-party `bleak` + `cryptography`;
- Does not depend on `storage/dashboard`: all output is handed to the caller through callbacks.

## Configuration and constants

| Item | Default | Description |
|---|---|---|
| `BLE_MTU` / `--mtu` | Automatic | Manually override the ATT MTU (23–517); do not set it without evidence |
| `SCAN_TIMEOUT` / `--scan-timeout` | 90 s | Waits for isolated advertising pulses, 120 recommended |
| `CONNECT_TIMEOUT` / `--connect-timeout` | 75 s | On Linux, cover at least the 70 s advertising cycle |
| `--no-direct-connect` | Direct connect on | Force the scanning path on Linux for troubleshooting |
| `CHUNKED_*` | — | 11B header for the first chunk / 5B for subsequent ones, payload split by MTU |
| `AUTH_STEP1_*` | 16+48 | Random salt + public key; reassembly cap `MAX_REASSEMBLY_BYTES=1024` |
| `RAW_SENSOR_ACCEL_LSB_PER_G` | 4096 | int16 acceleration conversion |

## Failure modes

| Situation | Behavior |
|---|---|
| Scan timeout | Prints the discovery target and the "one pulse every 40–60 s" hint, fails the session and reconnects with backoff |
| Auth chunk gap/duplicate/out-of-range | Records the sequence error and fails; retries on the next session, never splices misaligned data |
| Auth timeout | Reconnects after `auth_timeout` (default 30 s); DEBUG logs keep frame summaries (without keys) |
| Heartbeat keepalive write failure | Treated as link loss, triggers reconnection |
| GATT `InProgress` | `_write_with_in_progress_retry` serializes and retries |
| Device name/MAC mismatch | Explicit "target found" log; on macOS use the UUID or `DEVICE_NAME` |
| No IMU data | Some firmware requires a specific motion mode; `--imu` is experimental |
| Callback raises | Logged and continued inside notification handling, does not block the event loop |

## Tests

- `tests/test_chunked_protocol.py`: chunked frame format, MTU negotiation and passthrough, auth reassembly (gap/duplicate/out-of-range/invalid length);
- `tests/test_device_matching.py`: MAC/UUID/name matching, placeholders and precedence, CLI arguments;
- `tests/test_simulated_band.py`: end-to-end authentication, the three data streams, reconnection, fast failure on disconnect during auth against the simulated band;
- `tests/test_ecdh_backends.py`: byte-level agreement of the ECDH backends used for authentication;
- After the refactor, tests are organized as `tests/simulator/{test_auth,test_streams,test_monitor}.py`.

## Related documentation

- [modules/crypto.md](crypto.md), [modules/bluez.md](bluez.md), [modules/simulator.md](simulator.md)
- [modules/cli.md](cli.md) (session supervision and reconnect policy)
- [guides/cross-platform.md](../guides/cross-platform.md), [guides/data-formats.md](../guides/data-formats.md)
