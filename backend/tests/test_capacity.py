"""Template capacity contract: stable structure, field budgets, freshness."""

from __future__ import annotations

import json
from pathlib import Path

from templates.capacity import (
    CAPACITY_FILE,
    build_capacity_contract,
    capacity_status,
)
from templates.remix import normalize_structured_plan
from templates.slot_tree import split_composite_slots

from tests.test_remix import ROW_HTML


def _pack(tmp_path: Path, html: str = ROW_HTML) -> Path:
    root = tmp_path / "pack"
    (root / "slides").mkdir(parents=True)
    (root / "slides" / "content.html").write_text(html, encoding="utf-8")
    meta = {
        "template_id": "pack",
        "slides": [{"file": "slides/content.html", "title": "content"}],
    }
    (root / "template.json").write_text(
        json.dumps(meta, ensure_ascii=False),
        encoding="utf-8",
    )
    return root


def test_capacity_contract_has_rows_fields_and_is_fresh(tmp_path: Path) -> None:
    root = _pack(tmp_path)
    out, stats = split_composite_slots(ROW_HTML)
    assert stats["leaves"] == 6
    contract = build_capacity_contract(root)

    assert contract["status"] == "ready"
    assert contract["summary"]["text_slots"] == 6
    page = contract["pages"][0]
    first = page["slots"][0]
    assert first["group"] == "row"
    assert first["capacity"]["lines"][0]["field"] == "title"
    assert first["capacity"]["lines"][1]["field"] == "desc"
    assert all(
        line["max_chars"] > 0 for line in first["capacity"]["lines"]
    )
    assert (root / CAPACITY_FILE).is_file()
    assert capacity_status(root)["capacityStatus"] == "ready"

    # Copy writes change text nodes, not geometry/typography.
    (root / "slides" / "content.html").write_text(
        (root / "slides" / "content.html")
        .read_text(encoding="utf-8")
        .replace("军地需求双向清单", "新的第一项标题")
        .replace("建立街道与驻区部队需求双向清单", "新的第一项内容说明"),
        encoding="utf-8",
    )
    assert capacity_status(root)["capacityStatus"] == "ready"

    # Moving a box invalidates the contract.
    changed = out.replace("left: 114.06px", "left: 130px", 1)
    (root / "slides" / "content.html").write_text(changed, encoding="utf-8")
    assert capacity_status(root)["capacityStatus"] == "stale"


def test_structured_page_row_field_plan_flattens_to_slots() -> None:
    html, _ = split_composite_slots(ROW_HTML)
    from templates.remix import inventory_slide_slots

    slots = inventory_slide_slots(html, file="slides/content.html")
    plan = {
        "label_zh": "x",
        "pages": [
            {
                "file": "slides/content.html",
                "rows": [
                    {
                        "row": 1,
                        "slots": [
                            {
                                "slot": "body-3-1",
                                "fields": [
                                    {"field": "title", "text": "新标题"},
                                    {"field": "desc", "text": "新说明"},
                                ],
                            },
                            {
                                "slot": "body-3-2",
                                "fields": [
                                    {"field": "owner", "text": "责任：新部门"},
                                    {"field": "when", "text": "节点：2027年"},
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
    }
    flat = normalize_structured_plan(plan, slots)
    assert flat["texts"]["slides/content.html"]["body-3-1"] == "新标题\n新说明"
    assert (
        flat["texts"]["slides/content.html"]["body-3-2"]
        == "责任：新部门\n节点：2027年"
    )


def test_nested_percentage_slot_is_not_collapsed_to_one_char(tmp_path: Path) -> None:
    html = """
    <div class="pptx-slide-root" style="position:relative;width:1920px;height:1080px">
      <div style="position:absolute;left:100px;top:80px;width:420px;height:160px">
        <div style="position:absolute;left:20px;top:10px;width:100%;height:100%">
          <div data-slot="nested" data-slot-type="text" data-slot-role="heading"
               style="width:100%;height:100%;white-space:nowrap">
            <div style="font-size:24pt;line-height:1"><span>完整标题不会只剩一个字</span></div>
          </div>
        </div>
      </div>
    </div>
    """
    root = _pack(tmp_path, html)
    contract = build_capacity_contract(root)
    slot = contract["pages"][0]["slots"][0]
    assert contract["status"] == "ready"
    assert slot["bbox"] == {"width": 420.0, "height": 160.0}
    assert slot["capacity"]["max_chars"] > 1
    assert not [
        issue
        for issue in contract["issues"]
        if issue["code"] in {"missing_width", "missing_height"}
    ]


def test_zero_size_text_slot_requires_review(tmp_path: Path) -> None:
    html = """
    <div class="pptx-slide-root" style="position:relative;width:1920px;height:1080px">
      <div data-slot="broken" data-slot-type="text" style="width:0px;height:0px">
        <div style="font-size:20pt"><span>这段文字没有可测量的文本框</span></div>
      </div>
    </div>
    """
    root = _pack(tmp_path, html)
    contract = build_capacity_contract(root, repair_structure=False)
    assert contract["status"] == "review_required"
    codes = {issue["code"] for issue in contract["issues"]}
    assert "missing_width" in codes
