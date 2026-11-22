"""Shared Mi Band 6 workout-summary fixture (Gadgetbridge v519 capture)."""

from __future__ import annotations

import struct

#: Real Mi Band 6 running summary, version 519 (320 bytes). Published in
#: Gadgetbridge's HuamiActivitySummaryParserTest (AGPL-3.0, test data only).
SUMMARY_V519_RUNNING = (
    "070201003d94446a7e9a446a0000000000000000e0b1ffff0000ffff00000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000100000000000f00"
    "0800000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000ff1000003d06000000000080ffffff7f00000080"
    "ffffff7fdcfcb3437ab7484500000000000000000050c3c70050c34700000000"
    "6666664000000000835f384000808a43e4388e3e73a3fe3ebcbb3b4000000000"
    "98762d40fc67613f000000003d56423ff4371a450e0c0000ac00f1014f00bb00"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
)


def shifted_summary(delta_seconds: int) -> bytes:
    """Return the fixture with its start/end timestamps shifted, for multi-fetch tests."""
    payload = bytearray.fromhex(SUMMARY_V519_RUNNING)
    for offset in (4, 8):
        value = struct.unpack_from("<I", payload, offset)[0] + delta_seconds
        struct.pack_into("<I", payload, offset, value)
    return bytes(payload)
