"""Tests for visual-spec generation that reads slide HTML."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from admin.providers import (
    llm_config_for_selection,
    list_vision_providers_public,
    resolve_vision_selection,
)
from config import LlmConfig, llm_vision_config
from llm import _normalize_chat_messages
from templates.prompts import (
    SYSTEM_PAGE_VISUAL_ANALYSIS,
    SYSTEM_VISUAL_SPEC,
    user_deck_visual_spec,
    user_page_visual_analysis,
    user_visual_spec,
)
from templates.visual_spec import (
    _analyze_page_with_vision,
    _page_records,
    _vision_user_content,
    build_deck_context,
    generate_visual_spec,
    overlap_candidates,
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
    assert "整页渲染预览" in SYSTEM_VISUAL_SPEC
    assert "完整 HTML" in SYSTEM_VISUAL_SPEC
    assert "文本关系" in SYSTEM_VISUAL_SPEC
    assert "禁止凭空编造" in SYSTEM_VISUAL_SPEC
    assert "配图色调" in SYSTEM_VISUAL_SPEC
    assert "禁止" in SYSTEM_VISUAL_SPEC and "题材" in SYSTEM_VISUAL_SPEC
    assert "主体完全跟用户新主题走" in SYSTEM_VISUAL_SPEC or "主体" in SYSTEM_VISUAL_SPEC
    assert "整页渲染预览" in SYSTEM_PAGE_VISUAL_ANALYSIS
    assert "完整 HTML" in SYSTEM_PAGE_VISUAL_ANALYSIS
    assert "linked-text-echo" in SYSTEM_PAGE_VISUAL_ANALYSIS
    user = user_visual_spec(deck_json='{"pages":[]}')
    assert "html_excerpts" in user
    assert "slot_role_summary" in user
    assert "配图色调" in user
    assert "样例内容" in user
    assert "内容锁" in user
    page_user = user_page_visual_analysis(
        page_context='{"full_html":"<html></html>"}',
        overlap_evidence="[]",
    )
    assert "完整 HTML" in page_user
    deck_user = user_deck_visual_spec(
        deck_json='{"theme_css":":root{}"}',
        page_analyses_json='{"text_relations":[]}',
    )
    assert "整页预览 + 完整 HTML" in deck_user
    assert "文本关系" in deck_user


def test_deck_context_omits_slot_sample_copy(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path)
    deck = build_deck_context(pack)
    assert "content_note" in deck
    cover = deck["pages"][0]
    assert cover.get("sample_title") == "封面标题"
    assert "title" not in cover or cover.get("title") is None
    for slot in cover["slots"]:
        assert "text" not in slot
        if slot.get("type") != "image" and slot.get("role") == "page-title":
            assert slot.get("text_chars", 0) > 0


def test_page_records_keep_full_html_and_complete_slot_copy(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path)
    deck = build_deck_context(pack)
    records = _page_records(pack, deck)

    assert len(records) == 3
    assert records[0]["html"] == MINIMAL_COVER
    assert any(
        slot.get("slot") == "title" and slot.get("current") == "封面标题"
        for slot in records[0]["slots"]
    )


def test_overlap_candidates_report_evidence_without_guessing_intent() -> None:
    html = MINIMAL_COVER.replace(
        '<div data-slot="hero"',
        """
  <div data-slot="title-echo" data-slot-type="text" data-slot-role="decorative"
       style="position:absolute;left:92px;top:209px;width:800px;height:100px;">
    <span style="font-size:56px;color:#111111;">封面标题</span>
  </div>
  <div data-slot="hero"
