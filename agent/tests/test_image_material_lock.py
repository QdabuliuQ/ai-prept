"""Shared material lock keeps sibling image prompts in one suite."""

from __future__ import annotations

from webppt_agent.image.generate import (
    build_image_prompt,
    build_shared_material_lock,
    collect_local_images,
    extract_theme_colors,
    image_ref_prompt,
)


def test_collect_local_images_from_img_and_div():
    html = """
<img data-element="image" src="../images/cover-hero.png" alt="封面主视觉" />
<div data-element="image"
     data-sizing="cover"
     src="../images/tech-route.png"
     alt="数据流抽象图"
     style="position:absolute;inset:0;"></div>
<div data-element="image" data-src="../images/side.png" data-alt="侧栏"></div>
"""
    refs = collect_local_images([html])
    assert refs["cover-hero.png"] == "封面主视觉"
    assert refs["tech-route.png"] == "数据流抽象图"
    assert refs["side.png"] == "侧栏"


def test_extract_theme_colors_reads_roles():
    css = """
    :root {
      --bg: #E8DCC8;
      --surface: #F5EFE4;
      --primary: #8B4513;
      --ink: #2A2218;
    }
    """
    colors = extract_theme_colors(css)
    assert colors["bg"] == "#E8DCC8"
    assert colors["surface"] == "#F5EFE4"
    assert colors["primary"] == "#8B4513"
    assert colors["ink"] == "#2A2218"


def test_shared_lock_infers_ink_family():
    lock = build_shared_material_lock(
        style_hint="湖墨复盘 水墨年度数据",
        bg_hex="#E8DCC8",
        alts=["左上淡墨角饰", "右下浓墨角饰"],
        theme_colors={"bg": "#E8DCC8", "surface": "#F5EFE4", "ink": "#2A2218"},
    )
    assert "SHARED MATERIAL LOCK" in lock
    assert "#E8DCC8" in lock
    assert "ink-wash" in lock.lower() or "Xuan-paper" in lock


def test_sibling_prompts_share_identical_material_lock():
    lock = build_shared_material_lock(
        style_hint="水墨数据呈现",
        bg_hex="#E8DCC8",
        alts=[
            "与同页 wash 同套材质，左上淡墨角饰",
            "与同页 wash 同套材质，右下略浓墨角饰",
        ],
        theme_colors={"bg": "#E8DCC8"},
    )
    p_tl = build_image_prompt(
        filename="cover-corner-tl.png",
        alt="与同页 wash 同套材质，左上淡墨角饰",
        style_hint="水墨数据呈现",
        bg_hex="#E8DCC8",
        material_lock=lock,
        aspect="1:1",
    )
    p_br = build_image_prompt(
        filename="cover-corner-br.png",
        alt="与同页 wash 同套材质，右下略浓墨角饰",
        style_hint="水墨数据呈现",
        bg_hex="#E8DCC8",
        material_lock=lock,
        aspect="1:1",
    )
    assert p_tl.startswith(lock.strip())
    assert p_br.startswith(lock.strip())
    assert "corner companion" in p_tl.lower() or "Slot:" in p_tl
    assert "corner companion" in p_br.lower() or "Slot:" in p_br
    # 槽位职责不同，材质锁相同
    assert p_tl != p_br
    assert p_tl[: len(lock.strip())] == p_br[: len(lock.strip())]
    assert "Canvas aspect 1:1" in p_tl
    assert "letterboxing" in p_tl.lower() or "letterbox" in p_tl.lower()


def test_image_ref_prompt_adds_slide_safe_composition():
    prompt = image_ref_prompt(
        {
            "prompt": "young football players entering a stadium",
            "focal_region": "right-center",
            "copy_safe_region": "left 42%",
        }
    )
    assert "right-center" in prompt
    assert "left 42%" in prompt
    assert "editable slide copy" in prompt
