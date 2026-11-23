"""样式一致性闸门（Harness 组件）。

Agent 放开了结构自由度，最大真实风险是**样式漂移**——写出技术上合格、
风格上平庸的页面，而且质检器完全不报错（它只管导出与越界）。

本模块提供四道闸门（按可靠性排序）：

1. **Palette 纪律** —— 机械判定：暖奶油底、霓虹 HUD 语汇、WCAG 对比度。
2. **风格卡语汇覆盖** —— 半机械：plan 的 geometry/visual_hook 是否命中卡内语汇。
3. **结构指纹** —— 机械：字体栈、装饰密度等与风格卡量化描述比对。
4. **VL 盲评"像不像"** —— 模型判定，故意与"好不好看"分开问，避免高分掩盖偏风格。

闸门 1/3 在 ``write_plan`` 时同步执行；闸门 2 作为提示性警告；闸门 4 由
``acceptance`` 在 finish 时按需调用（需要真实渲染预览，成本高）。

**保守原则**：自建检查器只做"比质检器更严"的判定，绝不更松——
质检器是黑盒（外部 Skill），两者冲突时本模块不能让坏产出过关。
"""

from __future__ import annotations

import re
from typing import Any

from ppt_master.palette import contrast_ratio, is_dark_field, parse_hex
from ppt_master.styles import is_paper_warm_style, style_title_ban_tokens

# WCAG 门槛（与 palette.py 的精修目标保持一致）
_MIN_TEXT_BG = 4.5
_MIN_MUTED_BG = 3.0
_MIN_ACCENT_BG = 2.5

# 允许使用 HUD / 霓虹语汇的风格
_TECH_HUD_OK = frozenset(
    {
        "dark-tech",
        "glassmorphism",
        "blueprint",
        "pixel-art",
        "kinetic-poster",
        "midnight-luxe",
    }
)

_HUD_TOKENS = (
    "hud",
    "neon",
    "霓虹",
    "轨道",
    "orbit",
    "粒子",
    "particle",
    "扫描线",
    "radar",
    "全息",
    "holograph",
)

# 暖奶油/米色判定：色相偏暖 + 高明度 + 低饱和
_WARM_TRAP_HEX = (
    "#F4F1EA",
    "#FAF7F2",
    "#F5F0E8",
    "#F7F3EC",
    "#FBF8F3",
)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def is_warm_cream(raw: Any) -> bool:
    """判断颜色是否属于"默认暖奶油底"——非纸质风格的经典漂移信号。"""
    rgb = parse_hex(raw)
    if rgb is None:
        return False
    r, g, b = rgb
    if _hex(rgb) in _WARM_TRAP_HEX:
        return True
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == 0:
        return False
    # 高明度
    if mx < 0xE0:
        return False
    # 低饱和
    if mx - mn > 0x24:
        return False
    # 偏暖：红 > 蓝 且 绿居中
    return r >= b + 6 and g >= b


def looks_like_neon_hud(plan: dict[str, Any]) -> bool:
    """是否使用 HUD / 霓虹语汇（用于非科技风格的越界判定）。"""
    haystack: list[str] = []
    for key in ("template_id", "label_zh", "product"):
        value = plan.get(key)
        if isinstance(value, str):
            haystack.append(value)
    for slide in plan.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        for key in ("geometry", "visual_hook", "title", "core_message"):
            value = slide.get(key)
            if isinstance(value, str):
                haystack.append(value)
    text = " ".join(haystack).lower()
    return any(token in text for token in _HUD_TOKENS)


def palette_issues(plan: dict[str, Any], style: str) -> list[str]:
    """闸门 1：Palette 纪律（机械判定）。"""
    issues: list[str] = []
    palette = plan.get("palette")
    if not isinstance(palette, dict):
        return ["缺少 palette（bg/panel/text/muted/accent/accent2）"]
    resolved = {str(k): parse_hex(v) for k, v in palette.items()}
    bg = resolved.get("bg")
    if bg is None:
        issues.append("palette.bg 缺失或不是合法 #RRGGBB")
        return issues
    missing = [k for k in ("panel", "text", "muted", "accent", "accent2") if resolved.get(k) is None]
    if missing:
        issues.append(f"palette 缺少/非法槽位：{', '.join(missing)}")
    if not is_paper_warm_style(style) and is_warm_cream(palette.get("bg")):
        issues.append(
            "非纸质风格（{0}）的 bg 用了默认暖奶油/米色（{1}）；"
            "浅色场请用冷白/冷灰/近纯白，或改深色哑光/高饱和色块".format(
                style, str(palette.get("bg"))
            )
        )
    if looks_like_neon_hud(plan) and style not in _TECH_HUD_OK:
        issues.append(
            f"风格 {style} 不属于科技/HUD 家族，但 plan 里出现了霓虹/HUD/轨道/粒子语汇"
        )
    # 对比度：只对已知的槽位做，缺失已在上方报告
    checks = (
        ("text", _MIN_TEXT_BG),
        ("muted", _MIN_MUTED_BG),
        ("accent", _MIN_ACCENT_BG),
    )
    dark = is_dark_field(bg)
    for key, minimum in checks:
        fg = resolved.get(key)
        if fg is None:
            continue
        ratio = contrast_ratio(fg, bg)
        if ratio < minimum:
            issues.append(
                f"palette.{key} 与 bg 对比度 {ratio:.2f} < {minimum}（{'暗场' if dark else '亮场'}）"
            )
    return issues


