"""生成引擎：``pipeline``（旧流水线）与 ``agent``（Loop + Harness）。

对外只需 ``base`` 里的契约与 ``build_engine`` 工厂：

    from ppt_master.engines import GenerateSpec, RunContext, build_engine

    engine = build_engine("pipeline")
    result = engine.run(GenerateSpec(prompt="..."), ctx)
"""

from ppt_master.engines.base import (
    AGENT_ENGINE,
    PIPELINE_ENGINE,
    SUPPORTED_ENGINES,
    Budget,
    EngineError,
    EngineName,
    EngineResult,
    EngineStatus,
    GenerateSpec,
    RunContext,
    SkillBridge,
    TemplateEngine,
    build_engine,
    resolve_engine_name,
)

__all__ = [
    "AGENT_ENGINE",
    "PIPELINE_ENGINE",
    "SUPPORTED_ENGINES",
    "Budget",
    "EngineError",
    "EngineName",
    "EngineResult",
    "EngineStatus",
    "GenerateSpec",
    "RunContext",
    "SkillBridge",
    "TemplateEngine",
    "build_engine",
    "resolve_engine_name",
]
