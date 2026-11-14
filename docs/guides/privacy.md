**English** · [简体中文](privacy.zh-CN.md)

# Privacy and Data Security

This project produces and writes a large amount of personal data. The repository should only contain code and redacted documentation; real device identifiers, credentials and health data always stay on the local machine and are ignored by git.

## 1. Data classification

| Content | Location | Sensitivity | git status |
|---|---|---|---|
| Device MAC / auth_key | `.env` | **High** (pairing credentials) | Ignored, mode 0600 |
| Live/history health data | `data/*.jsonl`, `data/mi_band.db`, `data/csv/` | **High** (personal health data) | Ignored |
| Real-device validation material | `validation/` (run.log, payloads, btmon) | **High** (MAC / data / over-the-air packets) | Ignored |
| Debug logs and captures | `*.log`, `*.btsnoop`, `*.pcap` | **High** | Ignored |
| Exported HTML dashboard | `dashboard_history.html` etc. | **High** (embedded health data) | Manage it yourself |
| Code and docs | repository root, `docs/` | No (examples are placeholders) | Tracked |

## 2. Credentials and .env

- `.env` is ignored by [.gitignore](../../.gitignore); on startup `secure_env_file()`
  tries to tighten it to **0600**;
- `AUTH_KEY` is equivalent to the band's Bluetooth pairing credential; treat it as a password: do not paste it into issues, chat messages or screenshots;
- `get_auth_key.py` / `fetch_by_token.py` write the result only to the local `.env`; the terminal shows only a masked status;
- On multi-user Linux hosts, confirm that `ls -l .env` shows `-rw-------`; `--doctor` checks the permissions;
- Do not put `.env` into Docker images, public directories of backup scripts, or shared cloud-drive directories.

## 3. Permission rules

| Path | POSIX mode | Notes |
|---|---|---|
| Output directory `data/` | 0700 | Set by `secure_directory` |
| JSONL / SQLite / CSV / HTML | 0600 | Set by `secure_file` / `secure_path` |
| `.env` | 0600 | Tightened on each startup attempt |
| `validation/` (forensics) | Your responsibility | Already ignored, but 0700 is still recommended |

Windows uses user ACLs; the `0600` semantics do not apply, but do not put the data directory in a shared location.

## 4. What is never committed

[.gitignore](../../.gitignore) covers, but is not limited to:

- `.env`, `.env.*` (with `.env.example` kept), `secrets/`, `*.pem/*.key/*.pfx`;
- `data/`, `exports/`, `*.jsonl`, `*.csv`, `*.db*`, `*.sqlite*`;
- `validation/`, `payloads/`, `captures/`, `*.btsnoop`, `*.pcap`, `*.log`;
- Locally built native libraries (`libecdh.dll/dylib`; on Linux `libecdh.so` is intentionally tracked).

Self-check before committing:

```bash
.venv/bin/python tools/check_privacy.py     # same as CI: real MACs/keys/paths
git status --short                          # confirm no data/, .env, validation/
```

## 5. External feedback and sharing

Before sharing logs, payloads or dashboard screenshots:

1. Redact MACs in logs:
   ```bash
   sed -E 's/([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/XX:XX:XX:XX:XX:XX/g' run.log > run.redacted.log
   ```
2. Confirm there is no auth_key / token:
   ```bash
   grep -inE "auth_key|AUTH_KEY|app_token|password" run.log || echo "clean"
   ```
3. DEBUG logs contain ECDH salt values and public keys (not secret credentials, but you may remove the
   `Received random challenge salt` / `Received band ECDH public key` lines as needed);
4. Post only the necessary fragments of health data; never package or screenshot `.env`, `data/` or capture files;
5. Use placeholders for device addresses in documentation (e.g. `C0:FF:EE:C0:FF:EE`) and placeholder dates.

For a detailed validation report template, see [validation/history-hardware.md](../validation/history-hardware.md) §9–§10.

## 6. Cleaning up local data

```bash
# Caution: the following commands permanently delete local health data; back up anything you need first
rm -f data/*.jsonl data/mi_band.db data/mi_band.db-wal data/mi_band.db-shm
rm -rf data/csv data/demo
rm -rf validation payloads captures          # forensic material
rm -f *.log *.btsnoop *.pcap
```

Note:

- Deleting the database is irreversible (the band keeps only about 40 hours of history);
- Offline dashboard HTML and CSV exports may have been copied elsewhere and must be cleaned up separately;
- Unpair on Linux: `bluetoothctl remove <MAC>` (when needed).

## 7. Third parties and license

- `huami_token/` (MIT), `vendor/tiny_ecdh/` (MIT), `ecdh.c/ecdh.h` and
  `libecdh.so` are third-party/upstream code and are kept as is;
- For the third-party code list and exemption reasons, see [architecture.md](../architecture.md#6-third-party-and-compatibility-exemptions);
- The project as a whole is released under the MIT License, see [LICENSE](../../LICENSE).

## 8. Security boundaries

- The live dashboard/HTTP API has **no authentication** and binds to `127.0.0.1` by default; do not expose it directly to the public internet;
- The BLE authentication key is used only for the local link to the band; cloud calls happen only when you actively run
  `get_auth_key.py` / `fetch_by_token.py`;
- This project does not upload data; all analysis (sleep, reports, dashboards) happens locally.
