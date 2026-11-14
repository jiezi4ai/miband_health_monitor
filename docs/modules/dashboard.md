**English** · [简体中文](dashboard.zh-CN.md)

# dashboard — Real-time dashboard and HTTP API

## Responsibilities

Provide a local web interface with **zero third-party dependencies** during a collection session:

- In-memory ring buffer + SSE real-time push;
- HTTP JSON API (snapshot/history/healthz);
- Single-page frontend (Canvas charts) assembled from local assets into a single-file HTML;
- Optional SQLite history provider: backfills already-persisted data when the page refreshes, instead of starting from an empty chart.

Source: [miband_monitor/dashboard/](../../miband_monitor/dashboard/)

## Module breakdown

| File | Contents |
|---|---|
| `constants.py` | Endpoint paths, SSE queue caps, default point sets, keepalive interval |
| `history.py` | `make_db_history_provider(db_path)`: `source=db` queries SQLite |
| `hub.py` | `TelemetryHub`: ring buffer, subscriber queues, `publish_*`, `snapshot`, `history` |
| `http.py` | Lightweight HTTP request parsing/response utilities |
| `page.py` | Composes `assets/` into a self-contained page |
| `server.py` | `DashboardServer`: asyncio HTTP server, routes, SSE |
| `assets/` | `dashboard.html`, `dashboard.css`, `dashboard.js` |

## Public API

| Name | Description |
|---|---|
| `TelemetryHub()` | `attach_loop`, `publish_heart_rate/steps/imu/spo2`, `snapshot`, `history`, `subscribe/unsubscribe`, `subscriber_count` |
| `DashboardServer(hub, host, port, history_provider=None)` | `start()`, `stop()`, `port`, `url` |
| `make_db_history_provider(db_path)` | Returns `(kind, limit) -> list[dict]` |
| Endpoints | `GET /`, `/api/snapshot`, `/api/history?kind=&limit=&source=db`, `/events` (SSE), `/healthz` |

## Data flow

```
cli.callbacks ──> hub.publish_*() ──> ring buffer ──> subscriber queues ──> /events SSE
                                            │
page load ──> /api/history?source=db ──> SQLite (thread pool, does not block the event loop)
         └─> /events first-frame snapshot (persisted points + live points merged and deduped by ts)
```

## Dependencies

- Standard library `asyncio`, `json`, `sqlite3`, `http`;
- `miband_monitor.config` (default host/port/buffer caps) and
  `miband_monitor.storage.readers` (`utc_iso` etc.);
- Imports no BLE: it only receives already-parsed samples, which makes it easy to test.

## Configuration and constants

| Item | Default | Description |
|---|---|---|
| `--web-port` / `WEB_PORT` | Off | `0` means a random free port |
| `--web-host` / `WEB_HOST` | `127.0.0.1` | Local only by default; `0.0.0.0` exposes it to the LAN |
| `DEFAULT_MAX_POINTS` | 7200 | In-memory points per metric |
| `DEFAULT_SNAPSHOT_POINTS` | 600 | Default number of snapshot/history entries |
| `DEFAULT_SSE_QUEUE_SIZE` | 512 | Slow-client drop threshold, never blocks BLE |
| `DEFAULT_SSE_KEEPALIVE_SECONDS` | 15 | SSE keepalive comment frame |

## Failure modes

| Situation | Behavior |
|---|---|
| Port in use | `start()` raises `OSError`, CLI logs an error and continues collecting without the dashboard |
| Slow client | Events are dropped when the queue is full, the connection stays up and BLE is not slowed down |
| Browser SSE disconnection | The browser reconnects automatically; the first-frame snapshot resynchronizes |
| SQLite missing/missing table/`--storage jsonl` | `source=db` silently degrades to an empty list, pure real-time view |
| Slow DB query | Goes through a thread pool (`asyncio.to_thread`), does not block the event loop |
| Page asset missing | `page.py` reports an error when assembly fails; a normal installation includes `assets/` |
| Unauthorized access | No authentication; bound to loopback by default, never expose it directly to the internet |

## Tests

- `tests/test_dashboard.py` (after the refactor `tests/dashboard/{test_hub,test_server,test_cli}.py`):
  hub ring buffer and subscriptions, HTTP API, SSE push, page routes and fallback page, SQLite history provider,
  CLI wiring.
- Hardware-link validation see [validation/linux-validation.md](../validation/linux-validation.md)
  (`/api/snapshot` and `/events` both carry real data).

## Related documentation

- [guides/usage.md](../guides/usage.md) (how to start the dashboard)
- [guides/data-formats.md](../guides/data-formats.md) (real-time/history time semantics)
- [modules/offline-dashboard.md](offline-dashboard.md) (differences from the offline version)
