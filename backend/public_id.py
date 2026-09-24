"""Stable public template ids: letters and digits only."""

from __future__ import annotations

import secrets
from pathlib import Path

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def new_public_template_id(length: int = 12) -> str:
    n = 12 if length < 8 else length
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def alloc_public_template_id(out_root: Path, length: int = 12) -> str:
    root = out_root.resolve()
    for _ in range(24):
        tid = new_public_template_id(length)
        if not (root / tid).exists():
            return tid
    return new_public_template_id(16)
