"""Regenerate one or more images on a slide in-place (same filename overwrite)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import is_mock, load_env
from image.generate import (
    extract_theme_colors,
    materialize_images,
    write_image_bytes,
)
from templates.page_rewrite import _load_meta, _resolve_slide_file, list_image_files
from usage import track_usage

LogFn = Callable[[str], None]

_ALT_ATTR_RE = re.compile(r'\balt=(["\'])(.*?)\1', re.I | re.S)
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)


def _log(log: LogFn | None, msg: str) -> None:
    if log:
        log(msg if msg.endswith("\n") else msg + "\n")


def _escape_attr(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _update_img_alts(html: str, targets: set[str], prompt: str) -> str:
    """Set alt on <img> tags whose ../images/<name> is in targets."""
    hint = re.sub(r"\s+", " ", (prompt or "").strip())[:300]
    if not hint or not targets:
        return html

    def repl(m: re.Match[str]) -> str:
        tag = m.group(0)
        src_m = re.search(
            r"""(?:src|data-src)=["']\.\./images/([^"'?#]+)["']""",
            tag,
            re.I,
        )
        if not src_m:
            return tag
        name = src_m.group(1).strip()
        if name not in targets:
            return tag
        esc = _escape_attr(hint)
        if _ALT_ATTR_RE.search(tag):
            return _ALT_ATTR_RE.sub(lambda _am: f'alt="{esc}"', tag, count=1)
        return re.sub(r"<img\b", f'<img alt="{esc}"', tag, count=1, flags=re.I)

    return _IMG_TAG_RE.sub(repl, html)


def _mock_write_image(dest: Path, prompt: str) -> None:
    """Write a tiny valid PNG so previews refresh without calling image APIs."""
    # 1x1 PNG
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf"
        b"\xc0\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4\xef\x00\x00\x00\x00IEND"
        b"\xaeB`\x82"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Prefer real helper when available (handles format by extension)
    try:
        write_image_bytes(dest, png)
    except Exception:
        dest.write_bytes(png)
    meta = dest.with_suffix(dest.suffix + ".mock.txt")
    meta.write_text(f"mock image regen\n{prompt[:500]}\n", encoding="utf-8")


def run_page_image_regen(
    package: str | Path,
    *,
    prompt: str,
    slide_file: str | None = None,
    page_index: int | None = None,
    image_file: str | None = None,
    mock: bool | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Overwrite slide image(s) under images/ with a new generation.

    Keeps the same filename so HTML src stays valid (cache-bust via mtime / reload).
    """
    load_env()
    package_dir = Path(package).expanduser().resolve()
    if not package_dir.is_dir():
        raise RuntimeError(f"模板目录不存在：{package_dir}")
    prompt = (prompt or "").strip()
    if len(prompt) < 2:
        raise RuntimeError("换图提示过短")
    if len(prompt) > 2000:
        raise RuntimeError("换图提示过长（最多 2000 字）")

    use_mock = is_mock() if mock is None else bool(mock)
    meta = _load_meta(package_dir)
    rel, slide_path = _resolve_slide_file(
        meta, package_dir, slide_file=slide_file, page_index=page_index
    )
    html = slide_path.read_text(encoding="utf-8")
    images = [n for n in list_image_files(html) if (package_dir / "images" / n).is_file()]
    if not images:
        # also allow regenerating listed files even if currently missing
        images = list_image_files(html)
    if not images:
        raise RuntimeError(f"页面没有本地配图：{rel}")

    target = (image_file or "").strip()
    if target:
        target = target.replace("\\", "/").split("/")[-1]
        if target not in images:
            raise RuntimeError(f"页面未引用图片：{target}")
        targets = [target]
    else:
        targets = images[:1]  # default: first image on the page (usually hero)

    subject = (prompt or "").strip()
    html2 = _update_img_alts(html, set(targets), subject)
    if html2 != html:
        slide_path.write_text(html2.rstrip() + "\n", encoding="utf-8")
        _log(log, f"[image-regen] updated alt on {', '.join(targets)}")

    refs = {name: subject for name in targets}
    warnings: list[str] = []
    _log(log, f"[image-regen] subject={subject[:160]}")

    if use_mock:
        for name in targets:
            _mock_write_image(package_dir / "images" / name, subject)
        _log(log, f"[image-regen] mock wrote {', '.join(targets)}")
    else:
        theme_css = ""
        theme_path = package_dir / "theme.css"
        if theme_path.is_file():
            theme_css = theme_path.read_text(encoding="utf-8")
        theme_colors = extract_theme_colors(theme_css)
        label = ""
        lab = meta.get("label")
        if isinstance(lab, dict):
            label = str(lab.get("zh_CN") or lab.get("en_US") or "").strip()
        label = label or str(meta.get("template_id") or package_dir.name)
        # Keep deck title only as weak mood; subject prompt_mode ignores heavy locks.
        style_hint = f"{label} {meta.get('visual_style') or ''}".strip()
        with track_usage() as usage:
            warnings = materialize_images(
                package_dir / "images",
                refs,
                style_hint=style_hint,
                bg_hex=theme_colors.get("bg"),
                theme_colors=theme_colors,
                force=True,
                prompt_mode="subject",
            )
            meta["usage"] = usage.merge_into(
                meta.get("usage") if isinstance(meta.get("usage"), dict) else None
            )
        _log(
            log,
            f"[image-regen] materialized {', '.join(targets)}"
            + (f" warnings={len(warnings)}" if warnings else ""),
        )

    meta["last_page_image_regen"] = {
        "file": rel,
        "images": targets,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt": prompt[:500],
        "subject": subject[:500],
    }
    (package_dir / "template.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "ok": True,
        "op": "regenerate_image",
        "template_id": str(
            meta.get("public_id") or meta.get("template_id") or package_dir.name
        ),
        "file": rel,
        "regeneratedImages": targets,
        "warnings": warnings,
    }
