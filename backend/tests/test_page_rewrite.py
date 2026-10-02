"""Tests for in-place Admin page rewrite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from templates.page_rewrite import (
    SYSTEM_PAGE_REWRITE,
    build_user_prompt,
    extract_title_hint,
    list_image_files,
    run_page_rewrite,
    validate_rewritten_html,
)


MINIMAL_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <title>cover</title>
  <link rel="stylesheet" href="../theme.css" />
</head>
<body>
<div class="pptx-slide-root slide" style="position:relative;width:1920px;height:1080px;overflow:hidden;background:#111;">
  <div data-slot="title" data-slot-type="text" data-slot-role="page-title"
       style="position:absolute;left:80px;top:200px;width:800px;height:100px;">
    <span style="font-size:48pt;color:#fff;">原始标题</span>
  </div>
  <div data-slot="hero-image" data-slot-type="image" data-slot-role="hero-image"
       style="position:absolute;left:1000px;top:100px;width:800px;height:800px;">
    <img src="../images/hero.png" alt="" />
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
    (tmp / "theme.css").write_text(":root{--bg:#111;--text:#fff;}\n", encoding="utf-8")
    (slides / "cover.html").write_text(MINIMAL_HTML, encoding="utf-8")
    (tmp / "template.json").write_text(
        """{
  "template_id": "test-pack",
  "public_id": "test-pack",
  "label": {"zh_CN": "测试包", "en_US": "test"},
  "visual_style": "editorial",
  "slides": [{"file": "slides/cover.html", "title": "原始标题", "layout": "cover"}]
}
""",
        encoding="utf-8",
    )
    return tmp


def test_list_image_files_and_title() -> None:
    assert list_image_files(MINIMAL_HTML) == ["hero.png"]
    assert extract_title_hint(MINIMAL_HTML) == "原始标题"


def test_validate_rejects_foreign_image() -> None:
    bad = MINIMAL_HTML.replace("hero.png", "other.png")
    with pytest.raises(RuntimeError, match="未允许"):
        validate_rewritten_html(bad, allowed_images=["hero.png"])


def test_prompt_includes_issue_and_constraints() -> None:
    assert "theme.css" in SYSTEM_PAGE_REWRITE
    assert "1920" in SYSTEM_PAGE_REWRITE
    user = build_user_prompt(
        issue="标题太大挡住图片",
        slide_file="slides/cover.html",
        html=MINIMAL_HTML,
        theme_excerpt=":root{--bg:#111}",
        label="测试包",
        visual_style="editorial",
        siblings=["slides/02.html: 下一页"],
        images=["hero.png"],
        slot_texts=[{"slot": "title", "text": "原始标题"}],
        visual_spec_excerpt="",
    )
    assert "标题太大挡住图片" in user
    assert "hero.png" in user
    assert "editorial" in user


def test_mock_rewrite_writes_slide_and_meta(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path)
    row = run_page_rewrite(
        pack,
        slide_file="slides/cover.html",
        issue="标题与图片重叠，请拉开间距",
        mock=True,
    )
    assert row["ok"] is True
    assert row["file"] == "slides/cover.html"
    html = (pack / "slides" / "cover.html").read_text(encoding="utf-8")
    assert "page-rewrite mock" in html
    assert "拉开间距" in html
    assert not (pack / "slides" / "_rewrites").exists()
    meta = (pack / "template.json").read_text(encoding="utf-8")
    assert "last_page_rewrite" in meta
    assert "backup" not in json.loads(meta).get("last_page_rewrite", {})
