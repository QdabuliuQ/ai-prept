"""生成后净化：强制收敛到 html-to-pptx 可映射 CSS。"""

from __future__ import annotations

import re
from dataclasses import dataclass


_FORBIDDEN_PROP = re.compile(
    r"(?:^|;|\{)\s*(?:"
    r"clip-path|backdrop-filter|mix-blend-mode|-webkit-mask|"
    r"-webkit-backdrop-filter|mask(?:-image)?|"
    r"perspective|will-change|"
    r"transition(?:-[a-z]+)?|animation(?:-[a-z]+)?"
    r")\s*:[^;{}]*",
    re.I,
)

_FILTER_PROP = re.compile(
    r"(?P<prefix>(?:^|;|\{)\s*)filter\s*:\s*(?P<val>[^;{}]*)",
    re.I,
)

_TRANSFORM_PROP = re.compile(
    r"(?P<prefix>(?:^|;|\{)\s*)transform\s*:\s*(?P<val>[^;{}]*)",
    re.I,
)

_KEYFRAMES_BLOCK = re.compile(
    r"@keyframes\s+[^{]+\{(?:[^{}]|\{[^{}]*\})*\}",
    re.I | re.S,
)

_VIEWPORT_IN_DECL = re.compile(
    r"(?P<prefix>(?:^|;|\{)\s*"
    r"(?:width|height|top|left|right|bottom|"
    r"margin(?:-(?:top|right|bottom|left))?|"
    r"padding(?:-(?:top|right|bottom|left))?|"
    r"font-size|gap|row-gap|column-gap|"
    r"min-width|max-width|min-height|max-height)\s*:\s*)"
    r"(?P<val>[^;{}]*(?:vh|vw|vmin|vmax)[^;{}]*)",
    re.I,
)

_COMPLEX_GRAD_NAMES = (
    "radial-gradient",
    "conic-gradient",
    "repeating-linear-gradient",
    "repeating-radial-gradient",
    "repeating-conic-gradient",
)

_BOX_SHADOW_DECL = re.compile(
    r"(box-shadow\s*:\s*)([^;{}]+)",
    re.I,
)

# data-element：仅当写了 inset（left/top/…）却无 absolute/fixed 时才补 position
_DATA_ELEMENT_OPEN = re.compile(
    r"<(?P<tag>[a-zA-Z][\w:-]*)"
    r"(?P<attrs>[^>]*?\bdata-element\s*=\s*['\"](?:text|shape|image)['\"][^>]*?)"
    r"(?P<slash>\s*/?)\s*>",
    re.I | re.S,
)

_STYLE_ATTR = re.compile(
    r"\bstyle\s*=\s*(?P<q>['\"])(?P<body>.*?)(?P=q)",
    re.I | re.S,
)

_POSITION_ABS = re.compile(
    r"position\s*:\s*(absolute|fixed)\b",
    re.I,
)

_HAS_INSET = re.compile(
    r"(?:^|;)\s*(?:left|top|right|bottom)\s*:",
    re.I,
)

# 空 div：未标 data-element，常被模型写成分隔线
_EMPTY_DIV = re.compile(
    r"<div(?P<attrs>[^>]*?)>\s*</div>",
    re.I | re.S,
)

_DIVIDER_CLASS = re.compile(
    r"\b(?:divider|separator|hairline|hrule|rule-?line|split-?line|分隔)\b",
    re.I,
)

_STYLE_BG = re.compile(
    r"(?:^|;)\s*(?:background(?:-color)?)\s*:\s*(?P<val>[^;]+)",
    re.I,
)

_STYLE_PX = re.compile(
    r"(?:^|;)\s*(?P<prop>width|height)\s*:\s*(?P<num>[\d.]+)px\b",
    re.I,
)

_STYLE_OPACITY = re.compile(
    r"(?:^|;)\s*opacity\s*:\s*(?P<op>[\d.]+)\b",
    re.I,
)

_STYLE_Z = re.compile(
    r"(?:^|;)\s*z-index\s*:\s*(?P<z>-?\d+)\b",
    re.I,
)


@dataclass(frozen=True)
class SanitizeResult:
    text: str
    fixes: list[str]


