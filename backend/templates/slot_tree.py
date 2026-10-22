"""把「复合文本槽」拆成叶子槽（一个槽只覆盖一个绝对定位文本框）。

PPTX→HTML 渲染器常把「6 行 × N 字段」的列表整块包进一个绝对定位 div，只打一个
``data-slot``。remix 管线因此只看到一坨文本：LLM 无法按行/字段对齐，fit 也只拿到
外层宽度，长文案会冲出卡片与画布。

本模块在 HTML 上做三件事：

1. ``split_composite_slots``：把复合槽内部每个绝对定位文本盒提升为独立
   ``data-slot``，父 div 降级为纯容器；纯序号列（01/02…）保持静态不动。
2. ``measure_slots``：按绝对定位累加祖先偏移，得到每个槽在画布上的真实位置与
   每行文本的字号，供越界校验使用。
3. ``split_package_slots``：对包内 slides/*.html 批量执行（remix 克隆后调用）。

改写采用「原始字符串拼接」而不是重新序列化整页 HTML：HTMLParser 会把属性名
小写化（SVG ``viewBox`` → ``viewbox``），重排整页会破坏渲染。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable

from templates.slot_ensure import (
    _Node,
    _TreeBuilder,
    _has_attr_slot,
    _has_slotted_descendant,
    _has_span_text,
    _max_font_pt,
    _plain_text,
    _style_pos_absolute,
)

LogFn = Callable[[str], None]

_INDEX_TEXTS = re.compile(r"^(?:\d{1,2}|[０-９]{1,2})$")
_SLOT_ATTR_RE = re.compile(
    r"""\s+data-slot\s*=\s*("[^"]*"|'[^']*')"""
    r"""|\s+data-slot-type\s*=\s*("[^"]*"|'[^']*')"""
    r"""|\s+data-slot-role\s*=\s*("[^"]*"|'[^']*')""",
    re.I,
)


def _style_px(style: str, prop: str) -> float | None:
    """Read a px value for one CSS property; ignore padding-/margin-/border- variants."""
    m = re.search(
        rf"(?<![-\w]){re.escape(prop)}\s*:\s*(-?[\d.]+)\s*px",
        style or "",
        re.I,
    )
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _px_width(node: _Node) -> float | None:
    return _style_px(node.attrs.get("style", ""), "width")


def _style_length(style: str, prop: str, basis: float) -> float | None:
    """Resolve a px or percentage CSS length against its containing box."""
    px = _style_px(style, prop)
    if px is not None:
        return px
    m = re.search(
        rf"(?<![-\w]){re.escape(prop)}\s*:\s*(-?[\d.]+)\s*%",
        style or "",
        re.I,
    )
    if not m or basis <= 0:
        return None
    try:
        return basis * float(m.group(1)) / 100.0
    except ValueError:
        return None


def _slot_role(node: _Node) -> str:
    return (node.attrs.get("data-slot-role") or "").strip()


def _has_image_slot(node: _Node) -> bool:
    if node.kind != "tag":
        return False
    if node.attrs.get("data-slot-type") == "image":
        return True
    return any(_has_image_slot(ch) for ch in node.children if ch.kind == "tag")


def _span_texts(node: _Node) -> list[str]:
    """Span 叶子文本，保持 DOM 顺序（相对 ``<span>`` 解析）。"""
    out: list[str] = []
    if node.kind != "tag":
        return out
    if node.tag == "span":
        text = _plain_text(node)
        if text:
            out.append(text)
        return out
    for ch in node.children:
        out.extend(_span_texts(ch))
    return out


def _is_index_text(text: str) -> bool:
    return bool(_INDEX_TEXTS.match(re.sub(r"\s+", "", text or "")))


def _looks_like_index_column(leaves: list[_Node]) -> set[int]:
    """同一列、top 各不相同的 1~2 位纯数字 → 版式序号列，保持静态。"""
    idx: list[_Node] = [
        leaf for leaf in leaves if _is_index_text(_plain_text(leaf))
    ]
    if len(idx) < 3:
        return set()
    lefts = [_style_px(leaf.attrs.get("style", ""), "left") or 0.0 for leaf in idx]
    tops = [_style_px(leaf.attrs.get("style", ""), "top") or 0.0 for leaf in idx]
    if max(lefts) - min(lefts) > 24.0:
        return set()
    if len({round(t, 1) for t in tops}) < len(idx):
        return set()
    return {id(leaf) for leaf in idx}


