"""PPT Master 管线用 LLM 提示词（规范 SVG → DrawingML）。"""

from __future__ import annotations

import json

from ppt_master.styles import load_style_card

SYSTEM_PLAN = """你是演示文稿策划师，为 PPT Master Quick Generate 规划页表。只输出一个 JSON object，不要 markdown 围栏。

约束：
- 画布 16:9，SVG viewBox 固定 0 0 1280 720
- visual_style 必须严格等于用户指定的风格 id（见任务区），禁止擅自改成 dark-tech
- 可选 id：
  swiss-minimal | soft-rounded | glassmorphism | dark-tech | blueprint |
  editorial | photo-editorial | data-journalism | brutalist |
  memphis | zine | vintage-poster | paper-cut |
  sketch-notes | ink-notes | chalkboard | ink-wash | pixel-art |
  gallery-white | midnight-luxe | nordic-calm | kinetic-poster | dossier-archive
- palette 由模型为本册原创，须符合所选风格的用色纪律（明暗、强调色稀密度、是否近单色等）；禁止套用固定色板；禁止在非 tech 风格里沿用深蓝底+青紫霓虹
- template_id 与 label_zh 必须是**10–15 个汉字**的详细中文名（可含少量字母数字/间隔符），用作落地目录名与展示名
  · **命名 = 本册内容主题**（产品/活动/受众/议题），取自用户需求文案；**不是** visual_style 的中文译名或风格卡隐喻
  · visual_style 只规定「页面长什么样」（构图/装饰/字体性格）；同一风格可服务完全不同的主题
  · ✅ 例：用户要「AI 产品发布会」+ 风格 concert-stage →「星河智能产品发布会」「NovaMind发布手册」
  · ✅ 例：用户要「话剧首演」+ 同一风格 →「春日话剧首演手册」「城厢剧场开幕册」
  · ❌ 禁止把风格词写进包名：如「舞台灯光AI发布会」「代码编辑器风发布册」「氰版晒蓝产品手册」「胶印狂潮」——除非用户需求本身就是该题材
  · 禁止过短（如仅 2–4 字）；禁止纯英文 kebab-case（pixel-forge / ai-launch）
  · template_id 与 label_zh 通常相同；二者都须含汉字
- category 必须与所选 visual_style 相同（类型 = 视觉风格 id，例如 dark-tech / swiss-minimal）
  · 不要按内容主题另选 business/finance 等旧业务类；无法对应风格时用 other
  · 例：选用暗色科技 → category 与 visual_style 均为 "dark-tech"
- 每页 core_message 一句话；geometry / visual_hook 必须符合该风格的造型语法（例如 ink-notes=手绘线与括号，不是轨道粒子）
- 禁止说明书式三栏白卡套路；要有发布会/提案级冲击力
- 先设计一个贯穿全 deck 的视觉母题，但母题必须属于所选风格，而不是默认 HUD/雷达
- 页面构图必须有节奏变化：cover/section 留白，content 至少混合 2 种构图，数据页也用 role=content（用比例/趋势/对比而非装饰性数字）
- 每页 role 只能是：cover | toc | section | content | ending（收尾用 ending，禁止 closing/close；数据/能力页用 content，禁止 data/metrics）
- 每页必须有一个可被记住的 visual_hook；避免连续两页使用相同几何骨架
- 每页先分配 layout_regions，再描述 geometry：每个区域写 id、role、bounds=[x,y,w,h]、padding=[top,right,bottom,left]、clearance；区域必须位于 40..1240 × 40..680 安全区且互不相交。标题/正文/指标/页脚分别占区，装饰不占区但不得进入文字区的 clearance
- 文案具体，可用虚构产品名/数字；禁止赋能/闭环/引领等空词
- **图文分工（重要）**：
  · 生图负责本页「被人看见的图」：封面主视觉、背景大图、侧栏插图、产品/场景示意等；题材按页需要决定（照片/插画/产品图/氛围底均可），**不要默认半调/纸纹**
  · SVG 负责结构与装饰：色条、胶带、撕边、标签框、错位字、小几何；禁止用成百上千 SVG 小圆点去仿印刷纹理
  · 纯排版/数据卡页可 need_image=false
- 配图：封面/章节/强视觉内容页设 need_image=true，并写英文 image_hint（具体主体/场景/风格，禁止 logo/文字/letterbox）
- need_image=true 时写 image_role：background | hero | panel | illustration（说明图在版面中的职责）
- need_image=true 时根据 geometry 写 image_copy_safe（留给可编辑文字的低细节区域）与 image_focal（主体所在区域），例如 copy_safe="left 42%"、focal="right-center"；禁止让主体与标题争抢空间
- need_image=true 时必须写 image_aspect：按该页 geometry 实际槽位选
  1:1（圆形框/徽章/居中方图）| 16:9（满版出血）| 4:3（半版/分栏）| 3:4 或 9:16（竖侧栏）| 3:2 / 2:3
  禁止一律写 16:9；圆形装饰框必须 1:1
- image_file 由系统分配，规划里不要自造文件名
- 本阶段不输出 SVG

输出：
{
  "template_id": "十到十五字中文名（内容主题，须含汉字；禁止用风格名当书名）",
  "label_zh": "与 template_id 相同的中文展示名（10–15 字；主题≠风格）",
  "product": "产品或主题名",
  "category": "<必须等于 visual_style id，例如 dark-tech>",
  "visual_style": "<必须等于用户指定 id>",
  "mode": "showcase|briefing|pyramid|narrative|instructional",
  "palette": {
    "bg": "#......",
    "panel": "#......",
    "text": "#......",
    "muted": "#......",
    "accent": "#......",
    "accent2": "#......"
  },
  "slides": [
    {
      "file": "01_cover.svg",
      "role": "cover",
      "title": "封面标题",
      "core_message": "…",
      "geometry": "…",
      "layout_regions": [
        {"id": "title", "role": "page-title", "bounds": [72, 56, 1136, 96], "padding": [12, 16, 12, 16], "clearance": 12},
        {"id": "body", "role": "body", "bounds": [72, 176, 1136, 448], "padding": [16, 16, 16, 16], "clearance": 16}
      ],
      "visual_hook": "…",
      "density": "breathing|anchor|dense",
      "motif_use": "固定/变体/不使用",
      "need_image": true,
      "image_role": "hero",
      "image_aspect": "16:9",
      "image_copy_safe": "left 42%",
      "image_focal": "right-center",
      "image_hint": "full-bleed editorial photo or illustration of …, no text, no logo, edge-to-edge, no letterbox"
    }
  ]
}
"""

