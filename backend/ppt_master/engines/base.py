"""生成引擎接口：让旧流水线与 Agent 引擎可以互换、可对比。

设计原则（见 ``docs/agent-loop-design.md``）：

- **引擎只负责调度**，样式、编译、验收永远来自 PPT Master（外部 Skill）。
- **Loop 与 Harness 分离**：本模块只定义两者共用的契约；Harness 的实现
  （验收、样式闸门、快照、trace）在各自引擎内，但对调用方接口一致。
- 旧引擎必须能零行为变化地包装进来，否则 A/B 对比没有意义。

术语：

- ``GenerateSpec``  一次生成任务的不可变输入。
- ``Budget``        硬预算，引擎不得自行放宽。
- ``EngineResult``  一次生成的结构化结果，含 trace 与用量。
- ``SkillBridge``   引擎访问 PPT Master Skill 的唯一通道（便于测试替身）。
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Literal

EngineName = Literal["pipeline", "agent"]
EngineStatus = Literal["accepted", "soft-pass", "partial", "failed"]

PIPELINE_ENGINE: EngineName = "pipeline"
AGENT_ENGINE: EngineName = "agent"
SUPPORTED_ENGINES: tuple[EngineName, ...] = (PIPELINE_ENGINE, AGENT_ENGINE)


class EngineError(RuntimeError):
    """引擎级失败：配置非法、前置依赖缺失等，不算"生成失败"。"""


@dataclass(frozen=True)
class Budget:
    """硬预算。到顶就降级交付，不允许模型或引擎自行续期。

    ``max_steps`` 只对 Agent 引擎有意义（流水线没有"步"的概念），
    其余三项对两者都生效。
    """

    max_steps: int = 40
    max_llm_calls: int = 60
    max_wall_seconds: float = 60 * 20
    max_tokens: int = 400_000

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise EngineError("Budget.max_steps 必须 ≥ 1")
        if self.max_llm_calls < 1:
            raise EngineError("Budget.max_llm_calls 必须 ≥ 1")
        if self.max_wall_seconds <= 0:
            raise EngineError("Budget.max_wall_seconds 必须 > 0")
        if self.max_tokens < 1:
            raise EngineError("Budget.max_tokens 必须 ≥ 1")


@dataclass(frozen=True)
class GenerateSpec:
    """一次模板生成任务的不可变输入。

    ``pages`` 是目标页数。Agent 引擎可以在 ``allow_page_reshuffle`` 为真时
    围绕它上下浮动（这是它相对流水线的核心自由度之一），流水线则严格要求相等。
    """

    prompt: str
    style: str = "dark-tech"
    pages: int = 7
    # True=强制生图，False=强制跳过，None=沿用环境变量 AGENT_SKIP_IMAGE
    with_images: bool | None = None
    quality_gate: str = "soft"
    palette_refine: bool = False
    fast_preview: bool = False
    svg_repair: bool = True
    strip_unsupported: bool = True
    slide_concurrency: int = 3
    out_root: Path | None = None
    template_id: str | None = None
    # Agent 专用自由度开关；流水线引擎忽略
    allow_page_reshuffle: bool = False
    allow_style_author: bool = False
    # True = 只导出 PPTX，不建 HTML 模板包（不写 template.json、不进浏览器转换队列）。
    # 后台「Agent Loop 生成方式」当前阶段只做到 PPTX，转 HTML 暂不接入。
    package_only: bool = False
    budget: Budget = field(default_factory=Budget)

    def __post_init__(self) -> None:
        if not (self.prompt or "").strip():
            raise EngineError("GenerateSpec.prompt 不能为空")
        if not 3 <= int(self.pages) <= 12:
            raise EngineError(f"GenerateSpec.pages 必须在 3..12，当前 {self.pages}")
        if self.quality_gate not in ("soft", "strict", "skip"):
            raise EngineError(
                f"GenerateSpec.quality_gate 必须是 soft/strict/skip，当前 {self.quality_gate!r}"
            )

    def normalized(self) -> "GenerateSpec":
        """收敛到流水线本来就接受的范围，保证两引擎输入可比。"""
        return replace(
            self,
            prompt=self.prompt.strip(),
            style=(self.style or "dark-tech").strip() or "dark-tech",
            pages=max(3, min(12, int(self.pages))),
            slide_concurrency=max(1, min(8, int(self.slide_concurrency))),
        )


@dataclass
class EngineResult:
    """一次生成的结构化结果。

    ``status`` 语义：

    - ``accepted``   全部验收通过（Agent 引擎要求 ``quality_gate=strict`` 级别）
    - ``soft-pass``  带已知缺陷交付（流水线 ``soft`` 模式）
    - ``partial``    预算/停滞导致的降级交付，产物可用但不完整
    - ``failed``     无可用产物
    """

    engine: EngineName
    status: EngineStatus
    ok: bool
    template_id: str | None = None
    output_dir: str | None = None
    project_dir: str | None = None
    quality_gate: str | None = None
    render: str | None = None
    steps: int = 0
    llm_calls: int = 0
    wall_seconds: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    trace_path: str | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def failure(
        cls, engine: EngineName, reason: str, *, trace_path: str | None = None
    ) -> "EngineResult":
        return cls(
            engine=engine,
            status="failed",
            ok=False,
            reason=reason,
            trace_path=trace_path,
        )

    @classmethod
    def from_pipeline_row(
        cls, row: dict[str, Any], *, wall_seconds: float = 0.0
    ) -> "EngineResult":
        """把 ``run_one_package`` 的返回行原样翻译成引擎结果。

        不改变任何字段语义，只做形状适配——这是"旧引擎零行为变化"的保证点。
        """
        ok = bool(row.get("ok"))
        gate = str(row.get("quality_gate") or "")
        if not ok:
            status: EngineStatus = "failed"
        elif gate.startswith("soft-pass"):
            status = "soft-pass"
        elif gate == "export-fallback-svg":
            status = "partial"
        else:
            status = "accepted"
        usage = {
            "page_tokens": int(row.get("page_tokens") or 0),
            "image_tokens": int(row.get("image_tokens") or 0),
            "image_count": int(row.get("image_count") or 0),
        }
        return cls(
            engine=PIPELINE_ENGINE,
            status=status,
            ok=ok,
            template_id=row.get("template_id"),
            output_dir=row.get("output_dir"),
            project_dir=row.get("project"),
            quality_gate=gate or None,
            render=row.get("render"),
            wall_seconds=wall_seconds,
            usage=usage,
            reason=row.get("error"),
            raw=dict(row),
        )

    def to_row(self) -> dict[str, Any]:
        """回写为旧格式行，保证 Admin / report 消费方不受影响。"""
        row = dict(self.raw)
        row.setdefault("ok", self.ok)
        row.setdefault("template_id", self.template_id)
        row.setdefault("output_dir", self.output_dir)
        row.setdefault("project", self.project_dir)
        row.setdefault("quality_gate", self.quality_gate)
        row["engine"] = self.engine
        row["engine_status"] = self.status
        row["steps"] = self.steps
        row["wall_seconds"] = round(self.wall_seconds, 2)
        if self.findings:
            row["findings"] = self.findings
        if self.trace_path:
            row["trace_path"] = self.trace_path
        if self.reason:
            row.setdefault("error", self.reason)
        return row


LogFn = Callable[[str], None]


class SkillBridge(abc.ABC):
    """访问 PPT Master Skill 的唯一通道。

    引擎不直接拼 ``skill_dir() / "scripts" / ...`` 路径，一律经过这里，
    以便：① 测试注入替身（无需真正解压 Skill）；② 后续替换实现。
    """

    @abc.abstractmethod
    def ready(self) -> None:
        """前置校验；不满足时抛 ``EngineError``。"""

    @abc.abstractmethod
    def init_project(self, name: str) -> Path:
        """通过 ``project_manager.py init`` 建工程目录（唯一脚手架入口）。"""

    @abc.abstractmethod
    def catalog(self) -> list[dict[str, Any]]:
        """风格卡目录（只读）。"""

    @abc.abstractmethod
    def style_card(self, style_id: str) -> str:
        """风格卡正文（只读）。"""

    @abc.abstractmethod
    def quality_report(self, project: Path, *, file_name: str | None = None) -> tuple[bool, dict[str, Any]]:
        """跑 ``svg_quality_checker.py``；``file_name`` 非空时只查单页。"""

    @abc.abstractmethod
    def export_pptx(
        self,
        project: Path,
        pptx_out: Path,
        *,
        flags: list[str],
    ) -> None:
        """调用 ``svg_to_pptx.py`` 导出。"""

    @abc.abstractmethod
    def export_argv(self, project: Path, pptx_out: Path, *, flags: list[str]) -> list[str]:
        """导出命令的 argv（供日志与测试断言）。"""


@dataclass
class RunContext:
    """引擎运行时共享上下文。"""

    log: LogFn
    bridge: SkillBridge
    mock: bool = False
    started_at: float = field(default_factory=time.time)
    cancelled: Callable[[], bool] | None = None

    def elapsed(self) -> float:
        return time.time() - self.started_at


class TemplateEngine(abc.ABC):
    """所有生成引擎实现的协议。

    调用方（CLI / Admin job）只依赖这个接口，不感知内部是流水线还是 Loop。
    """

    name: EngineName

    @abc.abstractmethod
    def run(self, spec: GenerateSpec, ctx: RunContext) -> EngineResult:
        ...


def resolve_engine_name(raw: str | None) -> EngineName:
    """把用户/配置输入规范化为引擎名；未知值报错而不是静默回退。"""
    value = (raw or "").strip().lower()
    if not value:
        return PIPELINE_ENGINE
    if value in SUPPORTED_ENGINES:
        return value  # type: ignore[return-value]
    raise EngineError(
        f"未知引擎 {raw!r}；可选：{', '.join(SUPPORTED_ENGINES)}"
    )


def build_engine(name: EngineName) -> TemplateEngine:
    """延迟导入，避免 CLI 只要 pipeline 时也把 agent 依赖拖进来。"""
    if name == PIPELINE_ENGINE:
        from ppt_master.engines.pipeline_engine import PipelineEngine

        return PipelineEngine()
    if name == AGENT_ENGINE:
        from ppt_master.engines.agent.loop import AgentEngine

        return AgentEngine()
    raise EngineError(f"未知引擎 {name!r}")
