"""流水线引擎：对现有 ``run_one_package`` 的薄包装。

**这一层的存在意义是"零行为变化"**：它必须产生与直接调用 ``run_one_package``
完全相同的产物与日志，只额外做两件事：

1. 把输入从 ``GenerateSpec`` 翻译成旧函数的关键字参数；
2. 把返回行翻译成 ``EngineResult``（``from_pipeline_row``）。

任何"顺手改进"都不该发生在这里——否则 A/B 对比的差异就不再只来自引擎。
"""

from __future__ import annotations

import time

from ppt_master.engines.base import (
    PIPELINE_ENGINE,
    EngineName,
    EngineResult,
    GenerateSpec,
    RunContext,
    TemplateEngine,
)


class PipelineEngine(TemplateEngine):
    """把 8 阶段硬编排流水线包装成统一引擎接口。"""

    name: EngineName = PIPELINE_ENGINE

    def run(self, spec: GenerateSpec, ctx: RunContext) -> EngineResult:
        from ppt_master.pipeline import run_one_package

        spec = spec.normalized()
        started = time.time()
        # None 保持 None：让 _want_images() 继续按环境变量决定，避免改变旧行为。
        skip_images: bool | None = (
            None if spec.with_images is None else not spec.with_images
        )
        try:
            row = run_one_package(
                spec.prompt,
                pages=spec.pages,
                visual_style=spec.style,
                template_id=spec.template_id,
                out_root=spec.out_root,
                mock=ctx.mock,
                skip_images=skip_images,
                palette_refine=spec.palette_refine,
                slide_concurrency=spec.slide_concurrency,
                fast_preview=spec.fast_preview,
                svg_repair=spec.svg_repair,
                quality_gate=spec.quality_gate,
                strip_unsupported=spec.strip_unsupported,
                log=ctx.log,
            )
        except Exception as exc:  # noqa: BLE001 - 引擎边界统一收敛为结果
            return EngineResult.failure(
                PIPELINE_ENGINE, str(exc), trace_path=None
            )
        result = EngineResult.from_pipeline_row(
            row if isinstance(row, dict) else {}, wall_seconds=time.time() - started
        )
        result.engine = PIPELINE_ENGINE
        return result
