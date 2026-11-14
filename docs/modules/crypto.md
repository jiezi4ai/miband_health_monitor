**English** · [简体中文](crypto.zh-CN.md)

# crypto — Dual ECDH backends

## Responsibilities

Provide NIST B-163 (sect163r2) curve operations for the band's Chunked ECDH authentication. Two interchangeable implementations:

- **native**: `libecdh.so` / `libecdh.dll` / `libecdh.dylib` compiled from `ecdh.c`, called through `ctypes`;
- **pure Python**: `vendor/tiny_ecdh/` (MIT) pure-Python implementation, usable on any platform.

The wire format must be identical on both ends: 24-byte little-endian private key, 48-byte little-endian public key
(`x||y`, 24 bytes each), 48-byte little-endian shared point. The two backends were cross-checked byte-for-byte on Linux.

Source: [miband_monitor/crypto/](../../miband_monitor/crypto/)

## Module breakdown

| File | Contents |
|---|---|
| `constants.py` | Candidate library file names, compilation flags, curve/byte-length constants |
| `native.py` | `load_native_library`, `NativeEcdhBackend`, compilation fallback |
| `pure_python.py` | `PurePythonEcdhBackend` wrapping `vendor/tiny_ecdh/` |
| `facade.py` | Backend selection and public functions: `select_backend`, `backend_name`, `generate_ecdh_keys`, `compute_shared_secret` |

## Public API

| Name | Description |
|---|---|
| `native_library_candidates() -> list[Path]` | `MIBAND_ECDH_LIB`, platform-named libraries under the project root, build directory |
| `compiled_library_path() -> Path` | Output location of an on-the-spot compilation |
| `load_native_library() -> CDLL | None` | Loads an existing library; returns None on failure (attempts a gcc/clang build when necessary) |
| `NativeEcdhBackend` / `PurePythonEcdhBackend` | Unified interface `generate_keys`, `shared_secret` |
| `select_backend(requested=None)` | `auto` / `native` / `python` selection |
| `backend_name() -> str` | `native` or `python`, printed in startup logs |
| `generate_ecdh_keys() -> (private, public)` | 48/24-byte wire format |
| `compute_shared_secret(private, peer_public) -> bytes` | 48-byte shared point |

## Data flow

```
ble.auth_handshake
   │ generate_ecdh_keys() ──> send 48B public key
   │ receive band public key + 16B salt
   └ compute_shared_secret(priv, peer) ──> shared[8:24] XOR auth_key ──> AES session key
                                  │
                     crypto.facade selects native / python
```

## Dependencies

- `miband_monitor.config` (`MIBAND_ECDH_BACKEND`, `MIBAND_ECDH_LIB`, paths).
- Standard library `ctypes`, `subprocess`, `pathlib`; the native backend depends on a system C compiler (optional).
- The pure-Python backend depends on the third-party [vendor/tiny_ecdh/](../../vendor/tiny_ecdh/).

## Configuration and constants

- `MIBAND_ECDH_BACKEND`: `auto` (default) / `native` / `python`;
- `MIBAND_ECDH_LIB`: explicitly select a library file, useful for self-compiled Windows DLLs;
- Library candidate order: explicit path → platform library under the repository root → on-the-spot compilation → pure-Python fallback;
- Compilation commands: Linux `gcc -O3 -shared -fPIC`; macOS `clang -O3 -dynamiclib`; Windows MinGW/MSVC see
  [guides/cross-platform.md](../guides/cross-platform.md).

## Failure modes

| Situation | Behavior |
|---|---|
| No `libecdh.*` | Automatically falls back to pure Python, logs `ECDH backend: python` |
| `MIBAND_ECDH_BACKEND=native` but the library is unavailable | Startup error, requiring installation/compilation or switching back to auto/python |
| Library ABI/function-name mismatch | `load_native_library` refuses to load and falls back (auto mode) |
| Compilation failure | Logs an stderr summary, falls back to pure Python |
| Invalid public-key length/point | Raises `ValueError`, authentication fails and reconnects, never silently produces a wrong key |
| Library path contains the user directory | `config.privacy.SENSITIVE_ENV_KEYS` treats it as sensitive and redacts it in logs |

## Tests

- `tests/test_ecdh_backends.py`: byte-for-byte cross-check of the two backends, backend selection, library file names per platform,
  and the error path when native is forced. Linux CI covers both native and `MIBAND_ECDH_BACKEND=python`.
- `tests/test_miband.py` (after the refactor `tests/test_crypto_parsers.py`): AES test vectors and key formats.

## Related documentation

- [modules/ble.md](ble.md) (how the authentication state machine uses ECDH)
- [guides/cross-platform.md](../guides/cross-platform.md)
- [architecture.md](../architecture.md#6-third-party-and-compatibility-exemptions)
