**English** · [简体中文](auth.zh-CN.md)

# auth — Account auth_key retrieval

## Responsibilities

Wrap "how to obtain `AUTH_KEY`" into two interactive flows and write it back safely to the local `.env`:

- `get_auth_key.py`: sign in with a Xiaomi account or a Zepp/Amazfit account → list bound devices → retrieve the key;
- `fetch_by_token.py`: when a browser login session already exists, look up devices directly with `user_id` + `app_token`.

The cloud protocol implementation lives in the third-party [huami_token/](../../huami_token/) (MIT); this package only contains the interactive flows, endpoint constants and secure file-writing logic.

Source: [miband_monitor/auth/](../../miband_monitor/auth/)

## Module breakdown

| File | Contents |
|---|---|
| `constants.py` | `.env` path, target device (read from the environment, never hard-coded), Zepp Web endpoints/headers/timeouts |
| `extractor.py` | Xiaomi/Zepp account interactive flow; only reports "found and written", never prints the full key |
| `token.py` | `fetch_devices(user_id, app_token)`, `main`; tries endpoints by region in order |

## Public API

`ENV_PATH`, `TARGET_MAC` (`DEVICE_ID` takes precedence, compatible with `DEVICE_MAC`), `run_extractor() -> int`,
`fetch_devices(user_id, app_token) -> bool`, `token_main() -> int`.

## Data flow

```
User enters account/password (getpass, never written to disk) or user_id/app_token
        │
        ├─ huami_token client ──> cloud API ──> device list + auth_key
        └─ config.env.update_env_file() ──> .env (chmod 0600; only writes keys such as AUTH_KEY)
The terminal only prints the masked device address/key status
```

## Dependencies

- Third-party `huami_token`, `requests`, `loguru`, `pycryptodome` (see requirements.txt);
- `miband_monitor.config` (paths, `.env` writing, redaction);
- Does not depend on BLE or storage.

## Configuration and constants

- Output keys: `DEVICE_ID`/`DEVICE_MAC` and `AUTH_KEY`, written to the project-root `.env`;
- `TARGET_MAC` is read from the environment; the repository contains no real MAC;
- Zepp Web endpoints are tried in the order CN / CN2 / Global / US3, with a 10 s timeout;
- The account password is read through `getpass` and is not written to shell history or logs.

## Failure modes

| Situation | Behavior |
|---|---|
| Wrong account/password or CAPTCHA required | Prints the server error, returns non-zero, does not write `.env` |
| No device under the account | Explicit notice, does not write the key |
| `app_token` expired | Prompts to obtain a new one from the browser |
| Network unreachable | Catches request exceptions and gives endpoint/network hints |
| `.env` not writable | Reports an error; never silently drops the key |
| Terminal does not support `getpass` | Reports an error and never echoes the password to the screen |

## Tests

- The cloud API flow is by default **not run in CI** (it needs a real account); verify it offline by following the steps in
  [guides/usage.md](../guides/usage.md).
- `tests/test_device_matching.py` covers `DEVICE_ID`/`DEVICE_MAC` precedence and placeholder handling
  (it shares config.env with the write-back logic).
- Privacy constraints are checked in CI by `tools/check_privacy.py` (the repository must not contain tokens/real MACs).

## Related documentation

- [guides/configuration.md](../guides/configuration.md) (three ways to obtain auth_key)
- [guides/privacy.md](../guides/privacy.md)
- [modules/config.md](config.md)
