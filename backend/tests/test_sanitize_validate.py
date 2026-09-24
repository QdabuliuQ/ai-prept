"""Sanitize + validate soft/hard issue classification."""

from __future__ import annotations

import re

from templates.sanitize import (
    count_data_element_missing_position,
    ensure_css_rules_position_absolute,
    ensure_data_element_position_absolute,
    sanitize_export_css,
)
from templates.validate import (
    audit_text_leaf_nesting,
    split_hard_soft_issues,
    validate_package_dir,
)


def test_sanitize_marks_divider_line():
    html = """
<div class="card">
  <!-- 分隔线 -->
  <div class="divider-line" style="width:100%; height:2px; background:#D4A017; opacity:0.5;"></div>
</div>
"""
    out = sanitize_export_css(html)
    assert 'data-element="shape"' in out.text
    assert 'data-shape-name="rect"' in out.text
    assert 'data-fill="#D4A017"' in out.text
    assert 'data-transparency="50"' in out.text
    assert any("分隔线补 data-element" in f for f in out.fixes)


def test_sanitize_css_rule_orphan_inset():
    html = """
<style>
.bento-card { position: absolute; }
.sticky-note { background: #fdf8ed; border-radius: 20px; }
.card-b { top: 220px; left: 760px; width: 360px; height: 250px; }
</style>
<div class="sticky-note card-b">note</div>
"""
    out = sanitize_export_css(html)
    # .card-b 应被补上 position:absolute
    assert re.search(
        r"\.card-b\s*\{[^}]*position\s*:\s*absolute",
        out.text,
        re.I | re.S,
    )
    assert any("position:absolute" in f for f in out.fixes)


def test_sanitize_inline_shell_orphan_inset():
    html = '<div class="panel" style="left:80px;top:64px;width:400px;height:200px;">x</div>'
    out = sanitize_export_css(html)
    assert "position:absolute" in out.text.replace(" ", "")


def test_sanitize_wash_gradient_and_multi_shadow():
    css = """
.slide {
  background: #f5f5dc;
  background-image: linear-gradient(175deg, rgba(255,255,255,0.4) 0%, rgba(230,230,210,0.2) 100%);
}
.node {
  box-shadow: 0 0 0 2px #6a0dad, 0 8px 18px rgba(106, 13, 173, 0.15);
}
.brand {
  background: linear-gradient(90deg, rgba(200,16,46,0.08) 0%, rgba(122,5,26,0.82) 100%);
}
"""
    out = sanitize_export_css(css)
    assert "rgba(255,255,255,0.4)" not in out.text.replace(" ", "")
    assert "background-image: none" in out.text.replace(" ", "").lower() or "none" in out.text
    assert "0 8px 18px" not in out.text
    assert "0 0 0 2px #6a0dad" in out.text or "0 0 0 2px #6A0DAD" in out.text
    assert "rgba(122,5,26,0.82)" in out.text.replace(" ", "")


def test_sanitize_strips_translate_vh_and_filter_blur():
    css = """
.x { transform: translateX(10px) rotate(-90deg); filter: blur(8px); width: 50vw; }
.y { filter: none; transform: rotate(15deg); }
@keyframes spin { from { opacity: 0 } to { opacity: 1 } }
"""
    out = sanitize_export_css(css)
    assert "translate" not in out.text.lower()
    assert "rotate(-90deg)" in out.text.replace(" ", "") or "rotate(-90deg)" in out.text
    assert "blur" not in out.text.lower()
    assert "filter: none" in out.text.lower() or "filter:none" in out.text.replace(" ", "").lower()
    assert "50vw" not in out.text
    assert "@keyframes" not in out.text.lower()


