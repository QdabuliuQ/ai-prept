"""Tests for visual-spec generation that reads slide HTML."""

from __future__ import annotations

from pathlib import Path

from templates.prompts import SYSTEM_VISUAL_SPEC, user_visual_spec
from templates.visual_spec import (
    build_deck_context,
    generate_visual_spec,
    _pick_excerpt_indices,
)

MINIMAL_COVER = """<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <link rel="stylesheet" href="../theme.css" />
</head>
<body>
<div class="pptx-slide-root" style="position:relative;width:1920px;height:1080px;overflow:hidden;background:#ffffff;">
  <div data-slot="title" data-slot-type="text" data-slot-role="page-title"
       style="position:absolute;left:80px;top:200px;width:800px;height:100px;font-size:56px;border-radius:0px;">
    <span style="font-size:56px;color:#111111;">封面标题</span>
  </div>
  <div data-slot="hero" data-slot-type="image" data-slot-role="hero-image"
       style="position:absolute;left:1000px;top:100px;width:800px;height:800px;border-radius:8px;">
    <img src="../images/hero.png" alt="" />
  </div>
</div>
</body>
</html>
"""

MINIMAL_CONTENT = """<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <link rel="stylesheet" href="../theme.css" />
</head>
<body>
<div class="pptx-slide-root" style="position:relative;width:1920px;height:1080px;overflow:hidden;background:#ffffff;">
  <div data-slot="title" data-slot-type="text" data-slot-role="page-title"
       style="position:absolute;left:80px;top:60px;width:1600px;height:80px;">
    <span style="font-size:36px;color:#111111;">内容页</span>
  </div>
  <div data-slot="body" data-slot-type="text" data-slot-role="body"
       style="position:absolute;left:80px;top:200px;width:1600px;height:600px;">
    <span style="font-size:24px;color:#5c5c5c;">正文说明</span>
  </div>
  <svg width="100" height="100"><rect fill="#2563eb"/></svg>
</div>
</body>
</html>
"""

MINIMAL_CLOSING = """<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <link rel="stylesheet" href="../theme.css" />
</head>
<body>
<div class="pptx-slide-root" style="position:relative;width:1920px;height:1080px;overflow:hidden;background:#111111;">
  <div data-slot="thanks" data-slot-type="text" data-slot-role="page-title"
       style="position:absolute;left:200px;top:400px;width:1500px;height:120px;">
    <span style="font-size:64px;color:#ffffff;">谢谢</span>
  </div>
</div>
</body>
</html>
"""


def _write_pack(tmp: Path) -> Path:
    slides = tmp / "slides"
    images = tmp / "images"
    slides.mkdir(parents=True)
    images.mkdir(parents=True)
    (images / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    (tmp / "theme.css").write_text(
        ":root{--color-bg:#ffffff;--color-text:#111111;--color-accent:#2563eb;}\n",
        encoding="utf-8",
    )
    (slides / "cover.html").write_text(MINIMAL_COVER, encoding="utf-8")
    (slides / "content.html").write_text(MINIMAL_CONTENT, encoding="utf-8")
    (slides / "closing.html").write_text(MINIMAL_CLOSING, encoding="utf-8")
    (tmp / "template.json").write_text(
        """{
  "template_id": "vis-spec-pack",
  "label": {"zh_CN": "视觉规范测试", "en_US": "visual spec test"},
  "description": {"zh_CN": "三页测试包", "en_US": "3-page pack"},
  "format": "html-slide",
  "visual_spec_outline": "formal sharp blue",
  "files": {"theme_css": "theme.css", "slides_dir": "slides"},
  "slides": [
    {"file": "slides/cover.html", "title": "封面标题", "layout": "cover",
     "description": "封面；图 1"},
    {"file": "slides/content.html", "title": "内容页", "layout": "content",
     "description": "内容；图 0"},
    {"file": "slides/closing.html", "title": "谢谢", "layout": "closing",
     "description": "封底"}
  ]
}
""",
        encoding="utf-8",
    )
    return tmp


def test_pick_excerpt_indices() -> None:
    assert _pick_excerpt_indices(0) == []
    assert _pick_excerpt_indices(1) == [("cover", 0)]
    assert _pick_excerpt_indices(2) == [("cover", 0), ("closing", 1)]
    picks3 = _pick_excerpt_indices(3)
    assert [p[0] for p in picks3] == ["cover", "sample-content", "closing"]
    assert [p[1] for p in picks3] == [0, 1, 2]


def test_build_deck_context_reads_pages(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path)
    deck = build_deck_context(pack)

    assert deck["page_count"] == 3
    assert len(deck["pages"]) == 3
    assert len(deck["html_excerpts"]) == 3

    cover = deck["pages"][0]
    assert cover["file"] == "slides/cover.html"
    assert "hero.png" in cover["images"]
    roles = {s["role"] for s in cover["slots"]}
    assert "page-title" in roles
    assert "hero-image" in roles
    assert "#111111" in cover["colors"] or "#ffffff" in cover["colors"]

    content = deck["pages"][1]
    assert content["svg_n"] >= 1
    assert "page-title" in deck["slot_role_summary"]

    excerpt_files = {e["file"] for e in deck["html_excerpts"]}
    assert "slides/cover.html" in excerpt_files
    assert "slides/closing.html" in excerpt_files
    assert any("pptx-slide-root" in e["html"] for e in deck["html_excerpts"])

    assert "--color-accent" in deck["theme_css_excerpt"]
    # prompt payload should stay compact relative to full HTML dump
    total = sum(len(e["html"]) for e in deck["html_excerpts"])
    assert total < 12_000


def test_prompt_requires_grounding_in_pages() -> None:
    assert "HTML 指纹" in SYSTEM_VISUAL_SPEC
    assert "禁止凭空编造" in SYSTEM_VISUAL_SPEC
    user = user_visual_spec(deck_json='{"pages":[]}')
    assert "html_excerpts" in user
    assert "slot_role_summary" in user


def test_generate_visual_spec_mock_reads_pages(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path)
    out = generate_visual_spec(pack, mock=True)
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "Pages read" in text
    assert "slides/cover.html" in text
    assert "mock" in text.lower()
    meta = (pack / "template.json").read_text(encoding="utf-8")
    assert "visual-spec.md" in meta
