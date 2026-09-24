from __future__ import annotations

import json
import re
from pathlib import Path

from templates.normalize import count_unsafe_rotated_text_wrappers
from templates.sanitize import (
    count_css_orphan_inset_rules,
)


FORBIDDEN_KEYS = {
    "name",
    "template_dir",
    "package_type",
    "taxonomy",
    "slides.slots",
}

# 生成期 HTML 安全检查（对齐 html-to-pptx / WebPPT 模板约定）
EXPORT_FORBIDDEN_PATTERNS: list[tuple[str, str, str]] = [
    ("cdn_tailwind", r"cdn\.tailwindcss\.com", "禁止 Tailwind CDN"),
    ("cdn_fonts", r"fonts\.googleapis\.com", "禁止 Google Fonts CDN"),
    ("cdn_fa", r"cdnjs\.cloudflare\.com/ajax/libs/font-awesome|use\.fontawesome\.com", "禁止 Font Awesome CDN"),
    ("keyframes", r"@keyframes\b", "含 @keyframes 动画"),
    (
        "unicode_decor",
        r'aria-hidden\s*=\s*["\']true["\'][^>]*>[◈◆◇✦●■▲◉◯]',
        "Unicode 几何符装饰",
    ),
    (
        "bg_url",
        r"background(?:-image)?\s*:[^;]*url\s*\(",
        "background-image:url 请改用 <img>",
    ),
]

# Emoji / pictographs as text icons → 圆芯片里常沉底被裁
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0000FE0F"
    "\U0000200D"
    "]"
)

# 警告：净化后仍残留时不导致 batch FAIL
EXPORT_WARN_PATTERNS: list[tuple[str, str, str]] = [
    ("pseudo_decor", r"::(?:before|after)", "伪元素装饰不可导出"),
    (
        "forbidden_css",
        # 忽略 *: none（常见误报 backdrop-filter:none）
        r"(?:clip-path|backdrop-filter|mix-blend-mode|-webkit-mask|-webkit-backdrop-filter|mask(?:-image)?)\s*:\s*(?!none\b)[^;]+",
        "含不可映射 CSS",
    ),
    (
        "complex_gradient",
        r"(?:radial-gradient|conic-gradient|repeating-(?:linear|radial|conic)-gradient)\s*\(",
        "复杂渐变仅近似",
    ),
]


def _scan_html_export_contract(html: str, rel: str) -> list[str]:
    issues: list[str] = []
    for code, pattern, msg in EXPORT_FORBIDDEN_PATTERNS:
        if re.search(pattern, html, re.I):
            issues.append(f"[export:{code}] {rel}: {msg}")
    for code, pattern, msg in EXPORT_WARN_PATTERNS:
        if re.search(pattern, html, re.I):
            issues.append(f"[export-warn:{code}] {rel}: {msg}")
    issues.extend(scan_html_emoji(html, rel))
    issues.extend(scan_html_fa_icons(html, rel))
    issues.extend(scan_html_text_hide(html, rel))
    return issues


def scan_html_emoji(html: str, rel: str, *, max_samples: int = 6) -> list[str]:
    """Emoji-as-icon is unstable in html-to-pptx (sinks / clips inside round chips)."""
    # Ignore <script>/<style> bodies
    stripped = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        "",
        html,
        flags=re.I | re.S,
    )
    # Ignore HTML comments
    stripped = re.sub(r"<!--.*?-->", "", stripped, flags=re.S)
    hits = _EMOJI_RE.findall(stripped)
    if not hits:
        return []
    samples: list[str] = []
    seen: set[str] = set()
    for ch in hits:
        if ch in seen or ch in {"\uFE0F", "\u200D"}:
            continue
        seen.add(ch)
        samples.append(ch)
        if len(samples) >= max_samples:
            break
    shown = " ".join(samples)
    return [
        f"[export:emoji] {rel}: 含表情/绘文字「{shown}」；"
        "禁止用 emoji 当圆芯片图标（导出易沉底裁切）。"
        "改用本地 <img> 或实色 oval + 短字母。"
    ]


_FA_ICON_RE = re.compile(
    r"""<i\b[^>]*\bclass\s*=\s*["'][^"']*\bfa(?:-solid|-regular|-brands|-light|-thin)?\b[^"']*["'][^>]*>""",
    re.I,
)


