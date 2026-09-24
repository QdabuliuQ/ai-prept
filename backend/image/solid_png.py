from __future__ import annotations

import struct
import zlib
from typing import Tuple


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", _crc32(chunk_type + data))
    )


def create_solid_color_png(
    width: int,
    height: int,
    rgb: Tuple[int, int, int],
) -> bytes:
    w = max(1, min(int(width), 2048))
    h = max(1, min(int(height), 2048))
    r, g, b = (max(0, min(255, int(v))) for v in rgb)
    row = bytes([0]) + bytes([r, g, b]) * w
    raw = row * h
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )
