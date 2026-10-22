"""Generate visual-spec.md for an existing template package (post-approval).

Reads slide HTML on disk (fingerprints + a few excerpts), then asks the LLM
to ground the design bible in observed pages — not meta descriptions alone.
"""

from __future__ import annotations

import base64
import json
import re
import tempfile
from contextlib import contextmanager
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from config import LlmConfig, llm_light_config, llm_vision_config
from llm import chat_json, chat_text, make_client_pool
from templates import prompts
from templates.page_rewrite import list_image_files
from templates.remix import inventory_slide_slots
from templates.render_check import capture_package_previews
from templates.slot_tree import canvas_size, measure_slots
from usage import track_usage, use_usage

_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
_RADIUS_RE = re.compile(r"border-radius\s*:\s*([^;}\"']+)", re.I)
_FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([^;}\"']+)", re.I)

# Token budget: fingerprints for all pages + a few HTML excerpts.
_HTML_EXCERPT_CHARS = 2_500
_MAX_SLOTS_PER_PAGE = 20
_MAX_MOTIF_SAMPLES = 12
_DESC_CHARS = 180
_SLOT_TEXT_CHARS = 80
_PREVIEW_SUFFIXES = {".webp", ".png", ".jpg", ".jpeg"}


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
    """Slot roles for visual-spec — omit sample copy so the bible stays skin-only."""
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
                # Length only: literal copy biases the LLM into content locks.
                row["text_chars"] = min(len(text), _SLOT_TEXT_CHARS * 4)
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
        # Sample pack copy — for inventory only; must not become image/subject locks.
        "sample_title": title,
        "sample_description": description[:_DESC_CHARS],
        "html_chars": len(html),
        "svg_n": html.lower().count("<svg"),
        "images": images[:16],
        "slots": _compact_slots(html, file=file),
        "colors": motifs["colors"],
        "border_radii": motifs["border_radii"],
        "font_sizes": motifs["font_sizes"],
    }


def _preview_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".jpg" or suffix == ".jpeg":
        return "image/jpeg"
    return "image/png"


def _image_data_url(path: Path) -> str:
    data = path.read_bytes()
    return f"data:{_preview_type(path)};base64,{base64.b64encode(data).decode('ascii')}"


def _visual_slots(html: str, *, file: str) -> list[dict[str, Any]]:
    """Complete slot facts used by the per-page multimodal analyzer."""
    rows: list[dict[str, Any]] = []
    for slot in inventory_slide_slots(html, file=file):
        row = {
            key: slot.get(key)
            for key in (
                "slot",
                "type",
                "role",
                "current",
                "src",
                "filename",
                "font_px",
                "abs_left",
                "abs_top",
                "box_width_px",
                "box_height_px",
                "line_count",
                "fields",
            )
            if slot.get(key) not in (None, "", [])
        }
        rows.append(row)
    return rows


def overlap_candidates(html: str, *, file: str) -> list[dict[str, Any]]:
    """Return every materially overlapping text pair as evidence, not a verdict."""
    boxes = measure_slots(html)
    text_slots = [
        slot
        for slot in inventory_slide_slots(html, file=file)
        if slot.get("type") == "text" and str(slot.get("slot") or "") in boxes
    ]
    pairs: list[dict[str, Any]] = []
    for index, left in enumerate(text_slots):
        left_box = boxes[str(left["slot"])]
        lx = float(left_box.get("x") or 0)
        ly = float(left_box.get("y") or 0)
        lw = float(left_box.get("width") or 0)
        lh = float(left_box.get("height") or 0)
        if lw <= 0 or lh <= 0:
            continue
        for right in text_slots[index + 1 :]:
            right_box = boxes[str(right["slot"])]
            rx = float(right_box.get("x") or 0)
            ry = float(right_box.get("y") or 0)
            rw = float(right_box.get("width") or 0)
            rh = float(right_box.get("height") or 0)
            if rw <= 0 or rh <= 0:
                continue
            overlap_w = max(0.0, min(lx + lw, rx + rw) - max(lx, rx))
            overlap_h = max(0.0, min(ly + lh, ry + rh) - max(ly, ry))
            overlap_area = overlap_w * overlap_h
            smaller = min(lw * lh, rw * rh)
            ratio = overlap_area / smaller if smaller > 0 else 0.0
            if ratio < 0.08:
                continue
            left_text = re.sub(r"\s+", " ", str(left.get("current") or "")).strip()
            right_text = re.sub(r"\s+", " ", str(right.get("current") or "")).strip()
            pairs.append(
                {
                    "slots": [left["slot"], right["slot"]],
                    "overlap_ratio_of_smaller": round(ratio, 3),
                    "offset_px": {
                        "x": round(rx - lx, 1),
                        "y": round(ry - ly, 1),
                    },
                    "same_text": bool(left_text and left_text == right_text),
                    "text_lengths": [len(left_text), len(right_text)],
                }
            )
    pairs.sort(key=lambda row: float(row["overlap_ratio_of_smaller"]), reverse=True)
    return pairs[:80]


