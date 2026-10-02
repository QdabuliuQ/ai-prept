"""Guards against default warm-cream palette skew."""

from __future__ import annotations

from ppt_master.prompts import SYSTEM_PLAN, SYSTEM_SVG
from ppt_master.styles import is_paper_warm_style, load_style_card


def test_is_paper_warm_style_known_ids() -> None:
    assert is_paper_warm_style("sketch-notes")
    assert is_paper_warm_style("kraft-folder-emboss")
    assert not is_paper_warm_style("dark-tech")
    assert not is_paper_warm_style("swiss-minimal")
    assert not is_paper_warm_style("gallery-white")


def test_load_style_card_bans_cream_for_non_paper() -> None:
    card = load_style_card("dark-tech")
    assert "warm-cream" in card or "#F4F1EA" in card
    assert "cool white" in card or "冷" in card or "Prefer cool" in card


def test_load_style_card_allows_paper_warm() -> None:
    card = load_style_card("sketch-notes")
    assert "warm paper" in card.lower() or "cream" in card.lower()
    assert "Hard ban on default warm-cream" not in card


def test_plan_prompt_mentions_cream_discipline() -> None:
    assert "米色" in SYSTEM_PLAN or "#F4F1EA" in SYSTEM_PLAN
    assert "奶油" in SYSTEM_SVG or "米色" in SYSTEM_SVG
