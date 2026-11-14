**English** · [简体中文](config.zh-CN.md)

# config — Configuration, paths and privacy constants

## Responsibilities

Centralize every "changes with the environment" value so that defaults are not scattered across the domain modules:

- Defaults/timeouts/ports/MTU bounds/reconnect parameters;
- Reading `.env` and process environment variables, bool/int/float parsing;
- Project paths (package root, repository root, default data/db/csv/.env locations);
- Masking/redaction of phone numbers/addresses/keys and log scrubbing;
- File and directory permissions (0600/0700);
- Physiological and physical constants (valid heart-rate/SpO2 ranges, standard gravity);
- Fake device identity used by demo mode.

Source: [miband_monitor/config/](../../miband_monitor/config/)

## Module breakdown

| File | Contents |
|---|---|
| [defaults.py](../../miband_monitor/config/defaults.py) | Environment-variable name constants, default timeouts, reconnect backoff, MTU bounds, dashboard defaults |
| [env.py](../../miband_monitor/config/env.py) | `load_env`, `secure_env_file`, `env_str/float/int/optional_int/flag`, `read_env_file`, `update_env_file` |
| [paths.py](../../miband_monitor/config/paths.py) | `PACKAGE_ROOT`, `PROJECT_ROOT`, `default_data_dir`, `default_db_path`, `default_csv_dir`, `default_env_path`, ECDH source/build directories |
| [privacy.py](../../miband_monitor/config/privacy.py) | `SENSITIVE_ENV_KEYS`, `mask_secret`, `mask_address`, `redact_log_value` |
| [security.py](../../miband_monitor/config/security.py) | `DIRECTORY_MODE=0o700`, `FILE_MODE=0o600`, `secure_path`, `secure_directory`, `secure_file` |
| [health.py](../../miband_monitor/config/health.py) | `HR_UNAVAILABLE=255`, `HR_MIN/HR_MAX`, `SPO2_MIN/SPO2_MAX`, `STANDARD_GRAVITY` |
| [demo.py](../../miband_monitor/config/demo.py) | `DEMO_DEVICE_ID`, `DEMO_DEVICE_NAME`, `DEMO_AUTH_KEY_HEX/BYTES` |

## Public API

The package-level `__init__` re-exports the names above (`__all__` contains every non-underscore global name), so
`from miband_monitor.config import DEFAULT_SCAN_TIMEOUT` is equivalent to
`from miband_monitor.config.defaults import ...`. Common entries:

| Name | Type | Description |
|---|---|---|
| `DEFAULT_SCAN_TIMEOUT` | float | 90 s, waits for the first advertising pulse |
| `DEFAULT_CONNECT_TIMEOUT` | float | 75 s; Linux raises it according to the 70 s advertising cycle |
| `DEFAULT_DIRECT_CONNECT_TIMEOUT` | float | 10 s, budget for the BlueZ direct-connect fast path |
| `DEFAULT_AUTH_TIMEOUT` | float | 30 s, total budget for chunked authentication |
| `DEFAULT_MTU_MIN/MAX` | int | 23 / 517 |
| `DEFAULT_WEB_PORT/HOST` | int/str | port disabled by default, address `127.0.0.1` |
| `DEFAULT_MAX_POINTS/SNAPSHOT_POINTS` | int | in-memory series caps for the dashboard |
| `env_flag(name, default)` | func | recognizes `1/true/yes/on` and `0/false/no/off` |
| `secure_env_file()` | func | tightens the working-directory `.env` to 0600 (failures are only logged, never fatal) |
| `mask_address()` / `mask_secret()` | func | redacts logs and terminal output |

## Data flow

```
process env / .env ──load_env()──> os.environ ──env_*()──> parameters of each module
                      └──secure_env_file()──> chmod 0600
defaults.py ──> argparse defaults in cli/args.py
           └─> timeouts and caps for bluez/ble/history/dashboard
paths.py   ──> storage db/jsonl/csv paths, auth .env path, crypto build dir
privacy.py ──> logs, doctor output, auth terminal output
```

## Dependencies

- Standard library only (`os`, `pathlib`, `typing`); imports no other `miband_monitor` domain package.
- `env.py` optionally imports `python-dotenv`; when missing it degrades to the process environment only, without error.

## Configuration and constants

The single source for environment-variable names is [defaults.py](../../miband_monitor/config/defaults.py):
`DEVICE_ID`, `DEVICE_MAC`, `DEVICE_NAME`, `AUTH_KEY`, `BLE_MTU`, `OUTPUT_DIR`,
`STORAGE_BACKEND`, `SCAN_TIMEOUT`, `CONNECT_TIMEOUT`, `LOG_LEVEL`, `DEMO_MODE`,
`WEB_PORT`, `WEB_HOST`, `HISTORY_DAYS`, `MIBAND_ECDH_BACKEND`, `MIBAND_ECDH_LIB`,
`MIBAND_BLUEZ_TRUST`, `MIBAND_BLUEZ_AGENT`, `MIBAND_BLUEZ_DUPLICATE_DATA`,
`MIBAND_SMP_SETTLE_DELAY`. For full meanings and defaults see
[guides/configuration.md](../guides/configuration.md).

## Failure modes

| Situation | Behavior |
|---|---|
| `.env` does not exist | `load_env` silently skips it and uses only the process environment and defaults |
| `.env` permissions too open | `secure_env_file` attempts chmod 0600; without permission it logs a warning and does not interrupt startup |
| Environment variable is not a valid number | `env_int/env_float` logs a warning and falls back to the default |
| Unknown boolean spelling | Treated as the default, no exception raised |
| Output directory cannot be created | Caught and reported by `storage`; config only supplies the path |
| Package moved/imported as a zip | `PACKAGE_ROOT` is based on `__file__`; a normal unpacked installation is recommended |

## Tests

- Environment-variable parsing, `DEVICE_MAC` compatibility and placeholders: `tests/test_device_matching.py`
  (after the refactor these live in split directories such as `tests/bluez/`, `tests/history/`).
- Privacy/permission assertions appear in `tests/test_storage.py` (`secure_path`) and
  `tests/test_bluez_support.py` (`.env` handling).
- CI additionally runs `tools/check_privacy.py` to ensure the repository contains no real addresses/keys/paths.

## Related documentation

- [guides/configuration.md](../guides/configuration.md)
- [guides/privacy.md](../guides/privacy.md)
- [architecture.md](../architecture.md)
