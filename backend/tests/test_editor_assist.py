"""Tests for editor assist planner + image regen (P0/P1)."""

from __future__ import annotations

import json
from pathlib import Path

from templates.editor_plan import (
    OP_ADD,
    OP_DELETE,
    OP_MODIFY,
    OP_REGENERATE_IMAGE,
    heuristic_plan,
    wants_image_regen,
)
from templates.page_image_regen import run_page_image_regen


def _mini_pack(tmp: Path) -> Path:
    root = tmp / "pack"
    (root / "slides").mkdir(parents=True)
    (root / "images").mkdir(parents=True)
    # minimal png
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf"
        b"\xc0\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4\xef\x00\x00\x00\x00IEND"
        b"\xaeB`\x82"
    )
    (root / "images" / "cover-asset-1.png").write_bytes(png)
    html = """<!DOCTYPE html><html><head>
<link rel="stylesheet" href="../theme.css" />
</head><body>
<div class="pptx-slide-root" style="width:1920px;height:1080px;position:relative;overflow:hidden">
<img src="../images/cover-asset-1.png" alt="old" />
<div data-slot="title" data-slot-type="text"><span>标题</span></div>
</div></body></html>
"""
    (root / "slides" / "cover.html").write_text(html, encoding="utf-8")
    (root / "theme.css").write_text(":root{--bg:#fff;}", encoding="utf-8")
    meta = {
        "template_id": "pack",
        "public_id": "pack",
        "slides": [{"file": "slides/cover.html", "title": "封面"}],
    }
    (root / "template.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return root


def test_wants_image_regen():
    assert wants_image_regen("第一页的图片重新换一下，换成几个老年人")
    assert wants_image_regen("换一下配图")
    assert wants_image_regen("replace the image with a garden")
    assert not wants_image_regen("标题润色一下")


def test_heuristic_plan_image_defers_to_llm():
    # 换图意图留给 LLM 规划（填写纯画面 prompt），启发式不硬编码清洗
    plan = heuristic_plan(
        "第一页的图片重新换一下，换成几个老年人围着坐在一起，写实风格",
        page_count=3,
        page_index=0,
        current_file="slides/cover.html",
    )
    assert plan is None


def test_heuristic_plan_delete_and_rewrite():
    plan = heuristic_plan("删掉这一页", page_count=3, page_index=1)
    assert plan is not None
    assert plan["actions"][0]["op"] == OP_DELETE

    plan2 = heuristic_plan("标题太大挡住图片，缩小字号", page_count=2, page_index=0)
    assert plan2 is not None
    assert plan2["actions"][0]["op"] == OP_MODIFY


def test_heuristic_plan_generate():
    plan = heuristic_plan("新增一页社区花园案例", page_count=2, page_index=0)
    assert plan is not None
    assert plan["actions"][0]["op"] == OP_ADD


def test_plan_mock_image_includes_regen():
    from templates.editor_plan import plan_editor_actions

    plan = plan_editor_actions(
        "第一页的图片重新换一下，换成几个老年人围着坐在一起，写实风格",
        page_count=3,
        page_index=0,
        current_file="slides/cover.html",
        mock=True,
    )
    ops = [a["op"] for a in plan["actions"]]
    assert OP_REGENERATE_IMAGE in ops
    assert OP_MODIFY in ops


def test_run_page_image_regen_mock(tmp_path: Path):
    pack = _mini_pack(tmp_path)
    row = run_page_image_regen(
        pack,
        prompt="几个老年人围坐写实风格",
        slide_file="slides/cover.html",
        mock=True,
    )
    assert row["ok"] is True
    assert row["regeneratedImages"] == ["cover-asset-1.png"]
    html = (pack / "slides" / "cover.html").read_text(encoding="utf-8")
    assert "几个老年人" in html
    assert (pack / "images" / "cover-asset-1.png.mock.txt").is_file()


def test_build_regen_prompt_trusts_planner_subject():
    from image.generate import build_regen_image_prompt

    prompt = build_regen_image_prompt(
        subject="几个老年人围着坐在一起，写实风格",
        aspect="16:9",
        style_hint="老社区微改造居民参与行动册",
    )
    assert "几个老年人" in prompt
    assert "PRIMARY REQUIREMENT" in prompt
    assert "换一下" not in prompt