def _leaf_role(text: str, font_pt: float | None, parent_role: str) -> str:
    tight = re.sub(r"\s+", " ", text or "").strip()
    n = len(tight)
    if parent_role in {"page-title", "cover-title", "section-title"} and n <= 80:
        return parent_role
    if font_pt is not None and font_pt < 12:
        return "meta"
    if font_pt is not None and font_pt >= 24 and n <= 40:
        return "heading"
    if n <= 12 and (font_pt is None or font_pt < 16):
        return "meta"
    return "body"


def _collect_leaf_boxes(node: _Node, out: list[_Node]) -> None:
    """收集复合槽内部最外层「有 px 宽度的绝对定位文本盒」。"""
    if node.kind != "tag":
        return
    if _has_attr_slot(node) or _has_image_slot(node):
        return
    if (
        node.tag == "div"
        and _style_pos_absolute(node)
        and _px_width(node) is not None
        and _has_span_text(node)
    ):
        out.append(node)
        return
    for ch in node.children:
        _collect_leaf_boxes(ch, out)


def _walk_slots(node: _Node, out: list[_Node]) -> None:
    if node.kind != "tag":
        return
    if _has_attr_slot(node) and node.attrs.get("data-slot-type", "text") != "image":
        out.append(node)
        return
    for ch in node.children:
        _walk_slots(ch, out)


class _OffsetBuilder(_TreeBuilder):
    """记录每个起始标签在原始 HTML 中的绝对偏移，供字符串拼接改写用。"""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.src = html
        self.line_starts = [0] + [m.end() for m in re.finditer(r"\n", html)]
        self.offsets: dict[int, int] = {}

    def _offset(self) -> int:
        line, col = self.getpos()
        if line <= 0 or line > len(self.line_starts):
            return -1
        return self.line_starts[line - 1] + col

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        if not self.stack:
            return
        top = self.stack[-1]
        # 非 void 标签已被 push，栈顶就是新节点；void 标签仍在父节点 children 末尾。
        node = top if top.tag == tag.lower() else (top.children[-1] if top.children else None)
        if node is not None:
            self.offsets[id(node)] = self._offset()

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        super().handle_startendtag(tag, attrs)
        if self.stack and self.stack[-1].children:
            self.offsets[id(self.stack[-1].children[-1])] = self._offset()


def _parse(html: str) -> _OffsetBuilder | None:
    builder = _OffsetBuilder(html)
    try:
        builder.feed(html)
        builder.close()
    except Exception:  # noqa: BLE001 - 坏 HTML 时直接放弃拆分
        return None
    return builder


