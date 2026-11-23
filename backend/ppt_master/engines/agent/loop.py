"""Agent 引擎：Loop（调度）+ Harness（约束、验收、观测）的组装。

分界（见设计文档 §2.3）：

- **Loop**：``run()`` 主循环、预算、停滞检测、``chat_tools`` 双模。
- **Harness**：``tools``（门禁长在工具里）、``acceptance``（唯一裁判）、
  ``style_guard``（四道样式闸门）、``workspace``（快照/回滚/trace）、
  本模块里的 job log 兼容与 finish 次数限制。

两种模式：

- ``plan``  —— S1 阶段：只产出 plan，SVG 交给既有流水线（``preset_plan`` 注入）。
- ``full``  —— S2/S3 阶段：规划 + 逐页 SVG。

**验收权永不交给模型**：``finish`` 一定触发 ``acceptance``，模型说的"我修好了"
不算数。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from ppt_master.engines.agent import acceptance as acceptance_mod
from ppt_master.engines.agent import prompts as prompts_mod
from ppt_master.engines.agent.tools import Tool, build_tools
from ppt_master.engines.agent.workspace import Workspace, WorkspaceError
from ppt_master.engines.base import (
    AGENT_ENGINE,
    EngineError,
    EngineName,
    EngineResult,
    GenerateSpec,
    RunContext,
    TemplateEngine,
)

# finish 被拒后的最大重试次数；之后无论状态如何都终止（防止无限自我说服）
_MAX_FINISH_ATTEMPTS = 3
# 连续同签名步数触发停滞终止
_STALL_THRESHOLD = 2


class AgentEngine(TemplateEngine):
    """Loop + Harness 组装体。"""

    name: EngineName = AGENT_ENGINE

    # ------------------------------------------------------------------
    # TemplateEngine
    # ------------------------------------------------------------------

    def run(self, spec: GenerateSpec, ctx: RunContext) -> EngineResult:
        spec = spec.normalized()
        # Harness：前置校验。没有 Skill 就没有样式与验收，直接拒绝启动。
        try:
            ctx.bridge.ready()
        except EngineError as exc:
            return EngineResult.failure(AGENT_ENGINE, str(exc))

        # 默认走 plan 模式的原因：S1 变量最干净——只测"规划是否变强"，
        # SVG/样式/导出仍 100% 由 PPT Master 流水线负责。
        mode = "full" if spec.allow_page_reshuffle else "plan"

        return self._run_loop(spec, ctx, mode=mode)

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    def _run_loop(
        self, spec: GenerateSpec, ctx: RunContext, *, mode: str
    ) -> EngineResult:
        from llm import chat_tools, make_client_pool, tool_result_messages
        from config import llm_config

        log = ctx.log
        started = ctx.started_at
        run_id = uuid.uuid4().hex[:8]
        root = self._workdir(spec, run_id)
        ws = Workspace.create(root, style=spec.style, pages=spec.pages, mode=mode)

        if mode == "full":
            try:
                ws.project = ctx.bridge.init_project(f"ai-prept-agent-{run_id}")
                log(f"[agent] project={ws.project}\n")
            except Exception as exc:  # noqa: BLE001
                log(f"[agent] project init skipped: {exc}\n")

        tools = build_tools(
            ws, bridge=ctx.bridge, prompt=spec.prompt, mode=mode
        )
        tools["finish"] = self._finish_tool(ws, spec, ctx, mode=mode)

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": prompts_mod.system_prompt(
                    style=spec.style, pages=spec.pages, mode=mode, prompt=spec.prompt
                ),
            },
            {
                "role": "user",
                "content": (
                    "开始。先用 read_style_card 读一下本次要用的风格卡，"
                    f"然后产出 {spec.pages} 页的规划。"
                    if mode == "plan"
                    else "开始。先读风格卡，再规划页表，然后逐页写 SVG。"
                ),
            },
        ]

        cfg = llm_config()
        pool = make_client_pool(cfg)
        tool_specs = [t.spec() for t in tools.values()]

        finish_attempts = 0
        last_verdict: dict[str, Any] | None = None

        for step in range(1, spec.budget.max_steps + 1):
            # Harness：预算（三重）——到顶就降级交付，不续期
            over = self._budget_exceeded(spec, ws, ctx)
            if over:
                return self._degrade(ws, spec, ctx, reason=over)

            # Loop：一轮模型调用
            ws.llm_calls += 1
            self._job_log(f"[agent-step] n={step} phase=call mode={mode}\n")
            try:
                reply = chat_tools(
                    model=cfg.model,
                    messages=messages,
                    tools=tool_specs,
                    pool=pool,
                    temperature=0.3,
                )
            except Exception as exc:  # noqa: BLE001 - 传输层失败收敛为降级
                return self._degrade(ws, spec, ctx, reason=f"模型调用失败：{exc}")

            call = reply.calls[0] if reply.calls else None
            if call is None:
                # 模型直接说了话但没调工具：提醒一次，不消耗额外预算
                messages.append(
                    {"role": "assistant", "content": reply.text or "(empty)"}
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "请用工具调用推进；没有问题就调用 finish。"
                            "工具清单与 JSON 协议见 system 消息。"
                        ),
                    }
                )
                continue

            # finish 特判：必须走独立验收
            if call.name == "finish":
                finish_attempts += 1
                verdict = self._verify(ws, spec, ctx, mode=mode)
                last_verdict = verdict.to_payload()
                self._job_log(
                    f"[agent-gate] n={step} finish=1 ok={int(verdict.ok)} "
                    f"blocking={len(verdict.blocking)}\n"
                )
                if verdict.ok:
                    return self._accept(ws, spec, ctx, mode=mode)
                if finish_attempts >= _MAX_FINISH_ATTEMPTS:
                    return self._degrade(
                        ws,
                        spec,
                        ctx,
                        reason=(
                            f"finish 连续 {finish_attempts} 次被拒；"
                            f"首个阻塞项：{verdict.blocking[0] if verdict.blocking else 'unknown'}"
                        ),
                        findings=verdict.blocking,
                    )
                messages.append(reply.assistant_message or {"role": "assistant", "content": reply.text})
                messages.extend(
                    tool_result_messages(reply, call, verdict.to_payload())
                )
                continue

            # 普通工具：分发 + 快照/trace + 停滞检测
            tool = tools.get(call.name)
            t0 = time.time()
            if tool is None:
                result: dict[str, Any] = {
                    "ok": False,
                    "error": f"未知工具 {call.name}；可用：{', '.join(sorted(tools))}",
                }
            else:
                try:
                    result = tool.handler(call.args)
                except Exception as exc:  # noqa: BLE001 - 工具异常不终止循环
                    result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            elapsed_ms = int((time.time() - t0) * 1000)

            signature = ""
            if not result.get("ok"):
                blocking = result.get("blocking") or [result.get("error") or ""]
                signature = f"{call.name}:{'|'.join(str(b)[:60] for b in blocking[:3])}"
            ws.record_step(
                tool=call.name,
                args=call.args,
                result=result,
                elapsed_ms=elapsed_ms,
                signature=signature,
            )
            self._job_log(
                f"[agent-step] n={step} tool={call.name} "
                f"ok={int(bool(result.get('ok')))} ms={elapsed_ms}\n"
            )

            messages.append(
                reply.assistant_message
                or {"role": "assistant", "content": reply.text}
            )
            messages.extend(tool_result_messages(reply, call, result))

            # Harness：停滞检测（连续同样的失败 → 终止，不烧预算）
            if ws.stalled(_STALL_THRESHOLD):
                return self._degrade(
                    ws,
                    spec,
                    ctx,
                    reason=f"连续 {_STALL_THRESHOLD} 步相同动作与相同错误，判定卡死",
                    findings=[signature],
                )
            # Harness：上下文控制——旧步压缩，避免 messages 无限膨胀
            messages = self._compact(messages)

        return self._degrade(
            ws, spec, ctx, reason=f"达到步数上限 {spec.budget.max_steps}"
        )

    # ------------------------------------------------------------------
    # finish 工具
    # ------------------------------------------------------------------

    def _finish_tool(
        self, ws: Workspace, spec: GenerateSpec, ctx: RunContext, *, mode: str
    ) -> Tool:
        def handler(args: dict[str, Any]) -> dict[str, Any]:
            verdict = self._verify(ws, spec, ctx, mode=mode)
            payload = verdict.to_payload()
            payload["summary"] = str(args.get("summary") or "")[:400]
            if str(args.get("reason") or "").strip():
                payload["model_reason"] = str(args["reason"])[:400]
            return payload

        return Tool(
            name="finish",
            description=(
                "声明完成。会立刻触发独立复检（结构/几何/样式/质检），"
                "不通过时返回具体 blocking 清单。不要用它试探——每次都会重跑验收。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "一句话说明完成了什么"},
                    "reason": {
                        "type": "string",
                        "description": "若某缺陷确实无法修复，在此说明原因",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=handler,
        )

    # ------------------------------------------------------------------
    # Harness helpers
    # ------------------------------------------------------------------

    def _verify(
        self, ws: Workspace, spec: GenerateSpec, ctx: RunContext, *, mode: str
    ) -> acceptance_mod.Verdict:
        """唯一验收入口。agent 永远比流水线更严：不接受 soft-pass。"""
        if mode == "plan":
            return acceptance_mod.check_plan_stage(ws, spec.prompt)
        return acceptance_mod.check_full_stage(
            ws, spec.prompt, ctx.bridge, strict=True
        )

    def _budget_exceeded(
        self, spec: GenerateSpec, ws: Workspace, ctx: RunContext
    ) -> str | None:
        if ws.llm_calls >= spec.budget.max_llm_calls:
            return f"LLM 调用数达到上限 {spec.budget.max_llm_calls}"
        if ctx.elapsed() >= spec.budget.max_wall_seconds:
            return f"墙钟时间达到上限 {spec.budget.max_wall_seconds:.0f}s"
        if ws.tokens >= spec.budget.max_tokens:
            return f"token 用量达到上限 {spec.budget.max_tokens}"
        return None

    def _accept(
        self, ws: Workspace, spec: GenerateSpec, ctx: RunContext, *, mode: str
    ) -> EngineResult:
        """验收通过后的交付。

        plan 模式：把 plan 交给流水线 ``preset_plan`` 走完 SVG→PPTX→HTML，
        这保证样式/编译/质检仍是 PPT Master 的那一套。
        """
        if mode == "plan":
            return self._deliver_via_pipeline(ws, spec, ctx)
        return self._deliver_direct(ws, spec, ctx)

    def _deliver_via_pipeline(
        self, ws: Workspace, spec: GenerateSpec, ctx: RunContext
    ) -> EngineResult:
        from ppt_master.pipeline import run_one_package

        plan = ws.load_plan()
        ctx.log(
            f"[agent] plan accepted in {ws.llm_calls} calls; "
            "handing off to pipeline (preset_plan)\n"
        )
        started = time.time()
        try:
            row = run_one_package(
                spec.prompt,
                pages=spec.pages,
                visual_style=spec.style,
                template_id=spec.template_id,
                out_root=spec.out_root,
                mock=ctx.mock,
                skip_images=None if spec.with_images is None else not spec.with_images,
                palette_refine=spec.palette_refine,
                slide_concurrency=spec.slide_concurrency,
                fast_preview=spec.fast_preview,
                svg_repair=spec.svg_repair,
                quality_gate=spec.quality_gate,
                strip_unsupported=spec.strip_unsupported,
                preset_plan=plan,
                log=ctx.log,
            )
        except Exception as exc:  # noqa: BLE001
            return EngineResult.failure(AGENT_ENGINE, f"流水线交付失败：{exc}")

        result = EngineResult.from_pipeline_row(
            row if isinstance(row, dict) else {},
            wall_seconds=ctx.elapsed(),
        )
        result.engine = AGENT_ENGINE
        result.steps = len(ws.trace)
        result.llm_calls = ws.llm_calls
        result.trace_path = str(ws.root / ".agent" / "trace.jsonl")
        result.raw["agent_plan_handoff"] = True
        result.raw["agent_steps"] = result.steps
        return result

    def _deliver_direct(
        self, ws: Workspace, spec: GenerateSpec, ctx: RunContext
    ) -> EngineResult:
        """full 模式：导出 PPTX 并落模板包。"""
        from ppt_master.pipeline import _convert_to_html_slide, _write_usage_into_template
        from public_id import alloc_public_template_id

        out_root = (spec.out_root or self._default_out_root()).resolve()
        out_root.mkdir(parents=True, exist_ok=True)
        tid = spec.template_id or alloc_public_template_id(out_root)
        ctx.log(f"[agent] exporting pptx tid={tid}\n")
        drafts = out_root.parent / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        pptx_path = drafts / f"{tid}.pptx"
        try:
            ctx.bridge.export_pptx(
                ws.project or ws.root, pptx_path, flags=["--quick-generate"]
            )
            pack_dir = _convert_to_html_slide(
                pptx_path,
                template_id=tid,
                out_root=out_root,
                log=ctx.log,
                pack_format="ppt-master",
                label_zh=str((ws.plan or {}).get("label_zh") or tid),
                category=str((ws.plan or {}).get("category") or spec.style),
            )
        except Exception as exc:  # noqa: BLE001
            return EngineResult.failure(
                AGENT_ENGINE,
                f"导出失败：{exc}",
                trace_path=str(ws.root / ".agent" / "trace.jsonl"),
            )

        usage = {"page_tokens": 0, "image_tokens": 0, "image_count": 0}
        try:
            _write_usage_into_template(pack_dir, usage)
        except Exception:  # noqa: BLE001 - 用量写入失败不影响交付
            pass

        result = EngineResult(
            engine=AGENT_ENGINE,
            status="accepted",
            ok=True,
            template_id=tid,
            output_dir=str(pack_dir),
            project_dir=str(ws.project or ws.root),
            quality_gate="agent-verified",
            render="svg",
            steps=len(ws.trace),
            llm_calls=ws.llm_calls,
            wall_seconds=ctx.elapsed(),
            usage=usage,
            trace_path=str(ws.root / ".agent" / "trace.jsonl"),
        )
        return result

    def _degrade(
        self,
        ws: Workspace,
        spec: GenerateSpec,
        ctx: RunContext,
        *,
        reason: str,
        findings: list[str] | None = None,
    ) -> EngineResult:
        """预算/停滞/多次被拒时的降级交付。

        与旧管线最大的产品差异：**不抛错、不整包作废**。
        带着当前产物、trace、缺陷清单返回 ``partial``，人能接着修。
        """
        ctx.log(f"[agent-finish] status=partial reason={reason}\n")
        trace = ws.root / ".agent" / "trace.jsonl"
        have_plan = ws.plan_path.is_file()
        payload: dict[str, Any] = {
            "ok": False,
            "partial": True,
            "agent_reason": reason,
            "agent_steps": len(ws.trace),
            "agent_llm_calls": ws.llm_calls,
            "agent_workdir": str(ws.root),
            "has_plan": have_plan,
            "findings": [{"detail": f} for f in (findings or [])],
            "trace_path": str(trace),
        }
        return EngineResult(
            engine=AGENT_ENGINE,
            status="partial",
            ok=False,
            project_dir=str(ws.project or ws.root),
            steps=len(ws.trace),
            llm_calls=ws.llm_calls,
            wall_seconds=ctx.elapsed(),
            trace_path=str(trace),
            findings=payload["findings"],
            reason=reason,
            raw=payload,
        )

    # ------------------------------------------------------------------
    # 观测性：Admin job 日志兼容
    # ------------------------------------------------------------------

    @staticmethod
    def _job_log(line: str) -> None:
        """按 Admin 解析器认识的形状输出。

        ``admin/jobs.py`` 的 ``_append_log`` 靠正则抓 ``[xxx]`` 行推进度；
        agent 每步必须打同格式日志，否则前端进度条与页列表全废。
        """
        import sys

        print(line, end="" if line.endswith("\n") else "\n", file=sys.stdout, flush=True)

    @staticmethod
    def _compact(messages: list[dict[str, Any]], *, keep_tail: int = 14) -> list[dict[str, Any]]:
        """上下文控制：把早期工具结果折叠成一行摘要。

        一页 SVG 完整重写就是 15KB，反复改会爆。保留 system + 首条 user +
        最近 ``keep_tail`` 条，中间折叠。
        """
        if len(messages) <= keep_tail + 4:
            return messages
        head = messages[:2]
        tail = messages[-keep_tail:]
        dropped = len(messages) - len(head) - len(tail)
        summary = {
            "role": "user",
            "content": (
                f"（上下文已压缩：省略了中间 {dropped} 条工具交互记录。"
                "需要具体内容时用 read_plan / read_page 重新读取，不要凭记忆推断。）"
            ),
        }
        return head + [summary] + tail

    # ------------------------------------------------------------------
    # 路径
    # ------------------------------------------------------------------

    @staticmethod
    def _default_out_root() -> Path:
        from ppt_master.paths import repo_root

        return repo_root() / "agent-output"

    @staticmethod
    def _workdir(spec: GenerateSpec, run_id: str) -> Path:
        from ppt_master.paths import repo_root

        base = repo_root() / ".agent-runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{run_id}"
        base.mkdir(parents=True, exist_ok=True)
        return base
