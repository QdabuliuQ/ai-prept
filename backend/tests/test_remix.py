"""Layout-preserving remix: text/image slots only."""

from __future__ import annotations

import json
import re
from pathlib import Path

from templates.remix import (
    apply_text_to_html,
    clamp_text_to_max_chars,
    estimate_max_chars,
    fit_slot_inner,
    inventory_slide_slots,
    parse_slot_box,
    remix_template_package,
)


SAMPLE_HTML = """<!DOCTYPE html>
<html><body>
<div class="pptx-slide-root" style="width:1920px;height:1080px;background:#111">
  <div style="position:absolute;left:0;top:0;width:100px;height:100px">
    <svg><path d="M0,0 L10,0 L10,10 L0,10 Z" fill="#222"/></svg>
  </div>
  <div data-slot="title" data-slot-type="text" data-slot-role="page-title"
       style="position:absolute;left:100px;top:200px;width:800px;height:80px">
    <div><span style="font-size:40pt;color:#fff">原标题ABC</span></div>
  </div>
  <div data-slot="subtitle" data-slot-type="text" data-slot-role="lede"
       style="position:absolute;left:100px;top:300px;width:600px;height:60px">
    <div><span style="font-size:18pt;color:#aaa">原副标题一行</span></div>
  </div>
</div>
</body></html>
"""


def test_inventory_and_apply_preserves_geometry() -> None:
    slots = inventory_slide_slots(SAMPLE_HTML, file="slides/cover.html")
    assert {s["slot"] for s in slots} >= {"title", "subtitle"}
    assert all(s["type"] == "text" for s in slots)

    out = apply_text_to_html(
        SAMPLE_HTML, {"title": "新主题发布会", "subtitle": "聚焦健康监测"}
    )
    assert "新主题发布会" in out
    assert "聚焦健康监测" in out
    assert "原标题ABC" not in out
    # geometry / colors untouched
    assert 'width:1920px;height:1080px;background:#111' in out
    assert 'fill="#222"' in out
    assert 'left:100px;top:200px' in out
    assert 'data-slot="title"' in out