def _tag_end(html: str, start: int) -> int:
    """返回起始标签 ``>`` 的下标；引号内的 ``>`` 不算。"""
    quote: str | None = None
    i = start
    n = len(html)
    while i < n:
        ch = html[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == ">":
            return i
        i += 1
    return -1


def _strip_slot_attrs(tag: str) -> str:
    return _SLOT_ATTR_RE.sub("", tag)


def split_composite_slots(html: str) -> tuple[str, dict[str, Any]]:
    """把复合文本槽拆成叶子槽；返回 (new_html, stats)。"""
    empty = {"split": 0, "leaves": 0, "index_kept": 0, "files": 0}
    if not html or "data-slot" not in html:
        return html, dict(empty)

    builder = _parse(html)
    if builder is None:
        return html, {**empty, "error": "parse_failed"}

    slot_nodes: list[_Node] = []
    _walk_slots(builder.root, slot_nodes)
    splices: list[tuple[int, int, str]] = []
    split = leaves = index_kept = 0

    for slot in slot_nodes:
        if slot.attrs.get("data-slot-type", "text") == "image":
            continue
        base = (slot.attrs.get("data-slot") or "").strip()
        if not base:
            continue
        candidates: list[_Node] = []
        for ch in slot.children:
            _collect_leaf_boxes(ch, candidates)
        if len(candidates) < 2:
            continue
        index_ids = _looks_like_index_column(candidates)
        target = [c for c in candidates if id(c) not in index_ids]
        if len(target) < 2:
            continue

        parent_start = builder.offsets.get(id(slot), -1)
        parent_end = _tag_end(html, parent_start) if parent_start >= 0 else -1
        if parent_start < 0 or parent_end < 0:
            continue
        prefix = html[parent_start : parent_end + 1]
        cleaned = _strip_slot_attrs(prefix)
        if cleaned == prefix:
            continue  # 父槽不在原始 HTML 里（理论不会发生），跳过避免半拆
        splices.append((parent_start, parent_end + 1, cleaned))
        split += 1
        index_kept += len(index_ids)

        parent_role = _slot_role(slot)
        # 序号列是版式元素，显式标记为静态：再套一次 remix 时
        # ensure_orphan_slots 不会把它们重新补成可改写槽。
        for leaf in candidates:
            if id(leaf) not in index_ids:
                continue
            start = builder.offsets.get(id(leaf), -1)
            end = _tag_end(html, start) if start >= 0 else -1
            if start < 0 or end < 0:
                continue
            tag = html[start : end + 1]
            if "data-slot-static" in tag:
                continue
            splices.append((start, end + 1, tag[:-1] + ' data-slot-static="1">'))

        for i, leaf in enumerate(target):
            start = builder.offsets.get(id(leaf), -1)
            end = _tag_end(html, start) if start >= 0 else -1
            if start < 0 or end < 0:
                continue
            text = _plain_text(leaf)
            font_pt = _max_font_pt(leaf)
            role = _leaf_role(text, font_pt, parent_role)
            tag = html[start : end + 1]
            added = (
                f' data-slot="{base}-{i + 1}"'
                f' data-slot-type="text"'
                f' data-slot-role="{role}"'
            )
            splices.append((start, end + 1, tag[:-1] + added + ">"))
            leaves += 1

    if not splices:
        return html, dict(empty)

    # 同一标签既做父槽清理又做叶子补丁时不会重叠（父与子不同标签）。
    out_parts: list[str] = []
    cursor = 0
    for start, end, replacement in sorted(splices, key=lambda s: s[0]):
        if start < cursor:
            continue
        out_parts.append(html[cursor:start])
        out_parts.append(replacement)
        cursor = end
    out_parts.append(html[cursor:])
    out = "".join(out_parts)
    return out, {
        "split": split,
        "leaves": leaves,
        "index_kept": index_kept,
        "files": 1,
    }


def split_package_slots(
    pack_dir: str | Path,
    *,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """扫描包内 slides/*.html，原地拆分复合槽。"""
    root = Path(pack_dir)
    slides = root / "slides"
    stats = {"files": 0, "split": 0, "leaves": 0, "index_kept": 0}
    if not slides.is_dir():
        return stats
    for path in sorted(slides.glob("*.html")):
        raw = path.read_text(encoding="utf-8")
        next_html, one = split_composite_slots(raw)
        if next_html == raw or not one.get("split"):
            continue
        path.write_text(
            next_html if next_html.endswith("\n") else next_html + "\n",
            encoding="utf-8",
        )
        stats["files"] += 1
        stats["split"] += int(one.get("split") or 0)
        stats["leaves"] += int(one.get("leaves") or 0)
        stats["index_kept"] += int(one.get("index_kept") or 0)
        if log:
            log(
                f"[slot-tree] {path.name}: split={one.get('split', 0)} "
                f"leaves={one.get('leaves', 0)} index_kept={one.get('index_kept', 0)}"
            )
    return stats


def _line_height_px(style: str, font_px: float) -> float:
    """Resolve one line box height in px from ``line-height`` (px/pt/unitless)."""
    m = re.search(r"line-height\s*:\s*([\d.]+)\s*(px|pt)?", style or "", re.I)
    if m:
        try:
            value = float(m.group(1))
        except ValueError:
            value = 0.0
        unit = (m.group(2) or "").lower()
        if unit == "px":
            return max(value, font_px * 1.05)
        if unit == "pt":
            return max(value * 96.0 / 72.0, font_px * 1.05)
        if value > 0:
            return max(value * font_px, font_px * 1.05)
    return font_px * 1.25


def _font_px_of(node: _Node) -> float:
    pt = _max_font_pt(node)
    return (pt * 96.0 / 72.0) if pt else 0.0


def _line_wrappers(node: _Node, out: list[_Node]) -> list[_Node]:
    """Innermost ``div`` wrappers that directly carry span text = one visual line."""
    if node.kind != "tag":
        return out
    if node.tag == "div":
        inner = [ch for ch in node.children if ch.kind == "tag"]
        has_direct_span_text = any(
            ch.tag == "span" and _plain_text(ch) for ch in inner
        )
        # Only *nested* spans count as deeper lines; direct spans are this line.
        deeper = any(
            _has_span_text(ch) for ch in inner if ch.tag != "span"
        )
        if has_direct_span_text and not deeper:
            out.append(node)
            return out
    for ch in node.children:
        _line_wrappers(ch, out)
    return out


def _is_flex_column(node: _Node) -> bool:
    style = node.attrs.get("style", "")
    if not re.search(r"display\s*:\s*flex", style, re.I):
        return False
    return bool(re.search(r"flex-direction\s*:\s*column", style, re.I))


def _visual_lines(node: _Node) -> list[dict[str, Any]]:
    """One entry per rendered line: text + font px + line-height px + spans.

    Spans inside the same line wrapper are inline (e.g. 「八一」+「· 军民共建」),
    so counting spans would double the line count and produce false overflow.
    A wrapper with ``flex-direction: column`` stacks each child span on its own
    line instead — that is the common "flex column of rows" renderer pattern.
    The ``spans`` list keeps each inline run's own text/font so width can be
    measured per run (mixed-size numbers inside one line).
    """
    lines: list[dict[str, Any]] = []
    if node.kind != "tag":
        return lines
    wrappers = _line_wrappers(node, [])
    unknown = not wrappers
    if unknown:
        # Unknown structure (spans directly under the slot): keep the historical
        # reading — one span per line — instead of merging unrelated copy.
        wrappers = [node]
    for wrap in wrappers:
        direct = [ch for ch in wrap.children if ch.kind == "tag" and ch.tag == "span"]
        if not direct:
            direct = _descendant_spans(wrap)
        column = _is_flex_column(wrap) or (unknown and wrap is node)
        groups = [[sp] for sp in direct] if column else [direct]
        for group in groups:
            runs: list[dict[str, Any]] = []
            for sp in group:
                text = re.sub(r"\s+", " ", _plain_text(sp)).strip()
                if not text:
                    continue
                runs.append({"text": text, "font_px": _font_px_of(sp)})
            text = "".join(r["text"] for r in runs).strip()
            if not text:
                continue
            font_px = 0.0
            for r in runs:
                font_px = max(font_px, float(r["font_px"] or 0))
            if font_px <= 0:
                font_px = _font_px_of(wrap) or _font_px_of(node)
                for r in runs:
                    r["font_px"] = font_px
            style = wrap.attrs.get("style", "")
            lines.append(
                {
                    "text": text,
                    "font_px": font_px,
                    "line_px": _line_height_px(style, font_px),
                    "spans": runs,
                }
            )
    return lines


def _descendant_spans(node: _Node) -> list[_Node]:
    out: list[_Node] = []
    for ch in node.children:
        if ch.kind != "tag":
            continue
        if ch.tag == "span":
            out.append(ch)
        else:
            out.extend(_descendant_spans(ch))
    return out


def _span_lines(node: _Node) -> list[dict[str, Any]]:
    """每个视觉行一条：文本 + 字号（pt）+ 行内各 run。

    ``runs`` keeps per-run fonts for inline mixed-size rows, so width checks match
    what the browser actually lays out.
    """
    out: list[dict[str, Any]] = []
    for ln in _visual_lines(node):
        font_px = float(ln.get("font_px") or 0)
        runs = [
            {
                "text": r.get("text") or "",
                "font_pt": round(float(r.get("font_px") or 0) * 72.0 / 96.0, 2)
                if r.get("font_px")
                else 0.0,
            }
            for r in (ln.get("spans") or [])
        ]
        out.append(
            {
                "text": ln.get("text") or "",
                "font_pt": round(font_px * 72.0 / 96.0, 2) if font_px else 0.0,
                "line_px": round(float(ln.get("line_px") or 0), 1),
                "runs": runs,
            }
        )
    return out


def _canvas_size(html: str) -> tuple[float, float]:
    m = re.search(
        r"""<div[^>]*class\s*=\s*["'][^"']*pptx-slide-root[^"']*["'][^>]*style\s*=\s*["']([^"']*)["']""",
        html,
        re.I,
    )
    style = m.group(1) if m else ""
    width = _style_px(style, "width") or 1920.0
    height = _style_px(style, "height") or 1080.0
    return width, height


def canvas_size(html: str) -> tuple[float, float]:
    """画布尺寸（默认 1920×1080）。"""
    return _canvas_size(html)


def _subtree_style(node: _Node, depth: int = 0) -> str:
    """Concatenate styles of a small subtree so inherited nowrap is visible."""
    if node.kind != "tag" or depth > 4:
        return ""
    parts = [node.attrs.get("style", "")]
    for ch in node.children:
        if ch.kind == "tag" and ch.tag != "svg":
            parts.append(_subtree_style(ch, depth + 1))
    return " ".join(p for p in parts if p)


def measure_slots(html: str) -> dict[str, dict[str, Any]]:
    """按绝对定位累加祖先偏移，返回 slot → {x, y, width, height, lines…}。"""
    builder = _parse(html)
    if builder is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    root_width, root_height = _canvas_size(html)

    def walk(
        node: _Node,
        ox: float,
        oy: float,
        parent_width: float,
        parent_height: float,
    ) -> None:
        if node.kind != "tag":
            return
        style = node.attrs.get("style", "")
        nx, ny = ox, oy
        if _style_pos_absolute(node):
            nx = ox + (_style_length(style, "left", parent_width) or 0.0)
            ny = oy + (_style_length(style, "top", parent_height) or 0.0)
        own_width = _style_length(style, "width", parent_width)
        own_height = _style_length(style, "height", parent_height)
        width = own_width if own_width is not None else parent_width
        height = own_height if own_height is not None else parent_height
        slot = (node.attrs.get("data-slot") or "").strip()
        if slot and node.attrs.get("data-slot-type", "text") != "image":
            lines = _span_lines(node)
            subtree = _subtree_style(node)
            out[slot] = {
                "slot": slot,
                "x": nx,
                "y": ny,
                "width": width,
                "height": height,
                "font_pt": _max_font_pt(node),
                "lines": lines,
                "nowrap": bool(
                    re.search(r"white-space\s*:\s*nowrap", subtree, re.I)
                ),
                "overflow_hidden": bool(
                    re.search(r"overflow\s*:\s*hidden", subtree, re.I)
                ),
                "role": node.attrs.get("data-slot-role") or "",
            }
        for ch in node.children:
            walk(ch, nx, ny, width, height)

    walk(builder.root, 0.0, 0.0, root_width, root_height)
    return out


def absolute_slot_boxes(html: str) -> dict[str, dict[str, Any]]:
    """兼容别名：与 :func:`measure_slots` 相同。"""
    return measure_slots(html)


def visual_lines_fragment(fragment: str) -> list[dict[str, Any]]:
    """Visual lines for a slot *inner fragment* (not a whole slide).

    Used by fit logic so an inline 「说明 + 数字 + 单位」 line is measured as one
    line at its summed width instead of one line per span.
    """
    if not fragment or "<span" not in fragment:
        return []
    builder = _parse(fragment)
    if builder is None:
        return []
    nodes: list[_Node] = [ch for ch in builder.root.children if ch.kind == "tag"]
    if len(nodes) == 1 and nodes[0].tag == "div":
        return _visual_lines(nodes[0])
    return _visual_lines(builder.root)
