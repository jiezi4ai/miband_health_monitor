**English** · [简体中文](installation.zh-CN.md)

# Installation

## 1. Requirements

| Item | Requirement |
|---|---|
| Operating system | Linux (BlueZ), Windows 10 19041+ (WinRT), macOS 12+ (CoreBluetooth) |
| Python | ≥ 3.10 (the code uses `X | Y` type annotations; the development environment is 3.13) |
| Bluetooth | Host built-in or USB Bluetooth adapter; WSL2 requires `usbipd` passthrough plus BlueZ |
| Compiler | **Optional**. On Linux, the native ECDH library is compiled automatically when `gcc`/`clang` is available; otherwise it falls back to pure Python |
| Dependencies | `bleak` installs the WinRT / pyobjc backend for each platform automatically; no manual handling needed |

Runtime dependencies ([requirements.txt](../../requirements.txt)):

- `bleak`: BLE scanning/connection;
- `cryptography`: AES-CBC;
- `python-dotenv`: reading `.env`;
- `loguru` / `pycryptodome` / `requests`: used only by `get_auth_key.py` / `fetch_by_token.py`;
- `pytest` / `pytest-asyncio`: tests.

## 2. Linux

```bash
# Debian/Ubuntu example
sudo apt-get install -y python3-venv python3-pip bluez
sudo systemctl enable --now bluetooth

cd miband_health_monitor
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

WSL2 has no Bluetooth stack by default (no `/sys/class/bluetooth`, no `bluetooth.service`),
so you must pass a USB adapter through into WSL, or run directly on native Linux.

Verify:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python miband_client.py --demo 2 --imu --output data/demo --export-csv
```

## 3. Windows 10/11

Install Python 3.10+ from [python.org](https://www.python.org/downloads/), and check
"Add python.exe to PATH" during installation.

```powershell
cd miband_health_monitor
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe miband_client.py --demo 2 --imu --output data\demo --export-csv
```

The command examples consistently use `.venv/bin/python`; on Windows replace it with `.venv\Scripts\python.exe`.
Windows does not need Visual Studio or gcc; `bleak` installs the WinRT dependencies automatically.

## 4. macOS

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scan_ble.py          # requests Bluetooth permission on first run
```

macOS does not expose MAC addresses: scan results are CoreBluetooth UUIDs; put one into `DEVICE_ID`,
or use `DEVICE_NAME` matching instead (see [configuration.md](configuration.md)).
In System Settings → Privacy & Security → Bluetooth, you must allow the terminal/IDE.

## 5. Native ECDH library (optional)

The default is `auto`: it first loads the library for the current platform under the project root, then
tries to compile it on the spot, and finally falls back to pure Python.
The two backends have been cross-checked byte for byte and are functionally equivalent; native is just faster.

```bash
# Linux
gcc -O3 -shared -fPIC ecdh.c -o libecdh.so
# macOS
clang -O3 -dynamiclib ecdh.c -o libecdh.dylib
# Windows (MinGW-w64)
gcc -O3 -shared -DECDH_BUILD_DLL ecdh.c -o libecdh.dll
# Windows (MSVC developer command prompt)
cl /nologo /O2 /LD /DECDH_BUILD_DLL ecdh.c /Fe:libecdh.dll
```

You can also point to any location with `MIBAND_ECDH_LIB=C:\path\to\libecdh.dll`.
The startup log shows `ECDH backend: native` or `python`; the latter does not affect functionality.

## 6. Post-install checks

```bash
# 1) Dependencies and tests
.venv/bin/python -m pytest -q

# 2) Full hardware-free path
.venv/bin/python miband_client.py --demo 2 --imu --sync-history 1 \
    --output data/demo --storage both --export-csv

# 3) Environment self-check (config/ECDH/output dir/BlueZ, read-only)
.venv/bin/python miband_client.py --doctor
```

The demo should produce `data/demo/*.jsonl`, `mi_band.db` and `csv/`; if these steps pass,
Python, dependencies, the ECDH fallback, storage and the dashboard path are all working, leaving only
the real BLE link.

## 7. Next steps

- Configure `.env`: [configuration.md](configuration.md)
- Real-device collection and dashboard: [usage.md](usage.md)
- Platform differences and pairing: [cross-platform.md](cross-platform.md)
- Troubleshooting: [faq.md](faq.md)
