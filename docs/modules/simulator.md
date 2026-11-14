**English** · [简体中文](simulator.zh-CN.md)

# simulator — In-memory simulated band

## Responsibilities

Impersonate a Mi Band 6 with pure in-memory objects when no Bluetooth hardware is available, so that `--demo` and integration tests can exercise the complete chain (authentication → real-time streams → history sync → persistence → export):

- Implements chunked frames, ECDH + AES-CBC authentication, heart-rate/steps/IMU/history notifications;
- Provides a fake bleak client and scanner that can be injected directly into `MiBand6Client`;
- Configurable real-world failures: authentication rejection, dropped auth chunks, disconnect after connecting.

Source: [miband_monitor/simulator/](../../miband_monitor/simulator/)

## Module breakdown

| File | Contents |
|---|---|
| `constants.py` | Fake MAC/name, RSSI, chunked headers and AUTH constants |
| `payloads.py` | Heart-rate/steps/IMU/SpO2/activity/sleep SpO2 packet builders |
| `devices.py` | `FakeDevice`, `FakeAdvertisement` |
| `auth.py` | `AuthMixin`: authentication state machine and responses |
| `history.py` | `HistoryMixin`: fetch start-date / chunks / completion / ACK |
| `streams.py` | `StreamMixin`: generation and stopping of the three real-time notification types |
| `band.py` | `SimulatedBand`: connection lifecycle + GATT dispatch (composing the mixins above) |
| `fake_bleak.py` | `FakeBleakClient`, `FakeBleakScanner` |
| `factory.py` | `simulated_factories`, `make_simulated_client` |

## Public API

`SimulatedBand(auth_key=..., fail_auth=..., drop_auth_seqs=..., disconnect_after=...)`,
`FakeDevice`, `FakeAdvertisement`, `FakeBleakClient`, `FakeBleakScanner`,
`simulated_factories(band)`, `make_simulated_client(band, ...)`;
the tests also use packet builders such as `_steps_packet`, `_imu_packet`, `_activity_payload`
(already re-exported by `__init__`).

## Data flow

```
cli.runner.run_demo
  └─ SimulatedBand(auth_key) ──> simulated_factories() ──> fake BleakClient/Scanner
                                    │
                     MiBand6Client(real authentication/parsing code)
                                    │
                 StreamCallbacks ──> storage / dashboard (same as real hardware)
```

## Dependencies

- `miband_monitor.ble` (the client only uses the real implementation), `history` (protocol constants/codecs are reused);
- Standard library `asyncio`, `struct`; AES uses `cryptography` (the same as the client);
- Not imported by production code; used only by the CLI demo and tests.

## Configuration and constants

- `DEMO_DEVICE_ID` (`C0:FF:EE:C0:FF:EE`), `DEMO_DEVICE_NAME`, `DEMO_AUTH_KEY_HEX`
  come from [config/demo.py](../../miband_monitor/config/demo.py);
- The simulated data is synthetic and contains no real health data;
- Triggered by `--demo [duration]` and `DEMO_MODE=1`.

## Failure modes

| Simulation option | Purpose |
|---|---|
| `fail_auth` | Verifies the authentication-failure path and reconnect/error reporting |
| `drop_auth_seqs` | Verifies chunk-gap detection and reassembly robustness |
| `disconnect_after` | Verifies disconnect detection and exponential-backoff reconnection |
| History fetch packet loss | Verifies the completion frame/ACK and retries |
| Unknown GATT operation | Raises an exception, helping expose the client's assumptions about characteristic capabilities |

## Tests

- `tests/test_simulated_band.py` (after the refactor `tests/simulator/{test_auth,test_streams,test_monitor}.py`):
  end-to-end authentication, the three data streams, disconnect-reconnect, persistence and export, fast failure on disconnect during authentication
  (reconnect cases adapt the timing window to the ECDH backend).
- CI directly runs `python miband_client.py --demo 2 --imu --sync-history 1 --sync-sleep-spo2 ...`
  and verifies the artifacts are non-empty.

## Related documentation

- [modules/ble.md](ble.md)
- [guides/testing.md](../guides/testing.md)
- [guides/usage.md](../guides/usage.md) (demo usage)
