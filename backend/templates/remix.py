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
from templates.slot_tree import (
    canvas_size,
    measure_slots,
    split_package_slots,
    visual_lines_fragment,
)
from templates.capacity import (
    build_capacity_contract,
    capacity_for_slots,
    ensure_capacity_contract,
)

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
_INDEX_ONLY_RE = re.compile(r"^(?:0\d|[０-９]{2})$")


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
    # Worst-case (largest) font in the slot: a mixed-size slot must budget for the
    # biggest run, otherwise fit decides a scale from the small font and the big
    # title still overflows its box.
    for m in _FONT_SIZE_DECL_RE.finditer(blob):
        px = _css_to_px(float(m.group(2)), m.group(4))
        if px > font_px:
            font_px = px
            font_unit = m.group(4).lower()
    letter_px = 0.0
    for m in _LETTER_SPACING_DECL_RE.finditer(blob):
        px = _css_to_px(float(m.group(2)), m.group(4))
        letter_px = max(letter_px, px)

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


def estimate_line_chars(box: dict[str, Any] | None) -> int:
    """Single-line char budget for a slot box (uses post-fit min font)."""
    if not box:
        return 0
    width = float(box.get("width_px") or 0)
    font = float(box.get("font_px") or 0)
    if width <= 0 or font <= 0:
        return 0
    # Assume post-fit min font (~55%) so LLM may write slightly fuller short phrases
    font_for_cap = max(font * _MIN_FONT_SCALE, font * 0.7)
    avg = font_for_cap + float(box.get("letter_spacing_px") or 0) * _MIN_FONT_SCALE
    return max(1, int((width * 0.94) / max(avg, 1.0)))


def per_line_char_budgets(
    content: str,
    width_px: float,
) -> list[int]:
    """Per-line char budget using each line's own font size.

    A row slot like 「标题（21pt）/ 说明（15.75pt）」 must not budget the small
    line at the big line's width-per-char, or short readable copy gets truncated.
    """
    budgets: list[int] = []
    width = float(width_px or 0)
    if width <= 0:
        return budgets
    for m in _SPAN_RE.finditer(content or ""):
        if _is_keep_meta_span(m.group(2) or ""):
            continue
        fragment = m.group(0)
        fm = _FONT_SIZE_DECL_RE.search(fragment)
        font = _css_to_px(float(fm.group(2)), fm.group(4)) if fm else 0.0
        lsm = _LETTER_SPACING_DECL_RE.search(fragment)
        ls = _css_to_px(float(lsm.group(2)), lsm.group(4)) if lsm else 0.0
        if font <= 0:
            budgets.append(0)
            continue
        avg = max(font * _MIN_FONT_SCALE, font * 0.7) + ls * _MIN_FONT_SCALE
        budgets.append(max(1, int((width * 0.94) / max(avg, 1.0))))
    return budgets


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
        per_line = estimate_line_chars(box)
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
    """Shrink font/letter-spacing (floor 55%), then truncate text if still overflows.

    Lines are measured as *rendered* lines: inline spans sharing a line wrapper are
    summed (「退役军人代表」+「18」+「人」 = one 298px line), while separate line
    wrappers are independent rows. Measuring span-by-span let a mixed-size inline
    row pass the fit check locally and still overflow once rendered.
    """
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

    # 0.97 not 0.94: template boxes are usually sized to the source copy, which
    # already renders at ~99% width. A 6% margin forced needless shrink/truncate
    # on every row that was simply re-written with same-length copy.
    usable = width * 0.97
    lines = visual_lines_fragment(content)
    if lines:
        line_inks = [_line_ink(ln, ls) for ln in lines]
    else:
        # Fallback: no parsable spans, keep the old newline model.
        chunks = text.splitlines() if "\n" in text else [text]
        line_inks = [estimate_text_width_px(c, font_px, ls) for c in chunks]
    worst = max(line_inks, default=0.0)
    if worst <= usable:
        return content, info

    scale = max(_MIN_FONT_SCALE, min(1.0, usable / max(worst, 1.0)))
    if scale < 0.999:
        content = _scale_typography_in_fragment(content, scale)
        font_px *= scale
        ls *= scale
        info["scaled"] = True
        info["scale"] = scale

    # Re-check with scaled fonts; truncate only the lines still too wide.
    lines2 = visual_lines_fragment(content)
    if not lines2:
        return content, info
    overflow = [_line_ink(ln, ls) > usable for ln in lines2]
    if not any(overflow):
        return content, info

    span_texts = [m.group(2) or "" for m in _SPAN_RE.finditer(content)]
    flat = [r for ln in lines2 for r in ln.get("spans") or []]
    if len(flat) != len(span_texts):
        # Inline runs changed shape after scaling (should not happen); keep as is.
        return content, info

    truncated = False
    idx = 0
    for ln, over in zip(lines2, overflow):
        runs = ln.get("spans") or []
        if over:
            _shrink_runs_to_width(runs, usable, ls, span_texts, idx)
            truncated = True
        idx += len(runs)
    if truncated:
        content = _replace_span_texts_by_index(content, span_texts)
        info["truncated"] = True
    return content, info


def _line_ink(line: dict[str, Any], letter_spacing_px: float) -> float:
    """Summed ink width of one rendered line, honouring per-run fonts."""
    runs = line.get("spans") or []
    if not runs:
        return estimate_text_width_px(
            str(line.get("text") or ""), float(line.get("font_px") or 0), letter_spacing_px
        )
    return sum(
        estimate_text_width_px(
            str(r.get("text") or ""),
            float(r.get("font_px") or line.get("font_px") or 0),
            letter_spacing_px,
        )
        for r in runs
    )


def _shrink_runs_to_width(
    runs: list[dict[str, Any]],
    max_width_px: float,
    letter_spacing_px: float,
    span_texts: list[str],
    offset: int,
) -> None:
    """Trim runs of one line from the end until the summed line fits."""
    targets = list(range(offset, offset + len(runs)))
    for pos in reversed(targets):
        run = runs[pos - offset]
        font = float(run.get("font_px") or 0)
        if font <= 0:
            continue
        others = sum(
            estimate_text_width_px(
                str(r.get("text") or ""), float(r.get("font_px") or font), letter_spacing_px
            )
            for r in runs
            if r is not run
        )
        room = max_width_px - others
        if room <= 0:
            run["text"] = ""
        else:
            run["text"] = _truncate_to_width(
                str(run.get("text") or ""), room, font, letter_spacing_px
            )
        if sum(
            estimate_text_width_px(
                str(r.get("text") or ""), float(r.get("font_px") or font), letter_spacing_px
            )
            for r in runs
        ) <= max_width_px:
            break
    for pos in targets:
        span_texts[pos] = str(runs[pos - offset].get("text") or "")


