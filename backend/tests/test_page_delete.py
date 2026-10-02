"""Tests for editor AI delete-page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from templates.page_delete import run_page_delete


MINIMAL_HTML = """<!DOCTYPE html>
<html lang="zh"><head><link rel="stylesheet" href="../theme.css" /></head>
<body>
<div class="pptx-slide-root" style="width:1920px;height:1080px"></div>
</body></html>
"""


def _write_pack(tmp: Path, *, pages: int = 2) -> Path:
    slides = tmp / "slides"
    slides.mkdir(parents=True)
    (tmp / "theme.css").write_text(":root{}\n", encoding="utf-8")
    slide_meta = []
    for i in range(pages):
        name = f"p{i}.html"
        (slides / name).write_text(MINIMAL_HTML, encoding="utf-8")
        slide_meta.append({"file": f"slides/{name}", "title": f"P{i}", "layout": "content"})
    (tmp / "template.json").write_text(
        json.dumps(
            {
                "template_id": "pack",
                "public_id": "pack",
                "slides": slide_meta,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return tmp


def test_delete_page_removes_file_and_meta(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path, pages=2)
    row = run_page_delete(pack, page_index=0)
    assert row["ok"] is True
    assert row["file"] == "slides/p0.html"
    assert not (pack / "slides" / "p0.html").exists()
    assert (pack / "slides" / "p1.html").exists()
    meta = json.loads((pack / "template.json").read_text(encoding="utf-8"))
    assert len(meta["slides"]) == 1
    assert meta["slides"][0]["file"] == "slides/p1.html"
    assert row["activateFile"] == "slides/p1.html"


def test_delete_last_page_rejected(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path, pages=1)
    with pytest.raises(RuntimeError, match="至少保留"):
        run_page_delete(pack, page_index=0)
