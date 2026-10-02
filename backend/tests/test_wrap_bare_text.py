from __future__ import annotations

import unittest

from templates.normalize import normalize_slide_html, wrap_bare_text_runs


class WrapBareTextTest(unittest.TestCase):
    def test_wraps_bare_text_beside_span(self) -> None:
        html = '<div data-slot="title">的社区更新<span style="color:red">强调</span></div>'
        out = wrap_bare_text_runs(html)
        self.assertEqual(out.bare_text_fixes, 1)
        self.assertIn(
            '<span data-element="text">的社区更新</span>',
            out.html,
        )
        self.assertIn('<span style="color:red">强调</span>', out.html)

    def test_skips_pure_shell_without_bare_text(self) -> None:
        html = '<div data-slot="title"><span>只有强调</span></div>'
        out = wrap_bare_text_runs(html)
        self.assertEqual(out.bare_text_fixes, 0)
        self.assertEqual(out.html, html)

    def test_skips_inside_data_element_text(self) -> None:
        html = '<span data-element="text">前缀<em>坏嵌套</em></span>'
        out = wrap_bare_text_runs(html)
        self.assertEqual(out.bare_text_fixes, 0)
        self.assertEqual(out.html, html)

    def test_normalize_slide_html_includes_wrap(self) -> None:
        html = "<div>前缀<span>后缀</span></div>"
        out = normalize_slide_html(html)
        self.assertGreaterEqual(out.bare_text_fixes, 1)
        self.assertIn('data-element="text"', out.html)


if __name__ == "__main__":
    unittest.main()
