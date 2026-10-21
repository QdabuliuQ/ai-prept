"""Shared material lock keeps sibling image prompts in one suite."""

from __future__ import annotations

from image.generate import (
    build_image_prompt,
    build_shared_material_lock,
    collect_local_images,
    extract_image_color_brief,
    extract_palette_from_visual_spec,
    extract_theme_colors,
    image_ref_prompt,
    is_dark_hex,
    resolve_image_theme_colors,
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


def test_extract_theme_colors_reads_color_prefixed_vars():
    css = ":root{--color-bg:#0B1220;--color-accent:#3D7EFF;--color-text:#E8EEF8;}"
    colors = extract_theme_colors(css)
    assert colors["bg"] == "#0B1220"
    assert colors["primary"] == "#3D7EFF"
    assert colors["ink"] == "#E8EEF8"


def test_extract_image_color_brief_prefers_配图色调_section():
    md = """# Spec
## 色板
- bg #0B1220
## 配图色调
- 明暗：偏暗深蓝
- 内容可换，色调不可换
- 避免：大面积亮白纸面
## 组件
- 卡片
"""
    brief = extract_image_color_brief(md)
    assert "偏暗深蓝" in brief
    assert "亮白纸面" in brief
    assert brief.index("配图色调") < brief.index("色板")
    assert "卡片" not in brief


def test_resolve_image_theme_colors_prefers_visual_spec_over_white_theme_stub():
    """PPTX convert theme.css is often #fff; real deck colors live in visual-spec."""
    theme_css = ":root{--color-bg:#ffffff;--color-accent:#2563eb;--color-text:#111111;}"
    spec = """
## 2. 色板
### 2.1 实际页面用色
| 角色 | 色值 |
| 页面底色（深空） | `rgb(13,18,32)` / `#0D1220` |
| 主强调（金） | `#D8A63C` |
| 浅纸色 / 前景文字 | `#EFE9DA` |
| 深蓝面 | `#2A3550` |
## 10. 配图色调
- 明暗倾向：偏暗。页面底色为深空 `#0D1220`
- 避免：大面积亮白/米色纸面
"""
    colors = resolve_image_theme_colors(theme_css, spec)
    assert colors["bg"].upper() == "#0D1220"
    assert colors["primary"].upper() == "#D8A63C"
    assert colors["ink"].upper() == "#EFE9DA"
    assert colors["surface"].upper() == "#2A3550"
    parsed = extract_palette_from_visual_spec(spec)
    assert parsed["bg"].upper() == "#0D1220"


def test_material_lock_follows_visual_spec_not_hardcoded_dark_ban():
    assert is_dark_hex("#0B1220")
    brief = "明暗偏暗；忌大面积亮白底"
    lock = build_shared_material_lock(
        style_hint="深蓝暗色科技",
        bg_hex="#0B1220",
        alts=["新人培训流程封面插图"],
        theme_colors={
            "bg": "#0B1220",
            "surface": "#111827",
            "primary": "#3D7EFF",
            "ink": "#E5E7EB",
        },
        palette_brief=brief,
    )
    assert "TEMPLATE COLOR KEY" in lock
    assert "DARK DECK LOCK" not in lock
    assert brief in lock
    prompt = build_image_prompt(
        filename="cover-hero.png",
        alt="seven-day onboarding workflow desk mockup",
        style_hint="深蓝暗色科技",
        bg_hex="#0B1220",
        material_lock=lock,
        aspect="16:9",
        palette_brief=brief,
    )
    assert "TEMPLATE COLOR KEY" in prompt
    assert "#0B1220" in prompt


def test_light_template_lock_keeps_beige_key():
    brief = "明暗偏亮米色；忌大面积深蓝底"
    lock = build_shared_material_lock(
        style_hint="米色纸感",
        bg_hex="#E8DCC8",
        alts=["桌面便签拼贴"],
        theme_colors={"bg": "#E8DCC8", "surface": "#F5EFE4", "ink": "#2A2218"},
        palette_brief=brief,
    )
    assert "TEMPLATE COLOR KEY" in lock
    assert "#E8DCC8" in lock
    assert brief in lock
    assert "DARK DECK LOCK" not in lock


def test_shared_lock_infers_ink_family():
    lock = build_shared_material_lock(
        style_hint="湖墨复盘 水墨年度数据",
        bg_hex="#E8DCC8",
        alts=["左上淡墨角饰", "右下浓墨角饰"],
        theme_colors={"bg": "#E8DCC8", "surface": "#F5EFE4", "ink": "#2A2218"},
    )
    assert "SHARED MATERIAL LOCK" in lock
    assert "#E8DCC8" in lock
    assert "ink-wash" in lock.lower() or "paper tone" in lock.lower()


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
