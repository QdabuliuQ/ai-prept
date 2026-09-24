"""Pack naming: content topic, not visual-style metaphor."""

from __future__ import annotations

from ppt_master.pipeline import (
    _plan_critique,
    _scrub_style_from_pack_name,
    _topic_hint_from_prompt,
)


def test_scrub_concert_stage_metaphor() -> None:
    out = _scrub_style_from_pack_name(
        "舞台灯光AI产品发布会",
        visual_style="concert-stage",
        prompt="虚构 AI 产品发布会：冲击力封面",
    )
    assert "舞台灯光" not in out
    assert "发布会" in out or "产品" in out


def test_scrub_keeps_token_when_prompt_is_about_it() -> None:
    out = _scrub_style_from_pack_name(
        "春日话剧首演手册",
        visual_style="concert-stage",
        prompt="春日话剧首演，需要舞台灯光氛围的手册",
    )
    # 话剧 is content; 舞台灯光 is in prompt as atmosphere — title itself ok
    assert "话剧" in out


def test_plan_critique_flags_style_title() -> None:
    issues = _plan_critique(
        {
            "label_zh": "代码编辑器AI发布会",
            "template_id": "代码编辑器AI发布会",
            "visual_style": "code-editor",
            "slides": [
                {"role": "cover", "geometry": "a", "visual_hook": "x"},
                {"role": "section", "geometry": "b", "visual_hook": "y"},
                {"role": "content", "geometry": "c", "visual_hook": "z"},
                {"role": "content", "geometry": "d", "visual_hook": "w"},
            ],
        },
        prompt="虚构 AI 产品发布会",
        visual_style="code-editor",
    )
    assert any("风格" in x or "书名" in x for x in issues)


def test_topic_hint_strips_style_clause() -> None:
    tip = _topic_hint_from_prompt(
        "虚构 AI 产品发布会：冲击力封面；风格=code-editor；禁止说明书式排版。"
    )
    assert "code-editor" not in tip
    assert "风格" not in tip


def test_resolve_drops_style_metaphor() -> None:
    from pathlib import Path
    from ppt_master.pipeline import _resolve_pack_name

    name = _resolve_pack_name(
        label_zh="舞台灯光AI产品发布会",
        template_id="",
        prompt="虚构 AI 产品发布会：冲击力封面",
        out_root=Path("/tmp/webppt-pack-naming-test"),
        visual_style="concert-stage",
    )
    assert "舞台灯光" not in name
    assert "发布会" in name
