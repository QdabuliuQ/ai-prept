"""Layout-preserving template remix: clone HTML pack, swap text/images only.

Keeps theme.css, absolute layout geometry, decorative SVG shapes, and slot
structure. Only innermost text runs and image refs change.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from config import is_mock, load_env
from public_id import alloc_public_template_id
from llm import chat_json, make_client_pool

LogFn = Callable[[str], None]

_SLOT_OPEN_RE = re.compile(
    r"""<div\b(?P<attrs>[^>]*?\bdata-slot\s*=\s*["'](?P<slot>[^"']+)["'][^>]*?)>""",
    re.I | re.S,
)
_TYPE_RE = re.compile(r"""\bdata-slot-type\s*=\s*["']([^"']+)["']""", re.I)
_ROLE_RE = re.compile(r"""\bdata-slot-role\s*=\s*["']([^"']+)["']""", re.I)
_SPAN_RE = re.compile(r"(<span\b[^>]*>)(.*?)(</span>)", re.I | re.S)
_IMG_SRC_RE = re.compile(
    r"""\b(?:src|data-src|href)=["'](\.\./images/([^"'?#]+))(?:[?#][^"']*)?["']""",
    re.I,
)
_ALT_ATTR_RE = re.compile(r"""\b(?:alt|data-alt)=["']([^"']*)["']""", re.I)
_WIDTH_PX_RE = re.compile(r"\bwidth\s*:\s*([\d.]+)\s*px", re.I)
_HEIGHT_PX_RE = re.compile(r"\bheight\s*:\s*([\d.]+)\s*px", re.I)
_FONT_SIZE_DECL_RE = re.compile(
    r"(font-size\s*:\s*)([\d.]+)(\s*)(pt|px)", re.I
)
_LETTER_SPACING_DECL_RE = re.compile(
    r"(letter-spacing\s*:\s*)([\d.]+)(\s*)(pt|px)", re.I
)
_NOWRAP_RE = re.compile(r"white-space\s*:\s*nowrap", re.I)
_TITLE_ROLES = frozenset(
    {"page-title", "heading", "title", "cover-title", "section-title"}
)
# 缩字号下限：保版式可读性，再短则截断文案
_MIN_FONT_SCALE = 0.7


def _log(log: LogFn | None, msg: str) -> None:
    if log:
        log(msg if msg.endswith("\n") else msg + "\n")


def _css_to_px(value: float, unit: str) -> float:
    if (unit or "px").lower() == "pt":
        return value * (96.0 / 72.0)
    return value


def _fmt_css_num(n: float) -> str:
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _char_advance_px(ch: str, font_px: float) -> float:
    """Rough ink width for one glyph (CJK ≈ em, Latin ≈ 0.58em)."""
    if not ch:
        return 0.0
    o = ord(ch)
    if ch.isspace():
        return font_px * 0.33
    # CJK / fullwidth / kana / hangul
    if (
        0x1100 <= o <= 0x11FF
        or 0x2E80 <= o <= 0x9FFF
        or 0xAC00 <= o <= 0xD7AF
        or 0xF900 <= o <= 0xFAFF
        or 0xFF01 <= o <= 0xFF60
        or 0xFFE0 <= o <= 0xFFE6
    ):
        return font_px * 1.0
    return font_px * 0.58


def estimate_text_width_px(
    text: str,
    font_px: float,
    letter_spacing_px: float = 0.0,
) -> float:
    if not text or font_px <= 0:
        return 0.0
    chars = list(text.replace("\n", ""))
    if not chars:
        return 0.0
    w = sum(_char_advance_px(c, font_px) for c in chars)
    if len(chars) > 1 and letter_spacing_px:
        w += (len(chars) - 1) * letter_spacing_px
    return w


