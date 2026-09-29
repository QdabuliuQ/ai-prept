"""补打遗漏的 data-slot：嵌套文本框 / 未标注图片。

PPTX 转换依赖绝对坐标匹配，组内相对定位文本常漏槽。
此模块在 HTML 上做兜底：叶子文本容器与裸 img 补 data-slot*。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from os import PathLike
from pathlib import Path
from typing import Any

_VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


def _slug(raw: str) -> str:
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff_-]+", "-", str(raw).strip().lower())
    s = re.sub(r"^-+|-+$", "", s)[:48]
    return s or "slot"


def _infer_text_role(text: str, font_pt: float | None) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    n = len(t)
    if font_pt is not None:
        if font_pt >= 40 and n <= 60:
            return "heading"
        if font_pt >= 28 and n <= 100:
            return "lede"
    if n <= 24:
        return "meta"
    if n <= 80:
        return "heading"
    return "body"


def _font_pt_from_style(style: str) -> float | None:
    m = re.search(r"font-size\s*:\s*([\d.]+)\s*pt", style or "", re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"font-size\s*:\s*([\d.]+)\s*px", style or "", re.I)
    if m:
        return float(m.group(1)) * 0.75
    return None


def _attr_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in attrs:
        if k:
            out[k.lower()] = v or ""
    return out


def _fmt_attrs(attrs: dict[str, str]) -> str:
    parts: list[str] = []
    for k, v in attrs.items():
        if v == "":
            parts.append(k)
        else:
            esc = v.replace("&", "&amp;").replace('"', "&quot;")
            parts.append(f'{k}="{esc}"')
    return (" " + " ".join(parts)) if parts else ""


class _Node:
    __slots__ = ("kind", "tag", "attrs", "children", "text", "void")

    def __init__(
        self,
        kind: str,
        tag: str = "",
        attrs: dict[str, str] | None = None,
        text: str = "",
        void: bool = False,
    ):
        self.kind = kind  # tag | text | comment | decl
        self.tag = tag.lower() if tag else ""
        self.attrs = attrs or {}
        self.children: list[_Node] = []
        self.text = text
        self.void = void


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.root = _Node("tag", "root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        node = _Node("tag", t, _attr_dict(attrs), void=t in _VOID)
        self.stack[-1].children.append(node)
        if not node.void:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        node = _Node("tag", t, _attr_dict(attrs), void=True)
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        # pop until matching
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == t:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self.stack[-1].children.append(_Node("text", text=data))

    def handle_entityref(self, name: str) -> None:
        self.stack[-1].children.append(_Node("text", text=f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.stack[-1].children.append(_Node("text", text=f"&#{name};"))

    def handle_comment(self, data: str) -> None:
        self.stack[-1].children.append(_Node("comment", text=data))

    def handle_decl(self, decl: str) -> None:
        self.stack[-1].children.append(_Node("decl", text=decl))


def _plain_text(node: _Node) -> str:
    if node.kind == "text":
        return node.text
    if node.kind != "tag":
        return ""
    if node.tag in {"script", "style"}:
        return ""
    parts: list[str] = []
    for ch in node.children:
        parts.append(_plain_text(ch))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _has_attr_slot(node: _Node) -> bool:
    return bool(node.attrs.get("data-slot"))


def _ancestor_has_slot(path: list[_Node]) -> bool:
    return any(_has_attr_slot(n) for n in path)


def _style_pos_absolute(node: _Node) -> bool:
    return bool(re.search(r"position\s*:\s*absolute", node.attrs.get("style", ""), re.I))


def _max_font_pt(node: _Node) -> float | None:
    best = _font_pt_from_style(node.attrs.get("style", ""))
    for ch in node.children:
        if ch.kind != "tag":
            continue
        got = _max_font_pt(ch)
        if got is None:
            continue
        best = got if best is None else max(best, got)
    return best


def _has_span_text(node: _Node) -> bool:
    if node.kind != "tag":
        return False
    if node.tag == "span" and _plain_text(node):
        return True
    return any(_has_span_text(ch) for ch in node.children if ch.kind == "tag")


def _has_slotted_descendant(node: _Node) -> bool:
    if node.kind != "tag":
        return False
    if _has_attr_slot(node):
        return True
    return any(_has_slotted_descendant(ch) for ch in node.children if ch.kind == "tag")


def _strip_slot_attrs(node: _Node) -> int:
    """Remove data-slot* from a subtree (cleanup nested duplicates)."""
    n = 0
    if node.kind != "tag":
        return 0
    for key in ("data-slot", "data-slot-type", "data-slot-role"):
        if key in node.attrs:
            del node.attrs[key]
            n += 1
    for ch in node.children:
        n += _strip_slot_attrs(ch)
    return n


def _dedupe_nested_slots(node: _Node, ancestor_slotted: bool) -> int:
    """Keep outermost data-slot; strip any nested data-slot*."""
    if node.kind != "tag":
        return 0
    slotted = _has_attr_slot(node)
    n = 0
    if slotted and ancestor_slotted:
        for key in ("data-slot", "data-slot-type", "data-slot-role"):
            if key in node.attrs:
                del node.attrs[key]
                n += 1
        slotted = False
    for ch in node.children:
        n += _dedupe_nested_slots(ch, ancestor_slotted or slotted)
    return n


def _count_slot_type(node: _Node, slot_type: str) -> int:
    if node.kind != "tag":
        return 0
    n = 1 if node.attrs.get("data-slot-type") == slot_type else 0
    for ch in node.children:
        n += _count_slot_type(ch, slot_type)
    return n


def _collect(
    node: _Node,
    path: list[_Node],
    text_cands: list[_Node],
    img_cands: list[_Node],
) -> None:
    if node.kind != "tag":
        return
    cur_path = path + [node]
    if node.tag == "img" and not _has_attr_slot(node) and not _ancestor_has_slot(path):
        img_cands.append(node)
    # absolute text boxes: skip if self/ancestor/descendant already slotted
    if (
        node.tag == "div"
        and _style_pos_absolute(node)
        and not _has_attr_slot(node)
        and not _ancestor_has_slot(path)
        and not _has_slotted_descendant(node)
        and _has_span_text(node)
        and len(_plain_text(node)) >= 1
    ):
        text_cands.append(node)
    for ch in node.children:
        _collect(ch, cur_path, text_cands, img_cands)


def _outer_text_boxes(cands: list[_Node]) -> list[_Node]:
    """Keep outermost absolute boxes (not contained by another candidate)."""
    out: list[_Node] = []
    for el in cands:
        if any(other is not el and _contains(other, el) for other in cands):
            continue
        out.append(el)
    return out


def _contains(parent: _Node, child: _Node) -> bool:
    for ch in parent.children:
        if ch is child:
            return True
        if ch.kind == "tag" and _contains(ch, child):
            return True
    return False


def _slot_attrs_for_text(text: str, font_pt: float | None, index: int) -> dict[str, str]:
    role = _infer_text_role(text, font_pt)
    if role in {"heading", "page-title"}:
        slot = "title" if index == 0 else f"title-{index + 1}"
        role = "page-title" if index == 0 and role == "heading" else role
    elif role == "lede":
        slot = "subtitle" if index == 0 else f"subtitle-{index + 1}"
    elif role == "meta":
        slot = "eyebrow" if index == 0 else f"eyebrow-{index + 1}"
    else:
        slot = f"body-{index + 1}"
    return {
        "data-slot": slot,
        "data-slot-type": "text",
        "data-slot-role": role,
    }


def _serialize(node: _Node) -> str:
    if node.kind == "text":
        return node.text
    if node.kind == "comment":
        return f"<!--{node.text}-->"
    if node.kind == "decl":
        return f"<!{node.text}>"
    if node.tag == "root":
        return "".join(_serialize(ch) for ch in node.children)
    attrs = _fmt_attrs(node.attrs)
    if node.void:
        return f"<{node.tag}{attrs}>"
    inner = "".join(_serialize(ch) for ch in node.children)
    return f"<{node.tag}{attrs}>{inner}</{node.tag}>"


def ensure_orphan_slots(html: str) -> tuple[str, dict[str, Any]]:
    """返回 (html, stats)。已有 data-slot 的节点不动。"""
    if not html or not html.strip():
        return html, {"text": 0, "image": 0}

    builder = _TreeBuilder()
    try:
        builder.feed(html)
        builder.close()
    except Exception:
        return html, {"text": 0, "image": 0, "error": "parse_failed"}

    text_cands: list[_Node] = []
    img_cands: list[_Node] = []
    # 先去掉嵌套重复槽（上次误打在内层时留下的）
    nested_stripped = _dedupe_nested_slots(builder.root, False)
    _collect(builder.root, [], text_cands, img_cands)
    targets = _outer_text_boxes(text_cands)

    # existing text slot count for index continuity
    existing_text = len(re.findall(r'data-slot-type=["\']text["\']', html, re.I))
    # recount from tree after dedupe for better indices
    existing_text = _count_slot_type(builder.root, "text")
    existing_img = _count_slot_type(builder.root, "image")

    text_added = 0
    for i, el in enumerate(targets):
        plain = _plain_text(el)
        if not plain:
            continue
        font_pt = _max_font_pt(el)
        attrs = _slot_attrs_for_text(plain, font_pt, existing_text + text_added)
        el.attrs.update(attrs)
        text_added += 1

    img_added = 0
    for el in img_cands:
        idx = existing_img + img_added
        el.attrs["data-slot"] = "hero-image" if idx == 0 else f"image-{idx + 1}"
        el.attrs["data-slot-type"] = "image"
        el.attrs["data-slot-role"] = "hero-image" if idx == 0 else "image"
        img_added += 1

    if text_added == 0 and img_added == 0 and nested_stripped == 0:
        return html, {"text": 0, "image": 0}

    out = _serialize(builder.root)
    out = _uniquify_slot_ids(out)
    return out, {
        "text": text_added,
        "image": img_added,
        "nested_stripped": nested_stripped,
    }


def _uniquify_slot_ids(html: str) -> str:
    seen: dict[str, int] = {}

    def repl(m: re.Match[str]) -> str:
        sid = m.group(1)
        n = seen.get(sid, 0) + 1
        seen[sid] = n
        if n == 1:
            return m.group(0)
        return f'data-slot="{sid}-{n}"'

    return re.sub(r'\bdata-slot="([^"]+)"', repl, html)


def ensure_package_orphan_slots(pack_dir: PathLike, log: Any = None) -> dict[str, Any]:
    """扫描包内 slides/*.html，原地补槽。"""
    root = Path(pack_dir)
    slides = root / "slides"
    if not slides.is_dir():
        return {"files": 0, "text": 0, "image": 0}
    files = 0
    text_n = 0
    image_n = 0
    for path in sorted(slides.glob("*.html")):
        raw = path.read_text(encoding="utf-8")
        next_html, stats = ensure_orphan_slots(raw)
        if stats.get("text") or stats.get("image") or stats.get("nested_stripped"):
            path.write_text(
                next_html if next_html.endswith("\n") else next_html + "\n",
                encoding="utf-8",
            )
            files += 1
            text_n += int(stats.get("text") or 0)
            image_n += int(stats.get("image") or 0)
            if log:
                log(
                    f"[slots] {path.name}: +text={stats.get('text', 0)} "
                    f"+image={stats.get('image', 0)} "
                    f"nested_stripped={stats.get('nested_stripped', 0)}"
                )
    return {"files": files, "text": text_n, "image": image_n}
