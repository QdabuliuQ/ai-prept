"""Composite text slot splitting + absolute text measurement."""

from __future__ import annotations

from templates.slot_tree import (
    canvas_size,
    measure_slots,
    split_composite_slots,
    split_package_slots,
)

ROW_TOP = {1: 0, 2: 114.225, 3: 228.45}
ROW_LEFT_TOP = {1: 0, 2: 99, 3: 198}
ROW_RIGHT_TOP = {1: 6.375, 2: 105.375, 3: 204.375}


def _index_box(top: float, label: str) -> str:
    return (
        f'<div style="position: absolute; left: 0px; top: {top}px; '
        'width: 39.129px; height: 46.2px">'
        '<div style="display: flex; flex-direction: column; overflow: hidden; '
        'white-space: nowrap"><div style="line-height: 22.5pt; font-size: 22.5pt">'
        f'<span style="font-size: 22.5pt">{label}</span></div></div></div>'
    )


def _title_box(top: float, title: str, desc: str) -> str:
    return (
        f'<div style="position: absolute; left: 114.06px; top: {top}px; '
        'width: 485.28px; height: 73.89px">'
        '<div style="width: 100%; display: flex; flex-direction: column; '
        'overflow: hidden; white-space: nowrap">'
        '<div style="line-height: 22.5pt; font-size: 21.3pt">'
        f'<span style="font-size: 21.3pt; font-weight: bold">{title}</span></div>'
        '<div style="line-height: 22.5pt; font-size: 15.75pt">'
        f'<span style="font-size: 15.75pt">{desc}</span></div>'
        "</div></div>"
    )


def _meta_box(top: float, owner: str, when: str) -> str:
    return (
        f'<div style="position: absolute; left: 1254.36px; top: {top}px; '
        'width: 211.68px; height: 62.34px">'
        '<div style="width: 100%; display: flex; flex-direction: column; '
        'overflow: hidden; white-space: nowrap">'
        '<div style="line-height: 22.5pt; font-size: 15.75pt">'
        f'<span style="font-size: 15.75pt">{owner}</span></div>'
        '<div style="line-height: 22.5pt; font-size: 15.75pt">'
        f'<span style="font-size: 15.75pt">{when}</span></div>'
        "</div></div>"
    )


def _composite_html(rows: int = 3) -> str:
    data = [
        ("军地需求双向清单", "建立街道与驻区部队需求双向清单", "责任：街道人民武装部", "节点：2026年9月"),
        ("社区国防教育角", "在三个社区试点共建教育角", "责任：社区党建办公室", "节点：2026年10月"),
        ("老兵议事会常态化", "每月一次进社区", "责任：退役军人服务站", "节点：2026年8月起"),
        ("军属就业与就学帮扶", "军属就业一人一策", "责任：民生保障办公室", "节点：2026年12月"),
    ]
    boxes = []
    for i in range(rows):
        title, desc, owner, when = data[i]
        boxes.append(_index_box(ROW_TOP[i + 1], f"0{i + 1}"))
        boxes.append(_title_box(ROW_LEFT_TOP[i + 1], title, desc))
        boxes.append(_meta_box(ROW_RIGHT_TOP[i + 1], owner, when))
    return (
        "<!DOCTYPE html><html><body>\n"
        '<div class="pptx-slide-root slide" style="position: relative; width: 1920px; '
        'height: 1080px; overflow: hidden">\n'
        '<div data-slot="body-3" data-slot-type="text" data-slot-role="body" '
        'style="position: absolute; left: 184.8px; top: 292.275px; width: 1466.04px; '
        'height: 568.89px">'
        + "".join(boxes)
        + "</div></div></body></html>"
    )


COMPOSITE_HTML = _composite_html()