# Core SVG author rules (style-agnostic). Style-specific addons are appended by
# ``system_svg_for`` so non-matching styles do not pay for unused constraints.
SYSTEM_SVG = """你是 PPT Master 规范 SVG 作者。只输出完整 SVG XML（可含 XML 声明），不要 markdown 围栏，不要解释。

硬规则：
1. 根节点：xmlns、viewBox="0 0 1280 720"、data-pptx-page-role（cover|toc|section|content|ending）、font-family="Arial, Microsoft YaHei, sans-serif"
2. 背景矩形带 data-pptx-role="background"；装饰形可带 decoration
3. 所有可见文字必须包在带 data-pptx-bounds="x y w h" 的直接根级 <g> 中；bounds 须盖住字形且互不重叠（>1px）
4. 颜色用大写 #RRGGBB；字号无单位数字；禁止 foreignObject、script、滤镜（除非极简单 opacity）；**禁止 `<style>` / class / @font-face / @import**
5. 多行同一段落用一个 <text> + <tspan x="…" dy="…">；独立语义块分开
6. **视觉必须服从 plan.visual_style 与风格卡**：造型、留白、装饰密度、配色都按该风格执行；非 dark-tech 时禁止默认 HUD（粒子网格、青紫霓虹光晕、轨道环）
7. 文本用原始 Unicode，XML 特殊字符写成 &amp; &lt; &gt; &quot;
8. 不要 Master/Layout/placeholder 元数据（flat 页）
9. **凡带 data-pptx-role 的元素必须有唯一稳定 id**（如 id="bg"、id="accent-bar"）；根下每个可见 <g> 也必须有 id 与 data-pptx-bounds
10. data-pptx-bounds 要比文字 ink 更宽松（上下左右至少多 12px），且根级模块 bounds 互不重叠
11. 禁止在 <text> 内使用 HTML <span>；多行/强调只用 <tspan>
12. **满版装饰必须是根级 shape**（rect/circle/line/polygon/path），各自带 id + data-pptx-role="decoration"。禁止把它们包进带 data-pptx-bounds 的根级 <g> 去盖住文字模块
13. 禁止对零高度/零宽度的 <line> 使用 url(#…) 渐变描边；改用细 <rect> + fill="url(#…)"
14. 超大数字字号必须落在 viewBox 内（估算墨迹不超出 0..1280 × 0..720）
15. 使用本册规划中的原创 palette；不要换成暗色科技默认霓虹配方
16. **图文分工**：生图=主视觉/插图/背景图（题材按 image_hint，照片或插画均可）；SVG=结构+局部装饰（色条/胶带/标签/撕边/错位字）。禁止用大量 <circle> 铺半调/纹理；每页装饰 circle 建议 <40
17. **配图（若本页提供了已准备文件）**：仅允许本地
   `<image id="hero-img" href="../images/<给定文件名>" x="…" y="…" width="…" height="…" preserveAspectRatio="xMidYMid slice" data-pptx-role="decoration" data-slot="hero-image" data-slot-type="image" data-slot-role="hero-image"/>`
   禁止 http(s)、data:、外链；禁止引用未列出的文件名；无配图清单时不要写 <image>
   **width/height 比例必须等于本页 image_aspect**（1:1 → 等宽高；16:9 → 满版可 1280×720）。
   圆形框：先用 1:1 的 width=height，再用 clipPath/mask 裁成圆，禁止把宽图硬塞进圆框导致四角方形溢出
   **图层**：先放 <image>，文字与局部装饰叠在其上；禁止在图上再铺近满版、opacity>0.12 的 rect/path/pattern（会盖住生图）；需要氛围请写进生图，不要二次遮罩
18. **语义槽位（SVG 阶段必带）**：每个含可见文字的根级 `<g>` 与每个 `<image>` 必须写
   `data-slot`（页内唯一 slug）、`data-slot-type`（text|image）、`data-slot-role`
   （text：page-title|heading|lede|body|meta；image：hero-image|image|logo）。
   建议：标题组 `data-slot="title"`；副题 `subtitle`；眉题/页脚短签 `eyebrow`；正文 `body`/`body-2`；主图 `hero-image`。
   纯装饰 shape（background/decoration）不要写 data-slot。可同时把 data-slot 写在组内 `<text>` 上。
19. **禁止在 `<text>` 上写 dx/dy**（导出拒绝）；水平位移改 x，竖向多行只用 `<tspan dy="…">`。clip-path 仅用于 `<image>` 或带 data-pptx-crop="1" 的包装，不要挂在普通 `<g>` 上
20. **禁止 HTML 标签**：不得在 SVG 内写 `<br>`/`<div>`/`<span>`；多行只用 `<tspan>`
21. **箭头 marker**：优先用小三角 `<polygon>` 画箭头。若使用 `marker-end`/`marker-start`，必须在同页 `<defs>` 内提供匹配的 `<marker id="…">`，且 **marker 内填充色必须与线的 stroke 同色**；禁止悬空 url(#…) 或色不一致
22. **禁止 SMIL**：不得写 `<animate>` / `<animateTransform>` / `<set>` 等动画节点
23. **原生转换兼容性**：`<pattern>` 内部的子元素禁止使用 `transform`，也不要使用 `patternTransform`；需要斜纹/点阵时使用简单几何或 `data-pptx-pattern` 兼容预设
24. **描边兼容性**：`stroke-dasharray` 的间隔必须为正数；实线不要写 `1 0`、`0 0` 等占位值，直接省略该属性
25. **执行 layout_regions**：本页每个规划区域都要映射到同 id 的根级文字 `<g>`；`data-pptx-bounds` 等于区域 bounds，文字墨迹必须落在扣除 padding 后的内框中。不得为了通过检查而缩小或嵌套 bounds
26. **文字安全区**：文字墨迹彼此不得相交；文字与非所属装饰线/形状至少保持该区域 clearance（默认 12px）。容器底板先画，文字后画；禁止在文字之后绘制与文字相交的不透明 shape
27. **内容超预算时的顺序**：先换行或改为更合适的版式，再扩大区域/移动后续区域；只有仍无法容纳时才小幅缩字号，且不能低于风格与阅读距离要求
"""