def parse_slot_box(attrs: str, content: str) -> dict[str, Any]:
    """Extract box geometry + typography from slot open attrs / inner HTML."""
    blob = f"{attrs or ''}\n{content or ''}"
    wm = _WIDTH_PX_RE.search(attrs or "") or _WIDTH_PX_RE.search(content or "")
    hm = _HEIGHT_PX_RE.search(attrs or "") or _HEIGHT_PX_RE.search(content or "")
    width_px = float(wm.group(1)) if wm else 0.0
    height_px = float(hm.group(1)) if hm else 0.0

    font_px = 0.0
    font_unit = "px"
    # Prefer innermost span font-size
    for m in _FONT_SIZE_DECL_RE.finditer(blob):
        font_px = _css_to_px(float(m.group(2)), m.group(4))
        font_unit = m.group(4).lower()
    letter_px = 0.0
    for m in _LETTER_SPACING_DECL_RE.finditer(blob):
        letter_px = _css_to_px(float(m.group(2)), m.group(4))

    nowrap = bool(_NOWRAP_RE.search(blob))
    line_h = max(font_px * 1.15, 1.0) if font_px > 0 else 1.0
    if nowrap or height_px <= 0 or font_px <= 0:
        lines = 1
    else:
        lines = max(1, int(height_px / line_h))

    return {
        "width_px": width_px,
        "height_px": height_px,
        "font_px": font_px,
        "font_unit": font_unit,
        "letter_spacing_px": letter_px,
        "nowrap": nowrap,
        "lines": lines,
    }


def estimate_max_chars(
    *,
    current: str,
    role: str,
    box: dict[str, Any] | None = None,
) -> int:
    """Hard budget for LLM + clamp: min(box capacity, slight growth from original)."""
    cur = (current or "").replace("\n", "")
    cur_len = max(0, len(cur))
    is_title = (role or "").strip().lower() in _TITLE_ROLES

    box_cap = 200
    if box and box.get("width_px", 0) > 0 and box.get("font_px", 0) > 0:
        # Conservative: assume CJK advance so Latin still fits
        avg = float(box["font_px"]) + float(box.get("letter_spacing_px") or 0)
        per_line = max(1, int((float(box["width_px"]) * 0.96) / max(avg, 1.0)))
        lines = int(box.get("lines") or 1)
        box_cap = max(1, per_line * max(1, lines))

    if cur_len > 0:
        growth = 1.1 if is_title else 1.25
        soft = max(cur_len, int(cur_len * growth + 0.999))
    else:
        soft = 24 if is_title else 60

    # Never ask for more than the box can hold; keep at least 1
    return max(1, min(200, box_cap, soft))


def clamp_text_to_max_chars(text: str, max_chars: int) -> str:
    """Clamp plain text to max_chars (newline-aware; keeps first N chars of content)."""
    raw = str(text or "")
    if max_chars <= 0 or len(raw.replace("\n", "")) <= max_chars:
        return raw
    # Prefer preserving line structure when multi-line
    lines = raw.splitlines()
    if len(lines) <= 1:
        return raw.replace("\n", "")[:max_chars]
    out: list[str] = []
    used = 0
    for ln in lines:
        if used >= max_chars:
            break
        room = max_chars - used
        if len(ln) <= room:
            out.append(ln)
            used += len(ln)
        else:
            if room > 0:
                out.append(ln[:room])
            break
    return "\n".join(out) if out else raw.replace("\n", "")[:max_chars]


def _scale_typography_in_fragment(content: str, scale: float) -> str:
    if scale >= 0.999 or scale <= 0:
        return content

    def _scale_decl(pattern: re.Pattern[str], s: str) -> str:
        def repl(m: re.Match[str]) -> str:
            v = float(m.group(2)) * scale
            return f"{m.group(1)}{_fmt_css_num(v)}{m.group(3)}{m.group(4)}"

        return pattern.sub(repl, s)

    out = _scale_decl(_FONT_SIZE_DECL_RE, content)
    out = _scale_decl(_LETTER_SPACING_DECL_RE, out)
    return out


