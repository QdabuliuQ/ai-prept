"""Layout-preserving remix: text/image slots only."""

from __future__ import annotations

import json
import re
from pathlib import Path

from templates.remix import (
    _compact_slot_row,
    _load_visual_brief,
    _plan_content_once,
    apply_text_to_html,
    clamp_text_to_max_chars,
    clamp_texts_for_slots,
    estimate_max_chars,
    fit_slot_inner,
    inventory_slide_slots,
    merge_remix_plans,
    missing_text_slots,
    parse_slot_box,
    remix_template_package,
    resolve_horizontal_slot_collisions,
    render_regressions,
    verify_slide_fit,
)
from templates.slot_tree import split_composite_slots


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


def test_remix_prompt_includes_complete_visual_brief() -> None:
    captured: dict[str, str] = {}

    def fake_chat_json(**kwargs):  # type: ignore[no-untyped-def]
        captured["user"] = kwargs.get("user") or ""
        return {
            "label_zh": "x",
            "description_zh": "y",
            "texts": {"slides/a.html": {"title": "t"}},
            "images": {},
        }

    from unittest.mock import patch

    tail = "尾部叠字组规则：title-3 与 title-4 必须使用相同文案。"
    visual_brief = "视觉规范开头\n" + ("背景说明" * 1200) + tail
    with patch("templates.remix.chat_json", side_effect=fake_chat_json), patch(
        "templates.remix.make_client_pool", return_value=object()
    ), patch("config.llm_config") as cfg:
        cfg.return_value.model = "mock"
        cfg.return_value.api_keys = ["k"]
        _plan_content_once(
            prompt="新人培训",
            slots=[
                {
                    "file": "slides/a.html",
                    "slot": "title",
                    "type": "text",
                    "role": "heading",
                    "current": "原标题",
                    "fields": ["title"],
                }
            ],
            source_label="测试模板",
            pages=[{"file": "slides/a.html", "title": "封面", "layout": "cover"}],
            visual_brief=visual_brief,
            log=None,
        )
    assert tail in captured["user"]


def test_visual_brief_reads_files_without_truncation(tmp_path: Path) -> None:
    spec_tail = "槽位尾部规则"
    theme_tail = "--tail-rule: keep;"
    long_spec = "# 规范\n" + ("规范正文" * 1200) + spec_tail
    long_theme = ":root {\n" + ("--unused: 1;\n" * 500) + theme_tail + "\n}"
    (tmp_path / "visual-spec.md").write_text(long_spec, encoding="utf-8")
    (tmp_path / "theme.css").write_text(long_theme, encoding="utf-8")

    brief = _load_visual_brief(tmp_path)
    assert spec_tail in brief
    assert theme_tail in brief


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


def test_leading_zero_index_slot_is_not_dynamic_copy() -> None:
    html = """<!DOCTYPE html><html><body>
<div class="pptx-slide-root" style="position:relative;width:1920px;height:1080px">
  <div data-slot="label" data-slot-type="text" data-slot-role="meta"
       style="position:absolute;left:50px;top:50px;width:80px;height:60px">
    <div style="font-size:24pt"><span>01</span></div>
  </div>
  <div data-slot="body" data-slot-type="text" data-slot-role="body"
       style="position:absolute;left:150px;top:50px;width:400px;height:60px">
    <div style="font-size:24pt"><span>正文</span></div>
  </div>
</div></body></html>"""
    slots = inventory_slide_slots(html, file="slides/a.html")
    assert [s["slot"] for s in slots] == ["body"]


# --- regression: composite row slots (图2 错位 + 出画) ---------------------

