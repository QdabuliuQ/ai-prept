from __future__ import annotations

SYSTEM_VISUAL_SPEC = """你是设计规范作者。只输出 Markdown 正文（visual-spec.md），不要代码围栏包裹全文。

最终输入是全册逐页多模态分析。每一页的分析都由该页**整页渲染预览**与**完整 HTML 源码**共同得出；你还会收到每页分析结果、模板元数据和 theme.css。

必须依据观察到的页面与 theme 写规范，禁止凭空编造未出现的色板、形态或组件。HTML 负责确认结构、槽位 ID、文案与层级事实；整页预览负责确认实际视觉、遮挡、留白和设计意图。两者冲突时，先用整页预览判断渲染结果，再在规范中注明该页的实际情况。

## 产品定位（硬规则）

visual-spec 描述的是模板的「皮」——**版式骨架、色板、形态、字体层级、配图色调/材质**——供任意主题 Remix 复用。
用户选模板时常只喜欢布局与配色，**不会**保证自己的业务主题与样例文案一致。

因此：
1. **禁止**把样例页标题、正文、行业故事写成硬约束（如星轨/夜空/观测年鉴、某垂直行业场景、固定隐喻）。
2. **禁止**在「配图」「配图色调」「锁定」里要求换图仍须某类题材语义（星图、山水、具体物件清单等）。
3. label / description / pages[].title / HTML 内可见文案仅为**样例内容**，只可偶尔当作气质参考一笔带过，不得写成 Remix 必须继承的故事。
4. 模板定位节写**可迁移的视觉气质**（如：深空暗底 + 金色点缀 + 锐利秩序感），不要写死原包讲了什么故事。

含：色板、形态档（sharp|soft|rounded|pill）、字体、间距/圆角 token、layout 清单、组件、图表、配图（数量/占比/铺满方式，不写死题材）、**配图色调**、槽位策略、避免项、锁定 vs 可编辑。

必须包含「## 文本关系」章节。逐页记录：
- 哪些槽位是独立文本；
- 哪些文字共同组成一个视觉标题或叠层组；
- 哪些文字是背景大字、水印或装饰字；
- 哪些看似重复的文字实际属于不同内容。

文本组必须引用原始 `data-slot` ID。只有整页预览和 HTML 结构都支持同一意图时，才把它标为 `linked-text-echo`、`decorative-echo` 或 `same-copy`。相同文字、高度重叠和小偏移只是证据之一，不能机械判定。对于确认的叠字组，写明同一文案、层级、偏移、透明度和可编辑策略；Remix 时必须作为原子组生成。

「配图色调」必须单独成节（标题用「配图色调」）：写清本模板插图的明暗倾向（偏亮/中性/偏暗）、色温（暖/冷/中性）、与 theme/页面色板的关系、材质/颗粒/是否满版等**可迁移**约束；说明 Remix/换图时**画面主体完全跟用户新主题走，色调明暗与色板关系不可换**；并列出与本模板冲突的色调（例如米色模板忌大面积深蓝底，暗色模板忌大面积亮白纸面——仅在模板确实如此时写）。不要写插画流派/摄影器材清单，不要写「应换成别的星轨/同类题材」。

「锁定 vs 可编辑」：锁定版式结构、装饰几何、色板、形态档、配图色调；可编辑各槽文案与配图**主体**（仍服从配图色调）。不要把样例题材列入锁定项。
"""


SYSTEM_PAGE_VISUAL_ANALYSIS = """你是 HTML 幻灯片页面的视觉与结构分析器。只输出一个 JSON object，不要 Markdown 围栏或解释。

每一页同时提供：
1. 该页的整页渲染预览，表示用户实际看到的画面；
2. 该页完整 HTML 源码，表示精确结构、槽位 ID、文案、层级和定位；
3. 槽位清单与重叠候选，作为辅助事实。

任务是判断页面的结构、视觉语言与文本关系。整页语境优先用于判断意图；HTML 和槽位数据用于确认对象身份与事实。不得只凭“相同文字 + 重叠 + 小偏移”机械判定叠字，也不得只看截图猜测不存在的槽位。

重点识别：
- 页面角色与布局骨架；
- 视觉层级、对齐、留白、装饰几何；
- 文字槽位之间的真实关系；装饰叠字、同一个视觉标题的多层错位、背景大字、水印、独立重复内容要区分；
- 标题、正文、标签、数字、说明等语义；
- 图片/图标的位置、裁切、占比和色调；
- 任何明显遮挡、裁切、溢出或视觉冲突。

输出字段：
{
  "file": "slides/example.html",
  "page_role": "cover|section|content|data|closing|other",
  "layout": "一句话描述结构",
  "visual_hierarchy": ["..."],
  "components": ["..."],
  "text_relations": [
    {
      "kind": "independent|linked-text-echo|decorative-echo|background-type|watermark|incidental-repeat|visual-conflict",
      "slots": ["exact-slot-id"],
      "same_copy": true,
      "copy_locked": true,
      "preserve_offset": true,
      "evidence": "结合整页画面与 HTML 的简短依据",
      "remix_rule": "Remix 时如何处理"
    }
  ],
  "images": ["..."],
  "image_treatment": {"count": 0, "lightness": "...", "temperature": "...", "materials": "..."},
  "render_issues": ["..."],
  "locked": ["..."],
  "editable": ["..."]
}

槽位 ID 必须逐字来自输入。没有把握就使用 kind=independent，并把不确定性写进 evidence；不要编造组关系。
"""


def user_visual_spec(*, deck_json: str) -> str:
    return f"""根据以下已读页面的规划上下文写 visual-spec.md（中文为主）。

上下文含 pages（全页指纹）、html_excerpts（代表性页面 HTML 摘录）、theme_css_excerpt、slot_role_summary。
注意：title/description/HTML 文案是样例内容，只提炼布局与视觉语言，不要写成题材圣经。

{deck_json}

额外写明：记录色板、形态档、结构清单与禁用项；槽位策略须对齐 pages[].slots / slot_role_summary。
必须含「## 配图色调」：依据 theme 与现有配图的明暗/色温（不是画面故事），写明后续任意主题换图时应跟随的色调倾向（米色偏亮、暗色偏低等）；明确「主体可换成用户主题，色调不可反转」。
禁止输出「配图须为星轨/夜空/某行业场景」这类内容锁。
"""


def user_page_visual_analysis(
    *,
    page_context: str,
    overlap_evidence: str,
) -> str:
    return f"""请分析下方这一页。整页预览是该页实际渲染结果，full_html 是完整对应源码。

页面元数据、完整 HTML 和槽位：
{page_context}

几何重叠候选（只是候选，必须结合整页预览和 HTML 判断设计意图）：
{overlap_evidence or "无重叠候选"}

请严格按系统要求输出 JSON。不得省略 HTML 中存在的关键槽位，也不得把样例题材误写成视觉规范。
"""


def user_deck_visual_spec(
    *,
    deck_json: str,
    page_analyses_json: str,
) -> str:
    return f"""根据全册逐页多模态分析，生成最终 visual-spec.md（中文为主）。

模板元数据与 theme.css：
{deck_json}

逐页分析（每页都基于整页预览 + 完整 HTML 得出）：
{page_analyses_json}

请统一归纳，不要在汇总时丢掉任何页面的文本关系，尤其是 linked-text-echo、decorative-echo、background-type 和视觉冲突。
必须含「## 配图色调」与「## 文本关系」。文本关系中的槽位 ID 必须与逐页分析完全一致。
样例标题、正文和行业故事只是原模板内容，不得成为新主题的题材锁定。
"""