def test_padding_zero_not_structural_hard():
    from pathlib import Path
    import json
    import tempfile

    theme = """
html, body, .slide-container, .slide {
  width: 1920px; height: 1080px; margin: 0; padding: 0; overflow: hidden;
}
"""
    html = """<!doctype html><html><head>
<link rel="stylesheet" href="../theme.css"/>
<style>.x{backdrop-filter:none}</style></head>
<body><div class="slide slide-container layout-cover" style="width:1920px">
<img src="../images/cover-hero.png" width="1920" height="1080" alt="hero" style="width:1920px;height:1080px;object-fit:cover"/>
</div></body></html>
"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "slides").mkdir()
        (root / "theme.css").write_text(theme, encoding="utf-8")
        (root / "slides" / "cover.html").write_text(html, encoding="utf-8")
        meta = {
            "schema_version": "1.0",
            "template_id": root.name,
            "format": "html-slide",
            "label": {"zh_CN": "t", "en_US": "t"},
            "description": {"zh_CN": "", "en_US": ""},
            "files": {"theme_css": "theme.css", "slides_dir": "slides"},
            "slides": [
                {
                    "file": "slides/cover.html",
                    "title": "封面",
                    "layout": "cover",
                    "description": "d",
                }
            ],
            "source": {"canvas": {"width": 1920, "height": 1080}},
        }
        (root / "template.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        issues = validate_package_dir(root)
        hard, soft = split_hard_soft_issues(issues)
        assert not any("结构布局" in x for x in hard)
        assert not any("forbidden_css" in x for x in issues)
        assert hard == []


def test_sanitize_then_validate_clears_warns():
    from pathlib import Path
    import json
    import tempfile

    dirty_theme = """