SYSTEM_SVG_ADDON_PIXEL_ART = """
## 本风格附加约束（pixel-art）
- 用少量大色块表达像素感（每页装饰 rect 建议 <80）；禁止成百上千 8×8 小格铺满
- 字体只用 Arial / Microsoft YaHei / Consolas / Courier New
"""

SYSTEM_SVG_REPAIR = """你是 PPT Master SVG 修复专家。只输出修复后的完整 SVG XML，不要 markdown 围栏，不要解释。

只修复给定页面的 blocking / 融合问题，保持原有文案、视觉风格、几何构图和 id 稳定。
重点：修复真实几何，不得只改 data-pptx-bounds。文字互撞时换行或移动对应模块；装饰线穿字时移动装饰线；后绘制形状盖字时调整 z-order；根级内容模块不得重叠；不要通过缩小字号掩盖问题。
若问题涉及配图：必须保留或补回本地 <image href="../images/…">；去掉盖住配图的满版高透明遮罩；把半调点阵改为少量局部装饰。
必须保留根节点 viewBox=\"0 0 1280 720\"、data-pptx-page-role、原有可见文字、唯一 id，以及已有 data-slot / data-slot-type / data-slot-role。
若文字模块或缺槽位：按语义槽位规则补齐，勿改文案语义。
若发现 `<pattern>` 子元素带 `transform` 或 `patternTransform`，改为不带变换的简单几何；若发现 `stroke-dasharray` 含非正间隔，删除该属性恢复实线。
"""


