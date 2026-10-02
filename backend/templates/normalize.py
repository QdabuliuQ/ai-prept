from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser


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
_SKIP_BARE_WRAP_TAGS = frozenset(
    {
        "script",
        "style",
        "svg",
        "textarea",
        "code",
        "pre",
        "title",
        "head",
        "option",
    }
)
_INLINE_SKIP_SIBLINGS = frozenset({"br", "wbr"})

_STYLE_ATTR_RE = re.compile(
    r"\bstyle\s*=\s*(?P<quote>['\"])(?P<style>.*?)(?P=quote)",
    re.I | re.S,
)
_SIMPLE_ROTATED_TEXT_WRAPPER_RE = re.compile(
    r"<(?P<tag>div|span)\b(?P<parent_attrs>[^>]*)>"
    r"(?P<space_before>\s*)"
    r"<span\b(?P<child_attrs>[^>]*)>"
    r"(?P<text>[^<>]+)"
    r"</span>"
    r"(?P<space_after>\s*)"
    r"</(?P=tag)>",
    re.I | re.S,
)
_ROTATE_90_RE = re.compile(
    r"transform\s*:\s*[^;]*rotate\s*\(\s*(?P<sign>-)?(?P<deg>90|270)\s*deg\s*\)",
    re.I,
)
_STYLE_BLOCK_RE = re.compile(
    r"(?P<head><style\b[^>]*>)(?P<body>.*?)(?P<tail></style>)",
    re.I | re.S,
)


@dataclass(frozen=True)
class HtmlNormalizationResult:
    html: str
    rotated_text_fixes: int = 0
    bounds_fixes: int = 0
    bare_text_fixes: int = 0


@dataclass
class _BareNode:
    kind: str  # tag | text | comment | decl
    tag: str = ""
    attrs: dict[str, str] | None = None
    children: list[_BareNode] | None = None
    text: str = ""
    void: bool = False

    def __post_init__(self) -> None:
        if self.attrs is None:
            self.attrs = {}
        if self.children is None:
            self.children = []


