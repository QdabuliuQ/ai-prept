from webppt_agent.ppt_master.sanitize import (
    generation_compatibility_issues,
    repair_layout_issues,
    sanitize_svg_text,
    shrink_overlapping_bounds,
)


def test_sanitize_removes_non_positive_dash_gap():
    raw = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
      <path id="arrow" d="M0 0 L100 100" stroke="#000000" fill="none" stroke-dasharray="1 0"/>
    </svg>'''
    out = sanitize_svg_text(raw)
    assert 'stroke-dasharray="1 0"' not in out


def test_sanitize_removes_transforms_inside_pattern():
    raw = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
      <defs><pattern id="stripe" width="12" height="12">
        <rect x="0" y="0" width="6" height="12" transform="rotate(45 3 6)"/>
      </pattern></defs>
      <rect id="bg" width="1280" height="720" fill="url(#stripe)"/>
    </svg>'''
    out = sanitize_svg_text(raw)
    assert 'transform="rotate(45 3 6)"' not in out


def test_generation_compatibility_reports_native_export_blockers():
    raw = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
      <defs><pattern id="stripe" width="12" height="12" patternTransform="rotate(10)">
        <rect width="6" height="12" transform="rotate(45)"/>
      </pattern></defs>
      <path d="M0 0 L100 100" stroke="#000" stroke-dasharray="1 0"/>
    </svg>'''
    issues = generation_compatibility_issues(raw)
    assert any("pattern" in item for item in issues)
    assert any("dasharray" in item for item in issues)


def test_layout_repair_moves_crossing_line() -> None:
    raw = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
      <g id="title" data-pptx-bounds="40 40 400 80"><text id="title-text" x="60" y="90" font-size="32">标题</text></g>
      <line id="rule" x1="50" y1="75" x2="200" y2="75" stroke="#000000" stroke-width="4"/>
    </svg>'''
    out = repair_layout_issues(
        raw,
        ['[TEXT_SHAPE_OCCLUSION] shape-id="rule" text-owner="title" crosses '
         '<text id="title-text"> by 100px x 4px; suggest-shape-dx=0.0 '
         'suggest-shape-dy=30.0 move the decoration'],
    )
    assert 'transform="translate(0 30)"' in out


def test_layout_repair_moves_occluding_shape_behind_text_module() -> None:
    raw = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
      <g id="title" data-pptx-bounds="40 40 400 80"><text id="title-text" x="60" y="90" font-size="32">标题</text></g>
      <rect id="cover" x="50" y="50" width="200" height="60" fill="#FFFFFF"/>
    </svg>'''
    out = repair_layout_issues(
        raw,
        ['[TEXT_SHAPE_OCCLUSION] shape-id="cover" text-owner="title" is painted after'],
    )
    assert out.index('id="cover"') < out.index('id="title"')


def test_bounds_overlap_repair_moves_real_module_and_metadata() -> None:
    raw = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
      <g id="a" data-pptx-bounds="40 40 400 100"><text x="60" y="90">A</text></g>
      <g id="b" data-pptx-bounds="40 120 400 100"><text x="60" y="170">B</text></g>
    </svg>'''
    out = shrink_overlapping_bounds(
        raw,
        ['<g id="a"> data-pptx-bounds overlaps <g id="b"> data-pptx-bounds'],
    )
    assert 'transform="translate(0 32)"' in out
    assert 'data-pptx-bounds="40 152 400 100"' in out