def _page_records(package_dir: Path, deck: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in deck.get("pages") or []:
        if not isinstance(page, dict) or page.get("missing"):
            continue
        rel = str(page.get("file") or "").strip()
        path = package_dir / rel
        if not path.is_file():
            continue
        html = path.read_text(encoding="utf-8")
        width, height = canvas_size(html)
        rows.append(
            {
                "file": rel,
                "path": path,
                "html": html,
                "layout": page.get("layout"),
                "sample_title": page.get("sample_title"),
                "sample_description": page.get("sample_description"),
                "canvas": {"width": round(width, 1), "height": round(height, 1)},
                "slots": _visual_slots(html, file=rel),
                "overlap_candidates": overlap_candidates(html, file=rel),
            }
        )
    return rows


def _fresh_existing_previews(
    package_dir: Path,
    pages: list[dict[str, Any]],
) -> list[Path] | None:
    preview_dir = package_dir / "previews"
    if not preview_dir.is_dir():
        return None
    previews = sorted(
        path
        for path in preview_dir.iterdir()
        if path.is_file() and path.suffix.lower() in _PREVIEW_SUFFIXES
    )
    if len(previews) < len(pages):
        return None
    previews = previews[: len(pages)]
    source_paths = [Path(page["path"]) for page in pages]
    theme = package_dir / "theme.css"
    if theme.is_file():
        source_paths.append(theme)
    try:
        newest_source = max(path.stat().st_mtime_ns for path in source_paths)
        oldest_preview = min(path.stat().st_mtime_ns for path in previews)
    except OSError:
        return None
    return previews if oldest_preview >= newest_source else None


@contextmanager
def _page_preview_paths(
    package_dir: Path,
    pages: list[dict[str, Any]],
) -> Iterator[list[Path]]:
    fresh = _fresh_existing_previews(package_dir, pages)
    if fresh is not None:
        yield fresh
        return
    with tempfile.TemporaryDirectory(prefix="ai-prept-visual-spec-") as tmp:
        yield capture_package_previews(
            package_dir,
            tmp,
            page_paths=[Path(page["path"]) for page in pages],
        )


def _vision_user_content(
    *,
    intro: str,
    prompt: str,
    image_paths: list[Path],
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": intro}]
    for index, path in enumerate(image_paths, start=1):
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": _image_data_url(path),
                    "detail": "high",
                },
            }
        )
        content.append(
            {
                "type": "text",
                "text": f"上图编号 {index:02d}：{path.name}",
            }
        )
    content.append({"type": "text", "text": prompt})
    return content


