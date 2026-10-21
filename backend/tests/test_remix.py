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
    merge_remix_plans,
    missing_text_slots,
    parse_slot_box,
    remix_template_package,
    resolve_horizontal_slot_collisions,
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


def test_remix_plan_prompt_locks_image_palette() -> None:
    from templates.remix import _plan_content_once

    # Inspect prompt construction without calling LLM: reuse the user template
    # by importing the same constraint strings via a dry run of the f-string
    # builder path (monkeypatch chat_json).
    captured: dict[str, str] = {}

    def fake_chat_json(**kwargs):  # type: ignore[no-untyped-def]
        captured["system"] = kwargs.get("system") or ""
        captured["user"] = kwargs.get("user") or ""
        return {
            "label_zh": "x",
            "description_zh": "y",
            "texts": {"slides/a.html": {"title": "t"}},
            "images": {},
        }

    import templates.remix as remix_mod
    from unittest.mock import patch

    with patch("templates.remix.chat_json", side_effect=fake_chat_json), patch(
        "templates.remix.make_client_pool", return_value=object()
    ), patch("config.llm_config") as cfg:
        cfg.return_value.model = "mock"
        cfg.return_value.api_keys = ["k"]
        remix_mod._plan_content_once(
            prompt="新人培训",
            slots=[
                {
                    "file": "slides/a.html",
                    "slot": "hero",
                    "type": "image",
                    "role": "hero-image",
                    "current": "dark navy abstract wash",
                    "max_chars": 120,
                }
            ],
            source_label="深蓝模板",
            pages=[{"file": "slides/a.html", "title": "封面", "layout": "cover"}],
            visual_brief="## visual-spec.md\n深蓝暗色\n## theme.css\n--color-bg:#0B1220",
            log=None,
        )
    assert "配图色调" in captured["system"] or "visual-spec" in captured["system"]
    assert "配图色调" in captured["user"]
    assert "只改画面主体" in captured["user"] or "只写新主体" in captured["user"]


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
    # Hard cut must not leave a 1-char orphan second line
    assert clamp_text_to_max_chars("a\nbc\ndef", 4) == "a\nbc"
    assert clamp_text_to_max_chars("一二三四五六七\nABCDEF", 8) == "一二三四五六七"


def test_two_line_nowrap_title_keeps_second_line() -> None:
    """Multi-span column + nowrap must budget N lines (not collapse to 1)."""
    html = """<!DOCTYPE html><html><body>
<div class="pptx-slide-root" style="width:1920px;height:1080px;overflow:hidden">
  <div data-slot="title" data-slot-type="text" data-slot-role="page-title"
       style="position:absolute;left:123px;top:225px;width:514.5px;height:226.5px">
    <div style="width:100%;height:100%;display:flex;flex-direction:column;overflow:hidden;white-space:nowrap">
      <div style="line-height:76.5pt;font-size:60.75pt">
        <div style="height:76.5pt"><span style="font-size:60.75pt;letter-spacing:2.26pt">原标题第一行</span></div>
        <div style="height:76.5pt"><span style="font-size:60.75pt;letter-spacing:2.26pt">原标题第二行</span></div>
      </div>
    </div>
  </div>
</div>
</body></html>"""
    slots = inventory_slide_slots(html, file="slides/cover.html")
    title = next(s for s in slots if s["slot"] == "title")
    assert title["span_count"] == 2
    # Two visual rows → capacity roughly 2× single-line, not ≈ single-line.
    assert title["max_chars"] >= 12

    line1, line2 = "新主题标题甲乙", "新主题副行丙丁"
    out = apply_text_to_html(html, {"title": f"{line1}\n{line2}"}, fit=True)
    spans = re.findall(r"<span[^>]*>(.*?)</span>", out)
    assert spans[0] == line1
    assert spans[1] == line2


def test_apply_skips_blank_so_source_copy_survives() -> None:
    html = SAMPLE_HTML
    out = apply_text_to_html(html, {"title": "新标题", "subtitle": ""})
    assert "新标题" in out
    assert "原副标题一行" in out


def test_multi_span_keeps_meta_clears_extra_prose() -> None:
    html = """<!DOCTYPE html><html><body>
<div class="pptx-slide-root" style="width:1920px;height:1080px">
  <div data-slot="card-1" data-slot-type="text" data-slot-role="body"
       style="position:absolute;left:40px;top:100px;width:400px;height:120px">
    <span style="font-size:14pt">01</span>
    <span style="font-size:20pt">原标题</span>
    <span style="font-size:12pt">原说明文案</span>
    <span style="font-size:18pt">45%</span>
  </div>
</div>
</body></html>"""
    out = apply_text_to_html(html, {"card-1": "新要点"}, resolve_collisions=False)
    assert "新要点" in out
    # meta kept; extra prose cleared to avoid overlap with new primary text
    assert "01" in out
    assert "45%" in out
    assert "原说明文案" not in out
    assert "原标题" not in out


def test_multi_span_distributes_newlines() -> None:
    html = """<!DOCTYPE html><html><body>
<div data-slot="card-1" data-slot-type="text" data-slot-role="body"
     style="position:absolute;left:40px;top:100px;width:400px;height:120px">
  <span>01</span>
  <span>原标题</span>
  <span>原说明</span>
</div>
</body></html>"""
    out = apply_text_to_html(
        html, {"card-1": "02\n新标题\n新说明"}, resolve_collisions=False
    )
    assert "02" in out
    assert "新标题" in out
    assert "新说明" in out
    assert "原标题" not in out


def test_horizontal_collision_truncates_left_slot() -> None:
    html = """<!DOCTYPE html><html><body>
<div class="pptx-slide-root" style="width:1920px;height:1080px">
  <div data-slot="left-title" data-slot-type="text" data-slot-role="heading"
       style="position:absolute;left:100px;top:200px;width:600px;height:48px;white-space:nowrap">
    <span style="font-size:28pt">讲解之后还要继续服务到底</span>
  </div>
  <div data-slot="right-title" data-slot-type="text" data-slot-role="heading"
       style="position:absolute;left:420px;top:200px;width:200px;height:48px;white-space:nowrap">
    <span style="font-size:28pt">服务继续</span>
  </div>
</div>
</body></html>"""
    out = resolve_horizontal_slot_collisions(html)
    # left ink must not still contain the full overlong string
    assert "讲解之后还要继续服务到底" not in out
    assert "服务继续" in out
    assert "讲解" in out


def test_missing_text_slots_and_merge() -> None:
    slots = [
        {"file": "slides/a.html", "slot": "t1", "type": "text", "current": "A"},
        {"file": "slides/a.html", "slot": "t2", "type": "text", "current": "B"},
        {"file": "slides/a.html", "slot": "hero", "type": "image", "current": ""},
    ]
    plan = {
        "label_zh": "x",
        "texts": {"slides/a.html": {"t1": "新A", "t2": ""}},
    }
    miss = missing_text_slots(slots, plan)
    assert [s["slot"] for s in miss] == ["t2"]

    merged = merge_remix_plans(
        plan,
        {"texts": {"slides/a.html": {"t2": "新B", "t1": ""}}},
    )
    assert merged["texts"]["slides/a.html"]["t1"] == "新A"
    assert merged["texts"]["slides/a.html"]["t2"] == "新B"
    assert not missing_text_slots(slots, merged)

