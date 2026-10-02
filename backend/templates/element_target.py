"""Normalize canvas-selected element targets for editor assist."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SAFE_SLOT = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


def normalize_element_target(raw: Any) -> dict[str, Any] | None:
    """Keep a small, JSON-safe subset of the frontend selection payload."""
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None

    out: dict[str, Any] = {}
    for key in (
        "selector",
        "editorId",
        "tagName",
        "textContent",
        "dataSlot",
        "dataSlotType",
        "dataSlotRole",
        "dataElement",
        "imageSrc",
    ):
        val = raw.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if not s:
            continue
        if key == "textContent":
            s = re.sub(r"\s+", " ", s)[:240]
        elif key == "selector":
            s = s[:240]
        elif key in {"dataSlot", "dataSlotType", "dataSlotRole", "dataElement", "editorId"}:
            if not _SAFE_SLOT.match(s):
                continue
            s = s[:120]
        elif key == "imageSrc":
            s = s.replace("\\", "/")[:240]
        elif key == "tagName":
            s = s.lower()[:32]
        out[key] = s

    if "isTextElement" in raw:
        out["isTextElement"] = bool(raw.get("isTextElement"))
    if "isImageElement" in raw:
        out["isImageElement"] = bool(raw.get("isImageElement"))

    if not out:
        return None
    return out


def image_filename_from_target(target: dict[str, Any] | None) -> str | None:
    if not target:
        return None
    src = str(target.get("imageSrc") or "").strip()
    if not src:
        return None
    name = Path(src.split("?", 1)[0]).name
    return name or None


def format_target_for_prompt(target: dict[str, Any] | None) -> str:
    if not target:
        return ""
    lines = ["## 选中元素（优先只改这个，尽量不动同页其它元素）"]
    mapping = [
        ("dataSlot", "data-slot"),
        ("dataSlotType", "data-slot-type"),
        ("dataSlotRole", "data-slot-role"),
        ("dataElement", "data-element"),
        ("editorId", "editor-id"),
        ("tagName", "tag"),
        ("imageSrc", "image"),
        ("textContent", "当前文案"),
        ("selector", "selector"),
    ]
    for key, label in mapping:
        val = target.get(key)
        if val:
            lines.append(f"- {label}: {val}")
    if target.get("isTextElement"):
        lines.append("- kind: text")
    if target.get("isImageElement") or target.get("imageSrc"):
        lines.append("- kind: image")
    lines.append("请围绕该元素落实用户要求；不要无关地大改整页。")
    return "\n".join(lines)
