from __future__ import annotations

SYSTEM_VISUAL_SPEC = """你是设计规范作者。只输出 Markdown 正文（visual-spec.md），不要代码围栏包裹全文。
含：色板、形态档（sharp|soft|rounded|pill）、字体、间距/圆角 token、layout 清单、组件、图表、配图、槽位策略、避免项、锁定 vs 可编辑。
（本提示用于「上传时补生成 visual-spec」。）"""


def user_visual_spec(*, deck_json: str) -> str:
    return f"""根据以下精简规划写 visual-spec.md（中文为主）：

{deck_json}

额外写明：记录色板、形态档、结构清单与禁用项。
"""
