"""Workspace：状态外置、快照回滚、停滞检测。

这些是 Harness 的核心保障——**agent 敢试错的前提**是能撤销。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ppt_master.engines.agent.workspace import Workspace, WorkspaceError, _safe_rel


@pytest.fixture()
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "run", style="dark-tech", pages=3, mode="plan")


SAMPLE_PLAN = {
    "template_id": "测试模板",
    "label_zh": "测试模板",
    "palette": {"bg": "#0A0E14", "text": "#F2F5F8"},
    "slides": [
        {"file": "01_cover.svg", "role": "cover"},
        {"file": "02_content.svg", "role": "content"},
        {"file": "03_ending.svg", "role": "ending"},
    ],
}


def test_safe_rel_rejects_traversal() -> None:
    with pytest.raises(WorkspaceError):
        _safe_rel("../etc/passwd")
    with pytest.raises(WorkspaceError):
        _safe_rel("/etc/passwd")
    with pytest.raises(WorkspaceError):
        _safe_rel("")


def test_safe_rel_accepts_nested() -> None:
    assert _safe_rel("svg_output/01.svg") == "svg_output/01.svg"


def test_create_makes_dirs(ws: Workspace) -> None:
    assert (ws.root / "svg_output").is_dir()
    assert (ws.root / "images").is_dir()
    assert (ws.root / ".agent" / "snapshots").is_dir()


def test_save_and_load_plan_roundtrip(ws: Workspace) -> None:
    ws.save_plan(SAMPLE_PLAN)
    assert ws.plan_path.is_file()
    # 模拟重启：丢掉内存态
    ws.plan = None
    loaded = ws.load_plan()
    assert loaded["template_id"] == "测试模板"
    assert len(loaded["slides"]) == 3


def test_load_plan_missing_raises(ws: Workspace) -> None:
    with pytest.raises(WorkspaceError):
        ws.load_plan()


def test_slide_files_follows_plan_order(ws: Workspace) -> None:
    ws.save_plan(SAMPLE_PLAN)
    assert ws.slide_files() == [
        "01_cover.svg",
        "02_content.svg",
        "03_ending.svg",
    ]


def test_write_and_read_page(ws: Workspace) -> None:
    ws.write_page("01_cover.svg", "<svg/>")
    assert ws.read_page("01_cover.svg").strip() == "<svg/>"


def test_read_missing_page_raises(ws: Workspace) -> None:
    with pytest.raises(WorkspaceError):
        ws.read_page("nope.svg")


def test_delete_page(ws: Workspace) -> None:
    ws.write_page("01_cover.svg", "<svg/>")
    assert ws.delete_page("01_cover.svg") is True
    assert ws.delete_page("01_cover.svg") is False


# ---------------------------------------------------------------------------
# 快照 / 回滚：agent 试错的安全网
# ---------------------------------------------------------------------------


def test_snapshot_and_rollback_restores_svg(ws: Workspace) -> None:
    ws.write_page("01_cover.svg", "<svg>v1</svg>")
    snap = ws.snapshot("before-edit")
    ws.write_page("01_cover.svg", "<svg>v2-broken</svg>")
    assert "v2" in ws.read_page("01_cover.svg")

    ws.rollback(snap)
    assert "v1" in ws.read_page("01_cover.svg")


def test_rollback_restores_plan(ws: Workspace) -> None:
    ws.save_plan(SAMPLE_PLAN)
    snap = ws.snapshot("after-plan")
    mutated = dict(SAMPLE_PLAN)
    mutated["template_id"] = "改坏了"
    ws.save_plan(mutated)
    ws.rollback(snap)
    ws.plan = None
    assert ws.load_plan()["template_id"] == "测试模板"


def test_rollback_latest_when_no_name(ws: Workspace) -> None:
    ws.write_page("01_cover.svg", "<svg>a</svg>")
    ws.snapshot("s1")
    ws.write_page("01_cover.svg", "<svg>b</svg>")
    ws.rollback("")
    assert "a" in ws.read_page("01_cover.svg")


def test_rollback_missing_snapshot_raises(ws: Workspace) -> None:
    with pytest.raises(WorkspaceError):
        ws.rollback("999")


def test_rollback_removes_pages_absent_from_snapshot(ws: Workspace) -> None:
    ws.write_page("01_cover.svg", "<svg/>")
    snap = ws.snapshot("one-page")
    ws.write_page("02_extra.svg", "<svg/>")
    ws.rollback(snap)
    assert not (ws.root / "svg_output" / "02_extra.svg").exists()


def test_snapshots_listed_in_order(ws: Workspace) -> None:
    ws.snapshot("a")
    ws.snapshot("b")
    assert ws.snapshots() == ["001", "002"]


# ---------------------------------------------------------------------------
# 停滞检测：防死循环
# ---------------------------------------------------------------------------


def _record(ws: Workspace, *, ok: bool, signature: str) -> None:
    ws.record_step(
        tool="write_page",
        args={"file": "x"},
        result={"ok": ok},
        elapsed_ms=1,
        signature=signature,
    )


def test_stalled_after_repeated_signature(ws: Workspace) -> None:
    _record(ws, ok=False, signature="write_page:overlap")
    _record(ws, ok=False, signature="write_page:overlap")
    assert ws.stalled(2) is True


def test_not_stalled_when_progressing(ws: Workspace) -> None:
    _record(ws, ok=False, signature="write_page:overlap")
    _record(ws, ok=False, signature="write_page:clipping")
    assert ws.stalled(2) is False


def test_successful_steps_do_not_count_as_stall(ws: Workspace) -> None:
    """成功的步骤签名留空，不应触发停滞判定。"""
    _record(ws, ok=True, signature="")
    _record(ws, ok=True, signature="")
    assert ws.stalled(2) is False


def test_trace_written_as_jsonl(ws: Workspace) -> None:
    _record(ws, ok=True, signature="")
    trace = ws.root / ".agent" / "trace.jsonl"
    assert trace.is_file()
    line = json.loads(trace.read_text(encoding="utf-8").strip())
    assert line["tool"] == "write_page"
    assert line["n"] == 1
