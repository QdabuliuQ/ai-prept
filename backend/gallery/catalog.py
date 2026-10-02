"""模板目录：从 agent-output/template.json 整理成可入库的行。

Admin 与公开墙共用 gallery_templates 表：
- 全量模板都会入库（含 local / draft / pending）
- 公开墙只展示 status=approved 且 cover 为 https 的行
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SAFE_TEMPLATE_DIR = re.compile(r"^[A-Za-z0-9._\u4e00-\u9fff-]+$")
# 与 admin.fsutil.RESERVED_OUTPUT_DIRS 对齐（含 sessions 临时包）
RESERVED_OUTPUT_DIRS = {"admin-jobs", "packs", "templates", "sessions"}


def repo_root() -> Path:
    # backend/gallery/catalog.py → parents[2] = repo root
    return Path(__file__).resolve().parents[2]


def output_root() -> Path:
    return repo_root() / "agent-output"


def https_pages(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [
        url
        for url in raw
        if isinstance(url, str) and url.startswith("https://")
    ]


def _text(block: Any, *keys: str) -> str:
    if not isinstance(block, dict):
        return ""
    for key in keys:
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def row_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """把 Admin to_summary 结果映射成表行。"""
    from templates.categories import coerce_category

    pages = [
        url
        for url in (summary.get("previewPages") or [])
        if isinstance(url, str) and url
    ]
    https = https_pages(pages)
    cover = https[0] if https else (pages[0] if pages else "")
    label = summary.get("label") if isinstance(summary.get("label"), dict) else {}
    description = (
        summary.get("description")
        if isinstance(summary.get("description"), dict)
        else {}
    )
    title = _text(label, "zh_CN", "en_US") or str(summary.get("id") or "")
    desc = _text(description, "zh_CN", "en_US")
    slide_count = int(summary.get("slideCount") or 0)
    if https:
        slide_count = max(slide_count, len(https))
    return {
        "id": str(summary.get("id") or ""),
        "title": title,
        "description": desc,
        "slide_count": slide_count,
        "cover": cover,
        "pages": https if https else pages,
        "status": str(summary.get("status") or "draft"),
        "storage_backend": str(summary.get("storageBackend") or "local"),
        "featured": bool(summary.get("featured")),
        "category": coerce_category(summary.get("category")),
        "summary": summary,
        "updated_ms": int(summary.get("mtimeMs") or 0),
    }


def row_from_meta(
    template_id: str,
    meta: dict[str, Any],
    updated_ms: int,
) -> dict[str, Any] | None:
    """兼容旧调用：任意有 template.json 的模板都入库。"""
    from admin.store import to_summary

    summary = to_summary(template_id, meta)
    if not summary.get("mtimeMs"):
        summary["mtimeMs"] = updated_ms
    return row_from_summary(summary)


def scan_all(root: Path | None = None) -> list[dict[str, Any]]:
    """扫描本地全部模板，生成入库行（Admin + 公开墙同源）。"""
    from admin.store import to_summary
    from admin.fsutil import read_meta

    base = root or output_root()
    if not base.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in RESERVED_OUTPUT_DIRS or not SAFE_TEMPLATE_DIR.match(entry.name):
            continue
        meta_path = entry / "template.json"
        if not meta_path.is_file():
            continue
        meta = read_meta(entry.name)
        if not meta:
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(loaded, dict):
                continue
            meta = loaded
        updated_ms = int(meta_path.stat().st_mtime * 1000)
        summary = to_summary(entry.name, meta)
        if not summary.get("mtimeMs"):
            summary["mtimeMs"] = updated_ms
        row = row_from_summary(summary)
        if row.get("id"):
            rows.append(row)
    return rows


def scan_uploaded(root: Path | None = None) -> list[dict[str, Any]]:
    """兼容旧名：现等同 scan_all（全量入库）。"""
    return scan_all(root)


def public_templates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """公开墙：仅已上传七牛（storage_backend=qiniu）且已通过的模板。"""
    visible = [
        row
        for row in rows
        if row.get("status") == "approved"
        and (row.get("storage_backend") or row.get("storageBackend")) == "qiniu"
        and isinstance(row.get("cover"), str)
        and row["cover"].startswith("https://")
        and isinstance(row.get("pages"), list)
        and any(
            isinstance(u, str) and u.startswith("https://") for u in row["pages"]
        )
    ]
    visible.sort(key=lambda row: int(row.get("updated_ms") or 0), reverse=True)
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "description": row.get("description") or "",
            "slideCount": row["slide_count"],
            "cover": row["cover"],
            "pages": [
                u
                for u in row["pages"]
                if isinstance(u, str) and u.startswith("https://")
            ],
            "featured": bool(row.get("featured")),
            "category": row.get("category") or "other",
            "updatedAt": int(row.get("updated_ms") or 0),
        }
        for row in visible
    ]