def _style_has_orphan_inset(style_body: str) -> bool:
    """True when left/top/right/bottom present without position:absolute|fixed."""
    if not style_body or not _HAS_INSET.search(style_body):
        return False
    return not _POSITION_ABS.search(style_body)


def ensure_data_element_position_absolute(html: str) -> tuple[str, int]:
    """仅为「写了 inset 却无 position」的 data-element 注入 position:absolute。

    壳内流式叶节点（无 left/top）保持 static/relative，由分区壳 absolute 定位。
    """
    fixes = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal fixes
        tag = m.group("tag")
        attrs = m.group("attrs")
        slash = m.group("slash") or ""
        sm = _STYLE_ATTR.search(attrs)
        if not sm:
            return m.group(0)
        body = sm.group("body")
        if not _style_has_orphan_inset(body):
            return m.group(0)
        q = sm.group("q")
        new_body = f"position:absolute;{body}" if body.strip() else "position:absolute;"
        new_attrs = (
            attrs[: sm.start()] + f"style={q}{new_body}{q}" + attrs[sm.end() :]
        )
        fixes += 1
        return f"<{tag}{new_attrs}{slash}>"

    out = _DATA_ELEMENT_OPEN.sub(repl, html)
    return out, fixes


_ANY_OPEN_WITH_STYLE = re.compile(
    r"<(?P<tag>div|section|article|aside|header|footer|nav|main|h[1-6]|p|span|ul|ol|li|figure)"
    r"(?P<attrs>[^>]*?\bstyle\s*=\s*(?P<q>['\"])(?P<body>.*?)(?P=q)[^>]*?)"
    r"(?P<slash>\s*/?)\s*>",
    re.I | re.S,
)


def ensure_inline_inset_position_absolute(html: str) -> tuple[str, int]:
    """任意块级节点：写了 left/top 却无 position → 补 absolute（html 轨常见漏标）。"""
    fixes = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal fixes
        body = m.group("body")
        if not _style_has_orphan_inset(body):
            return m.group(0)
        # 已有 data-element 的由 ensure_data_element_position_absolute 处理，避免双计
        if re.search(r"\bdata-element\s*=", m.group("attrs"), re.I):
            return m.group(0)
        q = m.group("q")
        new_body = f"position:absolute;{body}" if body.strip() else "position:absolute;"
        attrs = m.group("attrs")
        # replace style body inside attrs
        new_attrs = re.sub(
            r"\bstyle\s*=\s*(['\"])(.*?)\1",
            f"style={q}{new_body}{q}",
            attrs,
            count=1,
            flags=re.I | re.S,
        )
        fixes += 1
        return f"<{m.group('tag')}{new_attrs}{m.group('slash') or ''}>"

    return _ANY_OPEN_WITH_STYLE.sub(repl, html), fixes


_CSS_RULE_RE = re.compile(
    r"(?P<head>[^{}@][^{]*)\{(?P<body>[^{}]*)\}",
    re.S,
)


def ensure_css_rule_inset_position_absolute(css_or_html: str) -> tuple[str, int]:
    """
    <style> / theme 规则：声明了 left/top/right/bottom 却无 position:absolute|fixed
    → 注入 position:absolute（修复 .card-b{top/left} 挂在无 absolute 的 .sticky-note 上）。
    """
    fixes = 0

    def fix_body(body: str) -> str:
        nonlocal fixes
        if not _style_has_orphan_inset(body):
            return body
        # 已有 relative/static/sticky 则不改（避免误伤定位上下文）
        if re.search(r"position\s*:\s*(relative|static|sticky)\b", body, re.I):
            return body
        fixes += 1
        trimmed = body.strip()
        if trimmed and not trimmed.endswith(";"):
            trimmed += ";"
        return f"position:absolute;{trimmed}"

    def fix_chunk(text: str) -> str:
        def repl(m: re.Match[str]) -> str:
            head = m.group("head")
            # 跳过 @ 规则外壳（简化：head 含 @ 则不动）
            if "@" in head:
                return m.group(0)
            body = fix_body(m.group("body"))
            return f"{head}{{{body}}}"

        return _CSS_RULE_RE.sub(repl, text)

    # 优先处理 <style>…</style>，其余整段当 CSS
    if re.search(r"<style\b", css_or_html, re.I):

        def style_repl(m: re.Match[str]) -> str:
            return f"{m.group(1)}{fix_chunk(m.group(2))}{m.group(3)}"

        out = re.sub(
            r"(<style\b[^>]*>)(.*?)(</style>)",
            style_repl,
            css_or_html,
            flags=re.I | re.S,
        )
        return out, fixes

    return fix_chunk(css_or_html), fixes


