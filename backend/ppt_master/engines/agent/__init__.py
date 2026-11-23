"""Agent 引擎（Loop + Harness）。

对外只需要 ``AgentEngine``：

    from ppt_master.engines.agent import AgentEngine
    result = AgentEngine().run(spec, ctx)

模块划分（对应设计文档 §2.3 的 Loop / Harness 分界）：

| 模块 | 归属 | 职责 |
|---|---|---|
| ``loop`` | Loop | 主循环、预算、停滞检测、finish 强制复检 |
| ``tools`` | Harness | 工具表；门禁长在工具里 |
| ``acceptance`` | Harness | 唯一裁判，模型无法绕过 |
| ``style_guard`` | Harness | 四道样式一致性闸门 |
| ``workspace`` | Harness | 状态外置、快照回滚、trace |
| ``prompts`` | Harness | 精简后的 system prompt |
"""

from ppt_master.engines.agent.loop import AgentEngine

__all__ = ["AgentEngine"]