def _replace_span_texts_by_index(content: str, span_texts: list[str]) -> str:
    """Rewrite every span's inner text by ordinal, preserving attributes."""
    out: list[str] = []
    last = 0
    for i, m in enumerate(_SPAN_RE.finditer(content)):
        out.append(content[last : m.start()])
        body = span_texts[i] if i < len(span_texts) else (m.group(2) or "")
        out.append(m.group(1) + body + m.group(3))
        last = m.end()
    out.append(content[last:])
    return "".join(out)


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

    # 单行内联槽（同一行里「文字 + 强调数字 + 单位」）：整行是一句话，
    # 写单行时必须替换整行，否则残留的原数字会拼出「…楼层。42」并溢出。
    inline_single = (
        len(lines) == 1
        and len(spans) > 1
        and len(visual_lines_fragment(inner)) <= 1
    )

    meta_flags = [_is_keep_meta_span(m.group(2) or "") for m in spans]
    prose_indices = [i for i, is_meta in enumerate(meta_flags) if not is_meta]

    def _rebuild(assign: dict[int, str], *, keep_meta: bool = True) -> str:
        out: list[str] = []
        last = 0
        for i, m in enumerate(spans):
            out.append(inner[last : m.start()])
            if i in assign:
                content = assign[i]
            elif keep_meta and meta_flags[i]:
                content = m.group(2) or ""
            else:
                content = ""
            out.append(m.group(1) + content + m.group(3))
            last = m.end()
        out.append(inner[last:])
        return "".join(out)

    # 1 line per span: the model is mirroring the slot's own inline runs
    # (e.g. 「宾语」+「18」+「人」 with the number in accent color). Write positionally;
    # treating the numeric run as a fixed meta span here duplicates it
    # (「1818 人」) and leaves the row overwide.
    if len(lines) == len(spans) and len(spans) > 1:
        return _rebuild({i: lines[i] for i in range(len(spans))})

    # One blob: write into primary prose span; keep meta; clear other prose.
    # 多叶子槽（如「责任：…；节点：…」）收到单行时，先按分隔符拆回各叶子，
    # 避免把第二个字段整体清空。
    if len(lines) == 1:
        if inline_single:
            primary = _primary_span_index(spans)
            return _rebuild({primary: lines[0]}, keep_meta=False)
        if len(prose_indices) >= 2:
            parts = [
                p.strip()
                for p in re.split(r"[；;|｜]|\s{2,}", lines[0])
                if p.strip()
            ]
            if 2 <= len(parts) <= len(prose_indices):
                assign = {
                    span_i: parts[i]
                    for i, span_i in enumerate(prose_indices)
                    if i < len(parts)
                }
                return _rebuild(assign)
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
            # Renderer-created list/chapter numbers are layout, not editable copy.
            # Keeping them static avoids turning 「01」 into a one-character rewrite.
            if _INDEX_ONLY_RE.fullmatch(re.sub(r"\s+", "", text)):
                continue
            box = parse_slot_box(attrs, content)
            role_norm = role or "body"
            max_chars = estimate_max_chars(
                current=text, role=role_norm, box=box
            )
            span_n = len(list(_SPAN_RE.finditer(content)))
            budgets = per_line_char_budgets(content, float(box.get("width_px") or 0))
            slots.append(
                {
                    "file": file,
                    "slot": slot,
                    "type": "text",
                    "role": role_norm,
                    "current": text,
                    "max_chars": max_chars,
                    "line_chars": estimate_line_chars(box),
                    "line_budgets": budgets,
                    "span_count": span_n,
                    "box_width_px": round(float(box.get("width_px") or 0), 1),
                    "box_height_px": round(float(box.get("height_px") or 0), 1),
                    "font_px": round(float(box.get("font_px") or 0), 1),
                    "nowrap": bool(box.get("nowrap")),
                }
            )
    if slots:
        _annotate_layout(slots, html)
    return slots


_OWNER_LINE_RE = re.compile(r"^(?:责任|负责人|责任人|牵头|主体|承办)\s*[:：]")
_WHEN_LINE_RE = re.compile(
    r"^(?:节点|时间|日期|周期|频次|频次[:：]|[每]?[天周月年日]|[每]?学期|每月|每周|每日|每年)"
)
_VALUE_LINE_RE = re.compile(r"^\d{1,4}(?:[.．]\d+)?\s*[%％]?$")


