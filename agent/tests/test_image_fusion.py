"""Image / SVG fusion audit."""

from __future__ import annotations

from webppt_agent.ppt_master.image_fusion import (
    audit_svg_image_fusion,
    fusion_repair_brief,
)


def test_audit_requires_image_when_prepared() -> None:
    svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
  <rect id="bg" width="1280" height="720" fill="#FFF"/>
  <g id="t" data-pptx-bounds="40 40 400 80"><text x="40" y="80" font-size="32">Hi</text></g>
</svg>
"""
    issues = audit_svg_image_fusion(svg, prepared_image="01_cover.png")
    assert any("未引用" in x for x in issues)


def test_audit_accepts_visible_hero() -> None:
    svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
  <rect id="bg" width="1280" height="720" fill="#FFF" data-pptx-role="background"/>
  <image id="hero-img" href="../images/01_cover.png" x="0" y="0" width="1280" height="720"/>
  <rect id="bar" x="40" y="600" width="400" height="40" fill="#111" opacity="0.5"/>
  <g id="t" data-pptx-bounds="40 40 400 80"><text x="40" y="80" font-size="32">Title</text></g>
</svg>
"""
    assert audit_svg_image_fusion(svg, prepared_image="01_cover.png") == []


def test_audit_flags_heavy_overlay_and_circle_spam() -> None:
    circles = "\n".join(
        f'<circle cx="{i * 10}" cy="40" r="3" fill="#D00"/>' for i in range(60)
    )
    svg = f"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
  <image href="../images/01_cover.png" x="0" y="0" width="1280" height="720"/>
  <rect width="1280" height="720" fill="#111" opacity="0.4"/>
  {circles}
</svg>
"""
    issues = audit_svg_image_fusion(svg, prepared_image="01_cover.png")
    assert any("circle" in x for x in issues)
    assert any("遮罩" in x for x in issues)
    assert "融合校验失败" in fusion_repair_brief(issues)


def test_audit_flags_empty_text_page() -> None:
    svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
  <rect width="1280" height="720" fill="#EEE"/>
  <image href="../images/05_content.png" x="0" y="0" width="1280" height="720"/>
</svg>
"""
    issues = audit_svg_image_fusion(svg, prepared_image="05_content.png")
    assert any("<text>" in x for x in issues)