.slide-container { width:1920px; height:1080px; padding: 64px; display:flex; }
.bg { background: radial-gradient(circle, #fff, #000); }
"""
    dirty_html = """<!doctype html><html><head>
<link rel="stylesheet" href="../theme.css"/>
<style>.x{backdrop-filter:blur(8px); clip-path:inset(0)}</style></head>
<body><div class="slide slide-container layout-cover" style="width:1920px">
<img src="../images/cover-hero.png" alt="hero" style="width:1920px;height:1080px;object-fit:cover"/>
</div></body></html>
"""
    clean_theme = sanitize_export_css(dirty_theme, is_theme=True).text
    clean_html = sanitize_export_css(dirty_html, is_theme=False).text
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "slides").mkdir()
        (root / "theme.css").write_text(clean_theme, encoding="utf-8")
        (root / "slides" / "cover.html").write_text(clean_html, encoding="utf-8")
        meta = {
            "schema_version": "1.0",
            "template_id": root.name,
            "format": "html-slide",
            "label": {"zh_CN": "t", "en_US": "t"},
            "description": {"zh_CN": "", "en_US": ""},
            "files": {"theme_css": "theme.css", "slides_dir": "slides"},
            "slides": [
                {
                    "file": "slides/cover.html",
                    "title": "封面",
                    "layout": "cover",
                    "description": "d",
                }
            ],
            "source": {"canvas": {"width": 1920, "height": 1080}},
        }
        (root / "template.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        hard, soft = split_hard_soft_issues(validate_package_dir(root))
        assert hard == []
        assert soft == []


def test_ensure_position_absolute_only_for_orphan_inset():
    """裸 inset 才补 absolute；壳内流式叶节点保持不动。"""
    html = """
<div data-element="text" data-z-index="20"
     style="left:260px;top:320px;font-size:120px;color:#F5F0E8;z-index:20;width:1400px;height:180px;">节庆文化</div>
<img data-element="image" data-z-index="1"
     src="../images/a.png" style="position:absolute;left:0;top:0;width:100px;height:100px;" />
<div data-element="shape" data-fill="#111" style="left:10px;top:10px;width:50px;height:50px;"></div>
<div data-element="text" data-z-index="30"
     style="width:100%;height:80px;font-size:48px;color:#1A1A1A;z-index:30;">壳内流式</div>
"""
    assert count_data_element_missing_position(html) == 2
    out, n = ensure_data_element_position_absolute(html)
    assert n == 2
    assert count_data_element_missing_position(out) == 0
    assert "position:absolute;left:260px" in out.replace(" ", "") or (
        "position:absolute;" in out and "left:260px" in out
    )
    # flow leaf unchanged (no forced absolute)
    assert 'style="width:100%;height:80px;font-size:48px;color:#1A1A1A;z-index:30;"' in out

    san = sanitize_export_css(html, is_theme=False)
    assert any("裸 inset" in f or "position:absolute" in f for f in san.fixes)
    assert count_data_element_missing_position(san.text) == 0


def test_flow_leaf_inside_shell_needs_no_absolute():
    html = """
<div style="position:absolute;left:80px;top:160px;width:800px;height:400px;display:flex;flex-direction:column;gap:16px;">
  <div data-element="text" data-z-index="30"
       style="width:100%;height:80px;font-size:48px;color:#111;z-index:30;">标题</div>
</div>
"""
    assert count_data_element_missing_position(html) == 0
    out, n = ensure_data_element_position_absolute(html)
    assert n == 0
    assert "position:absolute" not in out.split("data-element")[1]



def test_audit_text_leaf_nesting_warns_on_inner_span():
    bad = """
<div data-element="text" data-font-size="18" data-z-index="14"
     style="font-size:18px;z-index:14;width:auto;height:60px;">
  <span style="display:block;font-size:32px;">98.7%</span>
  准确率
</div>
"""
    issues = audit_text_leaf_nesting(bad, rel="pages/kpi.html")
    assert any("[visual-warn:text-nest]" in x for x in issues)
    assert any("[visual-warn:text-tag]" in x for x in issues)
    assert any("[visual-warn:deprecated-data]" in x for x in issues)
    hard, soft = split_hard_soft_issues(issues)
    assert hard == []
    assert soft


def test_audit_text_leaf_nesting_allows_plain_and_br():
    good = """
<span data-element="text"
      style="font-size:32px;line-height:1.2;color:#111;text-align:left;z-index:14;width:100%;">98.7%</span>
<span data-element="text"
      style="font-size:18px;line-height:1.4;color:#111;text-align:left;z-index:15;width:100%;">准确率<br>第二行</span>
"""
    assert audit_text_leaf_nesting(good, rel="pages/kpi.html") == []


def test_audit_text_leaf_warns_bad_line_height():
    bad = """
<span data-element="text"
      style="font-size:16px;line-height:22px;color:#111;width:100%;">x</span>
"""
    issues = audit_text_leaf_nesting(bad, rel="pages/a.html")
    assert any("[visual-warn:line-height]" in x for x in issues)


def test_scan_html_absolute_bounds_flags_right_overflow():
    from templates.validate import scan_html_absolute_bounds

    # 模拟截图：KPI 网格偏右，第三列被裁
    html = """
<div class="slide" style="position:relative;width:1920px;height:1080px;overflow:hidden;">
  <div style="position:absolute;left:900px;top:280px;width:1200px;height:640px;display:grid;gap:24px;">
    <div>card</div>
  </div>
</div>
"""
    issues = scan_html_absolute_bounds(html, "slides/kpi-row.html")
    assert any("[export:bounds]" in x and "右缘" in x for x in issues)
    hard, soft = split_hard_soft_issues(issues)
    assert hard
    assert soft == []


def test_scan_html_absolute_bounds_ok_inside_canvas():
    from templates.validate import scan_html_absolute_bounds

    html = """
<div style="position:absolute;left:80px;top:200px;width:1760px;height:720px;"></div>
"""
    assert scan_html_absolute_bounds(html, "slides/ok.html") == []


def test_scan_html_emoji_flags_chip_icons():
    from templates.validate import scan_html_emoji

    html = """
<div style="width:64px;height:64px;border-radius:50%;background:#333;">🌿</div>
<div>☀️</div>
"""
    issues = scan_html_emoji(html, "slides/timeline.html")
    assert any("[export:emoji]" in x for x in issues)
    hard, soft = split_hard_soft_issues(issues)
    assert hard
    assert soft == []


def test_scan_html_emoji_ignores_style_block():
    from templates.validate import scan_html_emoji

    html = "<style>/* 🌿 not real content */</style><div>正常中文</div>"
    assert scan_html_emoji(html, "slides/ok.html") == []


def test_scan_html_fa_icons_flags_webfont():
    from templates.validate import scan_html_fa_icons

    html = """
<div style="width:64px;height:64px;border-radius:50%;">
  <i class="fa-solid fa-heart" style="color:#fff;"></i>
</div>
"""
    issues = scan_html_fa_icons(html, "slides/pillars.html")
    assert any("[export:fa-icon]" in x for x in issues)
    hard, soft = split_hard_soft_issues(issues)
    assert hard
    assert soft == []