def _field_hint(text: str, index: int) -> str:
    """Guess the semantic field of one text line inside a multi-line slot."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t:
        return "text"
    if _OWNER_LINE_RE.match(t):
        return "owner"
    if _WHEN_LINE_RE.match(t):
        return "when"
    if _VALUE_LINE_RE.match(t):
        return "value"
    return "title" if index == 0 else "desc"


def _annotate_layout(slots: list[dict[str, Any]], html: str) -> None:
    """Add absolute position, row/col index and per-line field hints to text slots.

    Row grouping is what lets the planner keep one entry per layout row instead of
    letting the model shuffle fields across rows.
    """
    try:
        boxes = measure_slots(html)
    except Exception:  # noqa: BLE001 - 位置信息只用于增强，失败不影响主流程
        return
    if not boxes:
        return
    text_slots = [s for s in slots if s.get("type") == "text"]
    for s in text_slots:
        box = boxes.get(str(s.get("slot")))
        if not box:
            continue
        measured_width = float(box.get("width") or 0)
        measured_height = float(box.get("height") or 0)
        if measured_width > 0:
            s["box_width_px"] = round(measured_width, 1)
        if measured_height > 0:
            s["box_height_px"] = round(measured_height, 1)
        s["abs_left"] = round(float(box.get("x") or 0), 1)
        s["abs_top"] = round(float(box.get("y") or 0), 1)
        lines = [str(ln.get("text") or "") for ln in box.get("lines") or []]
        labels = [_field_hint(t, i) for i, t in enumerate(lines)]
        used: dict[str, int] = {}
        keys: list[str] = []
        for label in labels:
            base = re.sub(r"[^a-z0-9_]+", "_", label.lower()).strip("_") or "text"
            used[base] = used.get(base, 0) + 1
            keys.append(base if used[base] == 1 else f"{base}_{used[base]}")
        s["fields"] = keys
        s["field_labels"] = labels
        s["line_count"] = len(lines)
        width = measured_width or float(s.get("box_width_px") or 0)
        line_budgets: list[int] = []
        for line in box.get("lines") or []:
            font_px = float(line.get("font_px") or 0)
            if font_px <= 0:
                font_px = _css_to_px(float(line.get("font_pt") or 0), "pt")
            if width > 0 and font_px > 0:
                geometry_budget = estimate_line_chars(
                    {"width_px": width, "font_px": font_px}
                )
                source_len = len(str(line.get("text") or "").strip())
                line_budgets.append(max(geometry_budget, min(source_len, 200)))
            else:
                line_budgets.append(int(s.get("line_chars") or 0))
        s["line_budgets"] = line_budgets
        if line_budgets:
            s["line_chars"] = min(line_budgets)
            s["max_chars"] = max(1, sum(line_budgets))

    ordered = [s for s in text_slots if "abs_top" in s]
    ordered.sort(key=lambda s: (s["abs_top"], s["abs_left"]))
    row_no = 0
    row: list[dict[str, Any]] = []

    def _row_span(items: list[dict[str, Any]]) -> tuple[float, float]:
        tops = [float(s["abs_top"]) for s in items]
        bottoms = [
            float(s["abs_top"]) + max(8.0, float(s.get("box_height_px") or 0))
            for s in items
        ]
        return min(tops), max(bottoms)

    def _same_row(item: dict[str, Any], items: list[dict[str, Any]]) -> bool:
        top = float(item["abs_top"])
        height = max(8.0, float(item.get("box_height_px") or 0))
        bottom = top + height
        r_top, r_bottom = _row_span(items)
        overlap = min(bottom, r_bottom) - max(top, r_top)
        return overlap > 0.5 * min(height, r_bottom - r_top)

    for s in ordered:
        if not row or not _same_row(s, row):
            if row:
                for col, item in enumerate(
                    sorted(row, key=lambda x: float(x["abs_left"])), start=1
                ):
                    item["col"] = col
            row_no += 1
            row = [s]
        else:
            row.append(s)
        s["row"] = row_no
    if row:
        for col, item in enumerate(sorted(row, key=lambda x: float(x["abs_left"])), start=1):
            item["col"] = col


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


def _relax_text_slot_open_tag(open_tag: str) -> str:
    """Keep the template's own overflow policy.

    Formerly this forced ``overflow: hidden`` → ``visible`` to avoid clipping the
    first/last glyph. That also disabled the only clip that kept overlong copy off
    the canvas, so a mis-fit text box could spill outside the slide. Fit/clamp now
    guarantees the text stays inside its own box, so the original CSS is kept.
    """
    return open_tag


def resolve_horizontal_slot_collisions(html: str) -> str:
    """If same-row text slots' ink overlaps, shrink/truncate the left slot."""
    measured: dict[str, dict[str, Any]] = {}
    try:
        measured = measure_slots(html)
    except Exception:  # noqa: BLE001
        measured = {}
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
        # Nested leaf slots carry parent-relative left/top; use absolute geometry
        # when available so cross-container comparisons stay meaningful.
        abs_box = measured.get(slot)
        if abs_box:
            left = float(abs_box.get("x") or left)
            top = float(abs_box.get("y") or top)
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
    fit_report: list[dict[str, Any]] | None = None,
) -> str:
    """Apply slot→text map; preserve non-slot markup. Optionally fit font/truncate."""
    if not updates:
        return html
    # Process from end to start so indices stay valid
    matches: list[tuple[int, int, int, str, str, str]] = []
    measured = measure_slots(html)
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
            box = measured.get(slot) or {}
            effective_attrs = attrs
            if float(box.get("width") or 0) > 0:
                effective_attrs += (
                    f' data-effective-width="{float(box["width"]):g}px"'
                    f' style="width: {float(box["width"]):g}px;'
                    f' height: {float(box.get("height") or 0):g}px;"'
                )
            new_content, fit_info = fit_slot_inner(effective_attrs, new_content)
            if fit_report is not None and (
                fit_info.get("scaled") or fit_info.get("truncated")
            ):
                fit_report.append(
                    {
                        "slot": slot,
                        "reason": (
                            "content_truncated"
                            if fit_info.get("truncated")
                            else "font_scaled"
                        ),
                        "planned": new_text[:160],
                        "written": _plain_text_from_spans(new_content)[:160],
                        "scale": fit_info.get("scale"),
                    }
                )
        open_tag = _relax_text_slot_open_tag(out[open_start:open_end])
        out = out[:open_start] + open_tag + new_content + tail + out[close_end:]
    if resolve_collisions:
        out = resolve_horizontal_slot_collisions(out)
    return out


def clamp_texts_for_slots(
    texts: dict[str, str],
    slots: list[dict[str, Any]],
) -> dict[str, str]:
    """Hard-clamp planned texts to each slot's per-line / total char budget.

    Per-line clamp runs first: with leaf slots a slot may hold 2 fields (e.g.
    「岗位」+「职责」), and clamping only the total would let line 2 eat line 1's
    budget and produce a mid-word cut.
    """
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
            budgets = [
                int(b)
                for b in (slot_meta.get("line_budgets") or [])
                if int(b or 0) > 0
            ]
            line_c = int(slot_meta.get("line_chars") or 0)
            lines = text.splitlines()
            if len(lines) > 1 and (budgets or line_c > 0):
                fixed: list[str] = []
                for i, ln in enumerate(lines):
                    if not ln.strip():
                        fixed.append(ln)
                        continue
                    budget = budgets[i] if i < len(budgets) else line_c
                    fixed.append(clamp_text_to_max_chars(ln, budget) if budget > 0 else ln)
                text = "\n".join(fixed)
            max_c = int(slot_meta.get("max_chars") or 0)
            if max_c > 0:
                text = clamp_text_to_max_chars(text, max_c)
        out[str(key)] = text
    return out