def test_remix_package_mock(tmp_path: Path) -> None:
    src = tmp_path / "源模板A"
    (src / "slides").mkdir(parents=True)
    (src / "images").mkdir()
    (src / "slides" / "cover.html").write_text(SAMPLE_HTML, encoding="utf-8")
    (src / "theme.css").write_text(":root{--color-bg:#111;}\n", encoding="utf-8")
    (src / "visual-spec.md").write_text(
        "# 视觉规范\n主色深灰，标题大字，副标题次级。\n",
        encoding="utf-8",
    )
    meta = {
        "schema_version": "1.0",
        "template_id": "源模板A",
        "format": "ppt-master",
        "label": {"zh_CN": "源模板A", "en_US": "A"},
        "description": {"zh_CN": "desc", "en_US": "desc"},
        "status": "approved",
        "files": {"theme_css": "theme.css", "slides_dir": "slides", "images_dir": "images"},
        "slides": [
            {
                "file": "slides/cover.html",
                "title": "原标题ABC",
                "layout": "cover",
                "description": "cover",
            }
        ],
    }
    (src / "template.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    out_root = tmp_path / "out"
    row = remix_template_package(
        src,
        prompt="智能穿戴新品发布会，强调轻量化",
        out_root=out_root,
        mock=True,
        skip_images=True,
        log=None,
    )
    assert row["ok"] is True
    dest = Path(row["output_dir"])
    assert dest.is_dir()
    html = (dest / "slides" / "cover.html").read_text(encoding="utf-8")
    assert "原标题ABC" not in html
    assert "原副标题一行" not in html
    assert "智能穿戴" in html
    # layout lock
    assert "background:#111" in html
    assert 'fill="#222"' in html
    theme = (dest / "theme.css").read_text(encoding="utf-8")
    assert "--color-bg:#111" in theme
    new_meta = json.loads((dest / "template.json").read_text(encoding="utf-8"))
    assert new_meta["status"] == "pending"
    assert new_meta["source_template_id"] == "源模板A"
    assert new_meta["remix"]["mode"] == "content-slots"


def test_remix_requires_visual_spec(tmp_path: Path) -> None:
    src = tmp_path / "无规范模板"
    (src / "slides").mkdir(parents=True)
    (src / "slides" / "cover.html").write_text(SAMPLE_HTML, encoding="utf-8")
    (src / "theme.css").write_text(":root{}\n", encoding="utf-8")
    meta = {
        "schema_version": "1.0",
        "template_id": "无规范模板",
        "format": "ppt-master",
        "label": {"zh_CN": "无规范模板", "en_US": "x"},
        "description": {"zh_CN": "", "en_US": ""},
        "status": "approved",
        "files": {"theme_css": "theme.css", "slides_dir": "slides"},
        "slides": [{"file": "slides/cover.html", "title": "t", "layout": "cover"}],
    }
    (src / "template.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        remix_template_package(
            src,
            prompt="随便改",
            out_root=tmp_path / "out",
            mock=True,
            skip_images=True,
        )
        raise AssertionError("expected RuntimeError for missing visual-spec")
    except RuntimeError as e:
        assert "visual-spec" in str(e)


def test_estimate_max_chars_prefers_box_over_soft_growth() -> None:
    attrs = 'data-slot="title" style="position:absolute;width:160px;height:40px"'
    content = (
        '<div style="overflow:hidden;white-space:nowrap">'
        '<span style="font-size:24pt">六个字标题</span></div>'
    )
    box = parse_slot_box(attrs, content)
    # 24pt ≈ 32px; 160/32 ≈ 5 CJK → box tighter than soft 6*1.1
    max_c = estimate_max_chars(current="六个字标题", role="page-title", box=box)
    assert max_c <= 6
    assert max_c >= 1


def test_apply_fits_long_title_by_shrink_or_truncate() -> None:
    html = """<!DOCTYPE html><html><body>
<div class="pptx-slide-root" style="width:1920px;height:1080px;overflow:hidden">
  <div data-slot="title" data-slot-type="text" data-slot-role="page-title"
       style="position:absolute;left:100px;top:200px;width:180px;height:48px">
    <div style="overflow:hidden;white-space:nowrap;width:180px;height:48px">
      <div style="font-size:28pt;line-height:1">
        <span style="font-size:28pt;letter-spacing:2pt">短标题</span>
      </div>
    </div>
  </div>
</div>
</body></html>"""
    slots = inventory_slide_slots(html, file="slides/x.html")
    title = next(s for s in slots if s["slot"] == "title")
    assert title["max_chars"] <= 8

    long = "这是非常非常长的新标题内容"
    out = apply_text_to_html(html, {"title": long}, fit=True)
    # geometry locked
    assert "width:180px;height:48px" in out
    assert 'data-slot="title"' in out
    # text present but not the full overflow string as-is without fit
    plain = re.sub(r"<[^>]+>", "", out)
    # either shrunk font below 28pt or truncated below original long length
    assert "这是非常非常长的新标题内容" not in plain or "font-size:19" in out or "font-size:20" in out
    # Must not keep original short title
    assert "短标题" not in out


def test_fit_slot_inner_shrinks_font() -> None:
    attrs = 'style="width:200px;height:50px"'
    content = (
        '<div style="overflow:hidden;white-space:nowrap;width:200px">'
        '<span style="font-size:36pt">abcdefghijklmnop</span></div>'
    )
    fitted, info = fit_slot_inner(attrs, content)
    assert info["scaled"] is True
    assert info["scale"] < 1.0
    assert "36pt" not in fitted


def test_clamp_text_to_max_chars() -> None:
    assert clamp_text_to_max_chars("一二三四五六", 4) == "一二三四"
    assert clamp_text_to_max_chars("a\nbc\ndef", 4) == "a\nbc\nd"

