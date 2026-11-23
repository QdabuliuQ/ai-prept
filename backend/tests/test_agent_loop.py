"""Agent Loop 主循环：预算、终止、finish 强制复检、降级交付。

这些测试用假的 LLM 与假的 Skill，验证**控制流**而非生成质量。
关键不变量：

1. ``finish`` 必走独立验收，模型说的不算；
2. 预算到顶 → 降级交付（partial），不是抛错；
3. 停滞 → 终止，不烧完预算；
4. 验收通过后 plan 模式下**交给流水线**（样式与编译仍归 PPT Master）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import config
import llm
from ppt_master.engines.agent.loop import AgentEngine
from ppt_master.engines.base import Budget, EngineResult, GenerateSpec, RunContext, SkillBridge

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
                },
                {
                    "id": "body",
                    "role": "body",
                    "bounds": [72, 176, 1136, 448],
                    "padding": [16, 16, 16, 16],
                    "clearance": 16,
                },
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
    """假 Skill：plan 模式只需 catalog / style_card / ready。"""

    def ready(self) -> None:
        return None

    def init_project(self, name: str) -> Path:  # pragma: no cover - plan 模式不用
        raise NotImplementedError

    def catalog(self) -> list[dict]:
        return [{"id": "dark-tech", "label_zh": "暗色科技"}]

    def style_card(self, style_id: str) -> str:
        return "## 暗色科技\n用色纪律：低饱和、单一强调色、大留白"

    def quality_report(self, project, *, file_name=None):
        return True, {"files": []}

    def export_argv(self, project, pptx_out, *, flags):
        return []

    def export_pptx(self, project, pptx_out, *, flags):
        return None


def _reply(name: str, args: dict[str, Any] | None = None) -> llm.ToolReply:
    call = llm.ToolCall(name=name, args=args or {})
    return llm.ToolReply(
        mode="pseudo",
        calls=[call],
        text="",
        assistant_message={"role": "assistant", "content": json.dumps({"action": {"name": name}})},
    )


class ScriptedLLM:
    """按脚本依次返回 reply；脚本用尽后重复最后一条。"""

    def __init__(self, replies: list[llm.ToolReply]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, **kwargs: Any) -> llm.ToolReply:
        self.calls += 1
        idx = min(self.calls - 1, len(self.replies) - 1)
        return self.replies[idx]


@pytest.fixture(autouse=True)
def _stub_llm_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """不需要真实 key / 网络。"""
    monkeypatch.setattr(
        config,
        "llm_config",
        lambda: config.LlmConfig(api_keys=("test",), base_url="http://x", model="stub"),
    )
    monkeypatch.setattr(llm, "make_client_pool", lambda cfg: None)
    # 工作目录与产物根都落在 tmp
    import ppt_master.paths as paths

    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        AgentEngine, "_default_out_root", staticmethod(lambda: tmp_path / "agent-output")
    )


def _ctx(tmp_path: Path) -> RunContext:
    return RunContext(log=lambda s: None, bridge=FakeBridge())


def _patch_pipeline(monkeypatch: pytest.MonkeyPatch, row: dict[str, Any]) -> dict[str, Any]:
    """替换 run_one_package，并记录是否收到 preset_plan。"""
    captured: dict[str, Any] = {}

    def fake_run_one_package(prompt: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        captured["prompt"] = prompt
        return row

    import ppt_master.pipeline as pipeline

    monkeypatch.setattr(pipeline, "run_one_package", fake_run_one_package)
    return captured


def _spec(**over: Any) -> GenerateSpec:
    base = dict(prompt="AI 产品发布会", style="dark-tech", pages=3)
    base.update(over)
    return GenerateSpec(**base)


PIPELINE_ROW = {
    "ok": True,
    "template_id": "abc123",
    "output_dir": "/tmp/out",
    "project": "/tmp/project",
    "quality_gate": "passed",
    "render": "svg",
}


# ---------------------------------------------------------------------------
# 正常路径：规划 → 验收 → 交给流水线
# ---------------------------------------------------------------------------


def test_plan_mode_accepts_and_hands_off_to_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _patch_pipeline(monkeypatch, PIPELINE_ROW)
    scripted = ScriptedLLM(
        [
            _reply("read_style_card", {"style": "dark-tech"}),
            _reply("write_plan", {"plan": GOOD_PLAN}),
            _reply("finish", {"summary": "3 页规划完成"}),
        ]
    )
    monkeypatch.setattr(llm, "chat_tools", scripted)

    result = AgentEngine().run(_spec(), _ctx(tmp_path))

    assert result.ok is True
    assert result.engine == "agent"
    assert result.template_id == "abc123"
    # 关键：plan 被注入流水线，SVG/样式/导出仍是 PPT Master 那一套
    assert captured["preset_plan"]["template_id"] == "星河智能产品发布会"
    assert captured["pages"] == 3


def test_agent_result_marks_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pipeline(monkeypatch, PIPELINE_ROW)
    monkeypatch.setattr(
        llm,
        "chat_tools",
        ScriptedLLM(
            [
                _reply("write_plan", {"plan": GOOD_PLAN}),
                _reply("finish", {}),
            ]
        ),
    )
    result = AgentEngine().run(_spec(), _ctx(tmp_path))
    assert result.raw.get("agent_plan_handoff") is True
    assert result.steps >= 1


# ---------------------------------------------------------------------------
# finish 必须走独立验收
# ---------------------------------------------------------------------------


def test_finish_rejected_when_plan_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """没写 plan 就 finish：必须被拒，且最终降级而不是假装成功。"""
    monkeypatch.setattr(
        llm, "chat_tools", ScriptedLLM([_reply("finish", {"summary": "done"})])
    )
    result = AgentEngine().run(_spec(), _ctx(tmp_path))
    assert result.ok is False
    assert result.status == "partial"
    assert "finish" in (result.reason or "")


def test_finish_retries_then_degrades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """连续被拒达到上限后终止——不允许无限自我说服。"""
    scripted = ScriptedLLM([_reply("finish", {})])
    monkeypatch.setattr(llm, "chat_tools", scripted)
    result = AgentEngine().run(_spec(), _ctx(tmp_path), )
    assert result.status == "partial"
    assert scripted.calls <= 4, f"应早停，实际调用 {scripted.calls} 次"


def test_rejected_finish_then_fix_then_accept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """被拒 → 按提示修 → 再 finish → 通过。这是正常修复回路。"""
    captured = _patch_pipeline(monkeypatch, PIPELINE_ROW)
    bad_plan = {**GOOD_PLAN, "palette": {**GOOD_PLAN["palette"], "bg": "#F4F1EA", "text": "#222222"}}
    scripted = ScriptedLLM(
        [
            _reply("write_plan", {"plan": bad_plan}),   # 会被样式闸门拒
            _reply("finish", {}),                        # 无 plan，被拒
            _reply("write_plan", {"plan": GOOD_PLAN}),   # 修正
            _reply("finish", {}),                        # 通过
        ]
    )
    monkeypatch.setattr(llm, "chat_tools", scripted)
    result = AgentEngine().run(_spec(budget=Budget(max_steps=10)), _ctx(tmp_path))
    assert result.ok is True
    assert captured["preset_plan"]["template_id"] == "星河智能产品发布会"


# ---------------------------------------------------------------------------
# 预算与停滞：Harness 的止损
# ---------------------------------------------------------------------------


def test_budget_max_steps_degrades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm, "chat_tools", ScriptedLLM([_reply("read_style_card", {"style": "dark-tech"})])
    )
    result = AgentEngine().run(_spec(budget=Budget(max_steps=3)), _ctx(tmp_path))
    assert result.status == "partial"
    assert "步数上限" in (result.reason or "")


def test_budget_max_llm_calls_degrades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm, "chat_tools", ScriptedLLM([_reply("read_style_card", {"style": "dark-tech"})])
    )
    result = AgentEngine().run(
        _spec(budget=Budget(max_steps=100, max_llm_calls=2)), _ctx(tmp_path)
    )
    assert result.status == "partial"
    assert "调用数" in (result.reason or "")


def test_stall_detected_terminates_early(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """重复同样的失败动作 → 判定卡死，不烧完预算。"""
    scripted = ScriptedLLM([_reply("write_plan", {"plan": {"bogus": True}})])
    monkeypatch.setattr(llm, "chat_tools", scripted)
    result = AgentEngine().run(_spec(budget=Budget(max_steps=40)), _ctx(tmp_path))
    assert result.status == "partial"
    assert "卡死" in (result.reason or "")
    assert scripted.calls < 10, f"应早停，实际 {scripted.calls} 次"


# ---------------------------------------------------------------------------
# 前置校验：没有 Skill 就不启动
# ---------------------------------------------------------------------------


class UnreadyBridge(FakeBridge):
    def ready(self) -> None:
        raise __import__("ppt_master.engines.base", fromlist=["EngineError"]).EngineError(
            "未找到 PPT Master Skill"
        )


def test_missing_skill_refuses_to_start(tmp_path: Path) -> None:
    ctx = RunContext(log=lambda s: None, bridge=UnreadyBridge())
    result = AgentEngine().run(_spec(), ctx)
    assert result.ok is False
    assert result.status == "failed"
    assert "PPT Master" in (result.reason or "")


# ---------------------------------------------------------------------------
# 降级交付的产物：不整包作废
# ---------------------------------------------------------------------------


def test_degrade_keeps_workdir_and_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm, "chat_tools", ScriptedLLM([_reply("read_style_card", {"style": "dark-tech"})])
    )
    result = AgentEngine().run(_spec(budget=Budget(max_steps=2)), _ctx(tmp_path))
    assert result.status == "partial"
    workdir = Path(result.raw["agent_workdir"])
    assert workdir.is_dir()
    assert (workdir / ".agent" / "trace.jsonl").is_file()
    assert result.trace_path


def test_tool_error_does_not_kill_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """单次工具失败应回灌给模型，而不是终止整个循环。"""
    captured = _patch_pipeline(monkeypatch, PIPELINE_ROW)
    scripted = ScriptedLLM(
        [
            _reply("no_such_tool", {}),                  # 未知工具 → 错误回灌
            _reply("write_plan", {"plan": GOOD_PLAN}),
            _reply("finish", {}),
        ]
    )
    monkeypatch.setattr(llm, "chat_tools", scripted)
    result = AgentEngine().run(_spec(budget=Budget(max_steps=10)), _ctx(tmp_path))
    assert result.ok is True
    assert captured["preset_plan"]
