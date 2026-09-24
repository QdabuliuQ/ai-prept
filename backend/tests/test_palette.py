"""Palette refine: contrast gate + enable flag."""

from __future__ import annotations

from ppt_master.palette import (
    apply_palette_to_plan,
    contrast_ratio,
    parse_hex,
    palette_refine_enabled,
    refine_palette,
)


def test_palette_refine_enabled_default_off(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_PALETTE_REFINE", raising=False)
    assert palette_refine_enabled() is False
    assert palette_refine_enabled(None) is False
    assert palette_refine_enabled(True) is True
    assert palette_refine_enabled(False) is False


def test_palette_refine_enabled_env(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_PALETTE_REFINE", "1")
    assert palette_refine_enabled() is True
    monkeypatch.setenv("AGENT_PALETTE_REFINE", "0")
    assert palette_refine_enabled() is False


def test_refine_disabled_passthrough() -> None:
    raw = {"bg": "#111111", "text": "#222222", "accent": "#FF0000"}
    out, notes = refine_palette(raw, enabled=False)
    assert out == raw
    assert notes == []


def test_refine_lifts_low_contrast_text() -> None:
    # near-black text on near-black bg — must lift
    raw = {
        "bg": "#0A0A0A",
        "text": "#1A1A1A",
        "muted": "#2A2A2A",
        "accent": "#3DDCFF",
    }
    out, notes = refine_palette(raw, enabled=True)
    assert "enabled" in notes
    bg = parse_hex(out["bg"])
    text = parse_hex(out["text"])
    muted = parse_hex(out["muted"])
    assert bg and text and muted
    assert contrast_ratio(text, bg) >= 4.5
    assert contrast_ratio(muted, bg) >= 3.0
    assert out["accent"].upper() == "#3DDCFF" or contrast_ratio(
        parse_hex(out["accent"]) or (0, 0, 0), bg
    ) >= 2.5


def test_apply_palette_to_plan_mutates_when_on() -> None:
    plan = {
        "palette": {"bg": "#050505", "text": "#101010", "muted": "#151515"},
        "slides": [],
    }
    plan2, notes = apply_palette_to_plan(plan, enabled=True)
    assert plan2 is plan
    assert plan["palette"]["text"] != "#101010"
    assert any(n.startswith("text:") or n == "enabled" for n in notes)


def test_apply_palette_to_plan_off_keeps_raw() -> None:
    plan = {
        "palette": {"bg": "#050505", "text": "#101010"},
        "slides": [],
    }
    before = dict(plan["palette"])
    plan2, notes = apply_palette_to_plan(plan, enabled=False)
    assert plan2["palette"] == before
    assert notes == []


def test_refine_fills_missing_slots() -> None:
    out, notes = refine_palette({"bg": "#0B1020", "accent": "#5B8CFF"}, enabled=True)
    for key in ("bg", "panel", "text", "muted", "accent", "accent2"):
        assert key in out
        assert parse_hex(out[key]) is not None
    assert "enabled" in notes