def system_svg_for(visual_style: str = "") -> str:
    """Core SVG system prompt + style-conditional addons (no style card)."""
    style = (visual_style or "").strip().lower()
    parts = [SYSTEM_SVG.rstrip()]
    if style == "pixel-art" or style.endswith("-pixel-art") or "pixel-art" in style:
        parts.append(SYSTEM_SVG_ADDON_PIXEL_ART.strip())
    return "\n\n".join(parts) + "\n"


def system_svg_cached(visual_style: str = "") -> str:
    """Stable cache prefix: SYSTEM rules → style card (identical across pages)."""
    style = (visual_style or "dark-tech").strip() or "dark-tech"
    card = load_style_card(style)
    return (
        f"{system_svg_for(style).rstrip()}\n\n"
        f"## 强制视觉风格\n\n{card.rstrip()}\n"
    )


def system_plan_cached(visual_style: str = "") -> str:
    """Stable cache prefix for plan candidates of the same style."""
    style = (visual_style or "dark-tech").strip() or "dark-tech"
    card = load_style_card(style)
    return (
        f"{SYSTEM_PLAN.rstrip()}\n\n"
        f"## 强制视觉风格（不可改成 dark-tech）\n\n{card.rstrip()}\n"
    )


def _aspect_placement_hint(aspect: str) -> str:
    a = (aspect or "16:9").strip()
    if a == "1:1":
        return (
            "本图已按 1:1 生成：<image> 必须 width=height（如 480×480 居中）；"
            "若有圆环装饰，用 clipPath 圆形裁切，禁止宽图硬塞导致四角方形溢出。"
        )
    if a in {"9:16", "3:4", "2:3"}:
        return (
            f"本图已按 {a} 竖幅生成：侧栏/竖槽 width:height ≈ {a}；"
            "不要拉伸成横图，可用 slice 裁切但保持竖向构图。"
        )
    if a in {"4:3", "3:2"}:
        return (
            f"本图已按 {a} 生成：半版/分栏槽 width:height ≈ {a}；"
            "勿强行拉成 1280×720 满版除非 geometry 明确满版。"
        )
    return (
        "本图已按 16:9 生成：满版可用 width=1280 height=720；"
        "半版保持 16:9 比例。preserveAspectRatio=xMidYMid slice。"
    )