def scan_html_fa_icons(html: str, rel: str) -> list[str]:
    """Font Awesome webfont glyphs do not embed into PPTX via html-to-pptx."""
    stripped = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        "",
        html,
        flags=re.I | re.S,
    )
    if not _FA_ICON_RE.search(stripped):
        # also catch span/div with fa- classes used as icons
        if not re.search(
            r"""<(?:span|div)\b[^>]*\bclass\s*=\s*["'][^"']*\bfa(?:-solid|-regular|-brands)\b""",
            stripped,
            re.I,
        ):
            return []
    return [
        f"[export:fa-icon] {rel}: 含 Font Awesome 图标字体；"
        "预览正常但 PPTX 不嵌入 FA 字库，会变成方块。"
        "改为本地 <img>、实色 shape（oval）或短字母/汉字装饰，禁止 <i class=\"fa-…\">。"
    ]


_TEXT_HIDE_RE = re.compile(
    r"(?:text-overflow\s*:\s*ellipsis|-webkit-line-clamp\s*:\s*[1-9]\d*)",
    re.I,
)


def scan_html_text_hide(html: str, rel: str) -> list[str]:
    """Ban ellipsis / line-clamp as a way to hide overflowing copy."""
    if not _TEXT_HIDE_RE.search(html):
        return []
    kinds: list[str] = []
    if re.search(r"text-overflow\s*:\s*ellipsis", html, re.I):
        kinds.append("text-overflow:ellipsis")
    if re.search(r"-webkit-line-clamp\s*:\s*[1-9]", html, re.I):
        kinds.append("-webkit-line-clamp")
    return [
        f"[export:text-clip] {rel}: 含 {' / '.join(kinds)}；"
        "禁止靠截断藏字。请减短文案、加高卡壳或拆页，保证全文可见。"
    ]


_STYLE_ATTR_RE = re.compile(
    r"\bstyle\s*=\s*(?P<quote>['\"])(?P<style>.*?)(?P=quote)",
    re.I | re.S,
)


def _parse_px_prop(style: str, name: str) -> float | None:
    m = re.search(
        rf"(?:^|;)\s*{re.escape(name)}\s*:\s*(-?\d+(?:\.\d+)?)\s*px\b",
        style,
        re.I,
    )
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _style_declares_absolute(style: str) -> bool:
    return bool(re.search(r"(?:^|;)\s*position\s*:\s*absolute\b", style, re.I))


def scan_html_absolute_bounds(
    html: str,
    rel: str,
    *,
    canvas_w: float = 1920.0,
    canvas_h: float = 1080.0,
    margin: float = 2.0,
    max_issues: int = 8,
) -> list[str]:
    """Detect inline absolute boxes that clearly sit outside 1920×1080.

    Catches the common KPI-grid failure: left+width > 1920 (right column clipped
    by root overflow:hidden). Does not fully simulate flex/grid flow.
    """
    issues: list[str] = []
    for m in _STYLE_ATTR_RE.finditer(html):
        if len(issues) >= max_issues:
            break
        style = m.group("style") or ""
        if not _style_declares_absolute(style):
            continue
        left = _parse_px_prop(style, "left")
        top = _parse_px_prop(style, "top")
        width = _parse_px_prop(style, "width")
        height = _parse_px_prop(style, "height")
        right = _parse_px_prop(style, "right")
        bottom = _parse_px_prop(style, "bottom")

        # Resolve right/bottom into left/top when possible
        if left is None and right is not None and width is not None:
            left = canvas_w - right - width
        if top is None and bottom is not None and height is not None:
            top = canvas_h - bottom - height

        if left is not None and width is not None:
            if left + width > canvas_w + margin:
                issues.append(
                    f"[export:bounds] {rel}: absolute 盒 left+width="
                    f"{left + width:.0f}px 超出画布右缘（1920）；"
                    f"请左移或缩小（当前 left={left:.0f} width={width:.0f}）"
                )
            elif left < -margin:
                issues.append(
                    f"[export:bounds] {rel}: absolute 盒 left={left:.0f}px 超出画布左缘"
                )
        if top is not None and height is not None:
            if top + height > canvas_h + margin:
                issues.append(
                    f"[export:bounds] {rel}: absolute 盒 top+height="
                    f"{top + height:.0f}px 超出画布下缘（1080）；"
                    f"请上移或缩小（当前 top={top:.0f} height={height:.0f}）"
                )
            elif top < -margin:
                issues.append(
                    f"[export:bounds] {rel}: absolute 盒 top={top:.0f}px 超出画布上缘"
                )
    return issues


