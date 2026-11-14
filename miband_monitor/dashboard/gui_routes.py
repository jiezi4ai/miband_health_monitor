"""HTTP route handlers for the interactive GUI control plane (/api/gui/*)."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from typing import Any, Dict
from urllib.parse import urlparse

from .http import read_json_body, send_json

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _is_trusted_origin(headers: Dict[str, str]) -> bool:
    """Reject cross-origin browser POSTs to protect local control endpoints."""
    origin = headers.get("origin", "").strip()
    if not origin:
        return True
    parsed = urlparse(origin)
    origin_host = (parsed.hostname or "").lower()
    host_header = headers.get("host", "").split(":", 1)[0].strip("[]").lower()
    return origin_host in _LOCAL_HOSTS or (bool(host_header) and origin_host == host_header)


async def handle_gui_request(
    controller: Any,
    method: str,
    path: str,
    headers: Dict[str, str],
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Dispatch /api/gui/* requests against a GuiSessionController instance."""
    if controller is None:
        await send_json(
            writer,
            HTTPStatus.NOT_IMPLEMENTED,
            {"error": "GUI controller is not enabled on this server (start via gui.py or --gui)."},
        )
        return

    try:
        if method == "GET" and path == "/api/gui/state":
            await send_json(writer, HTTPStatus.OK, controller.snapshot())
            return

        if method == "GET" and path == "/api/gui/doctor":
            result = await controller.run_doctor_check()
            await send_json(writer, HTTPStatus.OK, result)
            return

        if method != "POST":
            await send_json(writer, HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method not allowed"})
            return

        if not _is_trusted_origin(headers):
            await send_json(
                writer,
                HTTPStatus.FORBIDDEN,
                {"error": "Cross-origin POST requests are forbidden."},
            )
            return

        content_len = int(headers.get("content-length", "0").strip() or "0")
        content_type = headers.get("content-type", "").lower()
        if content_len > 0 and "application/json" not in content_type:
            await send_json(
                writer,
                HTTPStatus.BAD_REQUEST,
                {"error": "Content-Type must be application/json"},
            )
            return

        body = await read_json_body(reader, headers)

        if path == "/api/gui/connect":
            snapshot = await controller.start_session(body)
            await send_json(writer, HTTPStatus.OK, snapshot)
        elif path == "/api/gui/disconnect":
            snapshot = await controller.stop_session()
            await send_json(writer, HTTPStatus.OK, snapshot)
        elif path == "/api/gui/playbook":
            playbook_id = str(body.get("id") or "").strip()
            if not playbook_id:
                await send_json(writer, HTTPStatus.BAD_REQUEST, {"error": "missing playbook id"})
                return
            probe_duration = float(body.get("probe_duration") or 15.0)
            result = await controller.execute_playbook(playbook_id, probe_duration=probe_duration)
            await send_json(writer, HTTPStatus.OK, result)
        elif path == "/api/gui/scan":
            duration = float(body.get("duration") or 12.0)
            result = await controller.quick_scan(duration=duration)
            await send_json(writer, HTTPStatus.OK, result)
        elif path == "/api/gui/config":
            cfg = controller.update_config(body)
            await send_json(writer, HTTPStatus.OK, {"ok": True, "config": cfg})
        elif path == "/api/gui/export-csv":
            result = await controller.export_csv_now()
            await send_json(writer, HTTPStatus.OK, result)
        else:
            await send_json(writer, HTTPStatus.NOT_FOUND, {"error": "unknown gui endpoint"})
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        await send_json(writer, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
    except Exception as exc:
        await send_json(writer, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