def title_issues(plan: dict[str, Any], style: str, prompt: str) -> list[str]:
    """书名不得写成风格隐喻（沿用旧管线 ``style_title_ban_tokens``）。"""
    import re as _re

    title = str(plan.get("label_zh") or plan.get("template_id") or "").strip()
    if not title:
        return ["plan 缺少 label_zh / template_id"]
    issues: list[str] = []
    allowed_by_prompt = [
        token
        for token in style_title_ban_tokens(style)
        if token and token in (prompt or "")
    ]
    bad = [
        token
        for token in style_title_ban_tokens(style)
        if token and token in title and token not in allowed_by_prompt
    ]
    if bad:
        issues.append(
            "书名把视觉风格隐喻当成了内容主题（含：{0}）。"
            "书名应是内容主题（产品/活动/议题），例如「星河智能产品发布会」".format(
                "、".join(bad[:3])
            )
        )
    if not _re.search(r"[\u4e00-\u9fff]", title):
        issues.append("书名必须含中文；纯英文 kebab-case 不允许")
    elif len(title) < 6:
        issues.append(f"书名过短（{len(title)} 字）；建议 10–15 个汉字的内容主题名")
    return issues


def structure_issues(plan: dict[str, Any], style: str) -> list[str]:
    """闸门 3：结构指纹（机械）。

    只检查跨页可判定的粗粒度信号：构图重复、装饰语汇单一。
    更细的视觉判断交给 VL 闸门。
    """
    slides = [s for s in (plan.get("slides") or []) if isinstance(s, dict)]
    if not slides:
        return ["plan 没有 slides"]
    issues: list[str] = []
    geometries = [
        str(s.get("geometry") or "").strip().lower()
        for s in slides
        if str(s.get("geometry") or "").strip()
    ]
    if len(geometries) >= 3:
        unique = len(set(geometries))
        need = max(3, min(4, len(geometries)))
        if unique < need:
            issues.append(
                f"构图骨架只有 {unique} 种（≥{len(geometries)} 页要求至少 {need} 种）；"
                "连续相同骨架会显得模板化"
            )
        dupes = sorted({g for g in geometries if geometries.count(g) > 1})
        if dupes:
            issues.append(
                "存在重复构图：" + "、".join(d[:24] for d in dupes[:3])
            )
    hooks = [str(s.get("visual_hook") or "").strip() for s in slides]
    if hooks and sum(1 for h in hooks if h) < max(1, len(hooks) // 2):
        issues.append("多数页面缺少 visual_hook（每页应有一个可被记住的视觉记忆点）")
    return issues


def style_warnings(plan: dict[str, Any], style: str) -> list[str]:
    """闸门 2：风格卡语汇覆盖（提示性，不阻塞）。

    风格卡正文是散文，无法精确判定"像不像"，这里只做关键词弱检查，
    命中率过低时提醒模型回读风格卡。
    """
    card = ""
    try:
        from ppt_master.styles import load_style_card

        card = load_style_card(style) or ""
    except Exception:  # noqa: BLE001 - Skill 缺失时不影响主流程
        return []
    if not card.strip():
        return []
    tokens = {
        t.lower()
        for t in re.findall(r"[A-Za-z][A-Za-z-]{3,}", card)
    }
    if not tokens:
        return []
    haystack = " ".join(
        str(s.get(key) or "")
        for s in (plan.get("slides") or [])
        if isinstance(s, dict)
        for key in ("geometry", "visual_hook")
    ).lower()
    if not haystack.strip():
        return ["plan 未描述 geometry / visual_hook，无法核对风格卡语汇"]
    hits = sum(1 for t in tokens if t in haystack)
    if hits == 0:
        return [
            f"plan 的 geometry/visual_hook 没有命中风格卡 {style} 的任何造型语汇；"
            "请回读风格卡，用它的造型语言描述版面"
        ]
    return []


def check_plan(plan: dict[str, Any], style: str, prompt: str) -> dict[str, Any]:
    """执行同步可做的闸门，返回 ``{ok, blocking, warnings}``。

    blocking = palette + 命名 + 结构指纹（会阻止 write_plan 成功）
    warnings = 风格卡语汇弱检查（只提示）
    """
    blocking: list[str] = []
    blocking += palette_issues(plan, style)
    blocking += title_issues(plan, style, prompt)
    blocking += structure_issues(plan, style)
    warnings = style_warnings(plan, style)
    return {"ok": not blocking, "blocking": blocking, "warnings": warnings}