# data-element=text 开放标签 → 匹配闭合；允许仅 <br>
_TEXT_LEAF_OPEN_RE = re.compile(
    r"""<(?P<tag>[\w-]+)\b(?P<attrs>[^>]*?\bdata-element\s*=\s*['\"]text['\"][^>]*)>""",
    re.I,
)

_DEPRECATED_TEXT_DATA_RE = re.compile(
    r"""\bdata-(?:font-size|font-family|color|line-height|align|bold|italic|underline|strike|fill|z-index|transparency|highlight)\s*=""",
    re.I,
)

_LINE_HEIGHT_BAD_RE = re.compile(
    r"""line-height\s*:\s*(?:normal|\d+(?:\.\d+)?(?:px|em|rem|%))""",
    re.I,
)


def audit_text_leaf_nesting(html: str, *, rel: str) -> list[str]:
    """Soft-warn: nested markup, non-span tag, bad line-height, deprecated data-*."""
    nested = 0
    non_span = 0
    bad_lh = 0
    deprecated = 0
    pos = 0
    while True:
        m = _TEXT_LEAF_OPEN_RE.search(html, pos)
        if not m:
            break
        tag = m.group("tag")
        attrs = m.group("attrs") or ""
        start = m.end()
        close = re.search(rf"</{re.escape(tag)}\s*>", html[start:], re.I)
        if not close:
            pos = start
            continue
        body = html[start : start + close.start()]
        pos = start + close.end()
        if tag.lower() != "span":
            non_span += 1
        stripped = re.sub(r"<br\s*/?>", "", body, flags=re.I)
        if re.search(r"<[a-zA-Z]", stripped):
            nested += 1
        style_m = re.search(r"""\bstyle\s*=\s*['\"]([^'\"]*)['\"]""", attrs, re.I)
        style = style_m.group(1) if style_m else ""
        if _LINE_HEIGHT_BAD_RE.search(style):
            bad_lh += 1
        if _DEPRECATED_TEXT_DATA_RE.search(attrs):
            deprecated += 1
    issues: list[str] = []
    if nested:
        issues.append(
            f"[visual-warn:text-nest] {rel}: {nested} 个 data-element=text 内嵌了标签"
            "（请拆成多个兄弟 <span data-element=text>；仅允许纯文本或 <br>）"
        )
    if non_span:
        issues.append(
            f"[visual-warn:text-tag] {rel}: {non_span} 个 text 叶不是 <span>"
            "（请改用 <span data-element=\"text\">）"
        )
    if bad_lh:
        issues.append(
            f"[visual-warn:line-height] {rel}: {bad_lh} 处 line-height 使用了 px/em/%/normal"
            "（请写无单位倍数，如 line-height:1.4）"
        )
    if deprecated:
        issues.append(
            f"[visual-warn:deprecated-data] {rel}: {deprecated} 个 text 叶仍含废弃 data-*"
            "（字号/颜色/对齐等请只写 style）"
        )
    return issues


def _zero_box_value(val: str) -> bool:
    compact = re.sub(r"\s+", " ", val.strip().lower())
    compact = re.sub(r"\s*!important\s*$", "", compact).strip()
    if compact in {"0", "0px", "0em", "0rem", "0%", "auto"}:
        return True
    return bool(re.fullmatch(r"0(\s+0){0,3}", compact))


def _theme_has_structural_slide_container(theme: str) -> bool:
    """仅当 .slide-container 使用 flex/grid 或非零 padding 时判定结构布局。"""
    for m in re.finditer(r"\.slide-container[^{]*\{([^}]*)\}", theme, re.I | re.S):
        block = m.group(1)
        if re.search(r"display\s*:\s*(flex|grid)\b", block, re.I):
            return True
        for pm in re.finditer(
            r"padding(?:-(?:top|right|bottom|left))?\s*:\s*([^;]+)",
            block,
            re.I,
        ):
            if not _zero_box_value(pm.group(1)):
                return True
    return False


