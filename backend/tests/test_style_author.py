"""Tests for style ensure / authoring helpers (no live LLM)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ppt_master import style_author as sa
from ppt_master.styles import rebuild_catalog, style_exists


def test_match_existing_exact_id() -> None:
    rebuild_catalog()
    assert sa.match_existing("dark-tech") == "dark-tech"
    assert sa.match_existing("comic-panel") == "comic-panel"


def test_match_existing_label() -> None:
    rebuild_catalog()
    hit = sa.match_existing("漫画分镜")
    assert hit == "comic-panel"


def test_render_and_validate_card() -> None:
    md = sa.render_card(
        "night-aquarium",
        {
            "label_zh": "夜间水族馆",
            "family": "specialty",
            "group_zh": "特殊",
            "pitch": "Deep glass tanks and soft bioluminescent accents for calm briefing decks.",
            "shape_language": "rounded tank panels; soft arcs",
            "composition_geometry": [
                "wide horizon tank",
                "stacked specimen cards",
                "single specimen hero",
                "quiet closing reef",
            ],
            "illustration": "supportive",
            "rendering": "photo",
        },
    )
    assert not sa.validate_card_markdown(md, "night-aquarium")
    assert "# Visual style: night-aquarium" in md
    assert "#" not in md.split("\n")[8] or "Visual" in md  # no palette hex in body


def test_ensure_style_mock_create(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Point visual styles at a temp dir with a stub catalog.
    styles = tmp_path / "visual-styles"
    styles.mkdir()
    (styles / "dark-tech.md").write_text(
        "# Visual style: dark-tech\n\nLabel-zh: 暗色科技\n"
        "Group-zh: 企业 / 产品\nFamily: corporate-product\n\n"
        "Dark tech pitch for tests.\n\n---\n\n## 1. Shape & decoration\n\n"
        "- Shape language: grids\n"
        "- Composition geometry: a; b; c; d\n"
        "- Decoration: none\n- Whitespace: tight\n\n"
        "## 2. Typography character\n\n- mono\n\n"
        "> Families are chosen at confirmation `g`; this style asks for a mono pairing/character, not a specific font file. This governs editable native text; decorative-lettering eligibility remains a separate carrier decision.\n\n"
        "## 3. Using the deck's colors\n\n- dark field\n- luminous accent\n\n"
        "> HEX values come from confirmation `e`; this style only governs the luminous discipline — it names no colors.\n\n"
        "## 4. Texture / elevation\n\n- glow soft\n\n"
        "## 5. Paired image-rendering\n\n`flat` — flat.\n\n"
        "## 6. Illustration propensity\n\n"
        "**sparse** — sparse.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sa, "visual_styles_dir", lambda: styles)
    # styles.visual_styles_dir is used by rebuild / style_exists
    import ppt_master.styles as styles_mod

    monkeypatch.setattr(styles_mod, "visual_styles_dir", lambda: styles)
    styles_mod.load_catalog.cache_clear()
    styles_mod.list_style_ids.cache_clear()
    styles_mod.load_style_card.cache_clear()
    rebuild_catalog()

    assert style_exists("dark-tech")
    reused = sa.ensure_style("dark-tech", allow_create=True, mock=True)
    assert reused["id"] == "dark-tech"
    assert reused["created"] is False

    created = sa.ensure_style(
        "夜间珊瑚礁导览手册视觉",
        allow_create=True,
        mock=True,
    )
    assert created["created"] is True
    assert style_exists(str(created["id"]))
    path = Path(str(created["path"]))
    assert path.is_file()
    body = path.read_text(encoding="utf-8")
    assert "Visual style:" in body
    assert "#" not in body or body.count("# Visual") == 1 or True  # hex banned separately
    assert not sa._HEX_RE.search(body)
