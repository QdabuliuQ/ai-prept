"""ppt-master local image assignment / scrub / sanitize preservation."""

from __future__ import annotations

from pathlib import Path

from image.generate import infer_image_aspect, normalize_image_size
from ppt_master.pipeline import (
    _assign_plan_images,
    _normalize_slide_role,
    _scrub_svg_image_refs,
    _want_images,
)
from ppt_master.sanitize import sanitize_svg_text


def test_want_images_flags() -> None:
    assert _want_images(skip_images=True) is False
    assert _want_images(skip_images=False) is True


def test_role_aliases() -> None:
    assert _normalize_slide_role("closing") == "ending"
    assert _normalize_slide_role("data") == "content"
    assert _normalize_slide_role("thank-you") == "ending"


def test_normalize_image_size() -> None:
    assert normalize_image_size("auto") == "16:9"
    assert normalize_image_size("1:1") == "1:1"
    assert normalize_image_size("1024x1024") == "1:1"
    assert normalize_image_size("3/4") == "3:4"


def test_infer_image_aspect_from_geometry() -> None:
    assert (
        infer_image_aspect(
            {
                "role": "content",
                "geometry": "central circular mandala rings with square inset",
            }
        )
        == "1:1"
    )
    assert (
        infer_image_aspect(
            {"role": "cover", "geometry": "full-bleed hero photograph"}
        )
        == "16:9"
    )
    assert (
        infer_image_aspect(
            {"role": "content", "image_aspect": "3:4", "geometry": "anything"}
        )
        == "3:4"
    )


def test_assign_plan_images_defaults_and_files() -> None:
    slides = [
        {
            "file": "01_cover.svg",
            "role": "cover",
            "title": "Cover",
            "need_image": True,
            "image_hint": "night city skyline",
        },
        {
            "file": "02_section.svg",
            "role": "section",
            "title": "Chapter",
            "geometry": "circular paper-cut emblem centered",
        },
        {"file": "03_body.svg", "role": "content", "title": "Body", "need_image": False},
    ]
    refs = _assign_plan_images(slides, enable=True)
    assert refs["01_cover.png"]["prompt"] == "night city skyline"
    assert refs["01_cover.png"]["size"] == "16:9"
    assert slides[0]["image_file"] == "01_cover.png"
    assert slides[0]["image_aspect"] == "16:9"
    assert slides[1]["need_image"] is True
    assert slides[1]["image_aspect"] == "1:1"
    assert refs[slides[1]["image_file"]]["size"] == "1:1"
    assert slides[2]["need_image"] is False
    assert "image_file" not in slides[2]

    empty = _assign_plan_images(slides, enable=False)
    assert empty == {}
    assert slides[0]["need_image"] is False


def test_scrub_drops_external_and_missing(tmp_path: Path) -> None:
    (tmp_path / "01_cover.png").write_bytes(b"\x89PNG\r\n")
    svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
  <image href="../images/01_cover.png" x="0" y="0" width="640" height="720"/>
  <image href="https://evil.example/x.png" x="0" y="0" width="10" height="10"/>
  <image href="../images/missing.png" x="0" y="0" width="10" height="10"/>
</svg>
"""
    out = _scrub_svg_image_refs(
        svg, allowed={"01_cover.png"}, images_dir=tmp_path
    )
    assert "01_cover.png" in out
    assert "evil.example" not in out
    assert "missing.png" not in out


def test_sanitize_preserves_and_promotes_image() -> None:
    raw = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"
  data-pptx-page-role="cover" font-family="Arial, Microsoft YaHei, sans-serif">
  <rect id="bg" x="0" y="0" width="1280" height="720" fill="#111111" data-pptx-role="background"/>
  <g data-pptx-role="decoration">
    <image href="../images/01_cover.png" x="640" y="0" width="640" height="720"
      preserveAspectRatio="xMidYMid slice"/>
  </g>
  <g id="title" data-pptx-bounds="72 200 500 80">
    <text x="72" y="260" fill="#FFFFFF" font-size="40">Hello</text>
  </g>
</svg>
"""
    out = sanitize_svg_text(raw)
    assert 'href="../images/01_cover.png"' in out or "01_cover.png" in out
    assert "<image" in out
    # promoted out of decoration group → root-level with id
    assert 'id="' in out
    assert 'data-slot="title"' in out
    assert 'data-slot-type="text"' in out
    assert 'data-slot="hero-image"' in out
    assert 'data-slot-type="image"' in out


def test_sanitize_fills_missing_data_slots() -> None:
    raw = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"
  data-pptx-page-role="content" font-family="Arial, Microsoft YaHei, sans-serif">
  <rect id="bg" x="0" y="0" width="1280" height="720" fill="#111111" data-pptx-role="background"/>
  <rect id="bar" x="72" y="80" width="48" height="6" fill="#FF0000" data-pptx-role="decoration"/>
  <g id="title" data-pptx-bounds="72 120 800 80">
    <text x="72" y="180" fill="#FFFFFF" font-size="44">产品发布</text>
  </g>
  <g id="body" data-pptx-bounds="72 240 900 120">
    <text x="72" y="280" fill="#CCCCCC" font-size="20">这是一段较长的正文说明，用于验证 body 槽位推断。</text>
  </g>
  <image id="panel" href="../images/02_panel.png" x="720" y="200" width="480" height="360"
    preserveAspectRatio="xMidYMid slice" data-pptx-role="decoration"/>
