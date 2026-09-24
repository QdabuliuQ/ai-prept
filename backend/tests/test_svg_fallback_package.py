"""SVG preview fallback package when pptx export fails."""

from __future__ import annotations

import json
from pathlib import Path

from ppt_master.pipeline import (
    _layout_from_svg_filename,
    _rewrite_svg_image_hrefs_for_package,
    _write_svg_fallback_package,
    _wrap_svg_as_slide_html,
)


class _Usage:
    def to_dict(self) -> dict:
        return {"page_tokens": 12, "image_tokens": 0, "image": {"images": 0}}


def test_layout_from_svg_filename() -> None:
    assert _layout_from_svg_filename("01_cover.svg") == "cover"
    assert _layout_from_svg_filename("02_toc.svg") == "toc"
    assert _layout_from_svg_filename("weird.svg") == "weird"


def test_rewrite_keeps_fragment_and_fixes_images() -> None:
    svg = (
        '<svg><use href="#icon"/><image href="images/a.png"/>'
        '<image xlink:href="../images/b.jpg"/></svg>'
    )
    out = _rewrite_svg_image_hrefs_for_package(svg)
    assert 'href="#icon"' in out
    assert 'href="../images/a.png"' in out
    assert 'xlink:href="../images/b.jpg"' in out


def test_wrap_svg_as_slide_html_sets_stage() -> None:
    html = _wrap_svg_as_slide_html(
        '<?xml version="1.0"?><svg viewBox="0 0 1280 720"><rect/></svg>'
    )
    assert "1920" in html and "1080" in html
    assert 'data-pptx-export-fallback="svg"' in html
    assert "<?xml" not in html


def test_write_svg_fallback_package(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    svg_dir = project / "svg_output"
    svg_dir.mkdir(parents=True)
    (project / "images").mkdir()
    (svg_dir / "01_cover.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
        '<rect width="10" height="10" fill="#000"/></svg>\n',
        encoding="utf-8",
    )
    (svg_dir / "02_toc.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
        '<text x="10" y="20">toc</text></svg>\n',
        encoding="utf-8",
    )
    out_root = tmp_path / "agent-output"
    pack = _write_svg_fallback_package(
        project,
        template_id="测试回退包",
        label_zh="测试回退包",
        out_root=out_root,
        slides=[{"title": "封面"}, {"title": "目录"}],
        export_error="marker fill mismatch",
        usage=_Usage(),
        log=None,
        palette={"bg": "#F5F2E9", "text": "#222"},
    )
    meta = json.loads((pack / "template.json").read_text(encoding="utf-8"))
    assert meta["status"] == "pending"
    assert meta["render"] == "svg-fallback"
    assert meta["template_id"] == "测试回退包"
    assert len(meta["slides"]) == 2
    assert any("export_fallback=svg" in w for w in meta["warnings"])
    assert (pack / "slides" / "cover.html").is_file()
    assert (pack / "slides" / "toc.html").is_file()
    assert "人工" in (meta.get("review") or {}).get("note", "")