def _truncate_to_width(
    text: str,
    max_width_px: float,
    font_px: float,
    letter_spacing_px: float,
) -> str:
    if estimate_text_width_px(text, font_px, letter_spacing_px) <= max_width_px:
        return text
    lo, hi = 0, len(text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = text[:mid]
        if estimate_text_width_px(cand, font_px, letter_spacing_px) <= max_width_px:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best or text[:1]


def fit_slot_inner(attrs: str, content: str) -> tuple[str, dict[str, Any]]:
    """Shrink font/letter-spacing (floor 70%), then truncate text if still overflows."""
    box = parse_slot_box(attrs, content)
    text = _plain_text_from_spans(content)
    info: dict[str, Any] = {
        "scaled": False,
        "truncated": False,
        "scale": 1.0,
    }
    width = float(box.get("width_px") or 0)
    font_px = float(box.get("font_px") or 0)
    ls = float(box.get("letter_spacing_px") or 0)
    if not text or width <= 0 or font_px <= 0:
        return content, info

    # Multi-line: budget by total capacity; single-line nowrap: width only
    lines = text.splitlines() if not box.get("nowrap") and "\n" in text else [text.replace("\n", " ").strip()]
    usable = width * 0.96
    line_budget = usable
    worst = max(
        (estimate_text_width_px(ln, font_px, ls) for ln in lines if ln),
        default=0.0,
    )
    if worst <= line_budget:
        return content, info

    scale = max(_MIN_FONT_SCALE, min(1.0, line_budget / max(worst, 1.0)))
    if scale < 0.999:
        content = _scale_typography_in_fragment(content, scale)
        font_px *= scale
        ls *= scale
        info["scaled"] = True
        info["scale"] = scale

    # Re-check; truncate longest overflowing line(s)
    text2 = _plain_text_from_spans(content)
    lines2 = (
        text2.splitlines()
        if not box.get("nowrap") and "\n" in text2
        else [text2.replace("\n", " ").strip()]
    )
    fixed: list[str] = []
    truncated = False
    for ln in lines2:
        if estimate_text_width_px(ln, font_px, ls) > line_budget:
            fixed.append(_truncate_to_width(ln, line_budget, font_px, ls))
            truncated = True
        else:
            fixed.append(ln)
    if truncated:
        content = _replace_span_texts(content, "\n".join(fixed))
        info["truncated"] = True
    return content, info



def _find_matching_close(html: str, open_end: int) -> int:
    """Return index after the closing </div> that matches the open tag ending at open_end."""
    i = open_end
    depth = 1
    lower = html.lower()
    n = len(html)
    while i < n and depth > 0:
        next_open = lower.find("<div", i)
        next_close = lower.find("</div>", i)
        if next_close < 0:
            return n
        if next_open >= 0 and next_open < next_close:
            # skip if it's a self-closing-ish or comment; treat as open
            gt = html.find(">", next_open)
            if gt < 0:
                return n
            # ignore </div already handled; only real opens
            if not lower.startswith("</", next_open):
                depth += 1
            i = gt + 1
            continue
        depth -= 1
        i = next_close + len("</div>")
    return i


def _plain_text_from_spans(inner: str) -> str:
    parts: list[str] = []
    for m in _SPAN_RE.finditer(inner):
        t = re.sub(r"\s+", " ", (m.group(2) or "")).strip()
        if t:
            parts.append(t)
    if parts:
        return "\n".join(parts)
    # fallback: strip tags
    text = re.sub(r"<[^>]+>", " ", inner)
    return re.sub(r"\s+", " ", text).strip()


def _replace_span_texts(inner: str, new_text: str) -> str:
    """Replace leaf span texts; distribute multi-line content across existing spans."""
    spans = list(_SPAN_RE.finditer(inner))
    if not spans:
        return inner
    lines = [ln.strip() for ln in str(new_text or "").splitlines() if ln.strip()]
    if not lines:
        lines = [str(new_text or "").strip() or " "]
    if len(spans) == 1:
        m = spans[0]
        joined = " ".join(lines) if len(lines) > 1 and "\n" not in (new_text or "") else "\n".join(lines)
        # single span: prefer space-join for one-liners
        if len(lines) == 1:
            joined = lines[0]
        else:
            # keep first line only in single-span boxes to avoid overflow
            joined = lines[0] if len("".join(lines)) > 80 else " ".join(lines)
        return inner[: m.start()] + m.group(1) + joined + m.group(3) + inner[m.end() :]

    out: list[str] = []
    last = 0
    for i, m in enumerate(spans):
        out.append(inner[last : m.start()])
        content = lines[i] if i < len(lines) else ("" if i > 0 else lines[0])
        if i == len(spans) - 1 and len(lines) > len(spans):
            content = " ".join(lines[i:])
        out.append(m.group(1) + content + m.group(3))
        last = m.end()
    out.append(inner[last:])
    return "".join(out)


def inventory_slide_slots(html: str, *, file: str) -> list[dict[str, Any]]:
    """Return text/image slots for one slide HTML."""
    slots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in _SLOT_OPEN_RE.finditer(html):
        attrs = m.group("attrs") or ""
        slot = (m.group("slot") or "").strip()
        if not slot:
            continue
        type_m = _TYPE_RE.search(attrs)
        slot_type = (type_m.group(1) if type_m else "text").strip().lower()
        role_m = _ROLE_RE.search(attrs)
        role = (role_m.group(1) if role_m else "").strip()
        open_end = m.end()
        close_end = _find_matching_close(html, open_end)
        inner = html[open_end:close_end]
        # trim trailing closing tag from inner for content ops
        close_tag = inner.rfind("</div>")
        content = inner[:close_tag] if close_tag >= 0 else inner
        key = f"{file}::{slot}"
        if key in seen:
            # uniquify duplicates
            n = 2
            while f"{file}::{slot}-{n}" in seen:
                n += 1
            slot = f"{slot}-{n}"
            key = f"{file}::{slot}"
        seen.add(key)
        if slot_type == "image":
            src_m = _IMG_SRC_RE.search(content)
            alt_m = _ALT_ATTR_RE.search(content)
            slots.append(
                {
                    "file": file,
                    "slot": slot,
                    "type": "image",
                    "role": role or "image",
                    "src": src_m.group(1) if src_m else "",
                    "filename": src_m.group(2) if src_m else "",
                    "current": (alt_m.group(1) if alt_m else "").strip(),
                    "max_chars": 120,
                }
            )
        else:
            text = _plain_text_from_spans(content)
            if not text and slot_type != "text":
                continue
            box = parse_slot_box(attrs, content)
            role_norm = role or "body"
            max_chars = estimate_max_chars(
                current=text, role=role_norm, box=box
            )
            slots.append(
                {
                    "file": file,
                    "slot": slot,
                    "type": "text",
                    "role": role_norm,
                    "current": text,
                    "max_chars": max_chars,
                    "box_width_px": round(float(box.get("width_px") or 0), 1),
                    "box_height_px": round(float(box.get("height_px") or 0), 1),
                    "font_px": round(float(box.get("font_px") or 0), 1),
                    "nowrap": bool(box.get("nowrap")),
                }
            )
    return slots


def inventory_package_slots(pack_dir: Path) -> list[dict[str, Any]]:
    meta = json.loads((pack_dir / "template.json").read_text(encoding="utf-8"))
    slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
    out: list[dict[str, Any]] = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        rel = str(slide.get("file") or "").strip()
        if not rel:
            continue
        path = pack_dir / rel
        if not path.is_file():
            continue
        html = path.read_text(encoding="utf-8")
        out.extend(inventory_slide_slots(html, file=rel))
    return out


def apply_text_to_html(
    html: str,
    updates: dict[str, str],
    *,
    fit: bool = True,
) -> str:
    """Apply slot→text map; preserve non-slot markup. Optionally fit font/truncate."""
    if not updates:
        return html
    # Process from end to start so indices stay valid
    matches: list[tuple[int, int, int, str, str, str]] = []
    for m in _SLOT_OPEN_RE.finditer(html):
        attrs = m.group("attrs") or ""
        slot = (m.group("slot") or "").strip()
        type_m = _TYPE_RE.search(attrs)
        slot_type = (type_m.group(1) if type_m else "text").strip().lower()
        if slot_type == "image":
            continue
        if slot not in updates:
            continue
        open_start = m.start()
        open_end = m.end()
        close_end = _find_matching_close(html, open_end)
        matches.append((open_start, open_end, close_end, slot, updates[slot], attrs))

    # de-dupe by slot keeping first occurrence order but apply last-to-first by position
    matches.sort(key=lambda x: x[0], reverse=True)
    used: set[str] = set()
    out = html
    for open_start, open_end, close_end, slot, new_text, attrs in matches:
        if slot in used:
            continue
        used.add(slot)
        inner_with_close = out[open_end:close_end]
        close_tag = inner_with_close.rfind("</div>")
        if close_tag < 0:
            continue
        content = inner_with_close[:close_tag]
        tail = inner_with_close[close_tag:]
        new_content = _replace_span_texts(content, new_text)
        if fit:
            new_content, _info = fit_slot_inner(attrs, new_content)
        out = out[:open_end] + new_content + tail + out[close_end:]
    return out


def clamp_texts_for_slots(
    texts: dict[str, str],
    slots: list[dict[str, Any]],
) -> dict[str, str]:
    """Hard-clamp planned texts to each slot's max_chars."""
    by_slot = {
        str(s["slot"]): s
        for s in slots
        if s.get("type") == "text" and s.get("slot")
    }
    out: dict[str, str] = {}
    for key, val in texts.items():
        slot_meta = by_slot.get(str(key))
        text = str(val)
        if slot_meta:
            max_c = int(slot_meta.get("max_chars") or 0)
            if max_c > 0:
                text = clamp_text_to_max_chars(text, max_c)
        out[str(key)] = text
    return out


def apply_image_hints_to_html(
    html: str, updates: dict[str, str]
) -> tuple[str, list[str]]:
    """Update image slot alt/prompts; return (html, filenames to regenerate)."""
    regen: list[str] = []
    if not updates:
        return html, regen
    matches: list[tuple[int, int, int, str, str]] = []
    for m in _SLOT_OPEN_RE.finditer(html):
        attrs = m.group("attrs") or ""
        slot = (m.group("slot") or "").strip()
        type_m = _TYPE_RE.search(attrs)
        slot_type = (type_m.group(1) if type_m else "text").strip().lower()
        if slot_type != "image" or slot not in updates:
            continue
        open_end = m.end()
        close_end = _find_matching_close(html, open_end)
        matches.append((m.start(), open_end, close_end, slot, updates[slot]))
    matches.sort(key=lambda x: x[0], reverse=True)
    used: set[str] = set()
    out = html
    for _os, open_end, close_end, slot, hint in matches:
        if slot in used:
            continue
        used.add(slot)
        region = out[open_end:close_end]
        src_m = _IMG_SRC_RE.search(region)
        if src_m:
            regen.append(src_m.group(2))
        hint_clean = re.sub(r"\s+", " ", hint).strip()[:300]

        if _ALT_ATTR_RE.search(region):
            region2 = _ALT_ATTR_RE.sub(lambda _am: f'alt="{hint_clean}"', region, count=1)
        else:
            # inject alt onto first img-like tag
            region2 = re.sub(
                r"(<(?:img|image|div)\b)",
                rf'\1 alt="{hint_clean}"',
                region,
                count=1,
                flags=re.I,
            )
        out = out[:open_end] + region2 + out[close_end:]
    return out, regen


def _copy_package(source_dir: Path, dest: Path) -> None:
    """Copy pack; never merge into an existing directory."""
    if dest.exists():
        raise FileExistsError(str(dest))
    shutil.copytree(source_dir, dest)


def _mock_fill(slots: list[dict[str, Any]], prompt: str) -> dict[str, Any]:
    short = re.sub(r"\s+", " ", prompt).strip()[:24] or "新主题"
    texts: dict[str, dict[str, str]] = {}
    images: dict[str, dict[str, str]] = {}
    for s in slots:
        file = str(s["file"])
        if s["type"] == "image":
            images.setdefault(file, {})[s["slot"]] = f"{short} · {s.get('role') or 'image'}"
        else:
            role = str(s.get("role") or "body")
            cur = str(s.get("current") or "")
            max_c = int(s.get("max_chars") or 40)
            if role in {"page-title", "heading", "title"}:
                val = short[:max_c]
            elif role in {"lede", "subtitle"}:
                val = f"{short}相关内容与要点"[:max_c]
            else:
                val = (f"{short}：{cur}" if cur else short)[:max_c]
            texts.setdefault(file, {})[s["slot"]] = val
    return {
        "label_zh": short,
        "description_zh": f"基于模板改写：{short}",
        "texts": texts,
        "images": images,
    }


def _plan_content(
    *,
    prompt: str,
    slots: list[dict[str, Any]],
    source_label: str,
    pages: list[dict[str, Any]],
    visual_brief: str,
    mock: bool,
    log: LogFn | None,
) -> dict[str, Any]:
    if mock or is_mock():
        return _mock_fill(slots, prompt)

    compact_slots = [
        {
            "file": s["file"],
            "slot": s["slot"],
            "type": s["type"],
            "role": s.get("role"),
            "current": (s.get("current") or "")[:160],
            "max_chars": s.get("max_chars"),
            "box": (
                f"{int(s.get('box_width_px') or 0)}×{int(s.get('box_height_px') or 0)}px"
                if s.get("type") == "text"
                else None
            ),
        }
        for s in slots
    ]
    page_outline = [
        {
            "file": p.get("file"),
            "title": p.get("title"),
            "layout": p.get("layout"),
        }
        for p in pages
        if isinstance(p, dict)
    ]
    system = (
        "你是模板内容改写器。只输出 JSON。"
        "必须保留参考模板的页数、版式与槽位；只改文案与配图主题。"
        "禁止新增/删除 slot；禁止改颜色、布局或装饰。"
    )
    user = f"""参考模板：{source_label}
用户新主题/要求：
{prompt}

视觉规范摘要（只作语气参考，不要改版式）：
{(visual_brief or '')[:3500]}

页面列表：
{json.dumps(page_outline, ensure_ascii=False)}

可写槽位（必须全部覆盖 text；image 给生图提示词）：
{json.dumps(compact_slots, ensure_ascii=False)}

输出 JSON：
{{
  "label_zh": "新模板中文名（内容主题，不要写风格词）",
  "description_zh": "一句话描述",
  "texts": {{ "slides/cover.html": {{ "title": "新文案", "subtitle": "..." }} }},
  "images": {{ "slides/cover.html": {{ "hero-image": "英文或中文生图提示，描述画面内容" }} }}
}}
约束：
1. texts 的每个 file/slot 必须出现；文案字符数（不含换行）必须 ≤ max_chars，宁可短不可超。
2. 标题/短标签保持短句；不要硬塞长句进窄槽。
3. 不要输出 HTML；不要解释。
4. 数字/指标可按新主题合理改写。
"""
    from config import llm_config

    cfg = llm_config()
    pool = make_client_pool(cfg)
    _log(log, f"[remix] planning slots={len(slots)} model={cfg.model}")
    raw = chat_json(
        pool=pool,
        model=cfg.model,
        system=system,
        user=user,
        temperature=0.4,
    )
    if not isinstance(raw, dict):
        raise RuntimeError("remix plan 不是 JSON 对象")
    return raw


def remix_template_package(
    source_dir: Path,
    *,
    prompt: str,
    out_root: Path | None = None,
    mock: bool | None = None,
    skip_images: bool = False,
    status: str = "pending",
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Clone source pack and rewrite text/image slots for prompt."""
    load_env()
    source_dir = source_dir.resolve()
    if not (source_dir / "template.json").is_file():
        raise FileNotFoundError(f"不是有效模板包：{source_dir}")
    use_mock = is_mock() if mock is None else bool(mock)
    out_root = (out_root or source_dir.parent).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    meta = json.loads((source_dir / "template.json").read_text(encoding="utf-8"))
    source_id = str(meta.get("template_id") or source_dir.name)
    source_label = str((meta.get("label") or {}).get("zh_CN") or source_id)
    pages = meta.get("slides") if isinstance(meta.get("slides"), list) else []

    spec_path = source_dir / "visual-spec.md"
    if not spec_path.is_file() or not spec_path.read_text(encoding="utf-8").strip():
        raise RuntimeError(
            "源模板缺少 visual-spec.md（或内容为空）。"
            "请先生成设计规范后再套用模板。"
        )

    visual_brief = ""
    for name in ("visual-spec.md", "theme.css"):
        p = source_dir / name
        if p.is_file():
            visual_brief += f"\n## {name}\n" + p.read_text(encoding="utf-8")[:4000]

    slots = inventory_package_slots(source_dir)
    text_slots = [s for s in slots if s["type"] == "text"]
    image_slots = [s for s in slots if s["type"] == "image"]
    _log(
        log,
        f"[remix] source={source_id} text_slots={len(text_slots)} "
        f"image_slots={len(image_slots)} skip_images={skip_images}",
    )
    if not text_slots and not image_slots:
        raise RuntimeError(
            "源模板没有 data-slot 文本/图片槽，无法做保版式改写。"
            "请换用带 data-slot 的 ppt-master 包，或先重新转换。"
        )

    plan = _plan_content(
        prompt=prompt,
        slots=slots,
        source_label=source_label,
        pages=pages if isinstance(pages, list) else [],
        visual_brief=visual_brief,
        mock=use_mock,
        log=log,
    )
    label_zh = str(plan.get("label_zh") or "").strip() or f"{source_label}-改写"
    desc_zh = str(plan.get("description_zh") or "").strip() or f"基于「{source_label}」改写"
    texts_by_file = plan.get("texts") if isinstance(plan.get("texts"), dict) else {}
    images_by_file = plan.get("images") if isinstance(plan.get("images"), dict) else {}

    new_id = alloc_public_template_id(out_root)
    dest = out_root / new_id
    for _ in range(8):
        if not dest.exists():
            break
        new_id = alloc_public_template_id(out_root)
        dest = out_root / new_id
    _log(log, f"[remix] cloning → {dest.name}")
    try:
        _copy_package(source_dir, dest)
    except FileExistsError:
        new_id = alloc_public_template_id(out_root)
        dest = out_root / new_id
        _log(log, f"[remix] dest busy, retry → {dest.name}")
        _copy_package(source_dir, dest)

    # drop qiniu/upload provenance from clone
    try:
        new_meta = json.loads((dest / "template.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"克隆后 template.json 损坏: {e}") from e

    regen_files: list[str] = []
    for slide in pages if isinstance(pages, list) else []:
        if not isinstance(slide, dict):
            continue
        rel = str(slide.get("file") or "").strip()
        if not rel:
            continue
        path = dest / rel
        if not path.is_file():
            continue
        html = path.read_text(encoding="utf-8")
        file_texts = texts_by_file.get(rel) if isinstance(texts_by_file.get(rel), dict) else {}
        # also accept flat keys without path prefix
        if not file_texts:
            file_texts = {
                s["slot"]: texts_by_file.get(s["slot"])
                for s in text_slots
                if s["file"] == rel and isinstance(texts_by_file.get(s["slot"]), str)
            }
        file_texts = {str(k): str(v) for k, v in (file_texts or {}).items() if v is not None}
        file_slots = [s for s in text_slots if s["file"] == rel]
        file_texts = clamp_texts_for_slots(file_texts, file_slots)
        html = apply_text_to_html(html, file_texts, fit=True)

        file_imgs = images_by_file.get(rel) if isinstance(images_by_file.get(rel), dict) else {}
        file_imgs = {str(k): str(v) for k, v in (file_imgs or {}).items() if v}
        if file_imgs and not skip_images:
            html, regen = apply_image_hints_to_html(html, file_imgs)
            regen_files.extend(regen)
        path.write_text(html if html.endswith("\n") else html + "\n", encoding="utf-8")

        # update slide title from page-title / title slot when present
        title_val = (
            file_texts.get("title")
            or file_texts.get("page-title")
            or next((file_texts[k] for k in file_texts if "title" in k), None)
        )
        if title_val:
            slide["title"] = str(title_val)[:80]

    new_meta["template_id"] = new_id
    new_meta["public_id"] = new_id
    new_meta["label"] = {"zh_CN": label_zh, "en_US": label_zh}
    new_meta["description"] = {
        "zh_CN": desc_zh,
        "en_US": desc_zh,
    }
    from templates.categories import coerce_category

    # remix 保留源模板视觉类型（= 风格）
    new_meta["category"] = coerce_category(
        new_meta.get("category")
        or (plan.get("visual_style") if isinstance(plan, dict) else None)
        or (plan.get("category") if isinstance(plan, dict) else None)
    )
    new_meta["status"] = (
        "approved" if str(status).strip().lower() == "approved" else "pending"
    )
    new_meta["source_template_id"] = source_id
    new_meta["remix"] = {
        "mode": "content-slots",
        "source_template_id": source_id,
        "prompt": prompt[:2000],
    }
    new_meta.pop("storage", None)
    new_meta.pop("preview", None)
    if isinstance(pages, list):
        new_meta["slides"] = pages

    # force image regen: delete listed files so materialize rewrites them
    if regen_files and not skip_images and not use_mock:
        images_dir = dest / "images"
        for name in set(regen_files):
            fp = images_dir / name
            if fp.is_file():
                try:
                    fp.unlink()
                except OSError:
                    pass
        _log(log, f"[remix] rematerialize images ×{len(set(regen_files))}")
        try:
            from templates.write import rematerialize_package_images

            warnings = rematerialize_package_images(dest)
            for w in warnings:
                _log(log, f"[remix] image warn: {w}")
        except Exception as e:
            _log(log, f"[remix] image rematerialize skipped: {e}")
    elif skip_images:
        _log(log, "[remix] images kept (skip)")

    (dest / "template.json").write_text(
        json.dumps(new_meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # Bump directory mtime so Admin list (sorted by folder time) surfaces this pack.
    try:
        os.utime(dest, None)
    except OSError:
        pass
    _log(log, f"[remix] wrote {dest}")
    _log(log, f"[progress] done=1 total=1 ok=1 fail=0 skip=0 id={new_id} status=ok")
    return {
        "ok": True,
        "template_id": new_id,
        "output_dir": str(dest),
        "source_template_id": source_id,
        "text_slots": len(text_slots),
        "image_slots": len(image_slots),
        "label_zh": label_zh,
    }


def run_remix(
    source_id: str,
    prompt: str,
    *,
    out_root: Path | None = None,
    mock: bool | None = None,
    skip_images: bool = False,
    status: str = "pending",
    log: LogFn | None = None,
) -> dict[str, Any]:
    from ppt_master.paths import repo_root

    default_root = (repo_root() / "agent-output").resolve()
    root = (out_root or default_root).resolve()
    source_dir = Path(source_id)
    if not source_dir.is_absolute():
        # Prefer canonical catalog under agent-output/, even when writing elsewhere.
        candidate = default_root / source_id
        if (candidate / "template.json").is_file():
            source_dir = candidate
        else:
            source_dir = root / source_id
    return remix_template_package(
        source_dir,
        prompt=prompt,
        out_root=root,
        mock=mock,
        skip_images=skip_images,
        status=status,
        log=log,
    )
