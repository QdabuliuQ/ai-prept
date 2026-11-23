"""验收契约：唯一裁判，模型无法绕过。

最关键的三条：
1. ``finish`` 必然触发独立质检，不信任模型自评；
2. agent 比流水线更严——不接受 soft-pass 逃生；
3. 拒绝时给具体错误，而不是"不合格"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ppt_master.engines.agent import acceptance
from ppt_master.engines.agent.workspace import Workspace
from ppt_master.engines.base import SkillBridge

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


class FakeBridge(SkillBridge):
    def __init__(self, *, passed: bool = True, errors: list[str] | None = None) -> None:
        self.passed = passed
        self.errors = errors or []
        self.quality_calls: list[str | None] = []

    def ready(self) -> None:
        return None

    def init_project(self, name: str) -> Path:  # pragma: no cover
        raise NotImplementedError

    def catalog(self) -> list[dict]:
        return []

    def style_card(self, style_id: str) -> str:
        return ""

    def quality_report(self, project, *, file_name=None):
        self.quality_calls.append(file_name)
        if self.passed:
            return True, {"files": []}
        report = {
            "files": [
                {
                    "file": "01_cover.svg",
                    "errors": self.errors or ["[TEXT_TEXT_OVERLAP] title/body 相交 34px"],
                }
            ]
        }
        return False, report

    def export_argv(self, project, pptx_out, *, flags):
        return []

    def export_pptx(self, project, pptx_out, *, flags):
        return None


@pytest.fixture()
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "run", style="dark-tech", pages=3, mode="full")


# ---------------------------------------------------------------------------
# plan 模式验收
# ---------------------------------------------------------------------------


def test_plan_stage_accepts_good_plan(ws: Workspace) -> None:
    ws.save_plan(GOOD_PLAN)
    verdict = acceptance.check_plan_stage(ws, "AI 产品发布会")
    assert verdict.ok is True, verdict.blocking
    assert verdict.checks["plan_shape"] == "ok"


def test_plan_stage_rejects_wrong_page_count(ws: Workspace) -> None:
    plan = dict(GOOD_PLAN)
    plan["slides"] = GOOD_PLAN["slides"][:2]
    ws.save_plan(plan)
    verdict = acceptance.check_plan_stage(ws, "AI 产品发布会")
    assert verdict.ok is False
    assert any("页数" in b for b in verdict.blocking)


def test_plan_stage_rejects_style_drift(ws: Workspace) -> None:
    plan = dict(GOOD_PLAN)
    plan["palette"] = {**GOOD_PLAN["palette"], "bg": "#FAF7F2", "text": "#222222"}
    ws.save_plan(plan)
    verdict = acceptance.check_plan_stage(ws, "AI 产品发布会")
    assert verdict.ok is False
    assert any("暖奶油" in b or "米色" in b for b in verdict.blocking)


def test_plan_stage_without_plan_reports_clearly(ws: Workspace) -> None:
    verdict = acceptance.check_plan_stage(ws, "p")
    assert verdict.ok is False
    assert any("plan" in b for b in verdict.blocking)


# ---------------------------------------------------------------------------
# full 模式验收
# ---------------------------------------------------------------------------


def _write_pages(ws: Workspace) -> None:
    for rel in ws.slide_files():
        ws.write_page(rel, '<svg viewBox="0 0 1280 720"><g data-pptx-bounds="0 0 10 10"/></svg>')


def test_full_stage_accepts_when_quality_passes(ws: Workspace) -> None:
    ws.save_plan(GOOD_PLAN)
    _write_pages(ws)
    bridge = FakeBridge(passed=True)
    verdict = acceptance.check_full_stage(ws, "AI 产品发布会", bridge)
    assert verdict.ok is True, verdict.blocking
    assert verdict.checks["quality"] == "passed"
    assert bridge.quality_calls == [None], "必须真的跑一次质检"


def test_full_stage_rejects_when_quality_fails(ws: Workspace) -> None:
    ws.save_plan(GOOD_PLAN)
    _write_pages(ws)
    bridge = FakeBridge(passed=False)
    verdict = acceptance.check_full_stage(ws, "AI 产品发布会", bridge)
    assert verdict.ok is False
    assert any("34px" in b for b in verdict.blocking), "要透传具体错误"


def test_full_stage_rejects_missing_pages(ws: Workspace) -> None:
    ws.save_plan(GOOD_PLAN)
    ws.write_page("01_cover.svg", "<svg/>")
    bridge = FakeBridge(passed=True)
    verdict = acceptance.check_full_stage(ws, "AI 产品发布会", bridge)
    assert verdict.ok is False
    assert any("缺少" in b for b in verdict.blocking)


def test_full_stage_rejects_empty_pages(ws: Workspace) -> None:
    ws.save_plan(GOOD_PLAN)
    for rel in ws.slide_files():
        ws.write_page(rel, "   ")
    bridge = FakeBridge(passed=True)
    verdict = acceptance.check_full_stage(ws, "AI 产品发布会", bridge)
    assert verdict.ok is False
    assert any("为空" in b for b in verdict.blocking)


def test_full_stage_does_not_trust_model_self_report(ws: Workspace) -> None:
    """即使模型声称已检查过，验收仍必须自己跑一遍质检。"""
    ws.save_plan(GOOD_PLAN)
    _write_pages(ws)
    bridge = FakeBridge(passed=False)
    acceptance.check_full_stage(ws, "p", bridge)
    acceptance.check_full_stage(ws, "p", bridge)
    assert len(bridge.quality_calls) == 2


def test_full_stage_strict_flag_does_not_bypass(ws: Workspace) -> None:
    """strict=False 只加 warning，blocking 仍然存在——不能变成逃生通道。"""
    ws.save_plan(GOOD_PLAN)
    _write_pages(ws)
    bridge = FakeBridge(passed=False)
    verdict = acceptance.check_full_stage(ws, "p", bridge, strict=False)
    assert verdict.ok is False
    assert verdict.warnings


# ---------------------------------------------------------------------------
# payload 形状（要喂回模型，必须可读）
# ---------------------------------------------------------------------------


def test_verdict_payload_rejected_has_hint(ws: Workspace) -> None:
    plan = dict(GOOD_PLAN)
    plan["palette"] = {**GOOD_PLAN["palette"], "bg": "#F4F1EA", "text": "#222222"}
    ws.save_plan(plan)
    verdict = acceptance.check_plan_stage(ws, "p")
    payload = verdict.to_payload()
    assert payload["ok"] is False
    assert payload["status"] == "rejected"
    assert payload["blocking"]
    assert "hint" in payload


def test_verdict_payload_accepted_has_no_hint(ws: Workspace) -> None:
    ws.save_plan(GOOD_PLAN)
    payload = acceptance.check_plan_stage(ws, "AI 产品发布会").to_payload()
    assert payload["ok"] is True
    assert payload["status"] == "accepted"
    assert "hint" not in payload


def test_verdict_blocking_is_truncated(ws: Workspace) -> None:
    """缺陷清单要截断——回灌给模型时不能无限长。"""
    ws.save_plan(GOOD_PLAN)
    _write_pages(ws)
    bridge = FakeBridge(passed=False, errors=[f"错误 {i}" for i in range(50)])
    verdict = acceptance.check_full_stage(ws, "p", bridge)
    assert len(verdict.to_payload()["blocking"]) <= 12
