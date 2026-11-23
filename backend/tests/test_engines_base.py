"""引擎接口层：契约、形状适配、引擎解析。

这一层是 A/B 对比的地基——测试重点不是"生成得好不好"，而是
**旧引擎零行为变化**、**结果形状可回写**、**状态映射正确**。
"""

from __future__ import annotations

import pytest

from ppt_master.engines.base import (
    AGENT_ENGINE,
    PIPELINE_ENGINE,
    Budget,
    EngineError,
    EngineResult,
    GenerateSpec,
    resolve_engine_name,
)


def test_resolve_engine_name_defaults_to_pipeline() -> None:
    assert resolve_engine_name(None) == PIPELINE_ENGINE
    assert resolve_engine_name("") == PIPELINE_ENGINE
    assert resolve_engine_name("  ") == PIPELINE_ENGINE


def test_resolve_engine_name_accepts_both() -> None:
    assert resolve_engine_name("pipeline") == PIPELINE_ENGINE
    assert resolve_engine_name(" AGENT ") == AGENT_ENGINE


def test_resolve_engine_name_rejects_unknown() -> None:
    with pytest.raises(EngineError):
        resolve_engine_name("langgraph")


def test_budget_rejects_nonsense() -> None:
    with pytest.raises(EngineError):
        Budget(max_steps=0)
    with pytest.raises(EngineError):
        Budget(max_wall_seconds=0)
    with pytest.raises(EngineError):
        Budget(max_tokens=0)


def test_spec_requires_prompt() -> None:
    with pytest.raises(EngineError):
        GenerateSpec(prompt="   ")


def test_spec_rejects_out_of_range_pages() -> None:
    with pytest.raises(EngineError):
        GenerateSpec(prompt="x", pages=2)
    with pytest.raises(EngineError):
        GenerateSpec(prompt="x", pages=13)


def test_spec_rejects_bad_quality_gate() -> None:
    with pytest.raises(EngineError):
        GenerateSpec(prompt="x", quality_gate="lenient")


def test_spec_normalized_clamps_and_strips() -> None:
    spec = GenerateSpec(prompt="  hi  ", style="  ", pages=7, slide_concurrency=99)
    norm = spec.normalized()
    assert norm.prompt == "hi"
    assert norm.style == "dark-tech"
    assert norm.slide_concurrency == 8


# ---------------------------------------------------------------------------
# EngineResult 形状适配：这是"旧引擎零行为变化"的保证点
# ---------------------------------------------------------------------------


def test_from_pipeline_row_accepted() -> None:
    row = {
        "ok": True,
        "template_id": "abc",
        "output_dir": "/tmp/out",
        "project": "/tmp/project",
        "quality_gate": "passed",
        "render": "svg",
        "page_tokens": 1200,
        "image_tokens": 0,
        "image_count": 2,
    }
    result = EngineResult.from_pipeline_row(row, wall_seconds=9.5)
    assert result.engine == PIPELINE_ENGINE
    assert result.status == "accepted"
    assert result.ok is True
    assert result.template_id == "abc"
    assert result.usage["page_tokens"] == 1200
    assert result.usage["image_count"] == 2
    assert result.wall_seconds == 9.5


def test_from_pipeline_row_soft_pass() -> None:
    row = {"ok": True, "quality_gate": "soft-pass-after-repair"}
    result = EngineResult.from_pipeline_row(row)
    assert result.status == "soft-pass"
    assert result.ok is True


def test_from_pipeline_row_export_fallback_is_partial() -> None:
    row = {"ok": True, "quality_gate": "export-fallback-svg"}
    result = EngineResult.from_pipeline_row(row)
    assert result.status == "partial"


def test_from_pipeline_row_failure() -> None:
    row = {"ok": False, "error": "boom"}
    result = EngineResult.from_pipeline_row(row)
    assert result.status == "failed"
    assert result.ok is False
    assert result.reason == "boom"


def test_to_row_preserves_original_fields() -> None:
    """回写必须保留原始行——Admin / report 消费方依赖旧字段。"""
    row = {
        "ok": True,
        "template_id": "t1",
        "needs_browser_convert": True,
        "quality_gate": "passed",
        "custom_future_field": "keep-me",
    }
    result = EngineResult.from_pipeline_row(row)
    out = result.to_row()
    assert out["template_id"] == "t1"
    assert out["needs_browser_convert"] is True
    assert out["custom_future_field"] == "keep-me"
    assert out["engine"] == PIPELINE_ENGINE
    assert out["engine_status"] == "accepted"


def test_failure_factory() -> None:
    result = EngineResult.failure(AGENT_ENGINE, "no skill")
    assert result.status == "failed"
    assert result.ok is False
    assert result.engine == AGENT_ENGINE
    assert result.reason == "no skill"