def _analyze_page_with_vision(
    *,
    pool: Any,
    cfg: LlmConfig,
    page: dict[str, Any],
    preview: Path,
) -> dict[str, Any]:
    page_context = {
        "file": page["file"],
        "layout": page.get("layout"),
        "sample_title": page.get("sample_title"),
        "sample_description": page.get("sample_description"),
        "canvas": page.get("canvas"),
        "slots": page.get("slots"),
        "full_html": page.get("html"),
        "content_note": "sample_title / sample_description 与页面文案是原模板样例内容。",
    }
    user_prompt = prompts.user_page_visual_analysis(
        page_context=json.dumps(page_context, ensure_ascii=False, separators=(",", ":")),
        overlap_evidence=json.dumps(
            page.get("overlap_candidates") or [],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    raw = chat_json(
        pool=pool,
        model=cfg.model,
        messages=[
            {"role": "system", "content": prompts.SYSTEM_PAGE_VISUAL_ANALYSIS},
            {
                "role": "user",
                "content": _vision_user_content(
                    intro="下面是这一页的整页渲染预览。它必须与后面的完整 HTML 对照分析。",
                    prompt=user_prompt,
                    image_paths=[preview],
                ),
            },
        ],
        temperature=0.2,
    )
    raw["file"] = page["file"]
    return raw


def _deck_vision_context(
    deck: dict[str, Any],
    page_analyses: list[dict[str, Any]],
) -> str:
    return json.dumps(
        {
            "template_id": deck.get("template_id"),
            "label": deck.get("label"),
            "description": deck.get("description"),
            "format": deck.get("format"),
            "page_count": len(page_analyses),
            "theme_css": deck.get("theme_css_excerpt"),
            "content_note": deck.get("content_note"),
            "pages": page_analyses,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _generate_visual_spec_with_vision(
    root: Path,
    deck: dict[str, Any],
    vision_config: LlmConfig | None = None,
    synthesis_config: LlmConfig | None = None,
) -> str:
    pages = _page_records(root, deck)
    if not pages:
        raise RuntimeError("模板包没有可分析的 slides/*.html")

    cfg = vision_config or llm_vision_config()
    pool = make_client_pool(cfg)
    with track_usage() as usage:
        with use_usage(usage):
            with _page_preview_paths(root, pages) as previews:
                if len(previews) != len(pages):
                    raise RuntimeError(
                        f"页面预览数量不符：HTML {len(pages)} 页，预览 {len(previews)} 页"
                    )
                analyses = [
                    _analyze_page_with_vision(
                        pool=pool,
                        cfg=cfg,
                        page=page,
                        preview=preview,
                    )
                    for page, preview in zip(pages, previews)
                ]

    synthesis_cfg = synthesis_config or llm_light_config()
    synthesis_pool = make_client_pool(synthesis_cfg)
    with track_usage() as usage:
        with use_usage(usage):
            raw = chat_text(
                pool=synthesis_pool,
                model=synthesis_cfg.model,
                messages=[
                    {"role": "system", "content": prompts.SYSTEM_VISUAL_SPEC},
                    {
                        "role": "user",
                        "content": prompts.user_deck_visual_spec(
                            deck_json=_deck_vision_context(deck, analyses),
                            page_analyses_json=json.dumps(
                                analyses,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        ),
                    },
                ],
                temperature=0.35,
            )
    return _strip_fence(raw)


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
        theme_excerpt = theme_path.read_text(encoding="utf-8")

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
                    "sample_title": item.get("title"),
                    "sample_description": (str(item.get("description") or ""))[
                        :_DESC_CHARS
                    ],
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
        "content_note": (
            "sample_title / sample_description / HTML 文案仅为样例内容；"
            "visual-spec 只锁版式、色板、形态与配图色调，不锁题材故事。"
        ),
        # legacy key kept for mock / older callers that expect "slides"
        "slides": [
            {
                "file": p.get("file"),
                "layout": p.get("layout"),
                "title": p.get("sample_title") or p.get("title"),
                "description": p.get("sample_description") or p.get("description"),
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
    vision_config: LlmConfig | None = None,
    synthesis_config: LlmConfig | None = None,
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

    if mock:
        label = ""
        if isinstance(deck.get("label"), dict):
            label = str(deck["label"].get("zh_CN") or deck["label"].get("en_US") or "")
        outline = str(deck.get("visual_spec_outline") or "").strip()
        pages = deck.get("pages") or []
        layouts = [
            str(p.get("layout") or p.get("sample_title") or p.get("title") or "")
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
                "- Locked: 版式结构、装饰几何、主题色、配图色调（不锁题材故事）",
                "- Editable: `data-slot*` 文案与配图主体（服从配图色调）",
                "",
                "（mock 模式生成，已读页面指纹，未调用 LLM）",
                "",
            ]
        )
        return write_visual_spec(root, md)

    return write_visual_spec(
        root,
        _generate_visual_spec_with_vision(
            root,
            deck,
            vision_config=vision_config,
            synthesis_config=synthesis_config,
        ),
    )