def user_plan(
    *,
    prompt: str,
    page_count: int,
    visual_style: str,
    creative_seed: str = "",
    critique: str = "",
    enable_images: bool = True,
) -> str:
    """Variable plan task only. Style card lives in ``system_plan_cached``."""
    style = visual_style or "dark-tech"
    image_line = (
        "本任务启用配图：至少封面与一页强视觉内容 need_image=true；"
        "写 image_role（background|hero|panel|illustration）与具体英文 image_hint"
        "（题材按页需要：照片/插画/产品图均可，勿默认半调纹理）；"
        "并按槽位写 image_aspect（圆形=1:1，满版=16:9，半版=4:3，竖栏=3:4/9:16）。"
        if enable_images
        else "本任务关闭配图：所有页 need_image=false，不要写 image_hint / image_aspect / image_role。"
    )
    return f"""## 用户需求

{prompt}

## 任务

规划严格 {page_count} 页，不得增删。
visual_style 字段必须写死为：{style}
为本册原创一套 palette（符合风格用色纪律即可，不要套用任何固定 HEX 配方）；若用户需求文案里误写了其它风格词，以本任务指定的 {style} 为准。
创意方向提示：{creative_seed or "自行提出一个符合该风格的视觉母题"}
{f"上一版需要修正的问题：{critique}" if critique else ""}
{image_line}
template_id 与 label_zh：写成 **10–15 个汉字** 的**内容主题书名**（产品/活动/议题），依据「用户需求」提炼；
**禁止**把视觉风格 id、风格卡标题或其隐喻（舞台灯光、代码编辑器、胶印、氰版等）当作包名，除非用户需求本身就是该题材。
须含：冲击力封面、至少一页章节、能力/结构页、数据或结论页、收尾。
输出完整 JSON。
"""


def compact_plan_json(plan: dict) -> str:
    """Return the stable, page-authoring subset used for archival/debugging."""
    slides = []
    for item in plan.get("slides") or []:
        if not isinstance(item, dict):
            continue
        slides.append(
            {
                key: item.get(key)
                for key in (
                    "file",
                    "role",
                    "title",
                    "core_message",
                    "geometry",
                    "layout_regions",
                    "visual_hook",
                    "density",
                    "motif_use",
                    "need_image",
                    "image_role",
                    "image_aspect",
                    "image_file",
                )
                if item.get(key) is not None
            }
        )
    compact = {
        key: plan.get(key)
        for key in (
            "template_id",
            "label_zh",
            "product",
            "category",
            "visual_style",
            "mode",
            "palette",
        )
        if plan.get(key) is not None
    }
    compact["slides"] = slides
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def deck_authoring_context(plan: dict, *, current_file: str = "") -> str:
    """Build a small deck context for one SVG call.

    The current slide is sent separately with all of its authoring fields;
    sibling slides only need a short rhythm summary so the model can vary
    layouts without paying for the whole plan on every page.
    """
    compact = {
        key: plan.get(key)
        for key in ("visual_style", "mode", "palette", "product")
        if plan.get(key) is not None
    }
    siblings = []
    for item in plan.get("slides") or []:
        if not isinstance(item, dict) or str(item.get("file") or "") == current_file:
            continue
        summary = {
            "file": item.get("file"),
            "role": item.get("role"),
            "title": item.get("title"),
            "geometry": item.get("geometry"),
            "visual_hook": item.get("visual_hook"),
        }
        siblings.append({k: v for k, v in summary.items() if v is not None})
    compact["siblings"] = siblings
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def user_plan_rewrite(
    *,
    prompt: str,
    page_count: int,
    visual_style: str,
    plan: dict,
    critique: str,
    enable_images: bool = True,
) -> str:
    """Rewrite only the selected plan, without resending the full style card."""
    image_line = "图片字段保持启用并修正 need_image/image_*；" if enable_images else "所有页 need_image=false，删除 image_* 字段；"
    return f"""## 用户主题（仅作内容约束）
{prompt[:1600]}

## 指定风格
{visual_style}

## 当前 Plan（只修改必要字段）
{compact_plan_json(plan)}

## 必须修正的问题
{critique}

严格保持 {page_count} 页、visual_style={visual_style}、页面角色合法、命名为内容主题；{image_line}
只输出完整 JSON object，不要 markdown。"""


