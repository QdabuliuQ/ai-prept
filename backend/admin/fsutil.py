"""Filesystem helpers for agent-output templates."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SAFE_TEMPLATE_DIR = re.compile(r"^[A-Za-z0-9._\u4e00-\u9fff-]+$")
RESERVED_OUTPUT_DIRS = {"admin-jobs", "packs", "templates"}
PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9]{8,}$")


def repo_root() -> Path:
    # backend/admin/fsutil.py → parents[2] = repo root
    return Path(__file__).resolve().parents[2]


def templates_root() -> Path:
    return repo_root() / "agent-output"


def jobs_dir() -> Path:
    d = templates_root() / "admin-jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def template_dir(template_id: str) -> Path:
    return templates_root() / template_id


def resolve_under(template_id: str, rel: str) -> Path | None:
    if not SAFE_TEMPLATE_DIR.match(template_id):
        return None
    root = template_dir(template_id).resolve()
    target = (root / rel).resolve()
    if target != root and not str(target).startswith(str(root) + "/"):
        return None
    return target


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_meta(template_id: str) -> dict[str, Any] | None:
    path = resolve_under(template_id, "template.json")
    if not path or not path.is_file():
        return None
    try:
        data = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_meta(template_id: str, meta: dict[str, Any]) -> None:
    path = resolve_under(template_id, "template.json")
    if not path:
        raise ValueError("非法模板 id")
    write_json(path, meta)


def list_template_ids() -> list[str]:
    root = templates_root()
    if not root.is_dir():
        return []
    out: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in RESERVED_OUTPUT_DIRS:
            continue
        if not SAFE_TEMPLATE_DIR.match(entry.name):
            continue
        if (entry / "template.json").is_file():
            out.append(entry.name)
    return out


def template_mtime_ms(template_id: str) -> int:
    root = template_dir(template_id)
    best = 0.0
    try:
        best = root.stat().st_mtime
    except OSError:
        return 0
    try:
        best = max(best, (root / "template.json").stat().st_mtime)
    except OSError:
        pass
    return int(best * 1000)


def effective_status(meta: dict[str, Any] | None) -> str:
    if not meta:
        return "approved"
    status = meta.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return "approved"


def effective_format(meta: dict[str, Any] | None) -> str:
    raw = str((meta or {}).get("format") or "").strip()
    if raw == "ppt-master":
        return "ppt-master"
    return "html-slide"


def effective_render(meta: dict[str, Any] | None) -> str:
    """页面渲染形态：html-slide | svg | svg-fallback。

    svg-fallback = svg_to_pptx / 转 HTML 失败后的整页 SVG 预览包，不可当标准 html-slide。
    """
    if not meta:
        return "unknown"
    raw = str(meta.get("render") or "").strip().lower()
    if raw in {"svg-fallback", "html-slide", "svg"}:
        return raw
    if raw in {"html", "dom"}:
        return "html-slide"

    source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
    kind = str(source.get("kind") or "").lower()
    if "svg-fallback" in kind:
        return "svg-fallback"

    warnings = meta.get("warnings") if isinstance(meta.get("warnings"), list) else []
    for w in warnings:
        text = str(w)
        if "export_fallback=svg" in text or "svg-fallback" in text.lower():
            return "svg-fallback"

    review = meta.get("review") if isinstance(meta.get("review"), dict) else {}
    note = str(review.get("note") or "")
    if "SVG 预览" in note or "svg-fallback" in note.lower():
        return "svg-fallback"

    fmt = effective_format(meta)
    if fmt == "html-slide":
        return "html-slide"
    if fmt == "ppt-master":
        return "svg"
    return raw or "unknown"


def html_slide_count(meta: dict[str, Any]) -> int:
    slides = meta.get("slides") or []
    if not isinstance(slides, list):
        return 0
    return sum(
        1
        for s in slides
        if isinstance(s, dict)
        and str(s.get("file") or "").lower().endswith(".html")
    )
