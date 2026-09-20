from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from webppt_agent.templates.normalize import (
    count_unsafe_rotated_text_wrappers,
    normalize_out_of_bounds_rotated_labels,
    normalize_rotated_text_wrappers,
    normalize_slide_html,
)
from webppt_agent.templates.types import SlideSpec, TemplatePackage
from webppt_agent.templates.validate import validate_package_dir
from webppt_agent.templates.write import write_package


SIMPLE_UNSAFE = """<!DOCTYPE html>
<html><head><link rel="stylesheet" href="../theme.css" /></head><body>
<div class="slide slide-container" style="width:1920px;height:1080px">
  <div data-slot="side-label" style="transform:rotate(-90deg);display:flex">
    <span style="font-size:20px;color:#000">编辑时间线</span>
  </div>
</div>
</body></html>
"""

EDGE_ROTATE_OOB = """<!DOCTYPE html>
<html><head><link rel="stylesheet" href="../theme.css" /></head><body>
<div class="slide slide-container" style="width:1920px;height:1080px;overflow:hidden;position:relative">
  <div data-slot="vertical-note" style="position:absolute; right: 28px; bottom: 32px; transform: rotate(-90deg); transform-origin: right bottom; font-size: 20px; color: #FFFFFF; white-space: nowrap;">规划总览 · 2025</div>
</div>
</body></html>
"""


class RotatedTextNormalizeTest(unittest.TestCase):
    def test_flattens_simple_rotated_text_wrapper(self) -> None:
        self.assertEqual(count_unsafe_rotated_text_wrappers(SIMPLE_UNSAFE), 1)
        result = normalize_rotated_text_wrappers(SIMPLE_UNSAFE)
        self.assertEqual(result.rotated_text_fixes, 1)
        self.assertNotIn("<span", result.html)
        self.assertIn("transform:rotate(-90deg)", result.html)
        self.assertIn("font-size:20px", result.html)
        self.assertEqual(count_unsafe_rotated_text_wrappers(result.html), 0)

    def test_detects_complex_wrapper_that_is_not_auto_fixed(self) -> None:
        html = """
        <div style="display:grid;transform:rotate(-90deg)">
          <span data-role="label"><strong>复杂文字</strong></span>
        </div>
        """
        result = normalize_rotated_text_wrappers(html)
        self.assertEqual(result.rotated_text_fixes, 0)
        self.assertEqual(count_unsafe_rotated_text_wrappers(result.html), 1)

    def test_rewrites_bottom_rotate_edge_label_to_writing_mode(self) -> None:
        result = normalize_out_of_bounds_rotated_labels(EDGE_ROTATE_OOB)
        self.assertEqual(result.bounds_fixes, 1)
        self.assertNotIn("rotate(-90deg)", result.html.lower().replace(" ", ""))
        self.assertIn("writing-mode: vertical-rl", result.html)
        self.assertIn("bottom: 64px", result.html)

    def test_write_package_auto_fixes_and_records_warning(self) -> None:
        package = TemplatePackage(
            template_id="ppt-rotate-test",
            label_zh="旋转测试",
            label_en="Rotate Test",
            description_zh="测试",
            description_en="Test",
            visual_spec="",
            visual_spec_outline="测试 outline",
            theme_css=(
                "html,body,.slide-container{width:1920px;height:1080px;"
                "overflow:hidden;box-sizing:border-box;}"
            ),
            slides=[
                SlideSpec(
                    layout="timeline",
                    title="时间线",
                    description="旋转文字测试",
                    html=SIMPLE_UNSAFE,
                ),
                SlideSpec(
                    layout="cover",
                    title="封面",
                    description="越界竖排",
                    html=EDGE_ROTATE_OOB,
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ppt-rotate-test"
            write_package(package, root)
            cover = (root / "slides" / "cover.html").read_text(encoding="utf-8")
            meta = json.loads((root / "template.json").read_text(encoding="utf-8"))
            self.assertIn("writing-mode: vertical-rl", cover)
            self.assertTrue(
                any("旋转文字容器" in warning for warning in meta["warnings"])
            )
            self.assertTrue(
                any("writing-mode" in warning for warning in meta["warnings"])
            )
            # smoke: pipeline helper
            bundled = normalize_slide_html(EDGE_ROTATE_OOB)
            self.assertGreaterEqual(bundled.bounds_fixes, 1)
            self.assertEqual(validate_package_dir(root), [])


if __name__ == "__main__":
    unittest.main()