""",
        1,
    )
    rows = overlap_candidates(html, file="slides/cover.html")
    pair = next(
        row
        for row in rows
        if set(row["slots"]) == {"title", "title-echo"}
    )
    assert pair["same_text"] is True
    assert pair["overlap_ratio_of_smaller"] > 0.5
    assert pair["offset_px"] == {"x": 12.0, "y": 9.0}
    assert "kind" not in pair


def test_vision_user_message_contains_full_page_image(tmp_path: Path) -> None:
    image_path = tmp_path / "page.png"
    Image.new("RGB", (16, 9), "#ffffff").save(image_path)
    content = _vision_user_content(
        intro="整页预览",
        prompt="complete html evidence",
        image_paths=[image_path],
    )
    image_blocks = [
        block for block in content if block.get("type") == "image_url"
    ]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert any(
        block.get("type") == "text" and "complete html evidence" in block.get("text", "")
        for block in content
    )


def test_vision_config_can_select_workbuddy_vision_model(monkeypatch) -> None:
    monkeypatch.setenv("LLM_VISION_PROVIDER", "workbuddy")
    monkeypatch.setenv("LLM_VISION_MODEL", "glm-5v-turbo")
    monkeypatch.setenv("WORKBUDDY_API_KEY", "test-key")
    monkeypatch.setenv("WORKBUDDY_BASE_URL", "http://127.0.0.1:3000/v1")
    monkeypatch.delenv("LLM_VISION_API_KEY", raising=False)
    monkeypatch.delenv("LLM_VISION_API_KEYS", raising=False)

    cfg = llm_vision_config()
    assert cfg.base_url == "http://127.0.0.1:3000/v1"
    assert cfg.model == "glm-5v-turbo"
    assert cfg.api_keys == ("test-key",)


def test_multimodal_message_blocks_are_not_stringified() -> None:
    content = [
        {"type": "text", "text": "整页预览与完整 HTML"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,AA=="},
        },
    ]
    messages = _normalize_chat_messages(
        messages=[{"role": "user", "content": content}]
    )
    assert messages == [{"role": "user", "content": content}]


def test_page_analysis_sends_html_and_preview_together(
    tmp_path: Path, monkeypatch
) -> None:
    pack = _write_pack(tmp_path)
    deck = build_deck_context(pack)
    page = _page_records(pack, deck)[0]
    preview = tmp_path / "preview.png"
    Image.new("RGB", (16, 9), "#ffffff").save(preview)
    captured: dict = {}

    def fake_chat_json(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return {
            "file": "slides/cover.html",
            "page_role": "cover",
            "text_relations": [],
        }

    monkeypatch.setattr("templates.visual_spec.chat_json", fake_chat_json)
    cfg = LlmConfig(
        api_keys=("test",),
        base_url="https://example.test/v1",
        model="vision-test",
    )
    _analyze_page_with_vision(
        pool=object(),
        cfg=cfg,
        page=page,
        preview=preview,
    )

    user_content = captured["messages"][1]["content"]
    text = "\n".join(
        str(block.get("text") or "")
        for block in user_content
        if block.get("type") == "text"
    )
    assert "full_html" in text
    assert "封面标题" in text
    assert "icon" in text or "pptx-slide-root" in text
    assert any(block.get("type") == "image_url" for block in user_content)


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


def test_vision_model_catalog_and_selected_config(monkeypatch) -> None:
    monkeypatch.setenv("WORKBUDDY_API_KEY", "test-workbuddy-key")
    monkeypatch.setenv("WORKBUDDY_API_KEYS", "")
    monkeypatch.setenv("LLM_API_KEYS", "")
    monkeypatch.setenv("LLM_API_KEY", "")

    providers = list_vision_providers_public()
    workbuddy = next(p for p in providers if p["id"] == "workbuddy")

    assert [m["id"] for m in workbuddy["models"]] == ["glm-5v-turbo"]
    selection = resolve_vision_selection("workbuddy", "glm-5v-turbo")
    cfg = llm_config_for_selection(selection)

    assert selection["provider"] == "workbuddy"
    assert selection["model"] == "glm-5v-turbo"
    assert cfg.api_keys == ("test-workbuddy-key",)
    assert cfg.model == "glm-5v-turbo"
    assert cfg.base_url == selection["baseUrl"].rstrip("/")


def test_vision_model_selection_rejects_text_only_model() -> None:
    with pytest.raises(RuntimeError, match="视觉模型"):
        resolve_vision_selection("deepseek", "deepseek-v4-flash")