class _BareTextTreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.root = _BareNode("tag", "root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        node = _BareNode(
            "tag",
            t,
            {k.lower(): (v or "") for k, v in attrs if k},
            void=t in _VOID,
        )
        self.stack[-1].children.append(node)
        if not node.void:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        node = _BareNode(
            "tag",
            t,
            {k.lower(): (v or "") for k, v in attrs if k},
            void=True,
        )
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == t:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(_BareNode("text", text=data))

    def handle_entityref(self, name: str) -> None:
        self.stack[-1].children.append(_BareNode("text", text=f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.stack[-1].children.append(_BareNode("text", text=f"&#{name};"))

    def handle_comment(self, data: str) -> None:
        self.stack[-1].children.append(_BareNode("comment", text=data))

    def handle_decl(self, decl: str) -> None:
        self.stack[-1].children.append(_BareNode("decl", text=decl))


def _fmt_bare_attrs(attrs: dict[str, str]) -> str:
    parts: list[str] = []
    for k, v in attrs.items():
        if v == "":
            parts.append(k)
        else:
            esc = v.replace("&", "&amp;").replace('"', "&quot;")
            parts.append(f'{k}="{esc}"')
    return (" " + " ".join(parts)) if parts else ""


def _serialize_bare(node: _BareNode) -> str:
    if node.kind == "text":
        return node.text
    if node.kind == "comment":
        return f"<!--{node.text}-->"
    if node.kind == "decl":
        return f"<!{node.text}>"
    if node.tag == "root":
        return "".join(_serialize_bare(ch) for ch in (node.children or []))
    attrs = _fmt_bare_attrs(node.attrs or {})
    if node.void:
        return f"<{node.tag}{attrs}>"
    inner = "".join(_serialize_bare(ch) for ch in (node.children or []))
    return f"<{node.tag}{attrs}>{inner}</{node.tag}>"


def _wrap_bare_text_in_tree(node: _BareNode) -> int:
    """Wrap non-empty direct text siblings of elements in <span data-element=text>."""
    if node.kind != "tag":
        return 0
    if node.tag in _SKIP_BARE_WRAP_TAGS:
        return 0
    # text leaves must stay flat (plain text / <br> only)
    if (node.attrs or {}).get("data-element", "").lower() == "text":
        return 0

    fixes = 0
    kids = node.children or []
    has_element_sibling = any(
        ch.kind == "tag" and ch.tag not in _INLINE_SKIP_SIBLINGS for ch in kids
    )
    if has_element_sibling:
        new_kids: list[_BareNode] = []
        for ch in kids:
            if ch.kind == "text" and ch.text.strip():
                wrapped = _BareNode("tag", "span", {"data-element": "text"})
                wrapped.children = [ch]
                new_kids.append(wrapped)
                fixes += 1
            else:
                new_kids.append(ch)
        node.children = new_kids
        kids = new_kids

    for ch in kids:
        if ch.kind == "tag":
            fixes += _wrap_bare_text_in_tree(ch)
    return fixes


def wrap_bare_text_runs(html: str) -> HtmlNormalizationResult:
    """Wrap bare text that sits beside element siblings (mixed titles, etc.)."""
    if not html or not html.strip():
        return HtmlNormalizationResult(html=html or "")
    builder = _BareTextTreeBuilder()
    try:
        builder.feed(html)
        builder.close()
    except Exception:
        return HtmlNormalizationResult(html=html)
    fixes = _wrap_bare_text_in_tree(builder.root)
    if not fixes:
        return HtmlNormalizationResult(html=html)
    return HtmlNormalizationResult(html=_serialize_bare(builder.root), bare_text_fixes=fixes)


@dataclass
class _ElementFrame:
    tag: str
    rotated_layout: bool
    has_descendant_element: bool = False
    has_text: bool = False


class _RotatedTextWrapperScanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[_ElementFrame] = []
        self.count = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        for frame in self.stack:
            frame.has_descendant_element = True
        attr_map = {name.lower(): value or "" for name, value in attrs}
        style = attr_map.get("style", "")
        rotated = bool(
            re.search(r"transform\s*:\s*[^;]*rotate\([^)]*\)", style, re.I)
        )
        layout = bool(
            re.search(r"display\s*:\s*(?:inline-)?(?:flex|grid)\b", style, re.I)
        )
        self.stack.append(
            _ElementFrame(tag=tag.lower(), rotated_layout=rotated and layout)
        )

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        for frame in self.stack:
            frame.has_descendant_element = True

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        for frame in self.stack:
            frame.has_text = True

    def handle_endtag(self, tag: str) -> None:
        target = tag.lower()
        while self.stack:
            frame = self.stack.pop()
            if (
                frame.rotated_layout
                and frame.has_descendant_element
                and frame.has_text
            ):
                self.count += 1
            if frame.tag == target:
                break


def _style_from_attrs(attrs: str) -> tuple[re.Match[str], str] | None:
    match = _STYLE_ATTR_RE.search(attrs)
    if not match:
        return None
    return match, match.group("style").strip()


def _merge_styles(parent_style: str, child_style: str) -> str:
    left = parent_style.rstrip().rstrip(";")
    right = child_style.strip().strip(";")
    if left and right:
        return f"{left}; {right};"
    if left:
        return f"{left};"
    if right:
        return f"{right};"
    return ""


def _cleanup_style(style: str) -> str:
    style = re.sub(r";\s*;+", ";", style)
    style = re.sub(r"^\s*;\s*", "", style)
    style = re.sub(r"\s+", " ", style).strip()
    if style and not style.endswith(";"):
        style += ";"
    return style


def _is_dangerous_edge_rotate(style: str) -> bool:
    """bottom/right-bottom origin + ±90° often swings glyphs past 1080."""
    if not _ROTATE_90_RE.search(style):
        return False
    has_bottom = bool(re.search(r"(?:^|;)\s*bottom\s*:", style, re.I))
    origin_bottom = bool(
        re.search(r"transform-origin\s*:[^;]*\bbottom\b", style, re.I)
    )
    return has_bottom or origin_bottom


def _rewrite_rotate_to_writing_mode(style: str) -> str:
    """Replace ±90/270 rotate with writing-mode so the layout box stays in-flow."""
    m = _ROTATE_90_RE.search(style)
    if not m:
        return style
    # -90 / 270 → vertical-rl；+90 → vertical-lr（侧栏竖排常见）
    sign = m.group("sign") or ""
    deg = m.group("deg")
    if sign == "-" or deg == "270":
        mode = "vertical-rl"
    else:
        mode = "vertical-lr"

    out = _ROTATE_90_RE.sub("", style)
    # leftover empty transform: ...
    out = re.sub(r"(?:^|;)\s*transform\s*:\s*;", ";", out, flags=re.I)
    out = re.sub(r"transform-origin\s*:[^;]*;?", "", out, flags=re.I)

    def _bump_bottom(mm: re.Match[str]) -> str:
        raw = mm.group(1).strip()
        num = re.match(r"([\d.]+)", raw)
        if num and float(num.group(1)) < 64:
            return "bottom: 64px"
        return mm.group(0)

    out = re.sub(r"bottom\s*:\s*([^;]+)", _bump_bottom, out, flags=re.I)

    if not re.search(r"(?:^|;)\s*writing-mode\s*:", out, re.I):
        out = out.rstrip().rstrip(";") + f"; writing-mode: {mode};"
    else:
        out = re.sub(
            r"writing-mode\s*:\s*horizontal-tb\s*;?",
            f"writing-mode: {mode};",
            out,
            flags=re.I,
        )
    if not re.search(r"(?:^|;)\s*text-orientation\s*:", out, re.I):
        out = out.rstrip().rstrip(";") + "; text-orientation: mixed;"
    return _cleanup_style(out)


def normalize_rotated_text_wrappers(html: str) -> HtmlNormalizationResult:
    """Flatten simple rotated flex/grid wrapper + single span text for html-to-pptx."""
    fixes = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal fixes
        parent_attrs = match.group("parent_attrs")
        child_attrs = match.group("child_attrs")
        parent_info = _style_from_attrs(parent_attrs)
        child_info = _style_from_attrs(child_attrs)
        if not parent_info or not child_info:
            return match.group(0)

        parent_style_match, parent_style = parent_info
        child_style_match, child_style = child_info
        if not re.search(r"transform\s*:\s*[^;]*rotate\([^)]*\)", parent_style, re.I):
            return match.group(0)
        if not re.search(r"display\s*:\s*(?:inline-)?(?:flex|grid)\b", parent_style, re.I):
            return match.group(0)

        child_remainder = (
            child_attrs[: child_style_match.start()]
            + child_attrs[child_style_match.end() :]
        ).strip()
        if child_remainder:
            return match.group(0)

        merged_style = _merge_styles(parent_style, child_style)
        quote = parent_style_match.group("quote")
        merged_attr = f"style={quote}{merged_style}{quote}"
        merged_parent_attrs = (
            parent_attrs[: parent_style_match.start()]
            + merged_attr
            + parent_attrs[parent_style_match.end() :]
        )
        fixes += 1
        return (
            f"<{match.group('tag')}{merged_parent_attrs}>"
            f"{match.group('text').strip()}"
            f"</{match.group('tag')}>"
        )

    normalized = _SIMPLE_ROTATED_TEXT_WRAPPER_RE.sub(replace, html)
    return HtmlNormalizationResult(
        html=normalized,
        rotated_text_fixes=fixes,
    )


def normalize_out_of_bounds_rotated_labels(html: str) -> HtmlNormalizationResult:
    """
    Fix edge labels that use bottom + rotate(±90deg).
    CSS rotate around a bottom/right origin often paints glyphs below y=1080
    (preview + export). Prefer writing-mode vertical instead.
    """
    fixes = 0

    def fix_style_attr(m: re.Match[str]) -> str:
        nonlocal fixes
        quote = m.group("quote")
        style = m.group("style")
        if not _is_dangerous_edge_rotate(style):
            return m.group(0)
        fixes += 1
        return f"style={quote}{_rewrite_rotate_to_writing_mode(style)}{quote}"

    out = _STYLE_ATTR_RE.sub(fix_style_attr, html)

    def fix_style_block(m: re.Match[str]) -> str:
        nonlocal fixes
        body = m.group("body")
        parts = re.split(r"(?<=\})", body)
        new_parts: list[str] = []
        for rule in parts:
            if "{" not in rule or "}" not in rule or not _is_dangerous_edge_rotate(rule):
                new_parts.append(rule)
                continue
            head, _, rest = rule.partition("{")
            decls, _, tail = rest.rpartition("}")
            if not _is_dangerous_edge_rotate(decls):
                new_parts.append(rule)
                continue
            fixes += 1
            new_parts.append(f"{head}{{{_rewrite_rotate_to_writing_mode(decls)}}}{tail}")
        return f"{m.group('head')}{''.join(new_parts)}{m.group('tail')}"

    out = _STYLE_BLOCK_RE.sub(fix_style_block, out)
    return HtmlNormalizationResult(html=out, bounds_fixes=fixes)


def normalize_slide_html(html: str) -> HtmlNormalizationResult:
    """Run all HTML normalizers for export-safe slides."""
    a = normalize_rotated_text_wrappers(html)
    b = normalize_out_of_bounds_rotated_labels(a.html)
    c = wrap_bare_text_runs(b.html)
    return HtmlNormalizationResult(
        html=c.html,
        rotated_text_fixes=a.rotated_text_fixes,
        bounds_fixes=b.bounds_fixes,
        bare_text_fixes=c.bare_text_fixes,
    )


def count_unsafe_rotated_text_wrappers(html: str) -> int:
    """Count rotated flex/grid wrappers whose text still lives in a child node."""
    scanner = _RotatedTextWrapperScanner()
    scanner.feed(html)
    scanner.close()
    return scanner.count
