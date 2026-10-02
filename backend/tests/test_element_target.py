"""Tests for selected-element target normalization."""

from templates.element_target import (
    format_target_for_prompt,
    image_filename_from_target,
    normalize_element_target,
)


def test_normalize_element_target_keeps_slot_fields():
    raw = {
        "selector": '[data-editor-eid="eid_1"]',
        "editorId": "eid_1",
        "tagName": "DIV",
        "isTextElement": True,
        "textContent": "  院中围坐  ",
        "dataSlot": "hero-caption",
        "dataSlotType": "text",
        "imageSrc": "../images/cover-asset-1.png?v=1",
        "junk": "<script>",
    }
    out = normalize_element_target(raw)
    assert out is not None
    assert out["editorId"] == "eid_1"
    assert out["tagName"] == "div"
    assert out["textContent"] == "院中围坐"
    assert out["dataSlot"] == "hero-caption"
    assert out["imageSrc"].startswith("../images/cover-asset-1.png")
    assert "junk" not in out


def test_image_filename_from_target():
    assert (
        image_filename_from_target({"imageSrc": "../images/cover-asset-1.png"})
        == "cover-asset-1.png"
    )


def test_format_target_for_prompt():
    text = format_target_for_prompt(
        {
            "dataSlot": "title",
            "isTextElement": True,
            "textContent": "自己动手",
        }
    )
    assert "data-slot: title" in text
    assert "自己动手" in text