# 别名：sanitize_export_css / 测试使用
ensure_css_rules_position_absolute = ensure_css_rule_inset_position_absolute
ensure_style_blocks_position_absolute = ensure_css_rule_inset_position_absolute
ensure_inline_orphan_inset_absolute = ensure_inline_inset_position_absolute


def count_css_orphan_inset_rules(css_or_html: str) -> int:
    """统计 CSS 中「有 inset 无 absolute/fixed」的规则数（用于校验提示）。"""
    n = 0
    chunks: list[str] = []
    if re.search(r"<style\b", css_or_html, re.I):
        chunks.extend(
            m.group(1)
            for m in re.finditer(
                r"<style\b[^>]*>(.*?)</style>",
                css_or_html,
                flags=re.I | re.S,
            )
        )
    else:
        chunks.append(css_or_html)
    for chunk in chunks:
        for m in _CSS_RULE_RE.finditer(chunk):
            if "@" in m.group("head"):
                continue
            body = m.group("body")
            if _style_has_orphan_inset(body) and not re.search(
                r"position\s*:\s*(relative|static|sticky)\b", body, re.I
            ):
                n += 1
    return n


def count_data_element_missing_position(html: str) -> int:
    """统计写了 left/top/right/bottom 却缺少 position:absolute|fixed 的 data-element。"""
    n = 0
    for m in _DATA_ELEMENT_OPEN.finditer(html):
        attrs = m.group("attrs")
        sm = _STYLE_ATTR.search(attrs)
        if not sm:
            continue
        if _style_has_orphan_inset(sm.group("body")):
            n += 1
    return n