def user_svg(
    *,
    plan_json: str,
    slide: dict,
    page_index: int,
    page_total: int,
    visual_style: str = "",
    prepared_image: str | None = None,
    image_hint: str = "",
    fusion_critique: str = "",
) -> str:
    """Per-page variable user prompt. Style card lives in ``system_svg_cached``.

    Argument order is intentional for provider prefix cache within the user
    turn when callers still inline a style card: keep stable deck context
    before page-specific fields. Fusion critiques belong in a follow-up turn
    via ``user_svg_fusion_followup`` when using multi-turn chat.
    """
    style = visual_style or "dark-tech"
    role = str(slide.get("image_role") or "").strip() or "hero"
    if prepared_image:
        aspect = str(slide.get("image_aspect") or "16:9").strip() or "16:9"
        image_block = (
            f"本页已准备配图（image_role={role}），必须嵌入一次且保持可见：\n"
            f'  <image id="hero-img" href="../images/{prepared_image}" '
            f'x="…" y="…" width="…" height="…" '
            f'preserveAspectRatio="xMidYMid slice" data-pptx-role="decoration" '
            f'data-slot="hero-image" data-slot-type="image" data-slot-role="hero-image"/>\n'
            f"image_aspect={aspect}；{_aspect_placement_hint(aspect)}\n"
            f"题材参考：{image_hint or '（见规划 image_hint）'}——"
            f"按实际需要理解（可为照片、插画、产品图等，不限纹理）。\n"
            f"SVG 只做局部装饰与文字；禁止满版高透明遮罩盖住此图；禁止海量 circle 仿半调。\n"
            f"勿再引用其它文件名。"
        )
    else:
        image_block = "本页无配图文件：禁止输出任何 <image> 标签；用 SVG 形状与文字完成版面。"
    # Legacy single-shot path may still pass critique inline; prefer follow-up.
    critique = (
        f"\n## 上一稿融合问题（必须修正）\n\n{fusion_critique}\n"
        if fusion_critique
        else ""
    )
    deck_context = plan_json
    try:
        parsed_plan = json.loads(plan_json)
        if isinstance(parsed_plan, dict):
            deck_context = deck_authoring_context(
                parsed_plan, current_file=str(slide.get("file") or "")
            )
    except (TypeError, json.JSONDecodeError):
        # Keep compatibility with callers that pass an already compact string.
        pass
    slide_fields = {
        key: slide.get(key)
        for key in (
            "role",
            "file",
            "title",
            "core_message",
            "geometry",
            "layout_regions",
            "visual_hook",
            "density",
            "motif_use",
            "need_image",
            "image_role",
            "image_aspect",
            "image_file",
        )
        if slide.get(key) is not None
    }
    return f"""## 整包视觉上下文（只读）

{deck_context}

## 本页（{page_index}/{page_total}）

{json.dumps(slide_fields, ensure_ascii=False, separators=(",", ":"))}

## 配图

{image_block}
{critique}
## 任务

按 SYSTEM 硬规则与风格卡输出这一页的完整 SVG。
必须使用规划中的原创 palette，并让造型语法符合 {style}（不要画成 dark-tech）。
文件名对应 {slide.get("file")}。
"""


def user_svg_fusion_followup(*, fusion_critique: str) -> str:
    """Short follow-up after a failed fusion audit (multi-turn; no style card)."""
    return (
        "上一稿存在配图/兼容性问题，必须修正后重新输出完整 SVG XML。\n\n"
        f"{fusion_critique.strip()}\n\n"
        "只输出修复后的完整 SVG，不要解释。"
    )


def user_svg_repair(*, original_svg: str, slide: dict, issues: list[str]) -> str:
    return (
        f"""## 页面规划\nrole={slide.get('role')}\ntitle={slide.get('title')}\ngeometry={slide.get('geometry')}\nimage_file={slide.get('image_file')}\nimage_role={slide.get('image_role')}\n\n## 当前 SVG\n{original_svg}\n\n## 必须修复的 blocking issues\n"""
        + "\n".join(f"- {issue}" for issue in issues)
        + "\n\n输出修复后的完整 SVG。"
    )


def user_svg_repair_followup(*, issues: list[str]) -> str:
    """Continue a repair thread without re-sending the full SVG."""
    return (
        "上一轮修复后仍有 blocking issues，请在上一稿基础上继续修正，"
        "输出完整 SVG XML：\n"
        + "\n".join(f"- {issue}" for issue in issues)
        + "\n\n只输出修复后的完整 SVG，不要解释。"
    )
