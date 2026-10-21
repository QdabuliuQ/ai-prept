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
from image.generate import normalize_img_object_fit

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
# 缩字号下限：优先缩字再截断，减少「服务继」类半截词
_MIN_FONT_SCALE = 0.55
_LEFT_PX_RE = re.compile(r"\bleft\s*:\s*([\d.]+)\s*px", re.I)
_TOP_PX_RE = re.compile(r"\btop\s*:\s*([\d.]+)\s*px", re.I)
# 序号 / 百分比 / 装饰符：多 span 时保留，避免被当成正文清空或叠字
_META_SPAN_RE = re.compile(
    r"^(?:"
    r"\d{1,3}"
    r"|0\d"
    r"|[０-９]{1,3}"
    r"|\d{1,3}\s*%"
    r"|[０-９]{1,3}\s*%"
    r"|[·•●○◆◇■□]"
    r"|[A-Za-z]"
    r"|第[一二三四五六七八九十\d]+"
    r")$"
)


def _lookup_file_map(by_file: dict[str, Any] | Any, rel: str) -> dict[str, Any]:
    """Resolve per-slide map; tolerate basename / alternate path keys from LLM."""
    if not isinstance(by_file, dict):
        return {}
    direct = by_file.get(rel)
    if isinstance(direct, dict):
        return direct
    base = Path(rel).name
    for key, val in by_file.items():
        if not isinstance(val, dict):
            continue
        k = str(key).strip().replace("\\", "/")
        if k == base or k.endswith("/" + base) or Path(k).name == base:
            return val
    return {}