def verify_slide_fit(
    html: str,
    *,
    canvas: tuple[float, float] | None = None,
    baseline: str | None = None,
) -> list[dict[str, Any]]:
    """Post-write gate: text must stay inside its own box and inside the canvas.

    Positions are accumulated through nested absolute boxes, so a leaf text box
    inside a row container is checked against *its own* width — the case that let a
    40-char line live in a 190px column and run off the slide.

    Wrapping is modeled: a slot that soft-wraps can hold more characters as long as
    the wrapped block still fits its height. Only ``nowrap`` slots are width-gated.
    ``baseline`` (the cloned source page before rewriting) suppresses issues that
    the template already had, so only regressions get reported.
    """
    try:
        boxes = measure_slots(html)
    except Exception:  # noqa: BLE001 - 校验失败不阻断生成
        return []
    if not boxes:
        return []
    canvas_w, canvas_h = canvas or canvas_size(html)
    issues: list[dict[str, Any]] = []
    for slot, box in boxes.items():
        width = float(box.get("width") or 0)
        height = float(box.get("height") or 0)
        x = float(box.get("x") or 0)
        y = float(box.get("y") or 0)
        lines = box.get("lines") or []
        if width <= 0 or not lines:
            continue
        nowrap = bool(box.get("nowrap"))
        need_h = 0.0
        worst_ink = 0.0
        for ln in lines:
            text = str(ln.get("text") or "")
            font_pt = float(ln.get("font_pt") or box.get("font_pt") or 0)
            font_px = _css_to_px(font_pt, "pt")
            if not text or font_px <= 0:
                continue
            line_px = float(ln.get("line_px") or 0) or font_px * 1.25
            runs = ln.get("runs") or []
            if runs:
                ink = sum(
                    estimate_text_width_px(
                        str(r.get("text") or ""),
                        _css_to_px(float(r.get("font_pt") or font_pt), "pt"),
                    )
                    for r in runs
                )
            else:
                ink = estimate_text_width_px(text, font_px)
            worst_ink = max(worst_ink, ink)
            if nowrap:
                need_h += line_px
                if ink > width * 1.03 + 1.0:
                    issues.append(
                        {
                            "slot": slot,
                            "reason": "ink_overflow",
                            "ink_px": round(ink, 1),
                            "box_px": round(width, 1),
                            "sample": text[:40],
                        }
                    )
            else:
                wrapped = max(1, int(-(-ink // max(width * 0.98, 1.0))))
                need_h += wrapped * line_px
        if x + width > canvas_w + 1.0:
            issues.append(
                {
                    "slot": slot,
                    "reason": "canvas_x",
                    "right_px": round(x + width, 1),
                    "canvas_px": canvas_w,
                }
            )
        if y + height > canvas_h + 1.0:
            issues.append(
                {
                    "slot": slot,
                    "reason": "canvas_y",
                    "bottom_px": round(y + height, 1),
                    "canvas_px": canvas_h,
                }
            )
        if height > 0 and need_h > height * 1.08 + 2.0:
            issues.append(
                {
                    "slot": slot,
                    "reason": "vertical_overflow",
                    "need_px": round(need_h, 1),
                    "box_px": round(height, 1),
                    "ink_px": round(worst_ink, 1),
                }
            )
    if baseline and issues:
        return _drop_baseline_issues(issues, baseline, canvas)
    return issues


def _drop_baseline_issues(
    issues: list[dict[str, Any]],
    baseline: str,
    canvas: tuple[float, float] | None,
) -> list[dict[str, Any]]:
    """Keep only regressions: same slot+reason in the source page is not a regression."""
    try:
        base = measure_slots(baseline)
    except Exception:  # noqa: BLE001
        return issues
    keep: list[dict[str, Any]] = []
    for issue in issues:
        slot = str(issue.get("slot") or "")
        b = base.get(slot)
        if not b:
            keep.append(issue)
            continue
        width = max(float(b.get("width") or 0), 1.0)
        height = max(float(b.get("height") or 0), 1.0)
        if issue.get("reason") in {"canvas_x", "canvas_y"}:
            keep.append(issue)
            continue
        # Recompute the source overflow with the same model.
        nowrap = bool(b.get("nowrap"))
        need_h = 0.0
        worst = 0.0
        for ln in b.get("lines") or []:
            text = str(ln.get("text") or "")
            font_px = _css_to_px(float(ln.get("font_pt") or 0), "pt")
            if not text or font_px <= 0:
                continue
            line_px = float(ln.get("line_px") or 0) or font_px * 1.25
            ink = estimate_text_width_px(text, font_px)
            worst = max(worst, ink)
            if nowrap:
                need_h += line_px
            else:
                need_h += max(1, int(-(-ink // max(width * 0.98, 1.0)))) * line_px
        base_ratio = need_h / height
        if issue.get("reason") == "ink_overflow" and nowrap:
            if worst <= width * 1.03 + 1.0:
                keep.append(issue)
        elif issue.get("reason") == "vertical_overflow":
            need = float(issue.get("need_px") or 0)
            if need > max(base_ratio * height, height) * 1.05 + 2.0:
                keep.append(issue)
        else:
            keep.append(issue)
    return keep


def _render_issue_excess(issue: dict[str, Any]) -> float:
    reason = str(issue.get("reason") or "")
    if reason == "out_of_canvas":
        return max(
            float(issue.get("right") or 0) - 1920,
            float(issue.get("bottom") or 0) - 1080,
        )
    if reason in {"clipped_horizontally", "text_wider_than_box"}:
        if "text_right" in issue and "clip_right" in issue:
            return float(issue["text_right"]) - float(issue["clip_right"])
        return float(issue.get("text_px") or 0) - float(issue.get("box_px") or 0)
    if reason == "clipped_vertically":
        return float(issue.get("text_bottom") or 0) - float(
            issue.get("clip_bottom") or 0
        )
    return 0.0


def render_regressions(
    generated: dict[str, Any],
    baseline: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep real browser findings that are new or measurably worse than source."""
    base_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for issue in baseline.get("issues") or []:
        key = (
            str(issue.get("file") or ""),
            str(issue.get("slot") or ""),
            str(issue.get("reason") or ""),
        )
        base_by_key.setdefault(key, []).append(issue)
    out: list[dict[str, Any]] = []
    for issue in generated.get("issues") or []:
        key = (
            str(issue.get("file") or ""),
            str(issue.get("slot") or ""),
            str(issue.get("reason") or ""),
        )
        base_items = base_by_key.get(key) or []
        if not base_items:
            out.append(issue)
            continue
        base_excess = max((_render_issue_excess(x) for x in base_items), default=0.0)
        current_excess = _render_issue_excess(issue)
        if current_excess > base_excess + 2.0:
            out.append(issue)
    return out


def _restore_source_slots(
    *,
    html: str,
    source_html: str,
    file: str,
    slot_ids: set[str],
) -> str:
    """Safe fallback: restore only unsafe slots from the geometry-locked source."""
    if not slot_ids:
        return html
    source_slots = inventory_slide_slots(source_html, file=file)
    updates = {
        str(s.get("slot") or ""): str(s.get("current") or "")
        for s in source_slots
        if s.get("type") == "text"
        and str(s.get("slot") or "") in slot_ids
        and str(s.get("current") or "").strip()
    }
    return apply_text_to_html(html, updates, fit=True) if updates else html


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
        "current": (s.get("current") or "")[:240],
        "max_chars": s.get("max_chars"),
    }
    if s.get("type") == "text":
        row["box"] = (
            f"{int(s.get('box_width_px') or 0)}×{int(s.get('box_height_px') or 0)}px"
        )
        if s.get("row"):
            row["row"] = s["row"]
        if s.get("col"):
            row["col"] = s["col"]
        span_n = int(s.get("span_count") or 0)
        if s.get("fields"):
            row["fields"] = s["fields"]
            row["field_labels"] = s.get("field_labels") or s["fields"]
        if span_n > 1:
            row["lines"] = int(s.get("line_count") or span_n)
            row["hint"] = (
                f"该槽含 {span_n} 行：按 fields 顺序用换行输出 {span_n} 行，"
                f"禁止合并/拆多"
            )
        line_chars = int(s.get("line_chars") or 0)
        budgets = [int(b) for b in (s.get("line_budgets") or []) if int(b or 0) > 0]
        if budgets:
            row["line_chars"] = budgets if len(budgets) > 1 else budgets[0]
            row["field_budget"] = [
                {
                    "field": (s.get("fields") or [])[i]
                    if i < len(s.get("fields") or [])
                    else f"text_{i + 1}",
                    "max_chars": budget,
                }
                for i, budget in enumerate(budgets)
            ]
        elif line_chars > 0:
            row["line_chars"] = line_chars
    elif s.get("type") == "image":
        row["hint"] = (
            "只改画面主体/场景；色温与明暗须服从 visual-spec「配图色调」与 theme，勿自创相反色板"
        )
    return row


def _content_schema(
    slots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Page → group → row → slot → field prompt schema."""
    pages: dict[str, dict[str, Any]] = {}
    for s in slots:
        file = str(s.get("file") or "")
        if not file:
            continue
        page = pages.setdefault(file, {"file": file, "standalone": [], "rows": []})
        if s.get("type") == "image":
            page["standalone"].append(
                {
                    "slot": str(s.get("slot") or ""),
                    "type": "image",
                    "role": s.get("role"),
                    "sample": str(s.get("current") or "")[:80],
                }
            )
            continue
        fields = [str(x) for x in (s.get("fields") or ["text"])]
        budgets = [
            int(x or 0) for x in (s.get("line_budgets") or []) if int(x or 0) > 0
        ]
        samples = str(s.get("current") or "").splitlines()
        item = {
            "slot": str(s.get("slot") or ""),
            "fields": [
                {
                    "field": field,
                    "max_chars": (
                        budgets[i]
                        if i < len(budgets)
                        else int(s.get("line_chars") or s.get("max_chars") or 1)
                    ),
                    "sample": (samples[i] if i < len(samples) else "")[:80],
                }
                for i, field in enumerate(fields)
            ],
        }
        if s.get("row"):
            rows = page["rows"]
            row_no = int(s["row"])
            group = next((r for r in rows if int(r.get("row") or 0) == row_no), None)
            if not group:
                group = {"row": row_no, "slots": []}
                rows.append(group)
            group["slots"].append(item)
        else:
            page["standalone"].append(item)
    for page in pages.values():
        page["rows"].sort(key=lambda r: int(r.get("row") or 0))
        page["standalone"].sort(key=lambda s: str(s.get("slot") or ""))
        page["rows"].sort(
            key=lambda r: int(r["slots"][0].get("row") or r.get("row") or 0)
            if r.get("slots")
            else int(r.get("row") or 0)
        )
        for row in page["rows"]:
            row["slots"].sort(key=lambda s: str(s.get("slot") or ""))
    return {"pages": list(pages.values())}


def _slot_values_for_field_order(
    raw_values: Any,
    fields: list[str],
) -> str:
    """Convert page→row→field model output back to a slot's newline text."""
    if isinstance(raw_values, dict):
        out: list[str] = []
        for field in fields:
            value = raw_values.get(field)
            if value is not None and str(value).strip():
                out.append(str(value).strip())
        if not out:
            out = [str(v).strip() for v in raw_values.values() if str(v).strip()]
        return "\n".join(out)
    if isinstance(raw_values, list):
        out = []
        for item in raw_values:
            if isinstance(item, dict):
                value = item.get("text") or item.get("value")
            else:
                value = item
            if value is not None and str(value).strip():
                out.append(str(value).strip())
        return "\n".join(out)
    return str(raw_values or "").strip()


def normalize_structured_plan(
    plan: dict[str, Any],
    slots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Flatten a page/group/row/field JSON plan into the legacy slot text map."""
    if not isinstance(plan, dict) or not plan.get("pages"):
        return plan
    meta_by_key = {
        (str(s.get("file") or ""), str(s.get("slot") or "")): s for s in slots
    }
    texts = plan.get("texts") if isinstance(plan.get("texts"), dict) else {}
    texts = {
        str(f): dict(v)
        for f, v in texts.items()
        if isinstance(v, dict)
    }
    images = plan.get("images") if isinstance(plan.get("images"), dict) else {}
    images = {
        str(f): dict(v)
        for f, v in images.items()
        if isinstance(v, dict)
    }
    pages = plan.get("pages")
    page_list = pages.values() if isinstance(pages, dict) else pages
    for page in page_list or []:
        if not isinstance(page, dict):
            continue
        file = str(page.get("file") or "").strip()
        if not file:
            continue
        groups = list(page.get("standalone") or [])
        for key in ("rows", "rowGroups", "groups"):
            values = page.get(key)
            if isinstance(values, list):
                for group in values:
                    if isinstance(group, dict):
                        groups.extend(group.get("slots") or [])
        values = page.get("slots")
        if isinstance(values, dict):
            for slot_id, raw in values.items():
                meta = meta_by_key.get((file, str(slot_id)))
                if meta and meta.get("type") == "image":
                    images.setdefault(file, {})[str(slot_id)] = str(raw or "").strip()
                    continue
                fields = list(meta.get("fields") or ["text"]) if meta else ["text"]
                texts.setdefault(file, {})[str(slot_id)] = _slot_values_for_field_order(
                    raw, fields
                )
        elif isinstance(values, list):
            groups.extend(values)
        for item in groups:
            if not isinstance(item, dict):
                continue
            slot_id = str(item.get("slot") or "").strip()
            if not slot_id:
                continue
            meta = meta_by_key.get((file, slot_id))
            if meta and meta.get("type") == "image":
                prompt_text = item.get("prompt") or item.get("text")
                if prompt_text and str(prompt_text).strip():
                    images.setdefault(file, {})[slot_id] = str(prompt_text).strip()
                continue
            fields = list(meta.get("fields") or ["text"]) if meta else ["text"]
            raw = (
                item.get("fields")
                if "fields" in item
                else item.get("values")
                if "values" in item
                else item.get("lines")
                if "lines" in item
                else item.get("text")
            )
            text = _slot_values_for_field_order(raw, fields)
            if text:
                texts.setdefault(file, {})[slot_id] = text
    out = dict(plan)
    out["texts"] = texts
    out["images"] = images
    return out


def _load_visual_brief(source_dir: Path) -> str:
    """Load the complete visual spec and theme used by remix planning."""
    parts: list[str] = []
    for name in ("visual-spec.md", "theme.css"):
        path = source_dir / name
        if path.is_file():
            parts.append(f"\n## {name}\n{path.read_text(encoding='utf-8')}")
    return "".join(parts)


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
    content_schema = _content_schema(slots)
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
        "槽位带 row/col 时：同一 row 的多个槽位属于同一条目，必须写同一对象的不同字段，"
        "严禁把 A 行的字段写到 B 行。"
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
            "只输出这些 file/slot 对应的 pages 结构（可附带 images）；"
            "每个都必须非空，且同页平行条目不可只填一组。\n"
        )
    user = f"""参考模板：{source_label}
用户新主题/要求：
{prompt}
{focus_note}
视觉规范与 theme（版式锁定；插图色调/材质也必须服从，不要改版式）：
{visual_brief or ''}

页面列表：
{json.dumps(page_outline, ensure_ascii=False)}

可写结构（页面 → 组 → 行 → 槽位 → 字段）：
每个 text 槽位的 fields 必须按给定 field 顺序全部填写；sample 只是长度参考，
max_chars 是该字段的真实安全容量。image 槽位输出 prompt。
{json.dumps(content_schema, ensure_ascii=False)}

输出 JSON：
{{
  "label_zh": "新模板中文名（内容主题，不要写风格词）",
  "description_zh": "一句话描述",
  "pages": [
    {{
      "file": "slides/content-9.html",
      "standalone": [
        {{"slot": "title", "fields": [{{"field": "title", "text": "新标题"}}]}}
      ],
      "rows": [
        {{
          "row": 3,
          "slots": [
            {{"slot": "body-3-1", "fields": [
              {{"field": "title", "text": "第一项标题"}},
              {{"field": "desc", "text": "第一项说明"}}
            ]}},
            {{"slot": "body-3-2", "fields": [
              {{"field": "owner", "text": "责任：某部门"}},
              {{"field": "when", "text": "节点：2026年10月"}}
            ]}}
          ]
        }}
      ]
    }}
  ],
  "images": {{ "slides/cover.html": {{ "hero-image": "只写新主体/场景，勿写新色板" }} }}
}}
约束：
1. 结构中的每个 file/slot/field 必须出现且非空；每个字段 text 的字数 ≤ max_chars，宁可短不可超。
2. 每个槽只写完整可读短句/短语；禁止半截词、半截句，禁止把两句硬塞进窄槽。
3. 版式序号（01、02…页码）由模板保留，不会出现在槽位里；禁止把编号写进任何文案。
4. 同一 row 的多个槽位 = 同一条目的不同字段：按 fields 顺序写（如 ["title","desc"] 先标题后说明；["owner","when"] 先责任后节点），不得跨行错配或把字段挪到别的行。
5. 每个 field 单独写 text，不得增删 field；禁止把多行粘成一句，也禁止把一行拆成多行。
6. 每行内容必须自洽：写「岗位」的槽就写岗位名，写「责任/频次」的槽就写责任人或周期，不允许互换。
7. 禁止多个槽位复制同一句；同页每条目文案必须互不相同。
8. 并排短标题槽只写能装下的完整短语，不要写到邻框里去。
9. 不要输出 HTML；不要解释；不要另起 texts 字段，内容只写 pages 结构。
10. 只改写 fields 含 value 的数字/指标；其余槽不要凭空插入数字。
11. images 提示词只描述「画面主体/场景内容」，且必须贴合用户新主题；禁止在提示里另起色板或明暗（色调以 visual-spec「配图色调」+ theme 为准）。
12. 插图主体跟用户主题；色温/明暗必须继承该模板规范（亮色模板保持偏亮，暗色模板保持偏低）——只继承色调，不继承原包故事题材。
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


# 单次规划的上限：复合槽拆分后槽位可达上百个，一次超长请求容易网关超时。
# 按页切块（每块 ≤ N 个槽 / ≤ M 页）分别规划，再合并；单块失败只影响该块。
_PLAN_CHUNK_SLOTS = 55
_PLAN_CHUNK_PAGES = 3


def _chunk_slots_by_page(
    slots: list[dict[str, Any]],
    pages: list[dict[str, Any]],
) -> list[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """Group slots into per-page batches, packing pages up to the limits."""
    order: list[str] = []
    for page in pages:
        rel = str((page or {}).get("file") or "").strip()
        if rel and rel not in order:
            order.append(rel)
    for slot in slots:
        rel = str(slot.get("file") or "").strip()
        if rel and rel not in order:
            order.append(rel)
    page_by_file = {
        str((page or {}).get("file") or "").strip(): page
        for page in pages
        if isinstance(page, dict)
    }

    batches: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
    cur_slots: list[dict[str, Any]] = []
    cur_pages: list[dict[str, Any]] = []
    for rel in order:
        file_slots = [s for s in slots if str(s.get("file") or "").strip() == rel]
        if not file_slots:
            continue
        if cur_slots and (
            len(cur_slots) + len(file_slots) > _PLAN_CHUNK_SLOTS
            or len(cur_pages) >= _PLAN_CHUNK_PAGES
        ):
            batches.append((cur_slots, cur_pages))
            cur_slots, cur_pages = [], []
        cur_slots.extend(file_slots)
        page = page_by_file.get(rel)
        if page:
            cur_pages.append(page)
    if cur_slots:
        batches.append((cur_slots, cur_pages))
    return batches


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

    batches = _chunk_slots_by_page(slots, pages)
    if len(batches) <= 1:
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
        plan = normalize_structured_plan(plan, slots)
    else:
        _log(
            log,
            f"[remix] planning in {len(batches)} batches "
            f"(slots={len(slots)}, limit={_PLAN_CHUNK_SLOTS}/batch)",
        )
        plan: dict[str, Any] = {"texts": {}, "images": {}}
        for i, (batch_slots, batch_pages) in enumerate(batches, start=1):
            files = ", ".join(
                Path(str(p.get("file") or "")).name for p in batch_pages if isinstance(p, dict)
            )
            _log(
                log,
                f"[remix] batch {i}/{len(batches)} pages=[{files}] slots={len(batch_slots)}",
            )
            try:
                part = _plan_content_once(
                    prompt=prompt,
                    slots=batch_slots,
                    source_label=source_label,
                    pages=batch_pages,
                    visual_brief=visual_brief,
                    log=log,
                    temperature=0.4,
                    focus_missing=False,
                )
            except Exception as e:  # noqa: BLE001 - 单批失败留待补全重试
                _log(log, f"[remix] batch {i} failed: {e}")
                continue
            part = normalize_structured_plan(part, batch_slots)
            plan = merge_remix_plans(plan, part)

    missing = missing_text_slots(slots, plan)
    if not missing:
        return plan

    _log(
        log,
        f"[remix] incomplete plan missing_text={len(missing)}/"
        f"{sum(1 for s in slots if s.get('type') == 'text')}; retrying",
    )
    # 补全也按块做，避免再次堆出超长请求。
    miss_batches = _chunk_slots_by_page(missing, pages)
    for i, (batch_slots, batch_pages) in enumerate(miss_batches, start=1):
        try:
            patch = _plan_content_once(
                prompt=prompt,
                slots=batch_slots,
                source_label=source_label,
                pages=batch_pages,
                visual_brief=visual_brief,
                log=log,
                temperature=0.3,
                focus_missing=True,
            )
            patch = normalize_structured_plan(patch, batch_slots)
            plan = merge_remix_plans(plan, patch)
        except Exception as e:  # noqa: BLE001
            _log(log, f"[remix] missing-slot retry batch {i} failed: {e}")
            continue

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
    render_check: bool = False,
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
    try:
        ensure_capacity_contract(source_dir)
    except Exception as e:  # noqa: BLE001 - detailed validation runs after structural repair
        _log(log, f"[remix-capacity] source contract skipped: {e}")

    visual_brief = _load_visual_brief(source_dir)

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

    # 复合槽（一个大 div 里塞 N 行 × M 字段）拆成叶子槽：行/字段可对齐、
    # fit 拿到真实叶子宽度，避免整块文本挤成一坨并溢出画布。
    try:
        split_stats = split_package_slots(dest, log=lambda m: _log(log, m))
        if split_stats.get("split"):
            _log(
                log,
                f"[remix] composite slots split files={split_stats.get('files')} "
                f"parents={split_stats.get('split')} leaves={split_stats.get('leaves')} "
                f"index_kept={split_stats.get('index_kept')}",
            )
    except Exception as e:  # noqa: BLE001
        _log(log, f"[remix] composite slot split skipped: {e}")

    capacity_contract: dict[str, Any]
    try:
        capacity_contract = build_capacity_contract(
            dest,
            repair_structure=False,
            render_baseline=False,
        )
        if capacity_contract.get("status") != "ready":
            issues = capacity_contract.get("issues") or []
            sample = ", ".join(
                f"{i.get('slot') or i.get('file')}:{i.get('code')}"
                for i in issues[:6]
            )
            raise RuntimeError(
                f"模板容量契约不可用，禁止 Remix：{sample or '结构校验失败'}"
            )
        _log(
            log,
            f"[remix-capacity] status=ready slots="
            f"{(capacity_contract.get('summary') or {}).get('slots', 0)}",
        )
    except Exception:
        raise

    slots = inventory_package_slots(dest)
    contract_slots = capacity_for_slots(dest, slots)
    for slot in slots:
        key = (str(slot.get("file") or ""), str(slot.get("slot") or ""))
        if key in contract_slots:
            slot["capacity"] = contract_slots[key].get("capacity")
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
    fit_warnings: list[dict[str, Any]] = []
    fit_notes: list[dict[str, Any]] = []
    source_html_by_file: dict[str, str] = {}
    for slide in slide_list:
        rel = str(slide.get("file") or "").strip()
        if not rel:
            continue
        path = dest / rel
        if not path.is_file():
            continue
        html_before = path.read_text(encoding="utf-8")
        source_html_by_file[rel] = html_before
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
        page_fit_report: list[dict[str, Any]] = []
        html = apply_text_to_html(
            html,
            file_texts,
            fit=True,
            fit_report=page_fit_report,
        )
        for item in page_fit_report:
            target = (
                fit_warnings
                if item.get("reason") == "content_truncated"
                else fit_notes
            )
            target.append({**item, "file": rel, "source": "layout"})
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

        # 出画硬校验：按叶子真实盒宽/画布边界复查，仍溢出则记 warning 并降级状态
        page_issues = verify_slide_fit(html, baseline=html_before)
        if page_issues:
            for issue in page_issues[:6]:
                _log(
                    log,
                    f"[remix-fit] {rel}#{issue.get('slot')} {issue.get('reason')} "
                    f"{json.dumps({k: v for k, v in issue.items() if k not in {'slot', 'reason'}}, ensure_ascii=False)}",
                )
            fit_warnings.extend({**issue, "file": rel} for issue in page_issues)

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

    # 真实浏览器实测是最终闸门：捕获字体回退、letter-spacing 取整与 flex 行盒
    # 造成的溢出，并与源模板基线比较，只拦截新增/恶化的越界。
    render_report: dict[str, Any] | None = None
    if render_check:
        try:
            from templates.render_check import check_package_render

            probe = check_package_render(dest)
            baseline_probe = check_package_render(source_dir)
            regressions = render_regressions(probe, baseline_probe)
            remaining_truncations: list[dict[str, Any]] = []
            render_report = {
                "engine": probe.get("engine"),
                "pages": probe.get("pages"),
                "issues": len(probe.get("issues") or []),
                "regressions": len(regressions),
                "baseline_engine": baseline_probe.get("engine"),
                "baseline_issues": len(baseline_probe.get("issues") or []),
            }
            _log(
                log,
                f"[remix-render] engine={probe.get('engine')} pages={probe.get('pages')} "
                f"issues={len(probe.get('issues') or [])} "
                f"regressions={len(regressions)} "
                f"baseline={(baseline_probe.get('issues') or []).__len__()}",
            )

            repair_findings = list(regressions)
            repair_findings.extend(
                {
                    **item,
                    "reason": item.get("reason") or "content_truncated",
                }
                for item in fit_warnings
                if item.get("reason") in {
                    "content_truncated",
                    "ink_overflow",
                    "canvas_x",
                    "canvas_y",
                    "vertical_overflow",
                }
                and item.get("slot")
            )
            if repair_findings and not use_mock:
                files = {
                    str(item.get("file") or "")
                    for item in repair_findings
                    if item.get("file")
                }
                repair_slots: list[dict[str, Any]] = []
                for slot in text_slots:
                    if str(slot.get("file") or "") not in files:
                        continue
                    key = (
                        str(slot.get("file") or ""),
                        str(slot.get("slot") or ""),
                    )
                    if not any(
                        (
                            str(item.get("file") or ""),
                            str(item.get("slot") or ""),
                        )
                        == key
                        for item in repair_findings
                    ):
                        continue
                    compact = dict(slot)
                    budgets = [
                        max(1, int(int(x or 0) * 0.72))
                        for x in (slot.get("line_budgets") or [])
                        if int(x or 0) > 0
                    ]
                    compact["line_budgets"] = budgets
                    compact["line_chars"] = min(budgets) if budgets else 1
                    compact["max_chars"] = max(1, sum(budgets)) if budgets else 1
                    repair_slots.append(compact)
                repair_pages = [
                    p
                    for p in slide_list
                    if str(p.get("file") or "") in files
                ]
                if repair_slots:
                    try:
                        _log(
                            log,
                            f"[remix-render] auto-repair slots={len(repair_slots)} "
                            "with 72% capacity",
                        )
                        patch_plan = _plan_content_once(
                            prompt=(
                                prompt
                                + "\n浏览器实测发生文字溢出。请对指定槽位重写为更短、"
                                "完整的中文短语，严格遵守新的 max_chars。"
                            ),
                            slots=repair_slots,
                            source_label=source_label,
                            pages=repair_pages,
                            visual_brief=visual_brief,
                            log=log,
                            temperature=0.2,
                            focus_missing=True,
                        )
                        patch_plan = normalize_structured_plan(
                            patch_plan, repair_slots
                        )
                        repair_texts = (
                            patch_plan.get("texts")
                            if isinstance(patch_plan.get("texts"), dict)
                            else {}
                        )
                        repair_fit_report: list[dict[str, Any]] = []
                        for rel in files:
                            path = dest / rel
                            source_html = source_html_by_file.get(rel)
                            if not path.is_file() or source_html is None:
                                continue
                            planned = dict(_lookup_file_map(repair_texts, rel))
                            planned = clamp_texts_for_slots(planned, repair_slots)
                            if not planned:
                                continue
                            rebuilt = apply_text_to_html(
                                path.read_text(encoding="utf-8"),
                                planned,
                                fit=True,
                                fit_report=repair_fit_report,
                            )
                            path.write_text(
                                rebuilt
                                if rebuilt.endswith("\n")
                                else rebuilt + "\n",
                                encoding="utf-8",
                            )
                        probe = check_package_render(dest)
                        regressions = render_regressions(probe, baseline_probe)
                        remaining_truncations = [
                            item
                            for item in repair_fit_report
                            if item.get("reason") == "content_truncated"
                        ]
                        render_report["repair_rounds"] = 1
                        render_report["issues_after_repair"] = len(
                            probe.get("issues") or []
                        )
                        render_report["regressions_after_repair"] = len(regressions)
                        render_report["truncations_after_repair"] = len(
                            remaining_truncations
                        )
                        _log(
                            log,
                            f"[remix-render] after-repair issues="
                            f"{len(probe.get('issues') or [])} "
                            f"regressions={len(regressions)} "
                            f"truncations={len(remaining_truncations)}",
                        )
                        if not regressions and not remaining_truncations:
                            # The repaired copy passed both gates; do not keep the
                            # obsolete first-pass truncation warnings.
                            fit_warnings[:] = [
                                item
                                for item in fit_warnings
                                if not (
                                    item.get("file") in files
                                    and item.get("slot")
                                )
                            ]
                    except Exception as e:  # noqa: BLE001
                        _log(log, f"[remix-render] auto-repair skipped: {e}")

            fallback_findings = list(regressions) + list(remaining_truncations)
            if fallback_findings:
                # 最后一层安全网：真实越界槽位恢复源文案，绝不把截断文本静默发布。
                by_file: dict[str, set[str]] = {}
                for item in fallback_findings:
                    rel = str(item.get("file") or "")
                    slot_id = str(item.get("slot") or "")
                    if rel and slot_id:
                        by_file.setdefault(rel, set()).add(slot_id)
                restored = 0
                for rel, slot_ids in by_file.items():
                    path = dest / rel
                    source_html = source_html_by_file.get(rel)
                    if not path.is_file() or source_html is None:
                        continue
                    current = path.read_text(encoding="utf-8")
                    next_html = _restore_source_slots(
                        html=current,
                        source_html=source_html,
                        file=rel,
                        slot_ids=slot_ids,
                    )
                    if next_html != current:
                        restored += len(slot_ids)
                        path.write_text(
                            next_html
                            if next_html.endswith("\n")
                            else next_html + "\n",
                            encoding="utf-8",
                        )
                if restored:
                    probe = check_package_render(dest)
                    regressions = render_regressions(probe, baseline_probe)
                    render_report["source_fallback_slots"] = restored
                    render_report["regressions_after_fallback"] = len(regressions)
                    _log(
                        log,
                        f"[remix-render] restored source copy for {restored} unsafe "
                        f"slot(s); regressions={len(regressions)}",
                    )

            for item in (probe.get("issues") or [])[:20]:
                if item not in regressions:
                    continue
                _log(
                    log,
                    f"[remix-render] {item.get('file')}#{item.get('slot')} "
                    f"{item.get('reason')} {item.get('text', '')[:40]!r}",
                )
                fit_warnings.append({**item, "source": "render"})
            if probe.get("error") and probe.get("engine") == "none":
                _log(log, f"[remix-render] skipped: {probe.get('error')}")
                fit_warnings.append(
                    {
                        "slot": "",
                        "file": "",
                        "reason": "render_check_unavailable",
                        "message": str(probe.get("error") or ""),
                        "source": "render",
                    }
                )
            render_report["regressions"] = len(regressions)
            render_report["issues"] = len(probe.get("issues") or [])
        except Exception as e:  # noqa: BLE001 - 实测基础设施失败也不能静默发布
            _log(log, f"[remix-render] skipped: {e}")
            fit_warnings.append(
                {
                    "slot": "",
                    "file": "",
                    "reason": "render_check_failed",
                    "message": str(e),
                    "source": "render",
                }
            )

    if isinstance(pages, list):
        new_meta["slides"] = pages
    remix_meta = dict(new_meta.get("remix") or {})
    remix_meta.pop("in_progress", None)
    remix_meta["text_applied"] = text_applied
    remix_meta["capacity_schema"] = "1.0"
    if render_report is not None:
        remix_meta["render_check"] = render_report
    if fit_notes:
        remix_meta["fit_notes"] = fit_notes[:60]
    else:
        remix_meta.pop("fit_notes", None)
    if fit_warnings:
        remix_meta["fit_warnings"] = fit_warnings[:60]
        # 有越界就不许静默通过：已 approved 的批次降回 pending 待复核
        if str(new_meta.get("status")) == "approved":
            new_meta["status"] = "pending"
        _log(
            log,
            f"[remix] fit warnings={len(fit_warnings)} "
            f"→ status={new_meta.get('status')}（请复核该模板）",
        )
    else:
        remix_meta.pop("fit_warnings", None)
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
        "fit_warnings": len(fit_warnings),
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
    render_check: bool = False,
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
        render_check=render_check,
        log=log,
    )
