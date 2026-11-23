"""工具表：门禁长在工具里，模型绕不过去。

测试重点：
1. 写工具在**非法输入时拒绝且不落盘**（沙箱边界）；
2. 拒绝时返回**可操作的诊断**，而不是"请重试"；
3. 只读工具真的只读（风格卡不可改）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ppt_master.engines.agent.tools import build_tools
from ppt_master.engines.agent.workspace import Workspace
from ppt_master.engines.base import SkillBridge


class FakeBridge(SkillBridge):
    """测试替身：不依赖真实 PPT Master Skill 目录。"""

    def __init__(self, *, card: str = "## 暗色科技\n用色纪律：低饱和、单一强调色") -> None:
        self._card = card
        self.calls: list[str] = []

    def ready(self) -> None:
        return None

    def init_project(self, name: str) -> Path:  # pragma: no cover - plan 模式不用
        raise NotImplementedError

    def catalog(self) -> list[dict]:
        return [
            {"id": "dark-tech", "label_zh": "暗色科技", "family": "corporate-product"},
            {"id": "swiss-minimal", "label_zh": "瑞士极简", "family": "corporate-product"},
        ]

    def style_card(self, style_id: str) -> str:
        return self._card if style_id == "dark-tech" else ""

    def quality_report(self, project, *, file_name=None):
        self.calls.append(f"quality:{file_name or 'all'}")
        return True, {"files": []}

    def export_argv(self, project, pptx_out, *, flags):
        return ["python", "svg_to_pptx.py"]

    def export_pptx(self, project, pptx_out, *, flags):
        return None


@pytest.fixture()
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "run", style="dark-tech", pages=3, mode="plan")


@pytest.fixture()
def bridge() -> FakeBridge:
    return FakeBridge()


GOOD_PLAN = {
    "template_id": "星河智能产品发布会",
    "label_zh": "星河智能产品发布会",
    "palette": {
        "bg": "#0A0E14",
        "panel": "#141A22",
        "text": "#F2F5F8",
        "muted": "#8A96A3",
        "accent": "#4DA3FF",
        "accent2": "#FF7A45",
    },
    "slides": [
        {
            "file": "01_cover.svg",
            "role": "cover",
            "title": "发布会",
            "core_message": "开场",
            "geometry": "满版暗场，标题压左下",
            "visual_hook": "一道光带",
            "layout_regions": [
                {
                    "id": "title",
                    "role": "page-title",
                    "bounds": [72, 56, 1136, 96],
                    "padding": [12, 16, 12, 16],
                    "clearance": 12,
                }
            ],
        },
        {
            "file": "02_content.svg",
            "role": "content",
            "title": "能力",
            "core_message": "三点能力",
            "geometry": "左右非对称双栏",
            "visual_hook": "超大数字",
            "layout_regions": [
                {
                    "id": "body",
                    "role": "body",
                    "bounds": [72, 176, 1136, 448],
                    "padding": [16, 16, 16, 16],
                    "clearance": 16,
                }
            ],
        },
        {
            "file": "03_ending.svg",
            "role": "ending",
            "title": "结束",
            "core_message": "收尾",
            "geometry": "横向路径",
            "visual_hook": "节点连线",
            "layout_regions": [
                {
                    "id": "body",
                    "role": "body",
                    "bounds": [72, 176, 1136, 448],
                    "padding": [16, 16, 16, 16],
                    "clearance": 16,
                }
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# 只读工具
# ---------------------------------------------------------------------------


def test_list_styles_returns_catalog(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="p", mode="plan")
    result = tools["list_styles"].handler({})
    assert result["ok"] is True
    assert result["count"] == 2
    assert result["styles"][0]["id"] == "dark-tech"


def test_read_style_card_returns_body(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="p", mode="plan")
    result = tools["read_style_card"].handler({"style": "dark-tech"})
    assert result["ok"] is True
    assert "暗色科技" in result["card"]


def test_read_style_card_rejects_unknown(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="p", mode="plan")
    result = tools["read_style_card"].handler({"style": "nope"})
    assert result["ok"] is False


def test_read_style_card_requires_style(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="p", mode="plan")
    assert tools["read_style_card"].handler({})["ok"] is False


# ---------------------------------------------------------------------------
# write_plan：门禁
# ---------------------------------------------------------------------------


def test_write_plan_accepts_good_plan(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="AI 产品发布会", mode="plan")
    result = tools["write_plan"].handler({"plan": GOOD_PLAN})
    assert result["ok"] is True, result
    assert result["slides"] == 3
    assert ws.plan_path.is_file()


def test_write_plan_rejects_wrong_page_count(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="p", mode="plan")
    plan = dict(GOOD_PLAN)
    plan["slides"] = GOOD_PLAN["slides"][:2]
    result = tools["write_plan"].handler({"plan": plan})
    assert result["ok"] is False
    assert result["stage"] == "shape"
    assert not ws.plan_path.is_file(), "拒绝时不得落盘"


def test_write_plan_self_heals_region_outside_safe_area(ws, bridge) -> None:
    """越界 region 会被机械修复（沿用旧管线 repair_plan_layout），而不是直接拒。

    真正要保证的是：**落盘的 plan 里所有 region 都在安全区内**。
    """
    tools = build_tools(ws, bridge=bridge, prompt="p", mode="plan")
    plan = {
        **GOOD_PLAN,
        "slides": [
            {
                **GOOD_PLAN["slides"][0],
                "layout_regions": [
                    {
                        "id": "title",
                        "role": "page-title",
                        "bounds": [0, 0, 200, 100],
                        "padding": [4, 4, 4, 4],
                        "clearance": 4,
                    }
                ],
            },
            GOOD_PLAN["slides"][1],
            GOOD_PLAN["slides"][2],
        ],
    }
    result = tools["write_plan"].handler({"plan": plan})
    assert result["ok"] is True, result
    stored = ws.load_plan()
    for slide in stored["slides"]:
        for region in slide["layout_regions"]:
            x, y, w, h = region["bounds"]
            assert x >= 40 and y >= 40 and x + w <= 1240 and y + h <= 680, region


def test_write_plan_rejects_unhealable_structure(ws, bridge) -> None:
    """机械修复不了的结构错误必须拒绝，而不是放行。"""
    tools = build_tools(ws, bridge=bridge, prompt="p", mode="plan")
    plan = {
        **GOOD_PLAN,
        "slides": [
            {
                **GOOD_PLAN["slides"][0],
                "file": "02_content.svg",  # 与第 2 页重名，无法机械修复
            },
            GOOD_PLAN["slides"][1],
            GOOD_PLAN["slides"][2],
        ],
    }
    result = tools["write_plan"].handler({"plan": plan})
    assert result["ok"] is False
    assert result["stage"] == "shape"


def test_write_plan_rejects_warm_cream_palette(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="AI 产品发布会", mode="plan")
    plan = dict(GOOD_PLAN)
    plan["palette"] = {**GOOD_PLAN["palette"], "bg": "#F4F1EA", "text": "#222222"}
    result = tools["write_plan"].handler({"plan": plan})
    assert result["ok"] is False
    assert result["stage"] == "style"
    assert any("暖奶油" in b or "米色" in b for b in result["blocking"])
    assert not ws.plan_path.is_file()


def test_write_plan_empty_rejected(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="p", mode="plan")
    assert tools["write_plan"].handler({"plan": {}})["ok"] is False


def test_read_plan_after_write(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="AI 产品发布会", mode="plan")
    tools["write_plan"].handler({"plan": GOOD_PLAN})
    result = tools["read_plan"].handler({})
    assert result["ok"] is True
    assert result["plan"]["template_id"] == "星河智能产品发布会"


def test_read_plan_before_write_fails(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="p", mode="plan")
    assert tools["read_plan"].handler({})["ok"] is False


# ---------------------------------------------------------------------------
# 页数自由：insert / delete
# ---------------------------------------------------------------------------


def _four_page_plan() -> dict:
    extra = {
        "file": "02b_extra.svg",
        "role": "content",
        "title": "补充",
        "core_message": "补充页",
        "geometry": "中心放射",
        "visual_hook": "中心大图",
        "layout_regions": [
            {
                "id": "body",
                "role": "body",
                "bounds": [72, 176, 1136, 448],
                "padding": [16, 16, 16, 16],
                "clearance": 16,
            }
        ],
    }
    return {**GOOD_PLAN, "slides": [*GOOD_PLAN["slides"], extra]}


def test_plan_mode_rejects_page_count_drift(ws, bridge) -> None:
    """plan 模式下页数固定——下游流水线按 preset_plan 严格校验。"""
    tools = build_tools(ws, bridge=bridge, prompt="AI 产品发布会", mode="plan")
    result = tools["write_plan"].handler({"plan": _four_page_plan()})
    assert result["ok"] is False
    assert any("页数" in b for b in result["blocking"])


def test_full_mode_allows_page_count_drift(tmp_path, bridge) -> None:
    """full 模式下 agent 可以自行增减页数——这是它相对流水线的核心自由度。"""
    ws = Workspace.create(tmp_path / "full", style="dark-tech", pages=3, mode="full")
    tools = build_tools(ws, bridge=bridge, prompt="AI 产品发布会", mode="full")
    result = tools["write_plan"].handler({"plan": _four_page_plan()})
    assert result["ok"] is True, result
    assert result["slides"] == 4


def test_full_mode_rejects_page_count_out_of_range(tmp_path, bridge) -> None:
    ws = Workspace.create(tmp_path / "full2", style="dark-tech", pages=3, mode="full")
    tools = build_tools(ws, bridge=bridge, prompt="AI 产品发布会", mode="full")
    plan = {**GOOD_PLAN, "slides": GOOD_PLAN["slides"][:2]}
    result = tools["write_plan"].handler({"plan": plan})
    assert result["ok"] is False
    assert any("3..12" in b for b in result["blocking"])


def test_delete_page_reduces_plan(tmp_path, bridge) -> None:
    ws = Workspace.create(tmp_path / "full3", style="dark-tech", pages=3, mode="full")
    tools = build_tools(ws, bridge=bridge, prompt="AI 产品发布会", mode="full")
    tools["write_plan"].handler({"plan": _four_page_plan()})
    result = tools["delete_page"].handler({"file": "02_content.svg"})
    assert result["ok"] is True
    assert result["slides"] == 3


def test_delete_page_blocks_below_three(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="AI 产品发布会", mode="plan")
    tools["write_plan"].handler({"plan": GOOD_PLAN})
    tools["delete_page"].handler({"file": "03_ending.svg"})
    tools["delete_page"].handler({"file": "02_content.svg"})
    result = tools["delete_page"].handler({"file": "01_cover.svg"})
    assert result["ok"] is False
    assert "3" in result["error"]


def test_delete_missing_page(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="AI 产品发布会", mode="plan")
    tools["write_plan"].handler({"plan": GOOD_PLAN})
    assert tools["delete_page"].handler({"file": "nope.svg"})["ok"] is False


def test_insert_page_after_anchor(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="AI 产品发布会", mode="plan")
    tools["write_plan"].handler({"plan": GOOD_PLAN})
    extra = {
        "file": "02b_extra.svg",
        "role": "content",
        "title": "补充",
        "core_message": "补充页",
        "geometry": "中心放射",
        "visual_hook": "中心大图",
        "layout_regions": [
            {
                "id": "body",
                "role": "body",
                "bounds": [72, 176, 1136, 448],
                "padding": [16, 16, 16, 16],
                "clearance": 16,
            }
        ],
    }
    result = tools["insert_page"].handler({"after": "01_cover.svg", "slide": extra})
    assert result["ok"] is True
    assert result["index"] == 1


def test_insert_page_rejects_duplicate_file(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="AI 产品发布会", mode="plan")
    tools["write_plan"].handler({"plan": GOOD_PLAN})
    result = tools["insert_page"].handler({"slide": GOOD_PLAN["slides"][0]})
    assert result["ok"] is False
    assert "重复" in result["error"]


# ---------------------------------------------------------------------------
# 模式隔离：plan 模式不该有 SVG 工具
# ---------------------------------------------------------------------------


def test_plan_mode_has_no_svg_tools(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="p", mode="plan")
    assert "write_page" not in tools
    assert "check_page" not in tools
    assert "write_plan" in tools


def test_full_mode_has_svg_tools(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="p", mode="full")
    for name in ("write_page", "read_page", "edit_page", "check_page", "check_all"):
        assert name in tools, name


# ---------------------------------------------------------------------------
# 工具 schema 合法（模型要用它，形状必须对）
# ---------------------------------------------------------------------------


def test_every_tool_has_valid_spec(ws, bridge) -> None:
    tools = build_tools(ws, bridge=bridge, prompt="p", mode="full")
    for name, tool in tools.items():
        spec = tool.spec()
        assert spec["name"] == name
        assert isinstance(spec["description"], str) and spec["description"]
        params = spec["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