def _write_template_meta(dest: Path, meta: dict[str, Any]) -> None:
    (dest / "template.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
        return font_px * 1.02
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
    lm = _LEFT_PX_RE.search(attrs or "")
    tm = _TOP_PX_RE.search(attrs or "")
    left_px = float(lm.group(1)) if lm else 0.0
    top_px = float(tm.group(1)) if tm else 0.0

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
    # Multi-span column titles often set white-space:nowrap per row — that must
    # NOT collapse the slot to a single-line char budget (or we truncate to「半」).
    prose_spans = _prose_span_count(content or "")
    if prose_spans > 1:
        lines = prose_spans
    elif nowrap or height_px <= 0 or font_px <= 0:
        lines = 1
    else:
        lines = max(1, int(height_px / line_h))

    return {
        "width_px": width_px,
        "height_px": height_px,
        "left_px": left_px,
        "top_px": top_px,
        "font_px": font_px,
        "font_unit": font_unit,
        "letter_spacing_px": letter_px,
        "nowrap": nowrap,
        "lines": lines,
    }


def _prose_span_count(content: str) -> int:
    """Count non-meta leaf spans (title/body lines), ignoring 01 / 45% / bullets."""
    n = 0
    for m in _SPAN_RE.finditer(content or ""):
        if not _is_keep_meta_span(m.group(2) or ""):
            n += 1
    return n


def estimate_max_chars(
    *,
    current: str,
    role: str,
    box: dict[str, Any] | None = None,
) -> int:
    """Hard budget for LLM + clamp: prefer box capacity (after font shrink), not tiny originals."""
    cur = (current or "").replace("\n", "")
    cur_len = max(0, len(cur))
    is_title = (role or "").strip().lower() in _TITLE_ROLES

    box_cap = 200
    if box and box.get("width_px", 0) > 0 and box.get("font_px", 0) > 0:
        # Assume post-fit min font (~55%) so LLM may write slightly fuller short phrases
        font_for_cap = max(
            float(box["font_px"]) * _MIN_FONT_SCALE,
            float(box["font_px"]) * 0.7,
        )
        avg = font_for_cap + float(box.get("letter_spacing_px") or 0) * _MIN_FONT_SCALE
        per_line = max(1, int((float(box["width_px"]) * 0.94) / max(avg, 1.0)))
        lines = int(box.get("lines") or 1)
        box_cap = max(1, per_line * max(1, lines))

    if cur_len > 0:
        growth = 1.4 if is_title else 1.6
        soft = max(cur_len, int(cur_len * growth + 0.999))
    else:
        soft = 28 if is_title else 72

    # Use most of the geometric budget; soft floor only when box is huge/unknown
    if box and box.get("width_px", 0) > 0:
        return max(1, min(200, max(soft, int(box_cap * 0.9)), box_cap))
    return max(1, min(200, soft))


def clamp_text_to_max_chars(text: str, max_chars: int) -> str:
    """Clamp plain text to max_chars; prefer sentence/phrase boundaries."""
    raw = str(text or "")
    if max_chars <= 0 or len(raw.replace("\n", "")) <= max_chars:
        return raw
    # Prefer preserving line structure when multi-line
    lines = raw.splitlines()
    if len(lines) <= 1:
        return _cut_at_phrase_boundary(raw.replace("\n", ""), max_chars)
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
                cut = _cut_at_phrase_boundary(ln, room)
                # Avoid orphan single-char second lines like「半」from a hard cut.
                if len(cut) <= 1 and len(ln) > 1:
                    break
                out.append(cut)
            break
    if len(out) >= 2 and len(out[-1]) <= 1:
        out = out[:-1]
    return "\n".join(out) if out else _cut_at_phrase_boundary(
        raw.replace("\n", ""), max_chars
    )


_PHRASE_END_STRONG = set("。！？!?；;")
_PHRASE_END_WEAK = set("，、,：:")


def _cut_at_phrase_boundary(text: str, max_chars: int) -> str:
    """Cut to max_chars but prefer ending on punctuation so copy stays readable."""
    s = (text or "").strip()
    if max_chars <= 0 or len(s) <= max_chars:
        return s
    hard = s[:max_chars].rstrip()
    if not hard:
        return s[:1]
    # Prefer last strong sentence end in the second half of the budget
    min_keep = max(1, max_chars // 2)
    best = -1
    for i in range(len(hard) - 1, min_keep - 1, -1):
        if hard[i] in _PHRASE_END_STRONG:
            best = i
            break
    if best < 0:
        for i in range(len(hard) - 1, min_keep - 1, -1):
            if hard[i] in _PHRASE_END_WEAK:
                best = i
                break
    if best >= 0:
        return hard[: best + 1].rstrip()
    return hard


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
    if not best:
        return text[:1]
    # Prefer a complete phrase over a mid-word stump like 「带入日」
    cut = _cut_at_phrase_boundary(best, len(best))
    if cut and estimate_text_width_px(cut, font_px, letter_spacing_px) <= max_width_px:
        return cut
    return best.rstrip() or text[:1]


def fit_slot_inner(attrs: str, content: str) -> tuple[str, dict[str, Any]]:
    """Shrink font/letter-spacing (floor 55%), then truncate text if still overflows."""
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

    # Newlines always define visual rows. nowrap only means each row is one line
    # (no soft-wrap) — never join multi-line titles into a single width budget.
    if "\n" in text:
        lines = text.splitlines()
    else:
        lines = [text]
    usable = width * 0.94
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

    # Re-check; truncate overflowing line(s) individually
    text2 = _plain_text_from_spans(content)
    lines2 = text2.splitlines() if "\n" in text2 else [text2]
    fixed: list[str] = []
    truncated = False
    for ln in lines2:
        if estimate_text_width_px(ln, font_px, ls) > line_budget:
            cut = _truncate_to_width(ln, line_budget, font_px, ls)
            if len(cut) <= 1 and len(ln) > 1:
                # Prefer dropping an unreadable stump over keeping「半」
                truncated = True
                continue
            fixed.append(cut)
            truncated = True
        else:
            fixed.append(ln)
    if truncated:
        content = _replace_span_texts(content, "\n".join(fixed))
        info["truncated"] = True
    return content, info


def _is_keep_meta_span(text: str) -> bool:
    """True for index/percent/bullet runs that should survive multi-span rewrites."""
    t = re.sub(r"\s+", "", (text or "").strip())
    if not t:
        return True
    if _META_SPAN_RE.match(t):
        return True
    if len(t) <= 4 and t.endswith("%") and t[:-1].replace(".", "").isdigit():
        return True
    return False


def _primary_span_index(spans: list[re.Match[str]]) -> int:
    """Prefer the longest non-meta span as the rewrite target."""
    best_i, best_len = 0, -1
    for i, m in enumerate(spans):
        t = (m.group(2) or "").strip()
        if _is_keep_meta_span(t):
            continue
        if len(t) > best_len:
            best_len = len(t)
            best_i = i
    if best_len < 0:
        return max(0, len(spans) - 1)
    return best_i


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
    """Replace leaf span texts; distribute multi-line content across existing spans.

    Meta spans (01 / 45% / bullets) are kept. Extra prose spans are cleared when the
    model returns fewer lines than spans — keeps cards filled without stacking old
    copy on top of new copy (overlap).
    """
    spans = list(_SPAN_RE.finditer(inner))
    if not spans:
        return inner
    raw = str(new_text or "").strip()
    if not raw:
        return inner
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return inner
    if len(spans) == 1:
        m = spans[0]
        if len(lines) == 1:
            joined = lines[0]
        else:
            joined = lines[0] if len("".join(lines)) > 80 else " ".join(lines)
        return inner[: m.start()] + m.group(1) + joined + m.group(3) + inner[m.end() :]

    meta_flags = [_is_keep_meta_span(m.group(2) or "") for m in spans]
    prose_indices = [i for i, is_meta in enumerate(meta_flags) if not is_meta]

    def _rebuild(assign: dict[int, str]) -> str:
        out: list[str] = []
        last = 0
        for i, m in enumerate(spans):
            out.append(inner[last : m.start()])
            if i in assign:
                content = assign[i]
            elif meta_flags[i]:
                content = m.group(2) or ""
            else:
                content = ""
            out.append(m.group(1) + content + m.group(3))
            last = m.end()
        out.append(inner[last:])
        return "".join(out)

    # One blob: write into primary prose span; keep meta; clear other prose
    if len(lines) == 1:
        primary = _primary_span_index(spans)
        return _rebuild({primary: lines[0]})

    # Multi-line: map onto prose spans in order; leftover lines join into last prose
    assign: dict[int, str] = {}
    if not prose_indices:
        assign[len(spans) - 1] = "\n".join(lines)
        return _rebuild(assign)
    for i, span_i in enumerate(prose_indices):
        if i >= len(lines):
            break
        if i == len(prose_indices) - 1 and len(lines) > len(prose_indices):
            assign[span_i] = " ".join(lines[i:])
        else:
            assign[span_i] = lines[i]
    return _rebuild(assign)


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
            span_n = len(list(_SPAN_RE.finditer(content)))
            slots.append(
                {
                    "file": file,
                    "slot": slot,
                    "type": "text",
                    "role": role_norm,
                    "current": text,
                    "max_chars": max_chars,
                    "span_count": span_n,
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


_OVERFLOW_HIDDEN_RE = re.compile(
    r"overflow\s*:\s*hidden(?:\s+(?:hidden|visible|auto|scroll|clip))*",
    re.I,
)


def _relax_text_slot_open_tag(open_tag: str) -> str:
    """Text slots: overflow:hidden 会裁切首尾字形；改为 visible。"""
    if re.search(r"""data-slot-type\s*=\s*["']image["']""", open_tag, re.I):
        return open_tag
    return _OVERFLOW_HIDDEN_RE.sub("overflow: visible", open_tag)


def resolve_horizontal_slot_collisions(html: str) -> str:
    """If same-row text slots' ink overlaps, shrink/truncate the left slot."""
    collected: list[dict[str, Any]] = []
    for m in _SLOT_OPEN_RE.finditer(html):
        attrs = m.group("attrs") or ""
        slot = (m.group("slot") or "").strip()
        type_m = _TYPE_RE.search(attrs)
        slot_type = (type_m.group(1) if type_m else "text").strip().lower()
        if slot_type == "image" or not slot:
            continue
        open_end = m.end()
        close_end = _find_matching_close(html, open_end)
        inner = html[open_end:close_end]
        close_tag = inner.rfind("</div>")
        content = inner[:close_tag] if close_tag >= 0 else inner
        box = parse_slot_box(attrs, content)
        text = _plain_text_from_spans(content)
        font = float(box.get("font_px") or 0)
        ls = float(box.get("letter_spacing_px") or 0)
        width = float(box.get("width_px") or 0)
        left = float(box.get("left_px") or 0)
        top = float(box.get("top_px") or 0)
        height = float(box.get("height_px") or 0) or max(font * 1.25, 1.0)
        if not text or width <= 0 or font <= 0:
            continue
        first = text.splitlines()[0]
        ink_w = estimate_text_width_px(first, font, ls)
        collected.append(
            {
                "slot": slot,
                "open_start": m.start(),
                "open_end": open_end,
                "close_end": close_end,
                "attrs": attrs,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
                "font_px": font,
                "ls": ls,
                "text": text,
                "ink_w": ink_w,
            }
        )
    if len(collected) < 2:
        return html

    collected.sort(key=lambda s: (s["top"], s["left"], s["open_start"]))
    budget: dict[str, float] = {}
    for i, a in enumerate(collected):
        for b in collected[i + 1 :]:
            row_tol = 0.45 * min(a["height"], b["height"])
            if abs(a["top"] - b["top"]) > row_tol:
                if b["top"] > a["top"] + a["height"]:
                    break
                continue
            if a["left"] >= b["left"]:
                continue
            limit = min(a["width"] * 0.98, b["left"] - a["left"] - 10.0)
            if limit < 8:
                continue
            if a["ink_w"] > limit:
                prev = budget.get(a["slot"], a["ink_w"])
                budget[a["slot"]] = min(prev, limit)

    if not budget:
        return html

    by_slot = {s["slot"]: s for s in collected}
    ordered = sorted(
        (by_slot[k] for k in budget if k in by_slot),
        key=lambda s: s["open_start"],
        reverse=True,
    )
    out = html
    for s in ordered:
        max_w = budget[s["slot"]]
        open_start = int(s["open_start"])
        open_end = int(s["open_end"])
        close_end = int(s["close_end"])
        inner_with_close = out[open_end:close_end]
        close_tag = inner_with_close.rfind("</div>")
        if close_tag < 0:
            continue
        content = inner_with_close[:close_tag]
        tail = inner_with_close[close_tag:]
        lines = (s["text"] or "").splitlines() or [s["text"]]
        cut = _truncate_to_width(lines[0], max_w, float(s["font_px"]), float(s["ls"]))
        if cut == lines[0]:
            # still try font shrink against neighbor budget
            fake_attrs = s["attrs"]
            if _WIDTH_PX_RE.search(fake_attrs or ""):
                fake_attrs = _WIDTH_PX_RE.sub(
                    f"width: {_fmt_css_num(max_w)}px", fake_attrs, count=1
                )
            else:
                fake_attrs = f'{fake_attrs} style="width:{_fmt_css_num(max_w)}px"'
            new_content, info = fit_slot_inner(fake_attrs, content)
            if not info.get("scaled") and not info.get("truncated"):
                continue
        else:
            lines[0] = cut
            new_content = _replace_span_texts(content, "\n".join(lines))
            fake_attrs = s["attrs"]
            if _WIDTH_PX_RE.search(fake_attrs or ""):
                fake_attrs = _WIDTH_PX_RE.sub(
                    f"width: {_fmt_css_num(max_w)}px", fake_attrs, count=1
                )
            new_content, _info = fit_slot_inner(fake_attrs, new_content)
        open_tag = _relax_text_slot_open_tag(out[open_start:open_end])
        out = out[:open_start] + open_tag + new_content + tail + out[close_end:]
    return out


def apply_text_to_html(
    html: str,
    updates: dict[str, str],
    *,
    fit: bool = True,
    resolve_collisions: bool = True,
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
        open_tag = _relax_text_slot_open_tag(out[open_start:open_end])
        out = out[:open_start] + open_tag + new_content + tail + out[close_end:]
    if resolve_collisions:
        out = resolve_horizontal_slot_collisions(out)
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


def _lookup_slot_text(
    texts_by_file: dict[str, Any] | Any,
    *,
    file: str,
    slot: str,
) -> str | None:
    """Resolve planned text for one slot; tolerate basename keys / flat maps."""
    if not isinstance(texts_by_file, dict):
        return None
    file_map = _lookup_file_map(texts_by_file, file)
    if file_map and slot in file_map and file_map[slot] is not None:
        return str(file_map[slot])
    # flat: { "title": "..." } at top level (rare)
    if slot in texts_by_file and not isinstance(texts_by_file.get(slot), dict):
        return str(texts_by_file[slot])
    return None


def missing_text_slots(
    slots: list[dict[str, Any]],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Text slots with missing or blank planned copy."""
    texts = plan.get("texts") if isinstance(plan.get("texts"), dict) else {}
    missing: list[dict[str, Any]] = []
    for s in slots:
        if s.get("type") != "text":
            continue
        val = _lookup_slot_text(texts, file=str(s["file"]), slot=str(s["slot"]))
        if val is None or not str(val).strip():
            missing.append(s)
    return missing


def merge_remix_plans(
    base: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Merge patch texts/images into base; non-empty patch values win."""
    out = dict(base) if isinstance(base, dict) else {}
    for meta_key in ("label_zh", "description_zh"):
        patch_val = str((patch or {}).get(meta_key) or "").strip()
        if patch_val and not str(out.get(meta_key) or "").strip():
            out[meta_key] = patch_val

    def _merge_nested(key: str) -> None:
        base_map = out.get(key) if isinstance(out.get(key), dict) else {}
        patch_map = (patch or {}).get(key) if isinstance((patch or {}).get(key), dict) else {}
        merged: dict[str, Any] = {
            str(fk): dict(fv) if isinstance(fv, dict) else {}
            for fk, fv in base_map.items()
            if isinstance(fv, dict)
        }
        for fk, fv in patch_map.items():
            if not isinstance(fv, dict):
                continue
            dest = merged.setdefault(str(fk), {})
            for sk, sv in fv.items():
                if sv is None:
                    continue
                text = str(sv).strip()
                if not text:
                    continue
                dest[str(sk)] = str(sv)
        out[key] = merged

    _merge_nested("texts")
    _merge_nested("images")
    return out


def _compact_slot_row(s: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "file": s["file"],
        "slot": s["slot"],
        "type": s["type"],
        "role": s.get("role"),
        "current": (s.get("current") or "")[:160],
        "max_chars": s.get("max_chars"),
    }
    if s.get("type") == "text":
        row["box"] = (
            f"{int(s.get('box_width_px') or 0)}×{int(s.get('box_height_px') or 0)}px"
        )
        span_n = int(s.get("span_count") or 0)
        if span_n > 1:
            row["span_count"] = span_n
            row["hint"] = f"若含 {span_n} 行原文，请用换行输出等量短句"
    elif s.get("type") == "image":
        row["hint"] = (
            "只改画面主体/场景；色温与明暗须服从 visual-spec「配图色调」与 theme，勿自创相反色板"
        )
    return row


def _plan_content_once(
    *,
    prompt: str,
    slots: list[dict[str, Any]],
    source_label: str,
    pages: list[dict[str, Any]],
    visual_brief: str,
    log: LogFn | None,
    temperature: float = 0.4,
    focus_missing: bool = False,
) -> dict[str, Any]:
    compact_slots = [_compact_slot_row(s) for s in slots]
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
        "必须保留参考模板的页数、版式与槽位；只改文案与配图「画面内容」。"
        "禁止新增/删除 slot；禁止改颜色、布局或装饰。"
        "配图色调/明暗必须服从 visual-spec「配图色调」与 theme（米色偏亮、暗色偏低，以规范为准）；"
        "禁止自创与规范相反的色板。"
        "visual-spec 里若出现原包题材/隐喻（星轨、夜空、某行业故事等），一律忽略；"
        "配图主体只跟用户新主题走，不要为了「像原模板故事」而硬套隐喻。"
        "禁止空字符串；每个 text slot 必须非空。"
    )
    focus_note = ""
    if focus_missing:
        focus_note = (
            "\n【补全模式】上一轮漏填了下列槽位。"
            "只输出这些 file/slot 的 texts（可附带 images）；"
            "每个都必须非空，且同页平行条目不可只填一组。\n"
        )
    user = f"""参考模板：{source_label}
用户新主题/要求：
{prompt}
{focus_note}
视觉规范与 theme（版式锁定；插图色调/材质也必须服从，不要改版式）：
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
  "images": {{ "slides/cover.html": {{ "hero-image": "只写新主体/场景，勿写新色板" }} }}
}}
约束：
1. texts 的每个 file/slot 必须出现且非空；文案字符数（不含换行）必须 ≤ max_chars，宁可短不可超。
2. 每个槽位只写完整可读短句/短语；禁止半截词、半截句，禁止把两句硬塞进窄槽。
3. 标题/短标签保持短句；装不下就换更短的完整表达，不要靠截断。
4. 同一页若有多组平行条目（对比列表、多行卡片），每一组的每个 slot 都必须写互不相同的非空文案，禁止只填第一组、其余留空。
5. span_count>1 时用换行输出对应行数的短句（标题一行、说明一行）；禁止把标题和正文粘成一句塞进同一槽。
6. 并排短标题槽只写能装下的完整短语，不要写到邻框里去。
7. 不要输出 HTML；不要解释。
8. 数字/指标可按新主题合理改写。
9. images 提示词只描述「画面主体/场景内容」，且必须贴合用户新主题；禁止在提示里另起色板或明暗（色调以 visual-spec「配图色调」+ theme 为准）。
10. 插图主体跟用户主题；色温/明暗必须继承该模板规范（亮色模板保持偏亮，暗色模板保持偏低）——只继承色调，不继承原包故事题材。
"""
    from config import llm_config

    cfg = llm_config()
    pool = make_client_pool(cfg)
    mode = "retry-missing" if focus_missing else "full"
    _log(log, f"[remix] planning ({mode}) slots={len(slots)} model={cfg.model}")
    raw = chat_json(
        pool=pool,
        model=cfg.model,
        system=system,
        user=user,
        temperature=temperature,
    )
    if not isinstance(raw, dict):
        raise RuntimeError("remix plan 不是 JSON 对象")
    return raw


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

    plan = _plan_content_once(
        prompt=prompt,
        slots=slots,
        source_label=source_label,
        pages=pages,
        visual_brief=visual_brief,
        log=log,
        temperature=0.4,
        focus_missing=False,
    )
    missing = missing_text_slots(slots, plan)
    if not missing:
        return plan

    _log(
        log,
        f"[remix] incomplete plan missing_text={len(missing)}/{sum(1 for s in slots if s.get('type') == 'text')}; retrying",
    )
    try:
        patch = _plan_content_once(
            prompt=prompt,
            slots=missing,
            source_label=source_label,
            pages=pages,
            visual_brief=visual_brief,
            log=log,
            temperature=0.3,
            focus_missing=True,
        )
        plan = merge_remix_plans(plan, patch)
    except Exception as e:
        _log(log, f"[remix] missing-slot retry failed: {e}")

    still = missing_text_slots(slots, plan)
    if still:
        sample = ", ".join(
            f"{s['file']}#{s['slot']}" for s in still[:8]
        )
        more = f" (+{len(still) - 8})" if len(still) > 8 else ""
        _log(
            log,
            f"[remix] still missing_text={len(still)} after retry — "
            f"keeping source copy for: {sample}{more}",
        )
    return plan


def remix_template_package(
    source_dir: Path,
    *,
    prompt: str,
    out_root: Path | None = None,
    mock: bool | None = None,
    skip_images: bool = False,
    status: str = "pending",
    ephemeral: bool = False,
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

    # 先补组内漏槽，再 inventory / 规划（嵌套标题等才能进 LLM）
    try:
        from templates.slot_ensure import ensure_package_orphan_slots

        slot_stats = ensure_package_orphan_slots(
            dest, log=lambda m: _log(log, m)
        )
        if slot_stats.get("text") or slot_stats.get("image"):
            _log(
                log,
                f"[remix] orphan slots patched files={slot_stats.get('files')} "
                f"text=+{slot_stats.get('text')} image=+{slot_stats.get('image')}",
            )
    except Exception as e:  # noqa: BLE001
        _log(log, f"[remix] orphan slot patch skipped: {e}")

    slots = inventory_package_slots(dest)
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

    # drop qiniu/upload provenance from clone
    try:
        new_meta = json.loads((dest / "template.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"克隆后 template.json 损坏: {e}") from e

    from templates.categories import coerce_category

    slide_list = [s for s in (pages if isinstance(pages, list) else []) if isinstance(s, dict)]
    page_total = sum(1 for s in slide_list if str(s.get("file") or "").strip())

    new_meta["template_id"] = new_id
    new_meta["public_id"] = new_id
    new_meta["label"] = {"zh_CN": label_zh, "en_US": label_zh}
    new_meta["description"] = {
        "zh_CN": desc_zh,
        "en_US": desc_zh,
    }
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
        "in_progress": True,
    }
    if ephemeral:
        new_meta["ephemeral"] = True
        new_meta["storage"] = {
            "backend": "session",
            "path": f"workspace/{new_id}",
        }
    else:
        new_meta.pop("storage", None)
    new_meta.pop("preview", None)
    if isinstance(pages, list):
        new_meta["slides"] = pages
    # 尽早落盘，供编辑器按页拉取（仍含源文案，随后逐页覆写）
    _write_template_meta(dest, new_meta)
    try:
        os.utime(dest, None)
    except OSError:
        pass
    _log(log, f"[remix-cloned] id={new_id} total={page_total}")

    regen_files: list[str] = []
    text_applied = 0
    page_done = 0
    for slide in slide_list:
        rel = str(slide.get("file") or "").strip()
        if not rel:
            continue
        path = dest / rel
        if not path.is_file():
            continue
        html_before = path.read_text(encoding="utf-8")
        html = html_before
        file_texts = dict(_lookup_file_map(texts_by_file, rel))
        # also accept flat keys without path prefix
        if not file_texts:
            file_texts = {
                s["slot"]: texts_by_file.get(s["slot"])
                for s in text_slots
                if s["file"] == rel and isinstance(texts_by_file.get(s["slot"]), str)
            }
        # Skip blank values so empty model output never wipes source copy
        file_texts = {
            str(k): str(v)
            for k, v in (file_texts or {}).items()
            if v is not None and str(v).strip()
        }
        file_slots = [s for s in text_slots if s["file"] == rel]
        file_texts = clamp_texts_for_slots(file_texts, file_slots)
        html = apply_text_to_html(html, file_texts, fit=True)
        if file_texts and html != html_before:
            text_applied += len(file_texts)

        file_imgs = dict(_lookup_file_map(images_by_file, rel))
        file_imgs = {str(k): str(v) for k, v in (file_imgs or {}).items() if v}
        if file_imgs and not skip_images:
            html, regen = apply_image_hints_to_html(html, file_imgs)
            regen_files.extend(regen)
        # PPTX→HTML 默认 object-fit:fill 会拉伸新图；统一 cover 保比例
        html = normalize_img_object_fit(html)
        path.write_text(html if html.endswith("\n") else html + "\n", encoding="utf-8")

        # update slide title from page-title / title slot when present
        title_val = (
            file_texts.get("title")
            or file_texts.get("page-title")
            or next((file_texts[k] for k in file_texts if "title" in k), None)
        )
        if title_val:
            slide["title"] = str(title_val)[:80]

        page_done += 1
        _log(
            log,
            f"[remix-page] id={new_id} file={rel} index={page_done - 1} "
            f"done={page_done} total={page_total} texts={len(file_texts)}",
        )

    if text_slots and text_applied == 0:
        raise RuntimeError(
            "套用未写入任何文本槽：模型输出与 data-slot 未对齐。"
            "请重试或更换内容要求。"
        )

    # 强制覆写需换图的文件（不先删，避免预览空窗期 404）
    if regen_files and not skip_images and not use_mock:
        force_names = set(regen_files)
        _log(log, f"[remix] rematerialize images ×{len(force_names)} (force overwrite)")
        try:
            from templates.write import rematerialize_package_images

            warnings = rematerialize_package_images(dest, force_files=force_names)
            for w in warnings:
                _log(log, f"[remix] image warn: {w}")
        except Exception as e:
            _log(log, f"[remix] image rematerialize skipped: {e}")
    elif skip_images:
        _log(log, "[remix] images kept (skip)")
        # 即使不换图，也修掉 fill 拉伸
        for slide in pages if isinstance(pages, list) else []:
            rel = str((slide or {}).get("file") or "").strip()
            if not rel:
                continue
            path = dest / rel
            if not path.is_file():
                continue
            raw = path.read_text(encoding="utf-8")
            fixed = normalize_img_object_fit(raw)
            if fixed != raw:
                path.write_text(fixed if fixed.endswith("\n") else fixed + "\n", encoding="utf-8")

    if isinstance(pages, list):
        new_meta["slides"] = pages
    remix_meta = dict(new_meta.get("remix") or {})
    remix_meta.pop("in_progress", None)
    remix_meta["text_applied"] = text_applied
    new_meta["remix"] = remix_meta
    _write_template_meta(dest, new_meta)
    # Bump directory mtime so Admin list (sorted by folder time) surfaces this pack.
    try:
        os.utime(dest, None)
    except OSError:
        pass
    _log(log, f"[remix] wrote {dest}")
    _log(
        log,
        f"[progress] done={page_total or 1} total={page_total or 1} "
        f"ok={page_total or 1} fail=0 skip=0 id={new_id} status=ok",
    )
    return {
        "ok": True,
        "template_id": new_id,
        "output_dir": str(dest),
        "source_template_id": source_id,
        "text_slots": len(text_slots),
        "image_slots": len(image_slots),
        "text_applied": text_applied,
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
    ephemeral: bool = False,
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
        ephemeral=ephemeral,
        log=log,
    )
