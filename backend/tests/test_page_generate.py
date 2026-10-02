"""Tests for editor AI generate-page."""

from __future__ import annotations

import json
from pathlib import Path

from templates.page_generate import run_page_generate


MINIMAL_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <title>cover</title>
  <link rel="stylesheet" href="../theme.css" />
</head>
<body>
<div class="pptx-slide-root slide" style="position:relative;width:1920px;height:1080px;overflow:hidden;background:#111;">
  <div data-slot="title" data-slot-type="text" data-slot-role="page-title"
       style="position:absolute;left:80px;top:200px;width:800px;height:100px;">
    <span style="font-size:48pt;color:#fff;">原始标题</span>
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
    (tmp / "theme.css").write_text(":root{--bg:#111;--text:#fff;}\n", encoding="utf-8")
    (slides / "cover.html").write_text(MINIMAL_HTML, encoding="utf-8")
    (tmp / "template.json").write_text(
        """{
  "template_id": "test-pack",
  "public_id": "test-pack",
  "label": {"zh_CN": "测试包", "en_US": "test"},
  "visual_style": "editorial",
  "slides": [{"file": "slides/cover.html", "title": "原始标题", "layout": "cover"}]
}
""",
        encoding="utf-8",
    )
    return tmp


def test_mock_generate_appends_slide_and_meta(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path)
    row = run_page_generate(
        pack,
        issue="增加一页社区花园实践案例总结",
        after_file="slides/cover.html",
        mock=True,
    )
    assert row["ok"] is True
    assert str(row["file"]).startswith("slides/")
    assert (pack / row["file"]).is_file()
    html = (pack / row["file"]).read_text(encoding="utf-8")
    assert "page-generate mock" in html
    assert "theme.css" in html
    assert "1920" in html
    meta = json.loads((pack / "template.json").read_text(encoding="utf-8"))
    assert len(meta["slides"]) == 2
    assert meta["slides"][1]["file"] == row["file"]
    assert meta["last_page_generate"]["file"] == row["file"]
    assert row["insertAt"] == 1
