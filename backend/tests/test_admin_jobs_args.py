"""Admin 任务参数拼装：引擎选择与 package-only 线路。

这些断言只覆盖"命令行参数是否按预期拼出来"，不启动子进程。
关键不变量：

1. 默认（pipeline）不出现 ``--engine`` / ``--package-only``，旧行为零变化；
2. agent 线路带 ``--engine agent`` 与步数上限；
3. 只有 agent + package_only 才追加 ``--package-only``。
"""

from __future__ import annotations

from pathlib import Path

from admin.jobs import _build_ppt_master_args


def _args(**over: object) -> list[str]:
    base: dict[str, object] = dict(
        count=1,
        pages=5,
        visual_style="dark-tech",
        style_intent="",
        ensure_style=False,
        mock=True,
        skip_image=True,
        palette_refine=False,
        quality_gate="soft",
        svg_repair=True,
        strip_unsupported=True,
        report_path=Path("/tmp/r.json"),
        hint="发布会",
    )
    base.update(over)
    return _build_ppt_master_args(**base)  # type: ignore[arg-type]


def test_default_pipeline_args_unchanged() -> None:
    args = _args()
    assert "--engine" not in args
    assert "--agent-full" not in args
    assert "--package-only" not in args
    assert args[-2:] == ["--", "发布会"]


def test_agent_args_carry_engine_and_steps() -> None:
    args = _args(engine="agent", agent_max_steps=12)
    assert args[args.index("--engine") + 1] == "agent"
    assert args[args.index("--agent-max-steps") + 1] == "12"
    assert "--agent-full" not in args
    assert "--package-only" not in args


def test_agent_full_and_package_only() -> None:
    args = _args(engine="agent", agent_full=True, package_only=True)
    assert "--agent-full" in args
    assert "--package-only" in args
    assert args[-2] == "--"


def test_package_only_ignored_for_pipeline_engine() -> None:
    """流水线引擎没有"只出 PPTX"这条路，参数里不该出现该开关。"""
    args = _args(engine="pipeline", package_only=True)
    assert "--package-only" not in args
