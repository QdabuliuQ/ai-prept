"""Generate visual-spec.md for an existing template package (post-approval).

Reads slide HTML on disk (fingerprints + a few excerpts), then asks the LLM
to ground the design bible in observed pages — not meta descriptions alone.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from config import llm_light_config
from llm import chat_text, make_client_pool
from templates import prompts
from templates.page_rewrite import list_image_files
from templates.remix import inventory_slide_slots
from usage import track_usage, use_usage

_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
_RADIUS_RE = re.compile(r"border-radius\s*:\s*([^;}\"']+)", re.I)
_FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([^;}\"']+)", re.I)

# Token budget: fingerprints for all pages + a few HTML excerpts.
_THEME_EXCERPT_CHARS = 4_000
_HTML_EXCERPT_CHARS = 2_500
_MAX_SLOTS_PER_PAGE = 20
_MAX_MOTIF_SAMPLES = 12
_DESC_CHARS = 180
_SLOT_TEXT_CHARS = 80


def _strip_fence(text: str) -> str:
    s = (text or "").strip()
    if not s.startswith("```"):
        return s
    s = re.sub(r"^```(?:markdown|md)?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return data


def _truncate_html(html: str, *, max_chars: int = _HTML_EXCERPT_CHARS) -> str:
    text = html or ""
    if len(text) <= max_chars:
        return text
    head = max_chars * 3 // 4
    tail = max_chars - head - 80
    return (
        text[:head]
        + "\n\n<!-- … middle truncated for prompt … -->\n\n"
        + text[-max(0, tail) :]
    )


def _uniq_preserve(items: list[str], *, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        v = (raw or "").strip()
        if not v:
            continue
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
        if len(out) >= limit:
            break
    return out


def _motif_samples(html: str) -> dict[str, list[str]]:
    return {
        "colors": _uniq_preserve(_HEX_RE.findall(html or ""), limit=_MAX_MOTIF_SAMPLES),
        "border_radii": _uniq_preserve(
            [m.group(1).strip() for m in _RADIUS_RE.finditer(html or "")],
            limit=_MAX_MOTIF_SAMPLES,
        ),
        "font_sizes": _uniq_preserve(
            [m.group(1).strip() for m in _FONT_SIZE_RE.finditer(html or "")],
            limit=_MAX_MOTIF_SAMPLES,
        ),
    }


def _compact_slots(html: str, *, file: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slot in inventory_slide_slots(html, file=file)[:_MAX_SLOTS_PER_PAGE]:
        row: dict[str, Any] = {
            "slot": slot.get("slot"),
            "type": slot.get("type"),
            "role": slot.get("role"),
        }
        if slot.get("type") == "image":
            if slot.get("filename"):
                row["filename"] = slot["filename"]
        else:
            text = str(slot.get("current") or "").strip()
            if text:
                row["text"] = text[:_SLOT_TEXT_CHARS]
            if slot.get("font_px"):
                row["font_px"] = slot["font_px"]
        rows.append(row)
    return rows


def _page_fingerprint(
    *,
    file: str,
    layout: Any,
    title: Any,
    description: str,
    html: str,
) -> dict[str, Any]:
    motifs = _motif_samples(html)
    images = list_image_files(html)
    return {
        "file": file,
        "layout": layout,
        "title": title,
        "description": description[:_DESC_CHARS],
        "html_chars": len(html),
        "svg_n": html.lower().count("<svg"),
        "images": images[:16],
        "slots": _compact_slots(html, file=file),
        "colors": motifs["colors"],
        "border_radii": motifs["border_radii"],
        "font_sizes": motifs["font_sizes"],
    }


def _pick_excerpt_indices(n: int) -> list[tuple[str, int]]:
    """Label + index for cover / sample-content / closing (deduped by index)."""
    if n <= 0:
        return []
    if n == 1:
        return [("cover", 0)]
    if n == 2:
        return [("cover", 0), ("closing", 1)]
    mid = n // 2
    picks = [("cover", 0), ("sample-content", mid), ("closing", n - 1)]
    seen: set[int] = set()
    out: list[tuple[str, int]] = []
    for label, idx in picks:
        if idx in seen:
            continue
        seen.add(idx)
        out.append((label, idx))
    return out


def _slot_role_summary(pages: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for page in pages:
        for slot in page.get("slots") or []:
            if not isinstance(slot, dict):
                continue
            role = str(slot.get("role") or "").strip() or "unknown"
            counter[role] += 1
    return dict(counter.most_common(24))


def build_deck_context(package_dir: Path) -> dict[str, Any]:
    """Planning context grounded in slide HTML (fingerprints + few excerpts)."""
    meta_path = package_dir / "template.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"missing template.json: {meta_path}")
    meta = _read_json(meta_path)

    files = meta.get("files") if isinstance(meta.get("files"), dict) else {}
    theme_rel = str(files.get("theme_css") or "theme.css")
    theme_path = package_dir / theme_rel
    theme_excerpt = ""
    if theme_path.is_file():
        theme_excerpt = theme_path.read_text(encoding="utf-8")[:_THEME_EXCERPT_CHARS]

    pages: list[dict[str, Any]] = []
    html_by_index: list[tuple[str, str]] = []  # (file, html)
    missing_slides: list[str] = []

    for item in meta.get("slides") or []:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("file") or "").strip()
        if not rel:
            continue
        path = package_dir / rel
        if not path.is_file():
            missing_slides.append(rel)
            pages.append(
                {
                    "file": rel,
                    "layout": item.get("layout"),
                    "title": item.get("title"),
                    "description": (str(item.get("description") or ""))[:_DESC_CHARS],
                    "missing": True,
                }
            )
            continue
        html = path.read_text(encoding="utf-8")
        html_by_index.append((rel, html))
        pages.append(
            _page_fingerprint(
                file=rel,
                layout=item.get("layout"),
                title=item.get("title"),
                description=str(item.get("description") or ""),
                html=html,
            )
        )

    html_excerpts: list[dict[str, str]] = []
    for label, idx in _pick_excerpt_indices(len(html_by_index)):
        file, html = html_by_index[idx]
        html_excerpts.append(
            {
                "label": label,
                "file": file,
                "html": _truncate_html(html),
            }
        )

    return {
        "template_id": meta.get("template_id") or package_dir.name,
        "label": meta.get("label"),
        "description": meta.get("description"),
        "format": meta.get("format") or "html-slide",
        "visual_spec_outline": meta.get("visual_spec_outline") or "",
        "page_count": len(pages),
        "pages": pages,
        "slot_role_summary": _slot_role_summary(pages),
        "html_excerpts": html_excerpts,
        "missing_slides": missing_slides,
        "theme_css_excerpt": theme_excerpt,
        # legacy key kept for mock / older callers that expect "slides"
        "slides": [
            {
                "file": p.get("file"),
                "layout": p.get("layout"),
                "title": p.get("title"),
                "description": p.get("description"),
            }
            for p in pages
        ],
    }


def write_visual_spec(package_dir: Path, markdown: str) -> Path:
    text = (markdown or "").rstrip() + "\n"
    out = package_dir / "visual-spec.md"
    out.write_text(text, encoding="utf-8")

    meta_path = package_dir / "template.json"
    if meta_path.is_file():
        meta = _read_json(meta_path)
        files = meta.get("files") if isinstance(meta.get("files"), dict) else {}
        files = dict(files)
        files.setdefault("visual_spec", "visual-spec.md")
        meta["files"] = files
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return out


def generate_visual_spec(
    package_dir: Path,
    *,
    mock: bool = False,
    only_if_missing: bool = False,
) -> Path:
    """Read slide pages, call LLM (or mock stub), write visual-spec.md."""
    root = package_dir.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"package not found: {root}")

    existing = root / "visual-spec.md"
    if only_if_missing and existing.is_file():
        try:
            if existing.read_text(encoding="utf-8").strip():
                return existing
        except OSError:
            pass

    deck = build_deck_context(root)
    # Compact separators: fingerprints + excerpts already carry the signal.
    deck_json = json.dumps(deck, ensure_ascii=False, separators=(",", ":"))

    if mock:
        label = ""
        if isinstance(deck.get("label"), dict):
            label = str(deck["label"].get("zh_CN") or deck["label"].get("en_US") or "")
        outline = str(deck.get("visual_spec_outline") or "").strip()
        pages = deck.get("pages") or []
        layouts = [
            str(p.get("layout") or p.get("title") or "")
            for p in pages
            if isinstance(p, dict)
        ]
        roles = deck.get("slot_role_summary") or {}
        excerpt_files = [
            e.get("file")
            for e in (deck.get("html_excerpts") or [])
            if isinstance(e, dict)
        ]
        md = "\n".join(
            [
                f"# Visual Spec · {label or deck.get('template_id')}",
                "",
                "## Design Read",
                outline or "（mock：无 outline）",
                "",
                "## Pages read",
                f"- page_count: {deck.get('page_count', 0)}",
                f"- html_excerpts: {', '.join(str(x) for x in excerpt_files) or '（无）'}",
                f"- slot_roles: {json.dumps(roles, ensure_ascii=False)}",
                "",
                "## Layout inventory",
                "- " + "\n- ".join(x for x in layouts if x) if layouts else "- （无 slides）",
                "",
                "## Locked vs editable",
                "- Locked: 结构、装饰、主题色、非槽位样式",
                "- Editable: `data-slot*` 文案与配图",
                "",
                "（mock 模式生成，已读页面指纹，未调用 LLM）",
                "",
            ]
        )
        return write_visual_spec(root, md)

    # visual-spec is a documentation task; use the light tier when configured.
    cfg = llm_light_config()
    pool = make_client_pool(cfg)
    with track_usage() as usage:
        with use_usage(usage):
            raw = chat_text(
                pool=pool,
                model=cfg.model,
                system=prompts.SYSTEM_VISUAL_SPEC,
                user=prompts.user_visual_spec(deck_json=deck_json),
                temperature=0.35,
            )
    return write_visual_spec(root, _strip_fence(raw))
