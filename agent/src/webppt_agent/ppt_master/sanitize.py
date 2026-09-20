"""质检前修正 LLM SVG 常见硬错误：缺 id；可选按质检报告扩 bounds。"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ET.register_namespace("", "http://www.w3.org/2000/svg")

# Closed DrawingML text surface (mirrors svg_to_pptx text_properties allowlists).
# dx/dy are legal on <tspan> only — never on <text>.
_TEXT_DIRECT_ATTRIBUTES = frozenset({
    "fill",
    "fill-opacity",
    "filter",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "id",
    "letter-spacing",
    "opacity",
    "stroke",
    "stroke-opacity",
    "stroke-width",
    "style",
    "text-anchor",
    "text-decoration",
    "transform",
    "x",
    "xml:space",
    "y",
})

_TSPAN_DIRECT_ATTRIBUTES = frozenset({
    "baseline-shift",
    "dx",
    "dy",
    "fill",
    "fill-opacity",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "id",
    "letter-spacing",
    "opacity",
    "stroke",
    "stroke-opacity",
    "stroke-width",
    "style",
    "text-decoration",
    "x",
    "xml:space",
    "y",
})


def _strip_smil_animations(root: Any) -> int:
    """Remove SMIL animation nodes — native PPTX has no SVG timeline."""
    smil = {
        "animate",
        "animatetransform",
        "animatemotion",
        "animatecolor",
        "set",
        "mpath",
    }
    removed = 0
    for parent in list(root.iter()):
        for child in list(parent):
            if _local(child.tag).lower() in smil:
                parent.remove(child)
                removed += 1
    return removed


def _strip_html_foreign_nodes(root: Any) -> int:
    """Remove HTML-only nodes illegally nested in SVG (esp. <br> inside <text>)."""
    forbidden = {
        "br",
        "div",
        "p",
        "span",
        "strong",
        "b",
        "i",
        "em",
        "ul",
        "ol",
        "li",
        "a",
        "table",
        "tr",
        "td",
        "th",
        "foreignobject",
    }
    removed = 0
    for parent in list(root.iter()):
        for child in list(parent):
            tag = _local(child.tag).lower()
            if tag not in forbidden:
                continue
            # Prefer unwrap when the node carries SVG children; else drop.
            kids = list(child)
            if kids and tag != "br":
                idx = list(parent).index(child)
                for i, grand in enumerate(kids):
                    parent.insert(idx + 1 + i, grand)
            parent.remove(child)
            removed += 1
    return removed


def _strip_dangling_line_markers(root: Any) -> int:
    """Drop marker-start/mid/end that lack a matching <marker>, or whose fill
    does not match the host line stroke (ppt-master export hard-rejects that).
    """
    markers: dict[str, Any] = {}
    for el in root.iter():
        if _local(el.tag).lower() != "marker":
            continue
        mid = (el.attrib.get("id") or "").strip()
        if mid:
            markers[mid] = el

    def _marker_fill(marker_el: Any) -> str | None:
        for child in marker_el.iter():
            if _local(child.tag).lower() in {"polygon", "path", "circle", "rect"}:
                fill = (child.attrib.get("fill") or "").strip()
                if fill and fill.lower() not in {"none", "transparent"}:
                    return fill.upper() if fill.startswith("#") else fill
        return None

    def _host_stroke(el: Any) -> str | None:
        stroke = (el.attrib.get("stroke") or "").strip()
        if stroke and stroke.lower() not in {"none", "transparent"}:
            return stroke.upper() if stroke.startswith("#") else stroke
        style = el.attrib.get("style") or ""
        m = re.search(r"(?:^|;)\s*stroke\s*:\s*([^;]+)", style, flags=re.I)
        if m:
            stroke = m.group(1).strip()
            if stroke and stroke.lower() not in {"none", "transparent"}:
                return stroke.upper() if stroke.startswith("#") else stroke
        return None

    removed = 0
    for el in root.iter():
        for attr in ("marker-start", "marker-mid", "marker-end"):
            raw = el.attrib.get(attr)
            if not raw:
                continue
            m = re.fullmatch(r"url\(\s*#([^)]+)\s*\)", raw.strip(), flags=re.I)
            if m is None or m.group(1) not in markers:
                del el.attrib[attr]
                removed += 1
                continue
            marker_el = markers[m.group(1)]
            mfill = _marker_fill(marker_el)
            stroke = _host_stroke(el)
            # Export requires marker fill == effective line stroke when both set.
            if mfill and stroke and mfill.upper() != stroke.upper():
                del el.attrib[attr]
                removed += 1
    return removed


def _strip_illegal_clip_paths(root: Any) -> int:
    """clip-path is only legal on <image> or data-pptx-crop wrappers — drop others."""
    removed = 0
    referenced: set[str] = set()
    for el in root.iter():
        raw = el.attrib.get("clip-path")
        if not raw:
            continue
        tag = _local(el.tag)
        crop = el.attrib.get("data-pptx-crop") == "1"
        if tag == "image" or (tag == "svg" and crop):
            m = re.fullmatch(r"url\(\s*#([^)]+)\s*\)", raw.strip(), flags=re.I)
            if m:
                referenced.add(m.group(1))
            continue
        del el.attrib["clip-path"]
        removed += 1

    # Drop orphan clipPath defs that nothing references after the strip.
    for parent in root.iter():
        for child in list(parent):
            if _local(child.tag) != "clipPath":
                continue
            cid = child.attrib.get("id") or ""
            if cid and cid not in referenced:
                parent.remove(child)
                removed += 1
    return removed


def _attr_local(name: str) -> str:
    if name.startswith("{"):
        return name.rsplit("}", 1)[-1]
    if ":" in name:
        return name.split(":", 1)[-1]
    return name


def _strip_unsupported_text_attrs(root: Any) -> int:
    """Drop text/tspan attrs outside the closed DrawingML mapping (e.g. text@dx)."""
    removed = 0
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "text":
            allow = _TEXT_DIRECT_ATTRIBUTES
        elif tag == "tspan":
            allow = _TSPAN_DIRECT_ATTRIBUTES
        else:
            continue
        for raw_name in list(el.attrib):
            local = _attr_local(raw_name)
            if local.startswith("data-"):
                continue
            if local == "space":  # xml:space
                continue
            if local not in allow:
                del el.attrib[raw_name]
                removed += 1
    return removed


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _unique_id(base: str, used: set[str]) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_-]+", "-", base).strip("-") or "el"
    if raw[0].isdigit():
        raw = "n-" + raw
    cand = raw
    i = 2
    while cand in used:
        cand = f"{raw}-{i}"
        i += 1
    used.add(cand)
    return cand


def _parse_bounds(value: str) -> tuple[float, float, float, float] | None:
    parts = value.strip().split()
    if len(parts) != 4:
        return None
    try:
        return tuple(float(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _fmt_bounds(x: float, y: float, w: float, h: float) -> str:
    def fmt(n: float) -> str:
        return str(int(n)) if abs(n - int(n)) < 1e-6 else f"{n:.1f}"

    return f"{fmt(x)} {fmt(y)} {fmt(w)} {fmt(h)}"


_SLOT_FROM_ID = {
    "title": ("title", "page-title"),
    "heading": ("title", "heading"),
    "page-title": ("title", "page-title"),
    "subtitle": ("subtitle", "lede"),
    "lede": ("subtitle", "lede"),
    "eyebrow": ("eyebrow", "meta"),
    "meta": ("eyebrow", "meta"),
    "caption": ("eyebrow", "meta"),
    "footer": ("footer", "meta"),
    "body": ("body", "body"),
    "hero-image": ("hero-image", "hero-image"),
    "hero-img": ("hero-image", "hero-image"),
    "hero": ("hero-image", "hero-image"),
    "logo": ("logo", "logo"),
}


def _slug_slot(raw: str) -> str:
    if not (raw or "").strip():
        return ""
    s = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", raw.strip()).strip("-").lower()
    return (s or "slot")[:48]


def _unique_slot(base: str, used: set[str]) -> str:
    raw = _slug_slot(base) or "slot"
    cand = raw
    i = 2
    while cand in used:
        cand = f"{raw}-{i}"
        i += 1
    used.add(cand)
    return cand


def _group_has_visible_text(g: Any) -> bool:
    for el in g.iter():
        if _local(el.tag) != "text":
            continue
        if "".join(el.itertext()).strip():
            return True
    return False


def _text_len_and_size(g: Any) -> tuple[int, float | None]:
    chunks: list[str] = []
    sizes: list[float] = []
    for el in g.iter():
        if _local(el.tag) != "text":
            continue
        chunks.append("".join(el.itertext()).strip())
        try:
            sizes.append(float(el.attrib.get("font-size", "0") or 0))
        except ValueError:
            pass
    text = " ".join(c for c in chunks if c)
    size = max(sizes) if sizes else None
    return len(text), size


def _infer_text_slot(name: str, text_len: int, font_size: float | None) -> tuple[str, str]:
    key = _slug_slot(name)
    for token, pair in _SLOT_FROM_ID.items():
        if token in key.split("-") or key == token or key.startswith(token + "-"):
            if pair[1] != "hero-image" and pair[1] != "logo":
                return pair
    if font_size is not None and font_size >= 40 and text_len <= 60:
        return ("title", "heading")
    if font_size is not None and font_size >= 28 and text_len <= 100:
        return ("subtitle", "lede")
    if text_len <= 24:
        return ("eyebrow", "meta")
    if text_len <= 80:
        return ("title", "heading")
    return ("body", "body")


def _set_slot_attrs(el: Any, *, slot: str, slot_type: str, slot_role: str) -> None:
    el.set("data-slot", slot)
    el.set("data-slot-type", slot_type)
    el.set("data-slot-role", slot_role)
    # Prefer this name when svg_to_pptx exports cNvPr/@name
    if not (el.attrib.get("data-pptx-shape-name") or "").strip():
        el.set("data-pptx-shape-name", slot)


def _ensure_data_slots(root: Any) -> None:
    """Ensure content <g>/<text>/<image> carry stable data-slot* for editing."""
    used: set[str] = set()

    # Root content groups with text
    for child in list(root):
        if _local(child.tag) != "g":
            continue
        role = (child.attrib.get("data-pptx-role") or "").strip().lower()
        if role in {"background", "decoration"}:
            continue
        if not _group_has_visible_text(child):
            continue

        authored = _slug_slot(child.attrib.get("data-slot") or "")
        slot_type = (child.attrib.get("data-slot-type") or "").strip() or "text"
        slot_role = (child.attrib.get("data-slot-role") or "").strip()
        text_len, font_size = _text_len_and_size(child)
        if authored:
            slot = _unique_slot(authored, used)
            if not slot_role:
                slot_role = _infer_text_slot(authored, text_len, font_size)[1]
        else:
            slot_base, inferred_role = _infer_text_slot(
                child.attrib.get("id") or "body", text_len, font_size
            )
            slot = _unique_slot(slot_base, used)
            slot_role = slot_role or inferred_role
        _set_slot_attrs(child, slot=slot, slot_type=slot_type, slot_role=slot_role)

        for el in child.iter():
            if _local(el.tag) != "text":
                continue
            if not "".join(el.itertext()).strip():
                continue
            child_authored = _slug_slot(el.attrib.get("data-slot") or "")
            # Prefer parent slot id for export name stability; don't uniquify again
            t_slot = child_authored or slot
            t_role = (el.attrib.get("data-slot-role") or "").strip() or slot_role
            t_type = (el.attrib.get("data-slot-type") or "").strip() or "text"
            _set_slot_attrs(el, slot=t_slot, slot_type=t_type, slot_role=t_role)

    # Images (root or nested)
    image_i = 0
    for el in root.iter():
        if _local(el.tag) != "image":
            continue
        image_i += 1
        authored = _slug_slot(el.attrib.get("data-slot") or "")
        slot_type = (el.attrib.get("data-slot-type") or "").strip() or "image"
        slot_role = (el.attrib.get("data-slot-role") or "").strip()
        if authored:
            slot = _unique_slot(authored, used)
            if not slot_role:
                slot_role = (
                    "hero-image"
                    if "hero" in authored or "cover" in authored
                    else ("logo" if "logo" in authored else "image")
                )
        else:
            eid = _slug_slot(el.attrib.get("id") or "")
            if "logo" in eid:
                base, role = "logo", "logo"
            elif image_i == 1 or "hero" in eid or "cover" in eid:
                base, role = "hero-image", "hero-image"
            else:
                base, role = f"image-{image_i}", "image"
            slot = _unique_slot(base, used)
            slot_role = slot_role or role
        _set_slot_attrs(el, slot=slot, slot_type=slot_type, slot_role=slot_role)


_DECOR_ID_RE = re.compile(
    r"(decor|decoration|particle|particles|glow|halo|grid|orbit|corner|"
    r"triangle|accent-bar|side-decor|connector|link|frame|bg-shape)",
    re.I,
)
_SHAPE_TAGS = frozenset(
    {
        "rect",
        "circle",
        "ellipse",
        "line",
        "polygon",
        "polyline",
        "path",
        "use",
        "image",
    }
)


def _group_has_text(g: Any) -> bool:
    for el in g.iter():
        if _local(el.tag) in ("text", "tspan") and "".join(el.itertext()).strip():
            return True
    return False


def _is_decoration_root_group(g: Any) -> bool:
    """Root <g> that should not own a layout subcanvas competing with content."""
    if _local(g.tag) != "g":
        return False
    role = (g.attrib.get("data-pptx-role") or "").lower()
    if role in {"background", "decoration"}:
        return True
    eid = g.attrib.get("id") or ""
    if _DECOR_ID_RE.search(eid):
        return not _group_has_text(g)
    # text-free shape piles at root are decorations (particles, orbits, grids)
    return not _group_has_text(g)


def _apply_group_opacity(el: Any, group_opacity: float | None) -> None:
    if group_opacity is None or abs(group_opacity - 1.0) < 1e-6:
        return
    for key in ("opacity", "fill-opacity", "stroke-opacity"):
        if key not in el.attrib:
            continue
        try:
            el.set(key, f"{float(el.attrib[key]) * group_opacity:.4g}")
            return
        except ValueError:
            pass
    # prefer channel opacities when paint is present
    if el.attrib.get("fill") and el.attrib.get("fill") not in ("none",):
        try:
            cur = float(el.attrib.get("fill-opacity", "1"))
        except ValueError:
            cur = 1.0
        el.set("fill-opacity", f"{cur * group_opacity:.4g}")
    elif el.attrib.get("stroke") and el.attrib.get("stroke") not in ("none",):
        try:
            cur = float(el.attrib.get("stroke-opacity", "1"))
        except ValueError:
            cur = 1.0
        el.set("stroke-opacity", f"{cur * group_opacity:.4g}")
    else:
        el.set("opacity", f"{group_opacity:.4g}")


def _flatten_decoration_shapes(
    g: Any, *, used: set[str], out: list[Any], parent_opacity: float = 1.0
) -> None:
    try:
        go = float(g.attrib.get("opacity", "1"))
    except ValueError:
        go = 1.0
    opacity = parent_opacity * go
    for child in list(g):
        tag = _local(child.tag)
        if tag == "g":
            _flatten_decoration_shapes(child, used=used, out=out, parent_opacity=opacity)
            continue
        if tag not in _SHAPE_TAGS:
            continue
        _apply_group_opacity(child, opacity if opacity < 0.999 else None)
        if not child.attrib.get("id"):
            child.set("id", _unique_id(f"deco-{tag}", used))
        if not child.attrib.get("data-pptx-role"):
            child.set("data-pptx-role", "decoration")
        # drop inherited group bounds noise
        child.attrib.pop("data-pptx-bounds", None)
        out.append(child)


def _unwrap_decoration_root_groups(root: Any, used: set[str]) -> int:
    """Promote decoration-only root <g> into root primitives (no competing bounds)."""
    children = list(root)
    insert_at = 0
    for i, child in enumerate(children):
        if _local(child.tag) == "rect" and child.attrib.get("data-pptx-role") == "background":
            insert_at = i + 1
            break

    changed = 0
    for child in children:
        if not _is_decoration_root_group(child):
            continue
        shapes: list[Any] = []
        _flatten_decoration_shapes(child, used=used, out=shapes)
        if not shapes:
            # empty or only nested textless junk — drop group
            root.remove(child)
            changed += 1
            continue
        root.remove(child)
        for j, shape in enumerate(shapes):
            root.insert(insert_at + j, shape)
        insert_at += len(shapes)
        changed += 1
    return changed


def _fix_zero_height_gradient_strokes(root: Any, used: set[str]) -> int:
    """Replace horizontal/vertical lines painted with url(#…) stroke by thin rects."""
    n = 0
    for parent in [root, *root.iter()]:
        for child in list(parent):
            if _local(child.tag) != "line":
                continue
            stroke = child.attrib.get("stroke") or ""
            if not stroke.startswith("url("):
                continue
            try:
                x1, y1 = float(child.attrib["x1"]), float(child.attrib["y1"])
                x2, y2 = float(child.attrib["x2"]), float(child.attrib["y2"])
            except (KeyError, ValueError):
                continue
            if abs(y1 - y2) < 0.5:
                # horizontal
                x, y = min(x1, x2), y1 - 1
                w, h = abs(x2 - x1), 2.0
            elif abs(x1 - x2) < 0.5:
                x, y = x1 - 1, min(y1, y2)
                w, h = 2.0, abs(y2 - y1)
            else:
                continue
            rect = ET.Element("{http://www.w3.org/2000/svg}rect")
            rid = child.attrib.get("id") or _unique_id("grad-bar", used)
            if rid in used and child.attrib.get("id"):
                pass
            else:
                used.add(rid)
            rect.set("id", rid)
            rect.set("x", _fmt_num(x))
            rect.set("y", _fmt_num(y))
            rect.set("width", _fmt_num(w))
            rect.set("height", _fmt_num(h))
            rect.set("fill", stroke)
            if child.attrib.get("data-pptx-role"):
                rect.set("data-pptx-role", child.attrib["data-pptx-role"])
            else:
                rect.set("data-pptx-role", "decoration")
            idx = list(parent).index(child)
            parent.remove(child)
            parent.insert(idx, rect)
            n += 1
    return n


def _strip_invalid_dasharrays(root: Any) -> int:
    """Remove dash arrays that native DrawingML cannot represent.

    The SVG parser accepts values such as ``1 0`` in a browser, where they
    effectively render as a solid stroke.  The native converter rejects a
    non-positive gap, so keeping the attribute turns an otherwise exportable
    page into an ``svg-fallback`` package.  Dropping the attribute preserves
    the browser's solid-line appearance and keeps the stroke editable.
    """
    changed = 0
    for el in root.iter():
        raw = (el.attrib.get("stroke-dasharray") or "").strip()
        if not raw or raw.lower() == "none":
            continue
        parts = [p for p in re.split(r"[\s,]+", raw) if p]
        try:
            values = [float(p) for p in parts]
        except ValueError:
            continue
        if len(values) < 2:
            continue
        # SVG repeats an odd-length list, so every second value is a gap.
        expanded = values if len(values) % 2 == 0 else values * 2
        gaps = expanded[1::2]
        if any(gap <= 0 for gap in gaps):
            del el.attrib["stroke-dasharray"]
            changed += 1
    return changed


def _strip_pattern_child_transforms(root: Any) -> int:
    """Remove transforms unsupported on shapes inside SVG ``<pattern>``.

    Pattern transforms are decoration-only in generated decks.  Native
    DrawingML rejects a transformed child (for example a rotated stripe
    ``<rect>``), while browsers simply render it.  Removing only the child
    transform keeps the paint, size and position intact and allows the
    converter's compatible pattern fallback to preserve the visual intent.
    """
    changed = 0
    for pattern in root.iter():
        if _local(pattern.tag).lower() != "pattern":
            continue
        for child in pattern.iter():
            if child is pattern:
                continue
            if "transform" in child.attrib:
                del child.attrib["transform"]
                changed += 1
    return changed


def generation_compatibility_issues(raw: str) -> list[str]:
    """Return cheap, page-local issues that can make native export fail.

    This runs immediately after an LLM response, before the SVG is accepted
    into the project.  It deliberately reports only deterministic converter
    blockers; visual quality and bounds remain the responsibility of the full
    quality gate.
    """
    text = (raw or "").strip()
    if not text:
        return ["empty SVG"]
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [f"invalid XML: {exc}"]

    issues: list[str] = []
    for pattern in root.iter():
        if _local(pattern.tag).lower() != "pattern":
            continue
        if pattern.attrib.get("patternTransform"):
            issues.append("patternTransform is not supported")
        for child in pattern.iter():
            if child is not pattern and child.attrib.get("transform"):
                issues.append("pattern child transform is not supported")
                break

    for el in root.iter():
        raw_dash = (el.attrib.get("stroke-dasharray") or "").strip()
        if not raw_dash or raw_dash.lower() == "none":
            continue
        parts = [p for p in re.split(r"[\s,]+", raw_dash) if p]
        try:
            values = [float(p) for p in parts]
        except ValueError:
            issues.append(f"invalid stroke-dasharray: {raw_dash}")
            continue
        if len(values) >= 2:
            expanded = values if len(values) % 2 == 0 else values * 2
            if any(gap <= 0 for gap in expanded[1::2]):
                issues.append(f"stroke-dasharray has non-positive gap: {raw_dash}")

    # Preserve order while keeping the retry prompt short and deterministic.
    return list(dict.fromkeys(issues))[:8]


def _fmt_num(n: float) -> str:
    return str(int(n)) if abs(n - int(n)) < 1e-6 else f"{n:.1f}"


def _clamp_oversized_text(root: Any) -> int:
    """Shrink font-size when estimated ink would leave the 1280×720 viewBox."""
    n = 0
    for el in root.iter():
        if _local(el.tag) != "text":
            continue
        try:
            size = float(el.attrib.get("font-size", "0"))
            x = float(el.attrib.get("x", "0"))
            y = float(el.attrib.get("y", "0"))
        except ValueError:
            continue
        if size <= 0:
            continue
        content = "".join(el.itertext()).strip()
        if not content:
            continue
        # rough latin/mixed width
        est_w = len(content) * size * 0.62
        # vertical ink roughly size above baseline
        if est_w <= 1280 and y - size >= -20 and y <= 740 and x + est_w * 0.5 <= 1400:
            continue
        scale_w = 1100.0 / max(est_w, 1.0)
        scale_h = 600.0 / max(size, 1.0)
        scale = min(1.0, scale_w, scale_h)
        if scale >= 0.999:
            continue
        new_size = max(24.0, size * scale)
        el.set("font-size", _fmt_num(new_size))
        n += 1
    return n


def _resolve_content_overlaps(root: Any) -> int:
    """When two text-bearing root groups overlap, nest the smaller into the larger."""
    groups = [c for c in list(root) if _local(c.tag) == "g" and c.attrib.get("data-pptx-bounds")]
    boxes: list[tuple[Any, tuple[float, float, float, float]]] = []
    for g in groups:
        b = _parse_bounds(g.attrib["data-pptx-bounds"])
        if b:
            boxes.append((g, b))
    n = 0
    # iterate until stable / max pairs
    changed = True
    while changed:
        changed = False
        boxes = [
            (g, b)
            for g, b in (
                (g, _parse_bounds(g.attrib.get("data-pptx-bounds", "")))
                for g in list(root)
                if _local(g.tag) == "g" and g.attrib.get("data-pptx-bounds") and g in list(root)
            )
            if b
        ]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                ga, ba = boxes[i]
                gb, bb = boxes[j]
                if ga not in list(root) or gb not in list(root):
                    continue
                ax, ay, aw, ah = ba
                bx, by, bw, bh = bb
                ox = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
                oy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
                if ox <= 1 or oy <= 1:
                    continue
                # nest smaller-area into larger
                area_a, area_b = aw * ah, bw * bh
                parent, child = (ga, gb) if area_a >= area_b else (gb, ga)
                if child not in list(root):
                    continue
                root.remove(child)
                child.attrib.pop("data-pptx-bounds", None)
                parent.append(child)
                n += 1
                changed = True
                break
            if changed:
                break
    return n


def _strip_forbidden_css(text: str) -> str:
    """Remove <style> blocks and class= attrs (PPT Master forbids CSS)."""
    text = re.sub(r"<style\b[^>]*>.*?</style>", "", text, flags=re.I | re.S)
    text = re.sub(r"\sclass=(['\"]).*?\1", "", text, flags=re.I)
    text = re.sub(r"\sclass=([^\s>]+)", "", text, flags=re.I)
    return text


def _force_safe_font_family(text: str) -> str:
    """Keep editable text on PPT-safe stacks."""
    safe = 'font-family="Arial, Microsoft YaHei, sans-serif"'
    text = re.sub(
        r'font-family=(["\'])(.*?)\1',
        safe,
        text,
        flags=re.I,
    )
    # root svg without font-family
    if re.search(r"<svg\b", text, flags=re.I) and not re.search(
        r"<svg\b[^>]*font-family=", text, flags=re.I
    ):
        text = re.sub(r"<svg\b", f"<svg {safe}", text, count=1, flags=re.I)
    return text


def is_well_formed_svg(text: str) -> bool:
    body = text.strip()
    if body.startswith("<?xml"):
        end = body.find("?>")
        if end >= 0:
            body = body[end + 2 :].lstrip()
    try:
        ET.fromstring(body)
        return True
    except ET.ParseError:
        return False


def salvage_truncated_svg(raw: str) -> str | None:
    """Best-effort close a truncated SVG cut mid-attribute/tag."""
    text = raw.strip()
    if not text:
        return None
    if is_well_formed_svg(text):
        return text if text.endswith("\n") else text + "\n"

    # Drop a trailing incomplete tag / attribute
    cut = text
    for marker in ("<", '"', "'"):
        idx = cut.rfind(marker)
        if idx > 0 and idx > len(cut) - 240:
            # if last quote/tag looks unfinished, trim back to previous newline
            nl = cut.rfind("\n", 0, idx)
            if nl > len(cut) // 2:
                cut = cut[:nl]
                break
    # close open <g> roughly and ensure </svg>
    open_g = len(re.findall(r"<g\b", cut, flags=re.I)) - len(re.findall(r"</g>", cut, flags=re.I))
    if open_g > 0:
        cut += "\n" + ("</g>\n" * open_g)
    if not re.search(r"</svg>\s*$", cut, flags=re.I):
        cut += "\n</svg>\n"
    if not cut.lstrip().startswith("<?xml"):
        cut = '<?xml version="1.0" encoding="UTF-8"?>\n' + cut.lstrip()
    if is_well_formed_svg(cut):
        return cut if cut.endswith("\n") else cut + "\n"
    return None


def sanitize_svg_text(raw: str, *, strip_unsupported: bool = True) -> str:
    """Ensure ids; strip CSS; unwrap decoration groups; invent bounds.

    When strip_unsupported=True (default), also drop export-hard-fail attrs/nodes:
    text@dx/dy, illegal clip-path on non-image, SMIL <animate*>, HTML <br>,
    dangling marker-end/start.
    """
    text = raw.strip()
    if not text:
        return raw
    decl = ""
    if text.startswith("<?xml"):
        end = text.find("?>")
        if end >= 0:
            decl = text[: end + 2] + "\n"
            text = text[end + 2 :].lstrip()

    # cheap tag fix before parse
    text = re.sub(r"</?span\b", lambda m: m.group(0).replace("span", "tspan"), text)
    if strip_unsupported:
        # HTML line breaks inside SVG text — drop before parse (also catches <br>)
        text = re.sub(r"<br\s*/?>", "", text, flags=re.I)
    text = _strip_forbidden_css(text)
    text = _force_safe_font_family(text)

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        salvaged = salvage_truncated_svg((decl + text) if decl else text)
        if salvaged and salvaged != raw:
            return (
                sanitize_svg_text(salvaged, strip_unsupported=strip_unsupported)
                if is_well_formed_svg(salvaged)
                else (salvaged or raw)
            )
        return raw

    used: set[str] = set()
    for el in root.iter():
        eid = el.attrib.get("id")
        if eid:
            used.add(eid)

    _unwrap_decoration_root_groups(root, used)
    _fix_zero_height_gradient_strokes(root, used)
    if strip_unsupported:
        _strip_invalid_dasharrays(root)
        _strip_pattern_child_transforms(root)
    _clamp_oversized_text(root)
    if strip_unsupported:
        _strip_unsupported_text_attrs(root)
        _strip_illegal_clip_paths(root)
        _strip_smil_animations(root)
        _strip_html_foreign_nodes(root)
        _strip_dangling_line_markers(root)

    for i, child in enumerate(list(root), 1):
        tag = _local(child.tag)
        role = child.attrib.get("data-pptx-role")
        if (role or tag == "g") and not child.attrib.get("id"):
            child.set("id", _unique_id(f"{role or tag}-{i}", used))

    for k, el in enumerate(root.iter(), 1):
        if el.attrib.get("data-pptx-role") and not el.attrib.get("id"):
            r = el.attrib.get("data-pptx-role") or _local(el.tag)
            el.set("id", _unique_id(f"{r}-x{k}", used))
        if _local(el.tag) == "text" and not el.attrib.get("id"):
            el.set("id", _unique_id(f"text-{k}", used))
        if _local(el.tag) == "span":
            el.tag = "{http://www.w3.org/2000/svg}tspan"

    # Invent missing root-g bounds.  Do not "repair" overlapping modules by
    # nesting them: that only hides the contract violation and leaves the
    # rendered geometry in the same place.  The layout repair pass below moves
    # real content after the checker has measured it.
    for child in list(root):
        if _local(child.tag) != "g":
            continue
        if child.attrib.get("data-pptx-bounds"):
            continue
        box = _estimate_group_bounds(child)
        if box:
            child.set("data-pptx-bounds", _fmt_bounds(*box))

    _ensure_data_slots(root)

    body = ET.tostring(root, encoding="unicode")
    if not decl:
        decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return decl + body + ("\n" if not body.endswith("\n") else "")


def _estimate_group_bounds(g: Any) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for el in g.iter():
        tag = _local(el.tag)
        a = el.attrib
        try:
            if tag in ("rect",):
                x, y = float(a.get("x", 0)), float(a.get("y", 0))
                w, h = float(a.get("width", 0)), float(a.get("height", 0))
                xs.extend([x, x + w])
                ys.extend([y, y + h])
            elif tag in ("circle",):
                cx, cy, r = float(a["cx"]), float(a["cy"]), float(a["r"])
                xs.extend([cx - r, cx + r])
                ys.extend([cy - r, cy + r])
            elif tag in ("ellipse",):
                cx, cy = float(a["cx"]), float(a["cy"])
                rx, ry = float(a.get("rx", 0)), float(a.get("ry", 0))
                xs.extend([cx - rx, cx + rx])
                ys.extend([cy - ry, cy + ry])
            elif tag == "line":
                xs.extend([float(a["x1"]), float(a["x2"])])
                ys.extend([float(a["y1"]), float(a["y2"])])
            elif tag in ("text", "tspan"):
                if "x" in a and "y" in a:
                    x, y = float(a["x"]), float(a["y"])
                    size = float(a.get("font-size", 20))
                    # rough width estimate
                    content = "".join(el.itertext())
                    w = max(40.0, len(content) * size * 0.6)
                    xs.extend([x - 8, x + w])
                    ys.extend([y - size, y + size * 0.4])
            elif tag == "image":
                x, y = float(a.get("x", 0)), float(a.get("y", 0))
                w, h = float(a.get("width", 0)), float(a.get("height", 0))
                if w > 0 and h > 0:
                    xs.extend([x, x + w])
                    ys.extend([y, y + h])
            elif tag == "polygon" and a.get("points"):
                pts = a["points"].replace(",", " ").split()
                nums = [float(p) for p in pts]
                for i in range(0, len(nums) - 1, 2):
                    xs.append(nums[i])
                    ys.append(nums[i + 1])
        except (KeyError, ValueError):
            continue
    if not xs or not ys:
        return None
    pad = 8.0
    x1, x2 = max(0.0, min(xs) - pad), min(1280.0, max(xs) + pad)
    y1, y2 = max(0.0, min(ys) - pad), min(720.0, max(ys) + pad)
    return (x1, y1, max(1.0, x2 - x1), max(1.0, y2 - y1))


def expand_bounds_for_overflows(raw: str, messages: list[str]) -> str:
    """Expand specific group bounds mentioned in checker overflow errors."""
    # Example: exceeds <g id="title"> data-pptx-bounds on the horizontal axis:
    # content (419.9, 511.4)-(860.1, 530.6), container (440.0, 500.0)-(840.0, 540.0)
    targets: dict[str, tuple[float, float, float, float]] = {}
    for msg in messages:
        m = re.search(
            r"exceeds <g(?: id=\"([^\"]+)\")?> data-pptx-bounds on the ([\w\s]+?) axis:.*"
            r"content \(([-\d.]+), ([-\d.]+)\)-\(([-\d.]+), ([-\d.]+)\).*?"
            r"container \(([-\d.]+), ([-\d.]+)\)-\(([-\d.]+), ([-\d.]+)\)",
            msg,
        )
        if not m:
            continue
        gid = m.group(1) or ""
        axis = m.group(2)
        cx1, cy1, cx2, cy2 = map(float, m.group(3, 4, 5, 6))
        bx1, by1, bx2, by2 = map(float, m.group(7, 8, 9, 10))
        # expand container to cover content + 8px pad
        pad = 8.0
        nx1 = min(bx1, cx1) - pad
        ny1 = min(by1, cy1) - pad
        nx2 = max(bx2, cx2) + pad
        ny2 = max(by2, cy2) + pad
        nx1 = max(0.0, nx1)
        ny1 = max(0.0, ny1)
        nx2 = min(1280.0, nx2)
        ny2 = min(720.0, ny2)
        key = gid or f"__anon_{axis}_{len(targets)}"
        targets[key] = (nx1, ny1, max(1.0, nx2 - nx1), max(1.0, ny2 - ny1))

    if not targets:
        return raw

    text = raw.strip()
    decl = ""
    if text.startswith("<?xml"):
        end = text.find("?>")
        if end >= 0:
            decl = text[: end + 2] + "\n"
            text = text[end + 2 :].lstrip()
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return raw

    for el in root.iter():
        if _local(el.tag) != "g":
            continue
        eid = el.attrib.get("id", "")
        if eid in targets and el.attrib.get("data-pptx-bounds"):
            x, y, w, h = targets[eid]
            el.set("data-pptx-bounds", _fmt_bounds(x, y, w, h))

    # anonymous: expand first overflowing g without id match by order — skip if no id
    body = ET.tostring(root, encoding="unicode")
    if not decl:
        decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return decl + body + ("\n" if not body.endswith("\n") else "")


def sanitize_svg_dir(svg_dir: Path, *, strip_unsupported: bool = True) -> int:
    n = 0
    for path in sorted(svg_dir.glob("*.svg")):
        raw = path.read_text(encoding="utf-8")
        fixed = sanitize_svg_text(raw, strip_unsupported=strip_unsupported)
        if fixed != raw:
            path.write_text(fixed, encoding="utf-8")
            n += 1
    return n


def apply_overflow_fixes_from_report(
    project: Path,
    *,
    report_path: Path | None = None,
) -> int:
    """Read the quality report and apply deterministic geometry repairs."""
    report = report_path or project / "validation" / "svg_quality_report.json"
    if not report.is_file():
        return 0
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0

    files: dict[str, list[str]] = {}
    file_list = data.get("files") if isinstance(data, dict) else None
    if isinstance(file_list, list):
        for item in file_list:
            if not isinstance(item, dict):
                continue
            name = item.get("file") or item.get("path") or item.get("name")
            msgs: list[str] = []
            for key in ("errors", "warnings"):
                block = item.get(key)
                if isinstance(block, list):
                    for iss in block:
                        if isinstance(iss, str):
                            msgs.append(iss)
                        elif isinstance(iss, dict):
                            msgs.append(str(iss.get("message") or iss))
            if name and msgs:
                files[str(Path(str(name)).name)] = msgs

    touched = 0
    svg_dir = project / "svg_output"
    for name, msgs in files.items():
        path = svg_dir / name
        if not path.is_file():
            continue
        raw = path.read_text(encoding="utf-8")
        fixed = raw
        overflow_msgs = [m for m in msgs if "exceeds" in m and "data-pptx-bounds" in m]
        if overflow_msgs:
            fixed = expand_bounds_for_overflows(fixed, overflow_msgs)
        overlap_msgs = [m for m in msgs if "overlaps" in m and "data-pptx-bounds" in m]
        if overlap_msgs:
            fixed = shrink_overlapping_bounds(fixed, overlap_msgs)
        layout_msgs = [
            m
            for m in msgs
            if any(
                code in m
                for code in (
                    "[TEXT_TEXT_OVERLAP]",
                    "[TEXT_SHAPE_OCCLUSION]",
                )
            )
        ]
        if layout_msgs:
            if overlap_msgs:
                layout_msgs = [
                    re.sub(
                        r';\s*shift-module="[^"]+"\s+dx=[+-]?[\d.]+\s+dy=[+-]?[\d.]+',
                        '',
                        message,
                    )
                    for message in layout_msgs
                ]
            fixed = repair_layout_issues(fixed, layout_msgs)
        if fixed != raw:
            path.write_text(fixed, encoding="utf-8")
            touched += 1
    return touched


def shrink_overlapping_bounds(raw: str, messages: list[str]) -> str:
    """Resolve pairwise module overlap by moving the later module geometry."""
    # <g id="a"> data-pptx-bounds overlaps <g id="b"> data-pptx-bounds by WxH
    pairs: list[tuple[str, str]] = []
    for msg in messages:
        m = re.search(
            r'<g id="([^"]+)"> data-pptx-bounds overlaps <g id="([^"]+)">',
            msg,
        )
        if m:
            pairs.append((m.group(1), m.group(2)))
    if not pairs:
        return raw

    text = raw.strip()
    decl = ""
    if text.startswith("<?xml"):
        end = text.find("?>")
        if end >= 0:
            decl = text[: end + 2] + "\n"
            text = text[end + 2 :].lstrip()
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return raw

    by_id: dict[str, Any] = {}
    for el in root.iter():
        eid = el.attrib.get("id")
        if eid:
            by_id[eid] = el

    for a, b in pairs:
        ea, eb = by_id.get(a), by_id.get(b)
        if ea is None or eb is None:
            continue
        ba = _parse_bounds(ea.attrib.get("data-pptx-bounds", ""))
        bb = _parse_bounds(eb.attrib.get("data-pptx-bounds", ""))
        if not ba or not bb:
            continue
        ax, ay, aw, ah = ba
        bx, by, bw, bh = bb
        ax2, ay2 = ax + aw, ay + ah
        bx2, by2 = bx + bw, by + bh
        # Move the later module below the earlier one.  Updating both transform
        # and bounds changes the rendered page and keeps root-coordinate
        # metadata truthful.
        oy1, oy2 = max(ay, by), min(ay2, by2)
        ox1, ox2 = max(ax, bx), min(ax2, bx2)
        if oy2 - oy1 > 1 and ox2 - ox1 > 1:
            if ay <= by:
                dy = ay2 + 12 - by
                if by2 + dy <= 720:
                    _translate_element(eb, 0.0, dy)
                    eb.set("data-pptx-bounds", _fmt_bounds(bx, by + dy, bw, bh))
            else:
                dy = by2 + 12 - ay
                if ay2 + dy <= 720:
                    _translate_element(ea, 0.0, dy)
                    ea.set("data-pptx-bounds", _fmt_bounds(ax, ay + dy, aw, ah))

    body = ET.tostring(root, encoding="unicode")
    if not decl:
        decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return decl + body + ("\n" if not body.endswith("\n") else "")


def _translate_element(element: Any, dx: float, dy: float) -> None:
    """Apply one root-space translation while preserving an existing transform."""
    if not dx and not dy:
        return
    translate = f"translate({_fmt_num(dx)} {_fmt_num(dy)})"
    existing = (element.attrib.get("transform") or "").strip()
    element.set("transform", f"{translate} {existing}".strip())


def _serialize_svg(root: Any, decl: str) -> str:
    body = ET.tostring(root, encoding="unicode")
    prefix = decl or '<?xml version="1.0" encoding="UTF-8"?>\n'
    return prefix + body + ("\n" if not body.endswith("\n") else "")


def _parse_svg_document(raw: str) -> tuple[str, Any] | None:
    text = raw.strip()
    decl = ""
    if text.startswith("<?xml"):
        end = text.find("?>")
        if end >= 0:
            decl = text[: end + 2] + "\n"
            text = text[end + 2 :].lstrip()
    try:
        return decl, ET.fromstring(text)
    except ET.ParseError:
        return None


def _move_before(root: Any, moving: Any, anchor: Any) -> bool:
    """Move an element before an anchor at their nearest usable paint scope."""
    parent_by_id = {
        id(child): parent
        for parent in root.iter()
        for child in list(parent)
    }
    moving_parent = parent_by_id.get(id(moving))
    anchor_parent = parent_by_id.get(id(anchor))
    if moving_parent is anchor_parent and moving_parent is not None:
        moving_parent.remove(moving)
        moving_parent.insert(list(moving_parent).index(anchor), moving)
        return True

    # Root-level decoration can be placed before the text module safely.
    moving_top = moving
    while parent_by_id.get(id(moving_top)) is not None and parent_by_id[id(moving_top)] is not root:
        moving_top = parent_by_id[id(moving_top)]
    anchor_top = anchor
    while parent_by_id.get(id(anchor_top)) is not None and parent_by_id[id(anchor_top)] is not root:
        anchor_top = parent_by_id[id(anchor_top)]
    if moving_top in list(root) and anchor_top in list(root) and moving_top is not anchor_top:
        root.remove(moving_top)
        root.insert(list(root).index(anchor_top), moving_top)
        return True
    if moving_top is anchor_top and moving_parent is not None:
        # Within one module, a backplate/decoration belongs before all text.
        moving_parent.remove(moving)
        moving_parent.insert(0, moving)
        return True
    return False


def repair_layout_issues(raw: str, messages: list[str]) -> str:
    """Apply checker-directed z-order, decoration, and module translations."""
    parsed = _parse_svg_document(raw)
    if parsed is None:
        return raw
    decl, root = parsed
    by_id = {
        element.attrib["id"]: element
        for element in root.iter()
        if element.attrib.get("id")
    }
    changed = False

    for message in messages:
        module_match = re.search(
            r'shift-module="([^"]+)"\s+dx=([+-]?[\d.]+)\s+dy=([+-]?[\d.]+)',
            message,
        )
        if module_match:
            module = by_id.get(module_match.group(1))
            if module is not None:
                dx, dy = float(module_match.group(2)), float(module_match.group(3))
                _translate_element(module, dx, dy)
                bounds = _parse_bounds(module.attrib.get("data-pptx-bounds", ""))
                if bounds:
                    x, y, width, height = bounds
                    module.set(
                        "data-pptx-bounds",
                        _fmt_bounds(x + dx, y + dy, width, height),
                    )
                changed = changed or bool(dx or dy)

        shape_match = re.search(r'shape-id="([^"]+)"', message)
        if not shape_match:
            continue
        shape = by_id.get(shape_match.group(1))
        if shape is None:
            continue
        dx_match = re.search(r'suggest-shape-dx=([+-]?[\d.]+)', message)
        dy_match = re.search(r'suggest-shape-dy=([+-]?[\d.]+)', message)
        if _local(shape.tag) in {"line", "polyline"} and dx_match and dy_match:
            dx, dy = float(dx_match.group(1)), float(dy_match.group(1))
            _translate_element(shape, dx, dy)
            changed = changed or bool(dx or dy)
            continue
        owner_match = re.search(r'text-owner="([^"]*)"', message)
        owner = by_id.get(owner_match.group(1)) if owner_match else None
        if owner is not None:
            changed = _move_before(root, shape, owner) or changed

    return _serialize_svg(root, decl) if changed else raw
