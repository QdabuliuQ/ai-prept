"""验收契约（Harness 组件）：唯一裁判，模型无法绕过。

设计文档 §9：``finish`` 触发本模块，模型说"完成"永远不算数。

与旧管线的一处**刻意差异**：agent 默认按 ``strict`` 语义验收——质检必须全绿，
不接受 ``soft-pass``。原因：旧管线的 soft-pass 是给人兜底用的逃生通道，
agent 一旦拥有它就会学会"耗到预算就 soft-pass 交差"。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ppt_master.engines.agent import style_guard
from ppt_master.engines.agent.workspace import Workspace, WorkspaceError
from ppt_master.engines.base import SkillBridge

_MAX_DETAILS = 12


@dataclass
class Verdict:
    ok: bool
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "status": "accepted" if self.ok else "rejected",
            "blocking": self.blocking[:_MAX_DETAILS],
            "warnings": self.warnings[:_MAX_DETAILS],
        }
        if not self.ok:
            payload["hint"] = (
                "修复上面这些 blocking 后再调用 finish；"
                "若确实无法修复，请调用 finish 并在 args.reason 中说明具体原因。"
            )
        return payload


def _page_errors(report: dict[str, Any], file_name: str | None = None) -> list[str]:
    """从质检报告里抽取人类的可读错误。"""
    out: list[str] = []
    for item in report.get("files") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("file") or Path(str(item.get("path") or "")).name)
        if file_name and name != file_name:
            continue
        for err in item.get("errors") or []:
            message = err if isinstance(err, str) else str(err.get("message") or err)
            out.append(f"{name}: {message}")
    return out


def check_plan_stage(ws: Workspace, prompt: str) -> Verdict:
    """plan 模式的验收：只验规划（S1 阶段用）。"""
    blocking: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    try:
        plan = ws.load_plan()
    except (WorkspaceError, json.JSONDecodeError) as exc:
        return Verdict(ok=False, blocking=[f"读取 plan 失败：{exc}"])

    slides = [s for s in (plan.get("slides") or []) if isinstance(s, dict)]
    declared = len(slides)

    # 1) 页数约束（按模式）——full 模式允许 agent 自行增减，plan 模式固定
    if ws.mode == "full":
        if not 3 <= declared <= 12:
            blocking.append(f"页数 {declared} 超出 3..12 范围")
    elif declared != ws.pages:
        blocking.append(
            f"页数 {declared} != 目标 {ws.pages}（plan 模式页数固定）"
        )
    checks["pages"] = declared

    # 2) 复用旧管线的几何/名册校验（不重新发明）
    from ppt_master.pipeline import _validate_plan

    try:
        _validate_plan(plan, declared)
        checks["plan_shape"] = "ok"
    except RuntimeError as exc:
        blocking.append(f"规划结构不合格：{exc}")
        checks["plan_shape"] = "failed"

    # 3) 四道样式闸门（同步部分）
    gate = style_guard.check_plan(plan, ws.style, prompt)
    blocking.extend(gate["blocking"])
    warnings.extend(gate["warnings"])
    checks["style_gates"] = "ok" if gate["ok"] else "failed"

    return Verdict(
        ok=not blocking,
        blocking=blocking,
        warnings=warnings,
        checks=checks,
    )


def check_full_stage(
    ws: Workspace,
    prompt: str,
    bridge: SkillBridge,
    *,
    strict: bool = True,
) -> Verdict:
    """full 模式的验收：规划 + 每页 SVG + 独立质检。"""
    blocking: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    plan_verdict = check_plan_stage(ws, prompt)
    blocking.extend(plan_verdict.blocking)
    warnings.extend(plan_verdict.warnings)
    checks.update(plan_verdict.checks)

    try:
        files = ws.slide_files()
    except (WorkspaceError, json.JSONDecodeError) as exc:
        return Verdict(ok=False, blocking=blocking + [f"读取页面清单失败：{exc}"])

    # 磁盘页数必须与 plan 声明一致（full 模式下 plan 由 agent 自己定）
    if len(files) != checks.get("pages"):
        blocking.append(
            f"plan 声明 {checks.get('pages')} 页，但解析出 {len(files)} 个页文件名"
        )

    missing: list[str] = []
    empty: list[str] = []
    for rel in files:
        path = ws.page_path(rel)
        if not path.is_file():
            missing.append(rel)
            continue
        if not path.read_text(encoding="utf-8").strip():
            empty.append(rel)
    if missing:
        blocking.append(f"缺少页面文件：{', '.join(missing[:6])}")
    if empty:
        blocking.append(f"页面文件为空：{', '.join(empty[:6])}")
    checks["files"] = len(files) - len(missing) - len(empty)

    # 独立质检：不信任模型，也不信任"已经 check 过"
    if not missing and not empty:
        try:
            passed, report = bridge.quality_report(_svg_project(ws))
        except Exception as exc:  # noqa: BLE001 - 质检失败即拒
            blocking.append(f"质检执行失败：{exc}")
            checks["quality"] = "error"
        else:
            checks["quality"] = "passed" if passed else "failed"
            if not passed:
                errors = _page_errors(report)
                if errors:
                    blocking.extend(errors[:8])
                else:
                    blocking.append("质检未通过（报告未给出页面级错误）")
                if not strict:
                    warnings.append("strict=False：质检未通过但仍允许交付（仅调试用）")

    return Verdict(
        ok=not blocking,
        blocking=blocking,
        warnings=warnings,
        checks=checks,
    )


def _svg_project(ws: Workspace) -> Path:
    """质检脚本要的工程目录。

    full 模式用 PPT Master 初始化的 project；若未初始化则退化为 workspace 根
    （质检脚本按 ``svg_output/*.svg`` 找页面，两者结构一致）。
    """
    return ws.project if ws.project is not None else ws.root
