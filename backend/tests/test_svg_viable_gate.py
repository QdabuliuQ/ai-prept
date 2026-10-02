"""Empty / declaration-only SVG must not pass the authoring write gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from ppt_master.pipeline import (
    _MIN_AUTHORED_SVG_CHARS,
    _strip_svg,
    assert_svg_dir_viable,
    authored_svg_reject_reason,
    collect_nonviable_svgs,
)


MINIMAL_OK = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
    + ("<g>" + ("<rect x='0' y='0' width='10' height='10'/>" * 20) + "</g>")
    + "</svg>\n"
)


def test_strip_svg_empty_is_declaration_only() -> None:
    out = _strip_svg("")
    assert len(out.encode("utf-8")) == 39
    reason = authored_svg_reject_reason(out)
    assert reason in {"xml declaration only", "missing <svg> root"}


def test_strip_svg_empty_fence_rejected() -> None:
    out = _strip_svg("```\n```")
    assert authored_svg_reject_reason(out) is not None


def test_viable_minimal_ok() -> None:
    assert len(MINIMAL_OK) >= _MIN_AUTHORED_SVG_CHARS
    assert authored_svg_reject_reason(MINIMAL_OK) is None


def test_too_small_well_formed_rejected() -> None:
    tiny = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        "<rect/></svg>\n"
    )
    assert authored_svg_reject_reason(tiny) == f"too small ({len(tiny.strip())} chars)"


def test_collect_and_assert_svg_dir(tmp_path: Path) -> None:
    svg_dir = tmp_path / "svg_output"
    svg_dir.mkdir()
    (svg_dir / "01_ok.svg").write_text(MINIMAL_OK, encoding="utf-8")
    (svg_dir / "05_content2.svg").write_text(_strip_svg(""), encoding="utf-8")
    bad = collect_nonviable_svgs(svg_dir)
    assert any("05_content2.svg" in row for row in bad)
    assert not any("01_ok.svg" in row for row in bad)
    with pytest.raises(RuntimeError, match="empty/invalid SVG"):
        assert_svg_dir_viable(svg_dir, context="pre-export")
