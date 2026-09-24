"""Regression tests for compact PPT Master authoring prompts."""

from __future__ import annotations

import json

import pytest

from ppt_master.pipeline import _resolve_slide_concurrency, _validate_plan

from ppt_master.prompts import (
    SYSTEM_PLAN,
    SYSTEM_SVG,
    SYSTEM_SVG_ADDON_PIXEL_ART,
    deck_authoring_context,
    system_plan_cached,
    system_svg_cached,
    system_svg_for,
    user_plan,
    user_plan_rewrite,
    user_svg,
    user_svg_fusion_followup,
    user_svg_repair_followup,
)


def _plan() -> dict:
    return {
        "template_id": "星河智能产品发布会",
        "label_zh": "星河智能产品发布会",
        "product": "NovaMind",
        "visual_style": "editorial",
        "mode": "showcase",
        "palette": {"bg": "#111111", "text": "#FFFFFF", "accent": "#FF5500"},
        "slides": [
            {
                "file": "01_cover.svg",
                "role": "cover",
                "title": "让复杂变得清晰",
                "core_message": "发布新一代智能工作台",
                "geometry": "full-bleed hero",
                "visual_hook": "oversized cropped title",
                "need_image": True,
                "image_role": "hero",
                "image_aspect": "16:9",
                "image_file": "01_cover.png",
            },
            {
                "file": "02_body.svg",
                "role": "content",
                "title": "三步完成协作",
                "core_message": "从输入到决策形成清晰路径",
                "geometry": "asymmetric path",
                "visual_hook": "numbered route",
                "need_image": False,
            },
        ],
    }


def test_deck_context_excludes_current_slide_but_keeps_rhythm() -> None:
    context = json.loads(deck_authoring_context(_plan(), current_file="01_cover.svg"))
    assert context["visual_style"] == "editorial"
    assert context["palette"]["accent"] == "#FF5500"
    assert [item["file"] for item in context["siblings"]] == ["02_body.svg"]
    assert "core_message" not in context["siblings"][0]


def test_svg_prompt_does_not_repeat_current_slide_in_deck_context() -> None:
    plan = _plan()
    prompt = user_svg(
        plan_json=json.dumps(plan, ensure_ascii=False, separators=(",", ":")),
        slide=plan["slides"][0],
        page_index=1,
        page_total=2,
        visual_style="editorial",
        prepared_image="01_cover.png",
        image_hint="editorial portrait of a product team",
    )
    assert '"file":"01_cover.svg"' in prompt
    assert '"file":"02_body.svg"' in prompt
    assert '"file":"01_cover.svg","role":"cover"' not in prompt
    assert "hero-img" in prompt
    assert "../images/01_cover.png" in prompt
    # Style card moved to system prefix for provider prompt cache.
    assert "## 强制视觉风格" not in prompt


def test_cache_prefixes_put_style_card_in_system() -> None:
    plan_sys = system_plan_cached("editorial")
    svg_sys = system_svg_cached("editorial")
    assert SYSTEM_PLAN[:40] in plan_sys
    assert "## 强制视觉风格" in plan_sys
    assert "## 强制视觉风格" in svg_sys
    assert "执行 layout_regions" in svg_sys
    # Variable user prompts must not duplicate the card.
    assert "## 强制视觉风格" not in user_plan(
        prompt="产品发布会",
        page_count=2,
        visual_style="editorial",
    )


def test_pixel_art_addon_is_conditional() -> None:
    assert "8×8" not in SYSTEM_SVG
    assert "8×8" not in system_svg_for("editorial")
    assert "8×8" in system_svg_for("pixel-art")
    assert SYSTEM_SVG_ADDON_PIXEL_ART.strip() in system_svg_for("pixel-art")


def test_fusion_and_repair_followups_are_compact() -> None:
    fusion = user_svg_fusion_followup(fusion_critique="缺少可见 <image>")
    repair = user_svg_repair_followup(issues=["[TEXT_TEXT_OVERLAP] a vs b"])
    assert "缺少可见" in fusion
    assert "TEXT_TEXT_OVERLAP" in repair
    assert "<svg" not in repair
    assert len(fusion) < 800
    assert len(repair) < 800


