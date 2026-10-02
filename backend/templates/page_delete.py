"""Delete a slide from a template / workspace pack."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from templates.page_rewrite import _load_meta, _resolve_slide_file

LogFn = Callable[[str], None]


def _log(log: LogFn | None, msg: str) -> None:
    if log:
        log(msg if msg.endswith("\n") else msg + "\n")


def run_page_delete(
    package: str | Path,
    *,
    slide_file: str | None = None,
    page_index: int | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    package_dir = Path(package).expanduser().resolve()
    if not package_dir.is_dir():
        raise RuntimeError(f"模板目录不存在：{package_dir}")

    meta = _load_meta(package_dir)
    slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
    if not isinstance(slides, list) or len(slides) <= 1:
        raise RuntimeError("至少保留一页，无法删除")

    rel, slide_path = _resolve_slide_file(
        meta, package_dir, slide_file=slide_file, page_index=page_index
    )

    removed_index = None
    next_slides: list[Any] = []
    for i, item in enumerate(slides):
        if isinstance(item, dict) and str(item.get("file") or "") == rel:
            removed_index = i
            continue
        next_slides.append(item)
    if removed_index is None:
        raise RuntimeError(f"页面不在 template.json 中：{rel}")

    if slide_path.is_file():
        slide_path.unlink()
        _log(log, f"[delete-page] removed file {rel}")
    else:
        _log(log, f"[delete-page] meta-only remove {rel} (file missing)")

    meta["slides"] = next_slides
    meta["last_page_delete"] = {
        "file": rel,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "removedIndex": removed_index,
    }
    (package_dir / "template.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    activate_index = min(removed_index, len(next_slides) - 1)
    activate_file = None
    if 0 <= activate_index < len(next_slides) and isinstance(
        next_slides[activate_index], dict
    ):
        activate_file = str(next_slides[activate_index].get("file") or "") or None

    return {
        "ok": True,
        "template_id": str(
            meta.get("public_id") or meta.get("template_id") or package_dir.name
        ),
        "file": rel,
        "removedIndex": removed_index,
        "activateFile": activate_file,
        "deletedFiles": [rel],
        "slideCount": len(next_slides),
    }
