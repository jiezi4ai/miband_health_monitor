"""Low-level HTTP/1.1 and Server-Sent Events wire helpers.

Framing lives in one place so the page, JSON API and SSE endpoints always emit
the same status line, headers and CORS behaviour. The dashboard stays
stdlib-only on purpose: no web framework competes with the BLE stack for
dependencies.
"""

from __future__ import annotations

import asyncio
import json
from http import HTTPStatus
from typing import Any, Dict


#: Raw SSE response head. X-Accel-Buffering disables proxy buffering so events
#: reach the browser immediately behind nginx-style proxies.
SSE_RESPONSE_HEADERS = (
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: text/event-stream; charset=utf-8\r\n"
    "Cache-Control: no-cache\r\n"
    "Connection: keep-alive\r\n"
    "Access-Control-Allow-Origin: *\r\n"
    "X-Accel-Buffering: no\r\n"
    "\r\n"
)


_MAX_JSON_BODY_BYTES = 65536


def encode_json(payload: Any) -> bytes:
    """Serialize a JSON response body (UTF-8, non-ASCII kept readable)."""
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


async def read_json_body(
    reader: asyncio.StreamReader,
    headers: Dict[str, str],
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Read and parse a bounded JSON request body."""
    raw_len = headers.get("content-length", "").strip()
    if not raw_len:
        return {}
    length = int(raw_len)
    if length < 0 or length > _MAX_JSON_BODY_BYTES:
        raise ValueError(f"request body exceeds {_MAX_JSON_BODY_BYTES} bytes")
    if length == 0:
        return {}
    raw = await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("JSON body must be an object")
    return parsed


async def send_response(
    writer: asyncio.StreamWriter,
    status: HTTPStatus,
    content_type: str,
    body: bytes,
) -> None:
    """Write one complete HTTP response (Content-Length framed, no keep-alive)."""
    head = (
        f"HTTP/1.1 {status.value} {status.phrase}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Cache-Control: no-store\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    writer.write(head.encode("latin-1") + body)
    await writer.drain()


async def send_json(
    writer: asyncio.StreamWriter, status: HTTPStatus, payload: Dict
) -> None:
    """Write a JSON response with the dashboard JSON content type."""
    await send_response(
        writer, status, "application/json; charset=utf-8", encode_json(payload)
    )


async def send_sse_headers(writer: asyncio.StreamWriter) -> None:
    """Write the SSE response head and flush it before the first event."""
    writer.write(SSE_RESPONSE_HEADERS.encode("latin-1"))
    await writer.drain()


async def send_sse(writer: asyncio.StreamWriter, payload: Dict) -> None:
    """Write one SSE data frame; compact separators keep frames small."""
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    writer.write(f"data: {data}\n\n".encode("utf-8"))
    await writer.drain()


__all__ = [
    "SSE_RESPONSE_HEADERS",
    "encode_json",
    "read_json_body",
    "send_json",
    "send_response",
    "send_sse",
    "send_sse_headers",
]
