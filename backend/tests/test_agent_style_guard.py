"""样式一致性闸门：agent 放开结构自由后最重要的风险控制。

agent 可能写出技术上合格、风格上平庸的页面，而质检器**完全不报错**
（它只管导出与越界）。这些闸门专门补这个空缺。

判定原则：能机械判定的就机械判定，不靠 prompt。
"""

from __future__ import annotations

from ppt_master.engines.agent import style_guard


def _plan(bg: str = "#0A0E14", text: str = "#F2F5F8", **over) -> dict:
    plan = {
        "template_id": "星河智能产品发布会",
        "label_zh": "星河智能产品发布会",
        "palette": {
            "bg": bg,
            "panel": "#141A22",
            "text": text,
            "muted": "#8A96A3",
            "accent": "#4DA3FF",
            "accent2": "#FF7A45",
        },
        "slides": [
            {
                "file": "01_cover.svg",
                "role": "cover",
                "geometry": "满版暗场，标题压左下",
                "visual_hook": "一道光带切开画面",
            },
            {
                "file": "02_content.svg",
                "role": "content",
                "geometry": "左右非对称双栏",
                "visual_hook": "超大数字压住右侧",
            },
            {
                "file": "03_content.svg",
                "role": "content",
                "geometry": "横向路径推进",
                "visual_hook": "节点连线贯穿",
            },
        ],
    }
    plan.update(over)
    return plan


# ---------------------------------------------------------------------------
# 闸门 1：palette 纪律
# ---------------------------------------------------------------------------


def test_warm_cream_detected_for_known_trap_hexes() -> None:
    assert style_guard.is_warm_cream("#F4F1EA")
    assert style_guard.is_warm_cream("#FAF7F2")
    assert style_guard.is_warm_cream("#F5F0E8")


def test_warm_cream_rejects_cool_white() -> None:
    assert not style_guard.is_warm_cream("#FFFFFF")
    assert not style_guard.is_warm_cream("#F8FAFC")


def test_warm_cream_rejects_dark_fields() -> None:
    assert not style_guard.is_warm_cream("#0A0E14")
    assert not style_guard.is_warm_cream("#1A1512")


def test_palette_ok_for_dark_tech() -> None:
    issues = style_guard.palette_issues(_plan(), "dark-tech")
    assert issues == []


def test_palette_flags_warm_cream_for_non_paper_style() -> None:
    issues = style_guard.palette_issues(_plan(bg="#F4F1EA", text="#222222"), "dark-tech")
    assert any("暖奶油" in i or "米色" in i for i in issues)


def test_palette_allows_warm_cream_for_paper_style() -> None:
    """纸质风格可以合法用奶油底——闸门必须能区分，否则会误杀。"""
    issues = style_guard.palette_issues(
        _plan(bg="#F4F1EA", text="#2A2622"), "sketch-notes"
    )
    assert not any("暖奶油" in i for i in issues)


def test_palette_flags_low_contrast_text() -> None:
    issues = style_guard.palette_issues(
        _plan(bg="#0A0E14", text="#151A22"), "dark-tech"
    )
    assert any("对比度" in i for i in issues)


def test_palette_flags_missing_slots() -> None:
    issues = style_guard.palette_issues({"palette": {"bg": "#000000"}}, "dark-tech")
    assert any("缺少" in i for i in issues)


def test_palette_flags_missing_palette_entirely() -> None:
    issues = style_guard.palette_issues({"slides": []}, "dark-tech")
    assert any("palette" in i for i in issues)


def test_palette_flags_invalid_hex() -> None:
    issues = style_guard.palette_issues(_plan(bg="not-a-color"), "dark-tech")
    assert issues


# ---------------------------------------------------------------------------
# HUD 语汇越界
# ---------------------------------------------------------------------------


def test_hud_detected_in_geometry() -> None:
    plan = _plan()
    plan["slides"][0]["geometry"] = "HUD 全息面板，霓虹轨道环"
    assert style_guard.looks_like_neon_hud(plan) is True


def test_hud_rejected_for_non_tech_style() -> None:
    plan = _plan()
    plan["slides"][0]["geometry"] = "霓虹轨道环与粒子扫描线"
    issues = style_guard.palette_issues(plan, "swiss-minimal")
    assert any("HUD" in i or "霓虹" in i for i in issues)


def test_hud_allowed_for_dark_tech() -> None:
    plan = _plan()
    plan["slides"][0]["geometry"] = "霓虹轨道环"
    issues = style_guard.palette_issues(plan, "dark-tech")
    assert not any("HUD" in i or "霓虹" in i for i in issues)


# ---------------------------------------------------------------------------
# 命名：书名不是风格名
# ---------------------------------------------------------------------------


def test_title_rejects_style_metaphor() -> None:
    plan = _plan(template_id="暗色科技风发布会", label_zh="暗色科技风发布会")
    issues = style_guard.title_issues(plan, "dark-tech", "AI 产品发布会")
    assert any("风格" in i or "隐喻" in i for i in issues)


def test_title_accepts_content_topic() -> None:
    issues = style_guard.title_issues(_plan(), "dark-tech", "AI 产品发布会")
    assert issues == []


def test_title_allows_style_word_when_prompt_is_about_it() -> None:
    """用户需求本身就是该题材时应当放行，否则会误杀。"""
    plan = _plan(template_id="暗色科技风设计趋势", label_zh="暗色科技风设计趋势")
    issues = style_guard.title_issues(plan, "dark-tech", "讲一下暗色科技风")
    assert not any("隐喻" in i for i in issues)


def test_title_requires_chinese() -> None:
    plan = _plan(template_id="nova-launch", label_zh="nova-launch")
    issues = style_guard.title_issues(plan, "dark-tech", "prompt")
    assert any("中文" in i for i in issues)


def test_title_flags_too_short() -> None:
    plan = _plan(template_id="发布会", label_zh="发布会")
    issues = style_guard.title_issues(plan, "dark-tech", "prompt")
    assert any("过短" in i for i in issues)


# ---------------------------------------------------------------------------
# 闸门 3：结构指纹
# ---------------------------------------------------------------------------


def test_structure_flags_duplicate_geometry() -> None:
    plan = _plan()
    for slide in plan["slides"]:
        slide["geometry"] = "同样的三栏"
    issues = style_guard.structure_issues(plan, "dark-tech")
    assert any("构图" in i for i in issues)


def test_structure_ok_for_varied_geometry() -> None:
    issues = style_guard.structure_issues(_plan(), "dark-tech")
    assert issues == []


def test_structure_flags_missing_visual_hooks() -> None:
    plan = _plan()
    for slide in plan["slides"]:
        slide["visual_hook"] = ""
    issues = style_guard.structure_issues(plan, "dark-tech")
    assert any("visual_hook" in i for i in issues)


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


def test_check_plan_passes_clean_plan() -> None:
    result = style_guard.check_plan(_plan(), "dark-tech", "AI 产品发布会")
    assert result["ok"] is True
    assert result["blocking"] == []


def test_check_plan_blocks_warm_cream() -> None:
    result = style_guard.check_plan(
        _plan(bg="#FAF7F2", text="#222222"), "dark-tech", "AI 产品发布会"
    )
    assert result["ok"] is False
    assert result["blocking"]


def test_check_plan_warnings_do_not_block() -> None:
    """风格卡语汇弱检查只提示，不应阻塞——散文无法精确判定。"""
    result = style_guard.check_plan(_plan(), "dark-tech", "AI 产品发布会")
    assert isinstance(result["warnings"], list)