def test_slide_concurrency_defaults_and_cap() -> None:
    assert _resolve_slide_concurrency(None, 7) == 6
    assert _resolve_slide_concurrency(4, 7) == 4
    assert _resolve_slide_concurrency(99, 7) == 7
    assert _resolve_slide_concurrency(99, 20) == 8


def test_plan_rewrite_prompt_is_compact_and_has_critical_constraints() -> None:
    prompt = user_plan_rewrite(
        prompt="为 NovaMind 做一场面向企业客户的产品发布会",
        page_count=2,
        visual_style="editorial",
        plan=_plan(),
        critique="重复构图：full-bleed hero",
        enable_images=True,
    )
    assert "当前 Plan" in prompt
    assert "重复构图" in prompt
    assert "严格保持 2 页" in prompt
    assert "editorial" in prompt
    # The full style-card heading and long plan-only instructions are not resent.
    assert "## 强制视觉风格" not in prompt
    assert len(prompt) < 2400


def test_plan_and_svg_contract_include_layout_envelopes() -> None:
    assert "layout_regions" in SYSTEM_PLAN
    assert "padding" in SYSTEM_PLAN
    assert "clearance" in SYSTEM_PLAN
    assert "执行 layout_regions" in SYSTEM_SVG
    assert "禁止在文字之后绘制" in SYSTEM_SVG


def test_plan_validation_requires_non_overlapping_layout_regions() -> None:
    plan = _plan()
    for slide in plan["slides"]:
        slide["layout_regions"] = [
            {
                "id": "title",
                "role": "page-title",
                "bounds": [40, 40, 500, 100],
                "padding": [12, 12, 12, 12],
                "clearance": 12,
            },
            {
                "id": "body",
                "role": "body",
                "bounds": [40, 180, 1000, 400],
                "padding": [16, 16, 16, 16],
                "clearance": 16,
            },
        ]
    _validate_plan(plan, 2)

    plan["slides"][0]["layout_regions"][1]["bounds"] = [40, 120, 1000, 400]
    with pytest.raises(RuntimeError, match="clearance"):
        _validate_plan(plan, 2)


def test_repair_plan_layout_fixes_clearance_and_duplicate_footer() -> None:
    from ppt_master.pipeline import repair_plan_layout

    plan = _plan()
    for slide in plan["slides"]:
        slide["layout_regions"] = [
            {
                "id": "title",
                "role": "page-title",
                "bounds": [40, 40, 500, 100],
                "padding": [12, 12, 12, 12],
                "clearance": 12,
            },
            {
                "id": "body",
                "role": "body",
                "bounds": [40, 180, 1000, 400],
                "padding": [16, 16, 16, 16],
                "clearance": 16,
            },
        ]
    plan["slides"][0]["layout_regions"] = [
        {
            "id": "title",
            "role": "page-title",
            "bounds": [40, 40, 500, 100],
            "padding": [12, 12, 12, 12],
            "clearance": 12,
        },
        {
            "id": "body",
            "role": "body",
            "bounds": [40, 120, 1000, 400],
            "padding": [16, 16, 16, 16],
            "clearance": 16,
        },
        {
            "id": "footnote",
            "role": "footnote",
            "bounds": [40, 620, 600, 40],
            "padding": [4, 4, 4, 4],
            "clearance": 8,
        },
        {
            "id": "footer",
            "role": "footer",
            "bounds": [40, 625, 600, 40],
            "padding": [4, 4, 4, 4],
            "clearance": 8,
        },
    ]
    with pytest.raises(RuntimeError, match="clearance"):
        _validate_plan(plan, 2)

    repair_plan_layout(plan)
    _validate_plan(plan, 2)
    ids = {r["id"] for r in plan["slides"][0]["layout_regions"]}
    assert len(ids & {"footnote", "footer"}) == 1