def split_hard_soft_issues(issues: list[str]) -> tuple[list[str], list[str]]:
    """硬失败 vs 警告（export-warn / 已可忽略的主题结构提示）。"""
    hard: list[str] = []
    soft: list[str] = []
    for item in issues:
        if item.startswith("[export-warn:") or item.startswith("[cover-warn:") or item.startswith(
            "[visual-warn:"
        ):
            soft.append(item)
        elif "未知字段" in item and _unknown_fields_are_preview_only(item):
            # Preview-only keys (fontWeight / image rectRadius) must not fail the batch
            soft.append(f"[export-warn:preview-key] {item}")
        else:
            hard.append(item)
    return hard, soft


_PREVIEW_ONLY_OPTION_RE = re.compile(
    r"未知字段:\s*\[([^\]]*)\]",
)
_PREVIEW_ONLY_OPTION_NAMES = frozenset({"fontWeight", "rectRadius"})


def _unknown_fields_are_preview_only(issue: str) -> bool:
    m = _PREVIEW_ONLY_OPTION_RE.search(issue)
    if not m:
        return False
    raw = m.group(1).strip()
    if not raw:
        return False
    names = {p.strip().strip("'\"") for p in raw.split(",") if p.strip()}
    return bool(names) and names <= _PREVIEW_ONLY_OPTION_NAMES


_COVERISH_LAYOUT = re.compile(
    r"(?:^|-)(cover|section|closing|hero|title|chapter)(?:-|$)",
    re.I,
)


def _is_coverish_layout(layout: str, title: str = "") -> bool:
    blob = f"{layout} {title}".lower()
    if _COVERISH_LAYOUT.search(layout or ""):
        return True
    return any(k in blob for k in ("封面", "章节", "收尾", "扉页"))


def _parse_px(val: str | None) -> float | None:
    if not val:
        return None
    m = re.search(r"([\d.]+)\s*px", val, re.I)
    if m:
        return float(m.group(1))
    try:
        return float(val)
    except ValueError:
        return None


def _html_image_area_ratio(html: str) -> float:
    """Estimate max <img> area / 1920×1080 from inline width/height or style."""
    canvas = 1920.0 * 1080.0
    best = 0.0
    for m in re.finditer(r"<img\b[^>]*>", html, re.I):
        tag = m.group(0)
        wa = re.search(r'\bwidth\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        ha = re.search(r'\bheight\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        w = _parse_px(wa.group(1) if wa else None)
        h = _parse_px(ha.group(1) if ha else None)
        style = ""
        sm = re.search(r'\bstyle\s*=\s*["\']([^"\']*)["\']', tag, re.I)
        if sm:
            style = sm.group(1)
        if w is None:
            wm = re.search(r"(?<![-a-z])width\s*:\s*([\d.]+)\s*px", style, re.I)
            w = float(wm.group(1)) if wm else None
        if h is None:
            hm = re.search(r"(?<![-a-z])height\s*:\s*([\d.]+)\s*px", style, re.I)
            h = float(hm.group(1)) if hm else None
        if w and h and w > 0 and h > 0:
            best = max(best, (w * h) / canvas)
    return best


def _cover_image_issues(
    *,
    layout: str,
    title: str,
    rel: str,
    ratio: float,
    has_img_tag: bool,
) -> list[str]:
    if not _is_coverish_layout(layout, title):
        return []
    issues: list[str] = []
    if not has_img_tag or ratio <= 0.01:
        issues.append(
            f"[cover-image] {rel}: 封面/章节类页缺少主视觉图（PREMIUM_COVER 要求全出血或 ≥70%）"
        )
    elif ratio < 0.35:
        issues.append(
            f"[cover-image] {rel}: 主视觉过小（约 {ratio:.0%}），封面须 ≥70% 或至少 ≥35%"
        )
    elif ratio < 0.70:
        issues.append(
            f"[cover-warn:hero-area] {rel}: 主视觉约 {ratio:.0%}，建议 ≥70% 全出血（PREMIUM_COVER）"
        )
    return issues


def validate_package_dir(out_dir: Path) -> list[str]:
    issues: list[str] = []
    meta_path = out_dir / "template.json"
    if not meta_path.is_file():
        return ["缺少 template.json"]

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"template.json 解析失败: {e}"]

    for key in ("schema_version", "template_id", "label", "description", "files", "slides", "source"):
        if key not in meta:
            issues.append(f"template.json 缺少字段: {key}")

    if meta.get("schema_version") != "1.0":
        issues.append("schema_version 应为 \"1.0\"")

    tid = meta.get("template_id")
    if isinstance(tid, str) and tid.strip():
        folder = out_dir.resolve().name
        if tid != folder:
            issues.append(
                f"template_id 必须与文件夹名一致（当前 template_id={tid!r} folder={folder!r}）"
            )
        if re.search(r"[^a-z0-9_-]", tid):
            issues.append(
                f"template_id 仅允许小写字母、数字、短横线、下划线（当前 {tid!r}）"
            )
    else:
        issues.append("template_id 不能为空")

    if "name" in meta:
        issues.append("禁止字段 name")

    issues.extend(_validate_html_package(out_dir, meta))
    return issues


