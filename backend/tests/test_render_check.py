"""Browser-based render overflow check (optional dependency)."""

from __future__ import annotations

from pathlib import Path

from templates.render_check import check_package_render, find_browser

SIM = """<!DOCTYPE html><html><head><style>
html,body{margin:0}
.slide{position:relative;width:1920px;height:1080px;overflow:hidden}
</style></head><body>
<div class="pptx-slide-root slide">
  <div style="position:absolute;left:100px;top:100px;width:300px;height:80px;overflow:hidden">
    <div style="white-space:nowrap"><span style="font-size:24pt">%(text)s</span></div>
  </div>
</div>
</body></html>
"""


def _pack(tmp_path: Path, text: str) -> Path:
    pack = tmp_path / "pack"
    (pack / "slides").mkdir(parents=True)
    (pack / "slides" / "a.html").write_text(SIM % {"text": text}, encoding="utf-8")
    return pack


def test_check_package_render_without_slides(tmp_path) -> None:
    pack = tmp_path / "empty"
    pack.mkdir()
    result = check_package_render(pack)
    assert result["engine"] == "none"
    assert result["issues"] == []
    assert result["error"] == "no slides"


def test_find_browser_never_raises() -> None:
    found = find_browser()
    assert found is None or isinstance(found, str)


def test_render_check_finds_overflow_when_browser_available(tmp_path) -> None:
    """Geometry estimation passes here; only a real layout engine sees the clip."""
    if find_browser() is None:
        return
    pack = _pack(tmp_path, "这是一行明显超出三百像素宽度并且会被裁切的文案示例")
    result = check_package_render(pack, prefer="chrome")
    if result["engine"] == "none":
        return
    reasons = {i["reason"] for i in result["issues"]}
    assert reasons & {"clipped_horizontally", "text_wider_than_box"}


def test_render_check_clean_page_has_no_issues(tmp_path) -> None:
    if find_browser() is None:
        return
    pack = _pack(tmp_path, "短文案")
    result = check_package_render(pack, prefer="chrome")
    if result["engine"] == "none":
        return
    assert result["issues"] == []
