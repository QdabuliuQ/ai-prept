"""Layout-preserving remix: text/image slots only."""

from __future__ import annotations

import json
from pathlib import Path

from webppt_agent.templates.remix import (
    apply_text_to_html,
    inventory_slide_slots,
    remix_template_package,
)


SAMPLE_HTML = """<!DOCTYPE html>
<html><body>
<div class="pptx-slide-root" style="width:1920px;height:1080px;background:#111">
  <div style="position:absolute;left:0;top:0;width:100px;height:100px">
    <svg><path d="M0,0 L10,0 L10,10 L0,10 Z" fill="#222"/></svg>
  </div>
  <div data-slot="title" data-slot-type="text" data-slot-role="page-title"
       style="position:absolute;left:100px;top:200px;width:800px;height:80px">
    <div><span style="font-size:40pt;color:#fff">原标题ABC</span></div>
  </div>
  <div data-slot="subtitle" data-slot-type="text" data-slot-role="lede"
       style="position:absolute;left:100px;top:300px;width:600px;height:60px">
    <div><span style="font-size:18pt;color:#aaa">原副标题一行</span></div>
  </div>
</div>
</body></html>
"""


def test_inventory_and_apply_preserves_geometry() -> None:
    slots = inventory_slide_slots(SAMPLE_HTML, file="slides/cover.html")
    assert {s["slot"] for s in slots} >= {"title", "subtitle"}
    assert all(s["type"] == "text" for s in slots)

    out = apply_text_to_html(
        SAMPLE_HTML, {"title": "新主题发布会", "subtitle": "聚焦健康监测"}
    )
    assert "新主题发布会" in out
    assert "聚焦健康监测" in out
    assert "原标题ABC" not in out
    # geometry / colors untouched
    assert 'width:1920px;height:1080px;background:#111' in out
    assert 'fill="#222"' in out
    assert 'left:100px;top:200px' in out
    assert 'data-slot="title"' in out


def test_remix_package_mock(tmp_path: Path) -> None:
    src = tmp_path / "源模板A"
    (src / "slides").mkdir(parents=True)
    (src / "images").mkdir()
    (src / "slides" / "cover.html").write_text(SAMPLE_HTML, encoding="utf-8")
    (src / "theme.css").write_text(":root{--color-bg:#111;}\n", encoding="utf-8")
    meta = {
        "schema_version": "1.0",
        "template_id": "源模板A",
        "format": "ppt-master",
        "label": {"zh_CN": "源模板A", "en_US": "A"},
        "description": {"zh_CN": "desc", "en_US": "desc"},
        "status": "approved",
        "files": {"theme_css": "theme.css", "slides_dir": "slides", "images_dir": "images"},
        "slides": [
            {
                "file": "slides/cover.html",
                "title": "原标题ABC",
                "layout": "cover",
                "description": "cover",
            }
        ],
    }
    (src / "template.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    out_root = tmp_path / "out"
    row = remix_template_package(
        src,
        prompt="智能穿戴新品发布会，强调轻量化",
        out_root=out_root,
        mock=True,
        skip_images=True,
        log=None,
    )
    assert row["ok"] is True
    dest = Path(row["output_dir"])
    assert dest.is_dir()
    html = (dest / "slides" / "cover.html").read_text(encoding="utf-8")
    assert "原标题ABC" not in html
    assert "原副标题一行" not in html
    assert "智能穿戴" in html
    # layout lock
    assert "background:#111" in html
    assert 'fill="#222"' in html
    theme = (dest / "theme.css").read_text(encoding="utf-8")
    assert "--color-bg:#111" in theme
    new_meta = json.loads((dest / "template.json").read_text(encoding="utf-8"))
    assert new_meta["status"] == "pending"
    assert new_meta["source_template_id"] == "源模板A"
    assert new_meta["remix"]["mode"] == "content-slots"
