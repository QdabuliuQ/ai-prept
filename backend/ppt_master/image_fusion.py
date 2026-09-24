"""配图与 SVG 装饰分工：校验生图是否真正可见、页面是否有内容。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

_CIRCLE_RE = re.compile(r"<circle\b", re.I)
_TEXT_RE = re.compile(r"<text\b", re.I)
_IMAGE_HREF_RE = re.compile(
    r"""<(?:image)\b[^>]*?(?:href|xlink:href)\s*=\s*["']([^"']+)["']""",
    re.I | re.S,
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if tag else ""


def _href_name(href: str) -> str:
    return Path(href.strip()).name


def _parse_opacity(el: ET.Element) -> float:
    for key in ("opacity", "fill-opacity"):
        raw = el.attrib.get(key)
        if raw is None:
            continue
        try:
            return max(0.0, min(1.0, float(raw)))
        except ValueError:
            continue
    fill = (el.attrib.get("fill") or "").strip()
    m = re.search(r"rgba?\([^)]+,(\s*[\d.]+)\s*\)", fill, re.I)
    if m:
        try:
            return max(0.0, min(1.0, float(m.group(1))))
        except ValueError:
            pass
    return 1.0


def _is_near_full_bleed(el: ET.Element) -> bool:
    try:
        w = float(el.attrib.get("width") or 0)
        h = float(el.attrib.get("height") or 0)
    except ValueError:
        return False
    return w >= 1100 and h >= 600


def audit_svg_image_fusion(
    svg: str,
    *,
    prepared_image: str | None,
    require_text: bool = True,
    max_circles: int = 48,
    max_fullbleed_overlay_opacity: float = 0.15,
) -> list[str]:
    """Return human-readable issues; empty list means OK for fusion rules."""
    issues: list[str] = []
    text = svg or ""
    if not text.strip():
        return ["empty SVG"]

    circle_n = len(_CIRCLE_RE.findall(text))
    if circle_n > max_circles:
        issues.append(
            f"装饰 circle 过多（{circle_n}>{max_circles}）：半调/纹理应交给生图，"
            "SVG 只用少量局部装饰"
        )

    text_n = len(_TEXT_RE.findall(text))
    if require_text and text_n < 1:
        issues.append("页面缺少 <text>：配图页也必须有标题/文案，不能只留装饰或底图")

    expected = (prepared_image or "").strip()
    hrefs = [_href_name(h) for h in _IMAGE_HREF_RE.findall(text)]
    if expected:
        if expected not in hrefs:
            issues.append(
                f"已准备配图 {expected} 但 SVG 未引用 ../images/{expected}；"
                "主视觉/插图必须用 <image> 嵌入，装饰留给 SVG"
            )
        elif len(hrefs) > 1:
            extras = [h for h in hrefs if h != expected]
            if extras:
                issues.append(
                    f"仅允许引用本页配图，发现额外引用：{', '.join(extras)}"
                )
    elif hrefs:
        issues.append(f"本页无配图文件，却出现 <image>：{', '.join(hrefs)}")

    if expected and expected in hrefs:
        issues.extend(
            _audit_overlays_above_image(
                text, max_opacity=max_fullbleed_overlay_opacity
            )
        )

    return issues


def _audit_overlays_above_image(svg: str, *, max_opacity: float) -> list[str]:
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return []

    found_image = False
    heavy = 0
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "image":
            found_image = True
            continue
        if not found_image:
            continue
        if tag not in {"rect", "path", "polygon"}:
            continue
        role = (el.attrib.get("data-pptx-role") or "").strip().lower()
        if role == "background":
            continue
        if not _is_near_full_bleed(el):
            continue
        fill = (el.attrib.get("fill") or "").strip().lower()
        if fill in {"none", "transparent"}:
            continue
        if _parse_opacity(el) > max_opacity:
            heavy += 1
    if heavy:
        return [
            f"配图上方有 {heavy} 个近满版遮罩（opacity>{max_opacity}）："
            "会盖住生图；改为局部装饰或把需要的氛围写进 image_hint 由生图完成"
        ]
    return []


def fusion_repair_brief(issues: list[str]) -> str:
    if not issues:
        return ""
    bullets = "\n".join(f"- {x}" for x in issues)
    return (
        "配图融合校验失败，请重写本页 SVG：\n"
        f"{bullets}\n"
        "分工：生图=主视觉/插图/背景图（题材按本页需要：照片、插画、产品图等均可，"
        "不默认纹理半调）；SVG=结构与局部装饰。"
        "禁止用海量 circle 仿半调；禁止满版高透明遮罩盖住 <image>。"
    )