def _validate_html_package(out_dir: Path, meta: dict) -> list[str]:
    issues: list[str] = []
    slides = meta.get("slides") or []
    if not isinstance(slides, list) or not slides:
        issues.append("slides 为空")

    files = meta.get("files") or {}
    theme_rel = files.get("theme_css") or "theme.css"
    if not (out_dir / theme_rel).is_file():
        issues.append(f"缺少 {theme_rel}")

    theme = (out_dir / theme_rel).read_text(encoding="utf-8") if (out_dir / theme_rel).is_file() else ""
    if theme and _theme_has_structural_slide_container(theme):
        issues.append("theme.css 疑似在 .slide-container 上写了结构布局")

    layouts: set[str] = set()
    table_pages: list[str] = []
    for item in slides:
        if not isinstance(item, dict):
            issues.append("slides 项不是 object")
            continue
        for k in ("file", "title", "layout", "description"):
            if k not in item:
                issues.append(f"slide 缺少 {k}: {item}")
        if "slots" in item:
            issues.append(f"禁止 slides[].slots: {item.get('file')}")
        layout = str(item.get("layout") or "")
        if layout in layouts:
            issues.append(f"layout 重复: {layout}")
        layouts.add(layout)
        rel = str(item.get("file") or "")
        path = out_dir / rel
        if not path.is_file():
            issues.append(f"缺少页面文件: {rel}")
            continue
        html = path.read_text(encoding="utf-8")
        if 'href="../theme.css"' not in html and 'href="theme.css"' not in html:
            issues.append(f"{rel} 未引用 theme.css")
        if "1920" not in html and "1920" not in theme:
            issues.append(f"{rel} 与 theme 均未声明 1920 画布")
        if re.search(r"@keyframes\b", html, re.I):
            issues.append(f"{rel} 含 @keyframes 动画")
        html_anim = re.sub(
            r"transition(?:-(?:duration|delay|property|timing-function))?\s*:\s*(?:none|0(?:s|ms)?)\s*;?",
            "",
            html,
            flags=re.I,
        )
        if re.search(r"(?:@keyframes|transition(?:-|\s*:))", html_anim, re.I):
            issues.append(f"{rel} 含动画相关 CSS")

        unsafe_rotated_text = count_unsafe_rotated_text_wrappers(html)
        if unsafe_rotated_text:
            issues.append(
                f"[html-to-pptx:rotated-text-wrapper] {rel}: "
                f"发现 {unsafe_rotated_text} 个旋转 flex/grid 容器，"
                "文字必须与 transform 位于同一 DOM 节点"
            )

        issues.extend(_scan_html_export_contract(html, rel))
        issues.extend(scan_html_absolute_bounds(html, rel))
        orphan_css = count_css_orphan_inset_rules(html)
        if orphan_css:
            issues.append(
                f"[export:position] {rel}: {orphan_css} 条 CSS 规则写了 left/top "
                "却缺少 position:absolute（模块会掉回文档流叠到左上角）"
            )
        issues.extend(
            _cover_image_issues(
                layout=layout,
                title=str(item.get("title") or ""),
                rel=rel,
                ratio=_html_image_area_ratio(html),
                has_img_tag=bool(re.search(r"<img\b", html, re.I)),
            )
        )
        if re.search(r"<table\b", html, re.I):
            table_pages.append(rel)

    if len(table_pages) > 1:
        issues.append(
            f"[visual-warn:table-budget] 整包有 {len(table_pages)} 页含 <table>："
            f"{', '.join(table_pages[:4])}；请保留最多 1 页"
        )

    theme_export = _scan_html_export_contract(theme, theme_rel)
    issues.extend(theme_export)

    source = meta.get("source") or {}
    canvas = source.get("canvas") or {}
    if canvas.get("width") != 1920 or canvas.get("height") != 1080:
        issues.append("source.canvas 必须为 1920×1080")

    return issues