def _style_px_map(style_body: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for m in _STYLE_PX.finditer(style_body or ""):
        try:
            out[m.group("prop").lower()] = float(m.group("num"))
        except ValueError:
            continue
    return out


def _style_bg_fill(style_body: str) -> str | None:
    m = _STYLE_BG.search(style_body or "")
    if not m:
        return None
    val = m.group("val").strip()
    low = val.lower()
    if low in {"none", "transparent", "initial", "inherit"}:
        return None
    # 取 #hex 或 rgb(...)
    hm = re.search(r"#([0-9a-fA-F]{3,8})\b", val)
    if hm:
        return f"#{hm.group(1)}"
    rm = re.search(r"rgba?\([^)]+\)", val, re.I)
    if rm:
        return rm.group(0)
    return None


def _is_hairline_divider(attrs: str, style_body: str) -> bool:
    """细色条 / 分隔线：矮扁或细高 + 实色底，或 class 名提示。"""
    if re.search(r"\bdata-element\s*=", attrs, re.I):
        return False
    fill = _style_bg_fill(style_body)
    border_line = bool(
        re.search(
            r"(?:^|;)\s*border-(?:top|bottom|left|right)\s*:\s*[\d.]+px\s+solid\b",
            style_body or "",
            re.I,
        )
    )
    class_hint = bool(_DIVIDER_CLASS.search(attrs))
    if not fill and not border_line and not class_hint:
        return False

    px = _style_px_map(style_body)
    h = px.get("height")
    w = px.get("width")
    width_pct = bool(
        re.search(r"(?:^|;)\s*width\s*:\s*[\d.]+%\b", style_body or "", re.I)
    )
    height_pct = bool(
        re.search(r"(?:^|;)\s*height\s*:\s*[\d.]+%\b", style_body or "", re.I)
    )

    # 水平细线：height ≤ 8px，且宽度拉满或 ≥24px
    if h is not None and h <= 8 and (fill or border_line):
        if width_pct or (w is not None and w >= 24) or w is None:
            return True
    # 垂直细线：width ≤ 8px
    if w is not None and w <= 8 and (fill or border_line):
        if height_pct or (h is not None and h >= 24) or h is None:
            return True
    # class 名已点名分隔线，且有实色底（尺寸可能在 class CSS）
    if class_hint and (fill or border_line):
        return True
    return False


def ensure_divider_data_element(html: str) -> tuple[str, int]:
    """给未标记的细色条/分隔线空 div 补 data-element=shape。"""
    fixes = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal fixes
        attrs = m.group("attrs")
        if re.search(r"\bdata-element\s*=", attrs, re.I):
            return m.group(0)
        sm = _STYLE_ATTR.search(attrs)
        style_body = sm.group("body") if sm else ""
        if not _is_hairline_divider(attrs, style_body):
            return m.group(0)

        fill = _style_bg_fill(style_body) or "#000000"
        extras = [
            'data-element="shape"',
            'data-shape-name="rect"',
            f'data-fill="{fill}"',
        ]
        op_m = _STYLE_OPACITY.search(style_body)
        if op_m:
            try:
                op = float(op_m.group("op"))
                if 0 <= op < 0.999:
                    t = max(0, min(100, round((1 - op) * 100)))
                    extras.append(f'data-transparency="{t}"')
            except ValueError:
                pass
        if not re.search(r"\bdata-z-index\s*=", attrs, re.I):
            z_m = _STYLE_Z.search(style_body)
            z = z_m.group("z") if z_m else "20"
            extras.append(f'data-z-index="{z}"')
            if sm and not _STYLE_Z.search(style_body):
                q = sm.group("q")
                body = style_body.rstrip()
                if body and not body.endswith(";"):
                    body += ";"
                body += "z-index:20;"
                attrs = (
                    attrs[: sm.start()]
                    + f"style={q}{body}{q}"
                    + attrs[sm.end() :]
                )

        # 插在 tag 后、原 attrs 前
        inject = " " + " ".join(extras)
        fixes += 1
        return f"<div{inject}{attrs}></div>"

    out = _EMPTY_DIV.sub(repl, html)
    return out, fixes


def _find_func_call(text: str, name: str, start: int = 0) -> tuple[int, int] | None:
    """返回 name(...) 的 [start, end)，支持嵌套括号。"""
    needle = name.lower() + "("
    lower = text.lower()
    idx = start
    while True:
        idx = lower.find(needle, idx)
        if idx < 0:
            return None
        if idx > 0 and (lower[idx - 1].isalnum() or lower[idx - 1] in "-_"):
            idx += 1
            continue
        i = idx + len(needle) - 1
        depth = 0
        j = i
        while j < len(text):
            ch = text[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return idx, j + 1
            j += 1
        return None


def _replace_css_functions(
    text: str,
    names: tuple[str, ...],
    replacement: str,
) -> tuple[str, int]:
    count = 0
    for name in names:
        pos = 0
        while True:
            found = _find_func_call(text, name, pos)
            if not found:
                break
            a, b = found
            text = text[:a] + replacement + text[b:]
            count += 1
            pos = a + len(replacement)
    return text, count


def _gradient_stop_alphas(grad_src: str) -> list[float]:
    """粗解析 linear-gradient 色标 alpha（无 canvas）。"""
    alphas: list[float] = []
    for m in re.finditer(
        r"(transparent|rgba?\([^)]+\)|hsla?\([^)]+\)|#[0-9a-fA-F]{3,8})\s*(?:[\d.]+%?)?",
        grad_src,
        re.I,
    ):
        tok = m.group(1).lower()
        if tok == "transparent":
            alphas.append(0.0)
            continue
        if tok.startswith("rgba") or tok.startswith("hsla"):
            nums = re.findall(r"[\d.]+", tok)
            if len(nums) >= 4:
                try:
                    alphas.append(min(1.0, max(0.0, float(nums[3]))))
                except ValueError:
                    alphas.append(1.0)
            else:
                alphas.append(1.0)
            continue
        if tok.startswith("#") and len(tok) in (5, 9):
            hex_body = tok[1:]
            ahex = hex_body[3:] if len(hex_body) == 4 else hex_body[6:]
            try:
                alphas.append(int(ahex, 16) / (15 if len(ahex) == 1 else 255))
            except ValueError:
                alphas.append(1.0)
            continue
        alphas.append(1.0)
    return alphas


def _strip_wash_linear_gradients(text: str) -> tuple[str, int]:
    """全部色标 alpha < 0.5 的 linear-gradient 是氛围洗色，导出不可靠 → none。"""
    count = 0
    pos = 0
    while True:
        found = _find_func_call(text, "linear-gradient", pos)
        if not found:
            break
        a, b = found
        alphas = _gradient_stop_alphas(text[a:b])
        if alphas and max(alphas) < 0.5:
            text = text[:a] + "none" + text[b:]
            count += 1
            pos = a + len("none")
        else:
            pos = b
    return text, count


def _collapse_multi_box_shadow(text: str) -> tuple[str, int]:
    """多层 box-shadow → 只留第一层。"""
    n = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal n
        prefix, value = m.group(1), m.group(2).strip()
        parts: list[str] = []
        cur = ""
        depth = 0
        for ch in value:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                part = cur.strip()
                if part:
                    parts.append(part)
                cur = ""
                continue
            cur += ch
        if cur.strip():
            parts.append(cur.strip())
        if len(parts) <= 1:
            return m.group(0)
        n += 1
        return f"{prefix}{parts[0]}"

    out = _BOX_SHADOW_DECL.sub(repl, text)
    return out, n


def _strip_forbidden_props(text: str) -> tuple[str, int]:
    n = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal n
        n += 1
        raw = m.group(0)
        if raw.lstrip().startswith("{") or raw.startswith("{"):
            return "{"
        if ";" in raw[:2] or raw.startswith(";"):
            return ";"
        return ""

    out = _FORBIDDEN_PROP.sub(repl, text)
    if not n:
        return text, 0
    out = re.sub(r";\s*;+", ";", out)
    out = re.sub(r"\{\s*;+", "{", out)
    out = re.sub(r";\s*}", "}", out)
    return out, n


def _sanitize_filters(text: str) -> tuple[str, int]:
    """保留 filter:none；其余 filter 删除（blur 等导出差）。"""
    n = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal n
        val = m.group("val").strip().lower().rstrip(";")
        if val in {"none", "initial", "unset"}:
            return m.group(0)
        n += 1
        prefix = m.group("prefix")
        if prefix.endswith("{") or prefix.rstrip().endswith("{"):
            return prefix
        return ";" if ";" in prefix else ""

    return _FILTER_PROP.sub(repl, text), n


def _sanitize_transforms(text: str) -> tuple[str, int]:
    """只保留 rotate(...)；含 translate/scale/skew/matrix 则剥掉或收成纯 rotate。"""
    n = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal n
        val = m.group("val").strip()
        if not re.search(r"translate|scale|skew|matrix", val, re.I):
            return m.group(0)
        n += 1
        rotates = re.findall(r"rotate\s*\([^)]*\)", val, flags=re.I)
        prefix = m.group("prefix")
        if rotates:
            return f"{prefix}transform: {' '.join(rotates)}"
        if prefix.endswith("{") or prefix.rstrip().endswith("{"):
            return prefix
        return ";" if ";" in prefix else ""

    return _TRANSFORM_PROP.sub(repl, text), n


def _strip_keyframes(text: str) -> tuple[str, int]:
    out, n = _KEYFRAMES_BLOCK.subn("", text)
    return out, n


def _strip_viewport_units(text: str) -> tuple[str, int]:
    """声明里的 vh/vw 无法稳定映射 → 删除整条声明。"""
    n = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal n
        n += 1
        prefix = m.group("prefix")
        if prefix.endswith("{") or "{" in prefix[-2:]:
            # keep '{'
            if "{" in prefix:
                return prefix[prefix.rfind("{") :]
            return "{"
        return ";"

    out = _VIEWPORT_IN_DECL.sub(repl, text)
    if n:
        out = re.sub(r";\s*;+", ";", out)
        out = re.sub(r"\{\s*;+", "{", out)
        out = re.sub(r";\s*}", "}", out)
    return out, n


def _soften_slide_container_layout(css: str) -> tuple[str, int]:
    """theme 里 .slide-container 去掉非零 padding / flex|grid（保留 padding:0）。"""
    fixes = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal fixes
        head, body, tail = m.group(1), m.group(2), m.group(3)
        new_body = body
        if re.search(r"display\s*:\s*(flex|grid)\b", body, re.I):
            new_body = re.sub(
                r"display\s*:\s*(?:flex|grid)[^;]*;?",
                "display: block;",
                new_body,
                flags=re.I,
            )
            fixes += 1

        def pad_repl(pm: re.Match[str]) -> str:
            nonlocal fixes
            prop, val = pm.group(1), pm.group(2).strip()
            compact = re.sub(r"\s+", " ", val.lower())
            compact = re.sub(r"\s*!important\s*$", "", compact).strip()
            if compact in {"0", "0px", "0em", "0rem", "0%"} or re.fullmatch(
                r"0(\s+0){0,3}", compact
            ):
                return pm.group(0)
            fixes += 1
            return f"{prop}: 0;"

        new_body = re.sub(
            r"(padding(?:-(?:top|right|bottom|left))?)\s*:\s*([^;]+);?",
            pad_repl,
            new_body,
            flags=re.I,
        )
        return f"{head}{new_body}{tail}"

    out = re.sub(
        r"(\.slide-container[^{]*\{)([^}]*)(\})",
        repl,
        css,
        flags=re.I | re.S,
    )
    return out, fixes


def sanitize_export_css(text: str, *, is_theme: bool = False) -> SanitizeResult:
    """强制收敛到 html-to-pptx 白名单可映射子集。"""
    fixes: list[str] = []
    out = text

    out2, n_kf = _strip_keyframes(out)
    if n_kf:
        out = out2
        fixes.append(f"移除 @keyframes×{n_kf}")

    out2, n_forbid = _strip_forbidden_props(out)
    if n_forbid:
        out = out2
        fixes.append(f"移除不可映射 CSS×{n_forbid}")

    out2, n_filter = _sanitize_filters(out)
    if n_filter:
        out = out2
        fixes.append(f"移除 filter 效果×{n_filter}")

    out2, n_tf = _sanitize_transforms(out)
    if n_tf:
        out = out2
        fixes.append(f"收敛非法 transform×{n_tf}")

    out2, n_vh = _strip_viewport_units(out)
    if n_vh:
        out = out2
        fixes.append(f"移除 vh/vw 声明×{n_vh}")

    out2, n_grad = _replace_css_functions(out, _COMPLEX_GRAD_NAMES, "transparent")
    if n_grad:
        out = out2
        fixes.append(f"复杂渐变改 transparent×{n_grad}")

    out2, n_wash = _strip_wash_linear_gradients(out)
    if n_wash:
        out = out2
        fixes.append(f"半透明洗色 linear-gradient 改 none×{n_wash}")

    out2, n_shadow = _collapse_multi_box_shadow(out)
    if n_shadow:
        out = out2
        fixes.append(f"多层 box-shadow 收敛为单层×{n_shadow}")

    if is_theme:
        out2, n_layout = _soften_slide_container_layout(out)
        if n_layout:
            out = out2
            fixes.append(f"收敛 .slide-container 结构布局×{n_layout}")
        out2, n_css = ensure_css_rules_position_absolute(out)
        if n_css:
            out = out2
            fixes.append(f"CSS 规则补 position:absolute×{n_css}")
    else:
        out2, n_css = ensure_style_blocks_position_absolute(out)
        if n_css:
            out = out2
            fixes.append(f"<style> 补 position:absolute×{n_css}")
        out2, n_inline = ensure_inline_orphan_inset_absolute(out)
        if n_inline:
            out = out2
            fixes.append(f"inline 补 position:absolute×{n_inline}")
        out2, n_pos = ensure_data_element_position_absolute(out)
        if n_pos:
            out = out2
            fixes.append(f"补全裸 inset 的 position:absolute×{n_pos}")
        out2, n_div = ensure_divider_data_element(out)
        if n_div:
            out = out2
            fixes.append(f"分隔线补 data-element=shape×{n_div}")

    return SanitizeResult(text=out, fixes=fixes)