ROW_HTML = """<!DOCTYPE html><html><body>
<div class="pptx-slide-root slide" style="position: relative; width: 1920px; height: 1080px; overflow: hidden">
  <div data-slot="body-3" data-slot-type="text" data-slot-role="body"
       style="position: absolute; left: 184.8px; top: 292.275px; width: 1466.04px; height: 568.89px">
    <div style="position: absolute; left: 0px; top: 15.225px; width: 39.129px; height: 46.2px">
      <div style="display: flex; flex-direction: column; overflow: hidden; white-space: nowrap">
        <div style="line-height: 22.5pt; font-size: 22.5pt"><span style="font-size: 22.5pt">01</span></div>
      </div>
    </div>
    <div style="position: absolute; left: 114.06px; top: 0px; width: 485.28px; height: 73.89px">
      <div style="display: flex; flex-direction: column; overflow: hidden; white-space: nowrap">
        <div style="line-height: 22.5pt; font-size: 21.3pt"><span style="font-size: 21.3pt">军地需求双向清单</span></div>
        <div style="line-height: 22.5pt; font-size: 15.75pt"><span style="font-size: 15.75pt">建立街道与驻区部队需求双向清单</span></div>
      </div>
    </div>
    <div style="position: absolute; left: 1254.36px; top: 6.375px; width: 211.68px; height: 62.34px">
      <div style="display: flex; flex-direction: column; overflow: hidden; white-space: nowrap">
        <div style="line-height: 22.5pt; font-size: 15.75pt"><span style="font-size: 15.75pt">责任：街道人民武装部</span></div>
        <div style="line-height: 22.5pt; font-size: 15.75pt"><span style="font-size: 15.75pt">节点：2026年9月</span></div>
      </div>
    </div>
    <div style="position: absolute; left: 0px; top: 114.225px; width: 39.129px; height: 46.2px">
      <div style="display: flex; flex-direction: column; overflow: hidden; white-space: nowrap">
        <div style="line-height: 22.5pt; font-size: 22.5pt"><span style="font-size: 22.5pt">02</span></div>
      </div>
    </div>
    <div style="position: absolute; left: 114.06px; top: 99px; width: 443.28px; height: 73.89px">
      <div style="display: flex; flex-direction: column; overflow: hidden; white-space: nowrap">
        <div style="line-height: 22.5pt; font-size: 21.3pt"><span style="font-size: 21.3pt">社区国防教育角</span></div>
        <div style="line-height: 22.5pt; font-size: 15.75pt"><span style="font-size: 15.75pt">在三个社区试点共建教育角</span></div>
      </div>
    </div>
    <div style="position: absolute; left: 1254.36px; top: 105.375px; width: 211.68px; height: 62.34px">
      <div style="display: flex; flex-direction: column; overflow: hidden; white-space: nowrap">
        <div style="line-height: 22.5pt; font-size: 15.75pt"><span style="font-size: 15.75pt">责任：社区党建办公室</span></div>
        <div style="line-height: 22.5pt; font-size: 15.75pt"><span style="font-size: 15.75pt">节点：2026年10月</span></div>
      </div>
    </div>
    <div style="position: absolute; left: 0px; top: 213.225px; width: 39.129px; height: 46.2px">
      <div style="display: flex; flex-direction: column; overflow: hidden; white-space: nowrap">
        <div style="line-height: 22.5pt; font-size: 22.5pt"><span style="font-size: 22.5pt">03</span></div>
      </div>
    </div>
    <div style="position: absolute; left: 114.06px; top: 198px; width: 401.28px; height: 73.89px">
      <div style="display: flex; flex-direction: column; overflow: hidden; white-space: nowrap">
        <div style="line-height: 22.5pt; font-size: 21.3pt"><span style="font-size: 21.3pt">老兵议事会常态化</span></div>
        <div style="line-height: 22.5pt; font-size: 15.75pt"><span style="font-size: 15.75pt">每月一次进社区</span></div>
      </div>
    </div>
    <div style="position: absolute; left: 1254.36px; top: 204.375px; width: 211.68px; height: 62.34px">
      <div style="display: flex; flex-direction: column; overflow: hidden; white-space: nowrap">
        <div style="line-height: 22.5pt; font-size: 15.75pt"><span style="font-size: 15.75pt">责任：退役军人服务站</span></div>
        <div style="line-height: 22.5pt; font-size: 15.75pt"><span style="font-size: 15.75pt">节点：2026年8月起</span></div>
      </div>
    </div>
  </div>
</div>
</body></html>"""


def test_composite_slot_split_gives_row_and_field_metadata() -> None:
    """Every row field must be its own slot with row/col + per-line hints."""
    html, stats = split_composite_slots(ROW_HTML)
    assert stats["leaves"] == 6

    slots = inventory_slide_slots(html, file="slides/content-9.html")
    by_slot = {s["slot"]: s for s in slots}
    # Title/desc leaf and owner/when leaf of the same row share a row number.
    assert by_slot["body-3-1"]["row"] == by_slot["body-3-2"]["row"]
    assert by_slot["body-3-1"]["col"] < by_slot["body-3-2"]["col"]
    assert by_slot["body-3-1"]["fields"] == ["title", "desc"]
    assert by_slot["body-3-2"]["fields"] == ["owner", "when"]
    # Index column is layout, not copy: it is not offered to the planner.
    assert not any("01" == s["current"] for s in slots)

    compact = _compact_slot_row(by_slot["body-3-2"])
    assert compact["row"] == by_slot["body-3-2"]["row"]
    assert compact["lines"] == 2
    assert isinstance(compact["line_chars"], list)


