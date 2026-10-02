from __future__ import annotations

SYSTEM_VISUAL_SPEC = """你是设计规范作者。只输出 Markdown 正文（visual-spec.md），不要代码围栏包裹全文。

你会收到：模板元数据、theme.css 摘录、**每一页的 HTML 指纹**（槽位/配色/字号/圆角/图片）、以及若干页的 HTML 摘录（可能中间截断）。

必须依据观察到的页面与 theme 写规范，禁止凭空编造未出现的色板、形态或组件。摘录不完整时以指纹与 theme 为准；页内精确几何仍以 slides/*.html 为准。

含：色板、形态档（sharp|soft|rounded|pill）、字体、间距/圆角 token、layout 清单、组件、图表、配图、槽位策略、避免项、锁定 vs 可编辑。
"""


def user_visual_spec(*, deck_json: str) -> str:
    return f"""根据以下已读页面的规划上下文写 visual-spec.md（中文为主）。

上下文含 pages（全页指纹）、html_excerpts（代表性页面 HTML 摘录）、theme_css_excerpt、slot_role_summary。

{deck_json}

额外写明：记录色板、形态档、结构清单与禁用项；槽位策略须对齐 pages[].slots / slot_role_summary。
"""
