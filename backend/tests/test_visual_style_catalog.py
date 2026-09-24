"""Visual style catalog / path resolution."""

from __future__ import annotations

from ppt_master.styles import (
    assert_valid_style_id,
    load_catalog,
    load_style_card,
    rebuild_catalog,
    resolve_style_path,
    style_exists,
)


def test_catalog_lists_curated_styles() -> None:
    rebuild_catalog()
    data = load_catalog()
    assert int(data.get("count") or 0) >= 20
    ids = {s["id"] for s in data["styles"] if isinstance(s, dict)}
    assert "dark-tech" in ids
    assert "zine" in ids
    assert "readme" not in ids


def test_resolve_root_and_missing() -> None:
    assert style_exists("swiss-minimal")
    assert resolve_style_path("swiss-minimal") is not None
    assert resolve_style_path("definitely-not-a-style-xyz") is None


def test_assert_valid_style() -> None:
    assert assert_valid_style_id("nordic-calm") == "nordic-calm"
    try:
        assert_valid_style_id("no-such-style-zzz")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_load_style_card_contains_id() -> None:
    text = load_style_card("editorial")
    assert "visual_style id = editorial" in text
    assert "Shape" in text or "shape" in text.lower() or "Style reference" in text