def test_split_composite_slots_creates_leaves_and_keeps_index_column() -> None:
    out, stats = split_composite_slots(COMPOSITE_HTML)
    assert stats["split"] == 1
    assert stats["leaves"] == 6
    assert stats["index_kept"] == 3

    # Parent container is no longer a slot, leaf nodes are.
    assert 'data-slot="body-3"' not in out
    for i in range(1, 7):
        assert f'data-slot="body-3-{i}"' in out
    # Index column stays static text so numbering remains layout, not copy.
    assert ">01<" in out and ">03<" in out
    assert 'data-slot="body-3-1"' in out


def test_split_composite_slots_is_idempotent() -> None:
    once, _ = split_composite_slots(COMPOSITE_HTML)
    twice, stats = split_composite_slots(once)
    assert twice == once
    assert stats["split"] == 0


def test_split_preserves_svg_attributes_verbatim() -> None:
    html = COMPOSITE_HTML.replace(
        'height: 568.89px">',
        'height: 568.89px"><svg viewBox="0 0 10 10"><path d="M0,0 L10,0"/></svg>',
        1,
    )
    assert 'viewBox="0 0 10 10"' in html
    out, _ = split_composite_slots(html)
    # Whole-page re-serialization would lowercase viewBox; string splicing must not.
    assert 'viewBox="0 0 10 10"' in out


def test_measure_slots_accumulates_absolute_offsets_and_lines() -> None:
    out, _ = split_composite_slots(COMPOSITE_HTML)
    boxes = measure_slots(out)
    leaf = boxes["body-3-2"]
    # leaf left/top are parent-relative; absolute offsets must be accumulated
    assert abs(leaf["x"] - (184.8 + 1254.36)) < 1.0
    assert abs(leaf["y"] - (292.275 + 6.375)) < 1.0
    assert leaf["width"] == 211.68
    assert [ln["text"] for ln in leaf["lines"]] == [
        "责任：街道人民武装部",
        "节点：2026年9月",
    ]
    assert leaf["nowrap"] is True
    # Inline spans inside one line wrapper must stay one visual line.
    title_box = boxes["body-3-1"]
    assert [ln["text"] for ln in title_box["lines"]] == [
        "军地需求双向清单",
        "建立街道与驻区部队需求双向清单",
    ]


def test_nested_slot_inherits_real_container_size() -> None:
    html = """
    <div class="pptx-slide-root" style="position:relative;width:1920px;height:1080px">
      <div style="position:absolute;left:100px;top:80px;width:420px;height:160px">
        <div style="position:absolute;left:20px;top:10px;width:100%;height:100%">
          <div data-slot="nested" data-slot-type="text"
               style="width:100%;height:100%;white-space:nowrap">
            <div style="font-size:24pt;line-height:1"><span>完整标题不会只剩一个字</span></div>
          </div>
        </div>
      </div>
    </div>
    """
    box = measure_slots(html)["nested"]
    assert box["x"] == 120
    assert box["y"] == 90
    assert box["width"] == 420
    assert box["height"] == 160
    assert box["lines"][0]["text"] == "完整标题不会只剩一个字"


def test_canvas_size_defaults_and_parses_root() -> None:
    assert canvas_size(COMPOSITE_HTML) == (1920.0, 1080.0)
    assert canvas_size("<html><body></body></html>") == (1920.0, 1080.0)


def test_split_package_slots_writes_only_changed_files(tmp_path) -> None:
    (tmp_path / "slides").mkdir()
    plain = '<div data-slot="t" data-slot-type="text"><span>x</span></div>'
    (tmp_path / "slides" / "a.html").write_text(plain, encoding="utf-8")
    (tmp_path / "slides" / "b.html").write_text(COMPOSITE_HTML, encoding="utf-8")
    stats = split_package_slots(tmp_path)
    assert stats["files"] == 1
    assert stats["leaves"] == 6
    assert (tmp_path / "slides" / "a.html").read_text(encoding="utf-8") == plain
    assert 'data-slot="body-3-1"' in (tmp_path / "slides" / "b.html").read_text(
        encoding="utf-8"
    )