def test_per_line_budget_keeps_realistic_copy_without_truncation() -> None:
    html, _ = split_composite_slots(ROW_HTML)
    slots = inventory_slide_slots(html, file="slides/content-9.html")
    by_slot = {s["slot"]: s for s in slots}
    row = by_slot["body-3-2"]
    plan = {
        "body-3-2": "责任：街道退役军人服务站\n节点：2026年12月",
        "body-3-1": "军地需求双向清单\n建立街道与驻区部队需求双向清单，每季度更新一次",
    }
    out = clamp_texts_for_slots(plan, slots)
    assert out["body-3-2"] == plan["body-3-2"]
    assert out["body-3-1"] == plan["body-3-1"]
    applied = apply_text_to_html(html, out)
    assert "责任：街道退役军人服务站" in applied
    assert "节点：2026年12月" in applied
    assert verify_slide_fit(applied, baseline=html) == []


def test_overlong_copy_is_fitted_inside_leaf_box_not_canvas() -> None:
    """图2: a whole row packed into one column must never escape the slide."""
    html, _ = split_composite_slots(ROW_HTML)
    slots = inventory_slide_slots(html, file="slides/content-9.html")
    long = "这是一个明显过长并且会越界的文案示例内容用来测试截断" * 4
    updates = {
        s["slot"]: "\n".join([long] * max(1, len(s.get("fields") or [])))
        for s in slots
    }
    out = apply_text_to_html(html, clamp_texts_for_slots(updates, slots))
    assert verify_slide_fit(out, baseline=html) == []
    # Text was fitted into the leaf, not left to spill across the slide.
    assert long not in out
    # Row geometry untouched.
    assert "left: 1254.36px" in out


def test_verify_slide_fit_reports_new_overflow_only() -> None:
    html, _ = split_composite_slots(ROW_HTML)
    clean = verify_slide_fit(html)
    assert clean == []

    broken = html.replace(
        "<span style=\"font-size: 15.75pt\">责任：街道人民武装部</span>",
        "<span style=\"font-size: 15.75pt\">"
        "责任：街道人民武装部并附带一长串根本装不下的说明文字</span>",
        1,
    )
    issues = verify_slide_fit(broken, baseline=html)
    assert [i["reason"] for i in issues] == ["ink_overflow"]


def test_relax_keeps_template_overflow_policy() -> None:
    """Fit now guarantees containment, so original overflow CSS must survive."""
    html, _ = split_composite_slots(ROW_HTML)
    out = apply_text_to_html(html, {"body-3-2": "责任：某某办公室\n节点：2027年1月"})
    assert "overflow: hidden" in out


def test_chunk_slots_by_page_respects_limits() -> None:
    from templates.remix import _chunk_slots_by_page

    pages = [{"file": f"slides/p{i}.html"} for i in range(6)]
    slots = [
        {"file": f"slides/p{i}.html", "slot": f"s{j}", "type": "text"}
        for i in range(6)
        for j in range(20)
    ]
    batches = _chunk_slots_by_page(slots, pages)
    assert len(batches) >= 3
    assert sum(len(b[0]) for b in batches) == len(slots)
    for batch_slots, batch_pages in batches:
        assert len(batch_slots) <= 55
        assert len(batch_pages) <= 3
    # Every page is planned in exactly one batch (no page split across batches).
    files = [s["file"] for b in batches for s in b[0]]
    assert set(files) == {p["file"] for p in pages}
    for f in set(files):
        assert files.count(f) == 20


def test_render_regressions_ignore_source_baseline_but_flag_worse_overflow() -> None:
    baseline = {
        "issues": [
            {
                "file": "slides/a.html",
                "slot": "subtitle",
                "reason": "clipped_horizontally",
                "text_right": 764,
                "clip_right": 760,
            }
        ]
    }
    same = {
        "issues": [
            {
                "file": "slides/a.html",
                "slot": "subtitle",
                "reason": "clipped_horizontally",
                "text_right": 765,
                "clip_right": 760,
            }
        ]
    }
    worse = {
        "issues": [
            {
                "file": "slides/a.html",
                "slot": "subtitle",
                "reason": "clipped_horizontally",
                "text_right": 800,
                "clip_right": 760,
            },
            {
                "file": "slides/a.html",
                "slot": "body",
                "reason": "out_of_canvas",
                "right": 1940,
                "bottom": 600,
            },
        ]
    }
    assert render_regressions(same, baseline) == []
    assert len(render_regressions(worse, baseline)) == 2