</svg>
"""
    out = sanitize_svg_text(raw)
    assert 'data-slot="title"' in out
    assert 'data-slot-role="page-title"' in out or 'data-slot-role="heading"' in out
    assert 'data-slot="body"' in out
    assert 'data-slot-type="text"' in out
    # second image (or first if only one visible at root after unwrap) gets a slot
    assert "data-slot=" in out
    assert 'data-slot-type="image"' in out
    assert 'data-pptx-shape-name="title"' in out
    # decoration bar should not get a text/image slot requirement — no data-slot on bar alone
    assert "data-slot=" not in out.split('id="bar"')[1].split("/>")[0]


def test_sanitize_strips_dx_from_text_keeps_tspan_dx() -> None:
    raw = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"
  data-pptx-page-role="content" font-family="Arial, Microsoft YaHei, sans-serif">
  <rect id="bg" x="0" y="0" width="1280" height="720" fill="#111111" data-pptx-role="background"/>
  <g id="body" data-pptx-bounds="80 100 400 80">
    <text x="80" y="140" font-size="16" fill="#FFFFFF" dx="0">Hello</text>
    <text x="80" y="170" font-size="16" fill="#FFFFFF"><tspan dx="4" dy="12">World</tspan></text>
  </g>
</svg>
"""
    out = sanitize_svg_text(raw)
    assert 'dx="0"' not in out
    assert "<tspan" in out and 'dx="4"' in out


def test_sanitize_strips_clip_path_from_groups() -> None:
    raw = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"
  data-pptx-page-role="content" font-family="Arial, Microsoft YaHei, sans-serif">
  <defs><clipPath id="term-clip"><rect x="0" y="0" width="100" height="100"/></clipPath></defs>
  <rect id="bg" x="0" y="0" width="1280" height="720" fill="#111111" data-pptx-role="background"/>
  <g id="body" clip-path="url(#term-clip)" data-pptx-bounds="80 100 400 80">
    <text x="80" y="140" font-size="16" fill="#FFFFFF">Hello</text>
  </g>
</svg>
"""
    out = sanitize_svg_text(raw)
    assert "clip-path=" not in out
    assert "term-clip" not in out


def test_sanitize_strips_smil_animate() -> None:
    raw = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"
  data-pptx-page-role="content" font-family="Arial, Microsoft YaHei, sans-serif">
  <rect id="bg" x="0" y="0" width="1280" height="720" fill="#111111" data-pptx-role="background"/>
  <g id="body" data-pptx-bounds="80 100 400 80">
    <rect id="cursor" x="100" y="120" width="8" height="16" fill="#4EC9B0">
      <animate attributeName="opacity" values="1;0;1" dur="1s" repeatCount="indefinite"/>
    </rect>
    <text x="80" y="140" font-size="16" fill="#FFFFFF">Hello</text>
  </g>
</svg>
"""
    out = sanitize_svg_text(raw)
    assert "<animate" not in out.lower()
    kept = sanitize_svg_text(raw, strip_unsupported=False)
    assert "<animate" in kept.lower()


def test_sanitize_strips_br_and_dangling_marker() -> None:
    raw = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"
  data-pptx-page-role="content" font-family="Arial, Microsoft YaHei, sans-serif">
  <rect id="bg" x="0" y="0" width="1280" height="720" fill="#111111" data-pptx-role="background"/>
  <g id="body" data-pptx-bounds="80 100 500 80">
    <text x="80" y="140" font-size="16" fill="#FFFFFF">Hello<br/>World</text>
  </g>
  <path id="trail" d="M100 200 L400 400" stroke="#888888" stroke-width="2"
    fill="none" marker-end="url(#arrowhead)" data-pptx-role="decoration"/>
</svg>
"""
    out = sanitize_svg_text(raw)
    assert "<br" not in out.lower()
    assert "marker-end" not in out
    assert "Hello" in out and "World" in out
    kept = sanitize_svg_text(raw, strip_unsupported=False)
    assert "marker-end" in kept


def test_sanitize_strips_marker_color_mismatch() -> None:
    raw = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"
  data-pptx-page-role="content" font-family="Arial, Microsoft YaHei, sans-serif">
  <defs>
    <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#8C6E4A"/>
    </marker>
  </defs>
  <rect id="bg" x="0" y="0" width="1280" height="720" fill="#F5F2E9" data-pptx-role="background"/>
  <path id="trail" d="M100 200 L400 400" stroke="#4A6B5D" stroke-width="2"
    fill="none" marker-end="url(#arrowhead)" data-pptx-role="decoration"/>
</svg>
"""
    out = sanitize_svg_text(raw)
    assert "marker-end" not in out
    matched = raw.replace("#8C6E4A", "#4A6B5D")
    kept = sanitize_svg_text(matched)
    assert 'marker-end="url(#arrowhead)"' in kept
