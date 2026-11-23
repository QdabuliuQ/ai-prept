# Agent 生成引擎（Loop + Harness）· 设计文档

| 项 | 内容 |
|----|------|
| 产品 | AI Prept 模板制作（PPT Master 线） |
| 功能名 | Agent 生成引擎（Agent Loop + 领域 Harness） |
| 文档版本 | v0.1 |
| 日期 | 2026-11-23 |
| 状态 | 设计阶段，未实现 |
| 对应旧实现 | `backend/ppt_master/pipeline.py` `run_one_package` |
| 前置依赖 | `ppt-master/skills/ppt-master/`（外部 Skill，不在版本控制） |

---

## 1. 背景

现有模板制作线（`run_one_package`）是一条**硬编码的 8 阶段流水线**：LLM 在每个阶段被当作纯函数调用（单轮进、结构化 JSON 出、立刻校验），流程走向完全由 Python 决定，模型无法跳阶段、无法回退、无法自选策略。

大模型能力提升后，有一部分决策值得交还给模型。但要回答的问题不是"能不能让模型更自由"，而是：

> **哪些决策交出去能真正提升产出质量，哪些交出去只会让质量不可控？**

本文档定义一套与旧管线**并存**的 Agent Loop 引擎，用于做严格 A/B 对比。

---

## 2. 核心定位

### 2.1 不是替换 PPT Master

Agent Loop 是**调度层**，PPT Master 是**底座**。三层结构，只换最上面一层：

```
┌──────────────────────────────────────────────────────┐
│ 调度层（被替换）                                       │
│ Agent Loop                                           │
│ 决定：页数 / 结构 / region 划分 / 修复策略 / 选哪个风格   │
├──────────────────────────────────────────────────────┤
│ 编译层（锁死，唯一通道）                                │
│ svg_to_pptx.py  →  原生可编辑 PPT 形状                 │
├──────────────────────────────────────────────────────┤
│ 样式层（锁死，唯一来源）                                │
│ references/visual-styles/*.md + SYSTEM_SVG 契约        │
├──────────────────────────────────────────────────────┤
│ 验收层（锁死，唯一裁判）                                │
│ svg_quality_checker.py                               │
└──────────────────────────────────────────────────────┘
```

**样式不是 agent 生成的。** agent 每写一页，拿到的 system prompt 与旧管线逐字节相同（同一个 `system_svg_cached()`）。

```python
def write_page(args):
    system = prompts.system_svg_cached(spec.style)   # 旧管线的函数，一字未改
    ...
```

### 2.2 一句话原则

> **验收权留在代码，策略权交给模型。**

模型可以决定"怎么做"，但**永远不能决定"算不算过"**。

### 2.3 Loop 与 Harness 的分界

这套东西常被简单称为"Agent Loop"，但**它 90% 的重量在 Harness**。分界必须写清，否则团队会只实现循环、把保障层当可选项——而本设计的成败恰恰在后者。

| | 是什么 | 本设计中的组件 |
|---|---|---|
| **Agent Loop** | 调用模型 → 执行工具 → 循环，这个生命周期本身 | 主循环、预算与终止、停滞检测、`chat_tools` 双模 |
| **Harness** | 让循环可控、可信、可观测、可约束的一切 | 工具表与锁/放权限、`sanitize` 归一化、`acceptance` 独立裁决、四道样式闸门、快照回滚、`trace.jsonl`、Admin 观测兼容、启动前置校验 |

对照 DSH 自身的定义可以确认这条线：`dsh-agent-loop` 负责 *"drives each turn through model requests, streamed responses, tool execution, and durable session history"*；`dsh-tools` 负责 *"validate calls, enforce allow/deny/ask policy"*。前者是 Loop，后者是 Harness。

**为什么必须分清**：Loop 是通用件，30 行代码，换谁写都差不多，几乎不可能做错。生产里 agent 崩掉极少因为循环写错，几乎总是因为——

- 模型能自己宣布完成（缺独立裁决）
- 出错回不去（缺快照）
- 卡住不停（缺预算/停滞检测）
- 出事查不清（缺 trace）
- 能力边界模糊（工具锁/放没想清）

这五条全部属于 Harness。

对应到落地阶段：**S0 完全没有 Loop，是纯 Harness**（引擎接口 + 度量 + 报表）；S1 才开始动 Loop。这本身就说明重心。

| 组件 | 归属 |
|---|---|
| `loop.py` 主循环 / 预算 / 停滞检测 / `chat_tools` | Loop |
| 工具表 + 锁放清单 | Harness |
| `sanitize` 35 个函数 | Harness |
| `acceptance.check` | Harness |
| `style_guard` 四道闸门 | Harness |
| Workspace 快照 / 回滚 | Harness |
| `trace.jsonl` / `plan_lock.json` | Harness |
| Admin 日志格式兼容 | Harness |
| `assert_ppt_master_ready` | Harness |

> 旧管线（`run_one_package`）既不是 Loop 也不是 Harness，它是一条**确定性流水线**。本次改造的实质：把流水线的控制权部分让渡给 Loop，同时把原先写死在流程里的保障逻辑，重构成一层独立可测的 Harness。

---

## 3. 为什么值得做

现有管线的规划能力其实不弱（best-of-3 + 启发式打分 + critique 重写）。真正被硬编码锁死的是**修复策略和结构自由度**：

| 旧管线的固定决策 | 后果 |
|---|---|
| 每页 3 次尝试，失败**整包崩** | 12 页因为第 11 页前功尽弃 |
| 修复只能"改 bounds 几像素"或"整页重写" | **布局级问题修不了**：region 挤不下、图文抢位、内容冗余 |
| 页数、结构、region 由 Plan 一次定死 | 中途发现"这页该拆成两页"——无解 |
| 风格卡必须事先选对 | 选错了整个包作废 |
| 质检不过 → `soft-pass` 出厂 | 靠人兜底 |

关键的机制差异：**旧管线是盲写，agent 有反馈回路。**

旧管线里，模型写完直接进质检，失败后拿到的还是"重写一次"这种粗颗粒指令——它**从来不知道**"第 3 页 title 和 body 重叠 34px"。所以只能在 prompt 里预先写 27 条禁令，指望一遍写对。

Agent 能看见具体错误，只改需要改的地方。这就是"prompt 里不需要加那么多限制"的真正原因——**不是模型变强了，是错误信息终于能回流了。**

---

## 4. 完整运行时序

以「7 页，dark-tech 风格，AI 产品发布会」为例。`→` 是模型输出，`←` 是工具返回。

### Phase 0 — Bootstrap（代码）

```python
project = _init_project(f"ai-prept-{tid}")     # 复用：调 project_manager.py init
ws      = Workspace(project, spec)             # 管 svg_output/ images/ validation/ .snapshots/
messages = [
    {"role": "system", "content": agent_system_prompt(spec)},   # 见 §7
    {"role": "user",   "content": "目标：7 页，风格 dark-tech，主题：AI 产品发布会"},
]
```

进入循环前必须先过：

```python
assert_ppt_master_ready()    # 没有 Skill 目录直接拒绝启动
```

### Phase 1 — 规划

```
→ {"action":{"name":"list_styles","args":{}}}
← {"styles":[{"id":"dark-tech","label_zh":"暗色科技","family":"corporate-product"}, ...23 个]}

→ {"action":{"name":"read_style_card","args":{"style":"dark-tech"}}}
← {"card":"visual_style id = dark-tech\n用色纪律：...\n禁止 HUD 粒子..."}

→ {"action":{"name":"write_plan","args":{
     "template_id":"星河智能产品发布会",
     "palette":{"bg":"#0A0E14","panel":"#141A22","text":"#F2F5F8",
                "muted":"#8A96A3","accent":"#4DA3FF","accent2":"#FF7A45"},
     "slides":[
       {"file":"01_cover.svg","role":"cover",
        "layout_regions":[{"id":"title","role":"page-title",
                           "bounds":[72,56,1136,96],
                           "padding":[12,16,12,16],"clearance":12}],
        "geometry":"...","visual_hook":"...","core_message":"..."},
       ... 7 页
     ]}}}
← {"ok":true,"plan_path":"plan.json","slides":7}
```

`write_plan` 内部立刻跑两道门：

```python
_validate_plan(plan, spec.pages)          # pipeline.py:940，原样复用
repair_plan_layout(plan)                   # 只修安全区/内框这类机械错误
```

失败时返回**原文错误**，不是"请重试"：

```
← {"ok":false,"errors":[
     "第 3 页 layout regions title/body 未保留 clearance",
     "第 5 页 layout region stat 超出 40px 安全区"]}
```

模型可 `read_plan` 查看当前状态，只改第 3、5 页后重写。

### Phase 2 — 逐页生成

```
→ {"action":{"name":"write_page","args":{"file":"01_cover.svg","svg":"<svg ...>...</svg>"}}}
```

`write_page` 是门禁最密的工具，顺序照抄 `gen_one`：

```python
def write_page(args):
    raw = args["svg"]
    svg = sanitize_svg_text(raw, strip_unsupported=True)      # 1. 剥离非法节点
    if not is_well_formed_svg(svg):                            # 2. XML 必须合法
        return reject("Invalid XML")
    if reason := authored_svg_reject_reason(svg):              # 3. 空壳直接拒
        return reject(reason)
    svg = _scrub_svg_image_refs(svg, allowed, images_dir)      # 4. 清外链图片
    issues  = audit_svg_image_fusion(svg, prepared_image=...)  # 5. 图文融合
    issues += [f"export compat: {x}" for x in
               generation_compatibility_issues(svg)]           # 6. 原生转换兼容
    if issues:
        return {"ok": False, "issues": issues}
    write(file, svg)
    ws.snapshot()                                              # 7. 落盘 + 快照
    return {"ok": True}
```

接着模型主动查质：

```
→ {"action":{"name":"check_page","args":{"file":"01_cover.svg"}}}
← {"ok":false,"blocking":[
     "[TEXT_TEXT_OVERLAP] title / lede 相交 34px",
     "[TEXT_CANVAS_CLIPPING] footer 墨迹超出画布 12px"]}
```

**这里是分水岭。** 旧管线反应固定：把错误塞进 `user_svg_repair`，整页重写，最多 2 轮，无进展就 soft-pass。Agent 由模型选策略：

- `edit_page` 小步改（只改 title 那个 `<g>` 的 y 坐标）
- `write_page` 整页重写
- 调整 region 重新分配空间（甚至拆页）

前两种成本差一个数量级。**旧管线只有后一种。**

### Phase 3 — 整册验收

```
→ {"action":{"name":"check_all","args":{}}}
← {"ok":false,"files":[{"file":"05_content.svg","errors":[...]}]}

→ {"action":{"name":"measure_render","args":{}}}
← {"engine":"chrome","pages":7,"issues":[
     {"file":"05_content.svg","slot":"body-3-2",
      "reason":"vertical_overflow","excess_px":18}]}
```

`measure_render` 复用 `check_package_render`（真 Chrome 量像素）——唯一能抓"字体回退 / letter-spacing 取整"的检测，也是旧管线里最贵所以做成可选的一环。

### Phase 4 — finish（模型想收工，代码说了算）

```
→ {"action":{"name":"finish","args":{"summary":"7 页完成，封面主视觉 + 数据页强调"}}}
```

```python
def finish(args):
    verdict = acceptance.check(ws, spec)      # 独立、强制、不可跳过
    if not verdict.ok:
        return {"ok": False, "status": "rejected",
                "remaining": verdict.blocking[:12],
                "hint": "修复这些后再 finish，或说明为何无法修复"}
    return export_and_package(ws)             # 复用 _export_pptx + 转包
```

被拒后可继续改，也可再 `finish` 一次说明理由，但**每次都强制重跑验收**，最多 3 次，第 4 次判失败。

### 完整路径一览

```
bootstrap
  → plan 迭代（可多轮）
  → 逐页 write / check / fix
  → check_all
  → measure_render
  → finish 被拒 → 继续修
  → finish 通过
  → export_pptx → 转 HTML 包
```

平均 20–30 步，每步一次 LLM 调用。成本约为旧管线 1.5–3 倍，关键看其中多少步是"旧管线做不到的修复"。

---

## 5. 主循环

```python
def run(spec, ctx):
    ws = Workspace.init(spec)
    messages = bootstrap(spec, ws)
    signature_history = []

    for step in range(spec.budget.max_steps):
        if ws.over_budget():                          # tokens / wall-time / steps 三重预算
            return ws.degrade("budget-exhausted")

        reply = chat_tools(messages, TOOLS)           # 原生 tools 或伪协议，见 §5.1

        if reply.action.name == "finish":
            verdict = acceptance.check(ws, spec)
            if verdict.ok:
                return ws.accept()
            messages += tool_result(verdict)
            continue

        result = dispatch(reply.action, ws)            # 工具内部自带门禁
        ws.record(step, reply.action, result)          # trace.jsonl + job log
        messages += [assistant(reply), tool_result(result)]

        # 防死循环：连续 2 步动作+错误签名不变就停
        sig = (reply.action.name,
               json.dumps(reply.action.args)[:200],
               hash_of(result.get("issues")))
        if signature_history[-1:] == [sig]:
            return ws.degrade("stalled")
        signature_history.append(sig)

    return ws.degrade("max-steps")
```

### 5.1 工具调用：双模，不赌原生

`_create_chat`（`backend/llm.py:387`）当前没有 `tools=` 参数，且 `_is_workers_ai_run` 分支绕开 OpenAI SDK。项目跑在多厂商网关上，tool calling 兼容性参差。

```python
def chat_tools(messages, tools):
    try:
        return native(messages, tools)        # openai SDK tools=
    except UnsupportedToolCall:
        return pseudo(messages, tools)        # JSON 协议兜底
```

伪协议（网关无关，必然可用，且 A/B 时两引擎跑同一模型更公平）：

```json
{"thought":"标题与正文重叠，应把 body 上移",
 "action":{"name":"edit_page","args":{"file":"03.svg","ops":[...]}}}
```

解析失败走项目现成的 `_loads_json_object` 修复链（`backend/llm.py:555`），不另写。

---

## 6. 工具表

**关键设计：agent 不是"再写一套生成器"，而是给现有能力装上门把手。**

| 工具 | 复用实现 | 返回给模型的信号 | 权限 |
|---|---|---|---|
| `list_styles` | `load_catalog()` | 风格 id / 中文名 / 家族 | 只读 |
| `read_style_card` | `load_style_card()` | 卡正文 | 只读 |
| `write_plan` | `_validate_plan` + `repair_plan_layout` + palette 校验 | 原文错误列表 / accepted | 写 |
| `read_plan` | 读 `plan.json` | 结构化 plan | 只读 |
| `read_page` | 读 `svg_output/*.svg` | SVG 文本 | 只读 |
| `write_page` | `sanitize_svg_text` + `authored_svg_reject_reason` + `audit_svg_image_fusion` + `generation_compatibility_issues` | **具体拒绝原因** | 写 |
| `edit_page` | 同上，作用在 ops 上 | | 写 |
| `check_page` | `svg_quality_checker.py --stage page --json` | 逐条 blocking 错误 | 只读 |
| `check_all` | `svg_quality_checker.py --stage final --json` | 逐条错误 | 只读 |
| `measure_render` | `check_package_render()` | 槽级溢出像素数 | 只读 |
| `insert_page` / `delete_page` / `reorder_pages` | 改 `template.json` + 文件 | 新页表 | 写 |
| `generate_image` | `image.generate` | 文件名 + 比例 | 写 |
| `export_pptx` | `_export_pptx` | 成败 + 门禁状态 | 写 |
| `finish` | `acceptance.check()` | **可能被拒**，附缺陷清单 | 写 |

`write_page` 返回拒绝原因、`check_page` 返回逐条错误——**这正是 agent 强于旧管线的机制**：旧管线把这些信号压缩成"同一个 prompt 再要一遍"，agent 能读到"region title 和 body 重叠 34px"然后只改那一处。

### 6.1 锁 / 放清单

| 维度 | 旧管线 | Agent | 说明 |
|---|---|---|---|
| 页数 | 用户传参，Plan 必须严格等于 | ✅ **可增减** | "这页该拆两页"是真实需求 |
| 页面结构 / role 分布 | best-of-3 选一，一次定死 | ✅ **可迭代重构** | |
| `layout_regions` 划分 | 一次定死，只能机械修 | ✅ **可重排** | |
| 修复策略 | 固定：改 bounds 或整页重写，2 轮 | ✅ **自选** | 核心价值 |
| 选哪个风格 | 必须事先选对 | ✅ **先看卡再选** | |
| `ensure_style` 造新卡 | Admin/CLI 手动 | ❌ **默认关**（需 `AGENT_ALLOW_STYLE_AUTHOR=1`） | 漂移风险最大处 |
| **样式卡内容** | PPT Master | ❌ **锁死只读** | |
| **SVG→PPTX 转换** | PPT Master | ❌ **锁死唯一通道** | |
| **质检标准** | PPT Master | ❌ **锁死唯一裁判** | |
| **工程脚手架** | PPT Master | ❌ **锁死唯一入口** | |

前五行是"旧管线真做不到"的能力，后五行是"永不交给模型"的底线。

---

## 7. Prompt 重构：27 条 → 6~8 条

### 7.1 为什么旧 prompt 塞了那么多

`SYSTEM_SVG` 现有 **3,221 字符 / 27 条编号硬规则 / 45 处强制词**（禁止 17、必须 12、不要 11、不得 4、仅允许 1）。`SYSTEM_PLAN` 另有 34 处。

其中绝大部分是因为**盲写**不得不做的预防。核对 `sanitize.py` 的 35 个确定性函数后：**13 条有代码静默兜底，纯属冗余。**

| 规则 | 代码兜底 | 处置 |
|---|---|---|
| 禁 `foreignObject` / `script` / `filter` | `_strip_html_foreign_nodes` | ❌ 删 |
| 禁 `<style>` / class | `_strip_forbidden_css` | ❌ 删 |
| 禁 SMIL 动画 | `_strip_smil_animations` | ❌ 删 |
| 禁 `text@dx/dy` | `_strip_unsupported_text_attrs` | ❌ 删 |
| dasharray 间隔必须为正 | `_strip_invalid_dasharrays` | ❌ 删 |
| pattern 内禁 transform | `_strip_pattern_child_transforms` | ❌ 删 |
| 禁 HTML 标签 | `_strip_html_foreign_nodes` | ❌ 删 |
| 禁 `<span>`（用 tspan） | 自动 `span→tspan` | ❌ 删 |
| 元素必须有唯一 id | `_unique_id` 自动补 | ❌ 删 |
| 零高度线禁渐变描边 | `_fix_zero_height_gradient_strokes` | ❌ 删 |
| 超大字号不超 viewBox | `_clamp_oversized_text` | ❌ 删 |
| 箭头 marker 必须有 defs | `_strip_dangling_line_markers` | ❌ 删 |
| image 只能引本地 | `_scrub_svg_image_refs` | ❌ 删 |
| 字体必须安全栈 | `_force_safe_font_family` | ❌ 删 |
| 补 `data-slot` / bounds | `_ensure_data_slots` + `_estimate_group_bounds` | ✅ **保留，改写**（见 7.3） |
| 执行 layout_regions | 质检器报具体错误 | ⚠️ 简化 |
| 文字安全区 / clearance | 质检器 | ⚠️ 简化 |
| 图文分工 | **无** | ✅ 留 |
| 服从 visual_style + 风格卡 | **无** | ✅ 留 |
| 溢出时的处理顺序 | **无**（判断题） | ✅ 留 |
| palette 纪律 | 部分（对比度可测，色相不可测） | ✅ 留 |

### 7.2 两类绝不能删

**① `data-slot` / `data-pptx-bounds` —— 理由和直觉相反**

它不是为了过质检（`sanitize` 会自动补）。但补出来的是**猜的**：

```python
_estimate_group_bounds(g)                     # 按字形估算
_infer_text_slot(name, text_len, font_size)   # 按长度和字号猜角色
```

模型不写，代码会造一个"看起来合理但语义错"的槽位。**质检器不会报错**（看到的是补齐后的结果），于是零信号。真正的后果在之后：这些槽位是给 **remix** 用的，语义错了，用户下次套用模板时内容会填错位置——**问题延迟到下一个人使用时才暴露，且无法归因。**

**② 审美护栏 —— 唯一没有代码兜底的一类**

风格类限制（禁 HUD、禁暖奶油底、禁套路三栏、构图要 ≥3 骨架）全靠 prompt 一句话撑着，因为"像不像某风格"代码判不了。

它们防得很弱（可绕），**但删了就是零**。这里有个诱人但危险的推理：

> "质检器会兜底，所以 prompt 里的样式规则可以删"

**错。** 质检器管"导出不崩、文字不出框"，**不管"看起来是不是 dark-tech"**。删掉这些，会得到一叠技术上完美、风格上平庸的片子，而且**质检全绿，连报警都收不到。**

### 7.3 改写方式：从"指令"到"目的"

`data-slot` 那组规则别写：

> ❌ 每个含可见文字的根级 `<g>` 必须写 `data-slot`、`data-slot-type`、`data-slot-role`

改成讲原因：

> ✅ 这份模板以后会被人拿去换内容。把每块独立可编辑的文字标成一个槽位（标题写 `title`，正文写 `body`，页脚写 `meta`），这样换文案时能精确替换而不破版。

同一个约束，前者是指令，后者是目的。强模型理解目的后会自然做对，而且比规则描述更准。

### 7.4 新 prompt 全文（草案）

```text
你是这份模板的作者。产出 SVG，它会被转成原生可编辑的 PowerPoint。

契约
这份模板以后会被人拿去换内容。把每块独立可编辑的文字标记成一个槽位
（标题 title、正文 body、页脚 meta），这样换文案时能精确替换而不破版。

分工
主视觉图片由生图负责。你只画结构、色块、局部装饰。

风格
按给定风格卡的造型语言、留白气质、装饰密度执行。
非科技风格不要用 HUD / 霓虹 / 轨道环这类语汇。

你可以反复检查、修改、重试。你说"完成"时我会独立复检，
不通过会告诉你具体哪里不对。
```

约 300 字符，**6 条实质约束**。从 27 条降下来 78%。

### 7.5 配套不变的三件事

| 层 | 变化 |
|---|---|
| prompt 里的限制 | **大幅减少** |
| 工具内部门禁（`sanitize` 35 个函数） | **一条不减** |
| 最终验收 | **反而更严**（agent 默认 `strict`） |

**给更多自由，必须给更硬的边界**——这两件事配套，不是替代。

---

## 8. 样式一致性闸门

Agent 放开结构自由，最大的真实风险是**样式漂移**。必须再加一道闸，且不能靠 prompt。

| 闸门 | 判定方式 | 可靠性 |
|---|---|---|
| ① Palette 纪律 | `is_paper_warm_style()` + 色相判定 + WCAG 对比度 | 机械，最可靠 |
| ② 风格卡语汇覆盖 | 关键词命中 `geometry` / `visual_hook` | 半机械 |
| ③ VL 盲评"像不像" | `capture_package_previews` + `llm_vision_config` | 模型判定，模糊 |
| ④ 结构指纹 | 字体栈 / 圆角 / 留白比 / 装饰元素数 | 机械 |

`write_plan` 直接拒不合格的 palette：

```python
def palette_conformance(plan, style) -> list[str]:
    issues = []
    if not is_paper_warm_style(style) and is_warm_cream(plan["palette"]["bg"]):
        issues.append("非纸质风格的 bg 用了暖奶油底")
    if style in TECH_HUD_OK and looks_like_neon_hud(plan):
        pass                                        # 允许
    elif looks_like_neon_hud(plan):
        issues.append("非 dark-tech/glassmorphism/blueprint 用了霓虹 HUD 语汇")
    issues += [f"{k} 对比度 {r} < 门槛" for k, r in contrast_failures(plan)]
    return issues
```

闸门 ③ 的提问方式很关键——**"像不像"和"好不好看"必须分开问**：

```
只回答一个 0-10 分：这页的造型语言/留白/装饰密度/配色纪律，
是否属于「{style_card 全文}」这个风格？不要评价好不好看。
```

混在一起问，模型会给"好看但偏风格"的页面打高分，闸门就废了。

**加这四道后，样式一致性 + 技术合规性成为两个正交验收维度。旧管线只有后者。**

---

## 9. 验收契约

`acceptance.check()` 是唯一裁判，模型无法绕过：

1. `svg_quality_checker.py --stage final` 必须全绿（**默认 `strict`，不是 `soft`**）
2. 每页 SVG 根节点 `viewBox="0 0 1280 720"` / `data-pptx-page-role` 合法
3. 页数 == `spec.pages`
4. `plan.json` 每页都有对应 `svg_output/*.svg`
5. export 干跑一次不崩
6. 四道样式闸门全过

**为什么 agent 引擎要比管线更严**：否则模型会学会"耗到预算就 soft-pass 交差"。旧管线的 soft-pass 是给人兜底用的，agent 不该有这条逃生通道。

---

## 10. 状态管理与回滚

### 10.1 状态外置

| 层 | 职责 | 位置 |
|---|---|---|
| 状态层 | 磁盘 project 目录是唯一真相 | `ppt-master/projects/<name>/` |
| 决策层 | 每步看状态、选动作 | `engines/agent/loop.py` |
| 能力层 | 现有函数包装，门禁长在工具里 | `engines/agent/tools.py` |

**模型不持有任何状态。** 每步都是「读磁盘 → 决策 → 改磁盘」，所以中断可恢复、试错可回滚、失败可归因。

### 10.2 快照

```python
def snapshot(self, step):
    d = self.dir / ".snapshots" / f"{step:03d}"
    d.mkdir(parents=True)
    for f in (self.dir / "svg_output").glob("*.svg"):
        shutil.copy2(f, d / f.name)     # 每页 10~20KB，7 页 140KB
```

`rollback(step)` 直接覆盖回去。**这是 agent 敢试错的前提**：改坏了退一步重来，而不是整包重生成。

### 10.3 上下文控制

一页 SVG 完整重写就是 15KB，7 页反复改会爆。三个手段：

- **小步编辑**：`edit_page` 用 ops 改局部，不重发整页
- **状态外置**：要看当前 SVG 就 `read_page`，不进上下文常驻
- **旧步压缩**：超 N 步后把早期 `tool_result` 折叠成一行摘要

---

## 11. 观测性与 Admin 兼容

`_append_log`（`backend/admin/jobs.py:297`）靠正则抓 `[remix-page]` / `[remix-cloned]` 推进度。agent 每步必须打同格式日志，否则前端进度条、页列表、状态点全废：

```
[agent-step]   n=12 tool=write_page file=03_content.svg ok=1
[agent-gate]   n=12 blocking=2 detail=TEXT_TEXT_OVERLAP
[agent-finish] status=accepted steps=28 tokens=182k
```

**这是最容易在集成阶段翻车的地方。**

### 11.1 可复现

每步落 `trace.jsonl`：step / action / args 摘要 / result / tokens / 耗时。温度、模型、图片开关记入 `plan_lock.json`。否则出问题无法归因，A/B 也无法复核。

---

## 12. 对比实验设计

### 12.1 任务集

约 24 个，正交组合：

- 内容域：产品发布 / 数据年报 / 教学 / 品牌提案
- 难度：easy（7 页宽裕）· **hard（12 页密集数据 + 长中文标题）**
- 风格：3 张已有卡 + 1 个需 `ensure-style` 的新风格

每任务每引擎跑 3 次，模型/温度/图片开关全固定。

### 12.2 三层指标

**L1 硬指标**（代码算，最可信）

首次导出 gate 通过率 · 最终通过率 · `soft-pass` 占比 · 逐页 render issues 数 · 失败率 · wall time · LLM 调用次数 · `page_tokens`（复用 `usage.py` 记账，天然可比）

**L2 自动软评分**

复用 `capture_package_previews` + `llm_vision_config` + `chat_json` 多模态打分（`templates/visual_spec.py:339` 已在用）。统一 rubric：观感 / 层级清晰 / 构图多样 / 文字可读 / 主题贴合，0–10，双模型各打一次取均值。

**L3 人工盲评**

打乱来源成对比较，只出"更好/更差/差不多"。

### 12.3 预注册判据（防事后找理由）

- agent 赢 = **hard 子集** L1 通过率高 ≥15pp，或 L2 高 ≥1.0，**且**成本增幅 ≤2×
- 成本 >3× 而质量提升不显著 → 只保留混合式，不做全自主

**别只看平均分。** 预期结构是：agent 在 easy 打平、hard 明显赢、成本输。benchmark 要能测出这个结构，而不是被平均值糊掉。

---

## 13. 分阶段落地

| 阶段 | 内容 | 变量隔离 | 停手判据 |
|---|---|---|---|
| **S0** | 抽 Engine 接口 + 旧引擎包装 + 任务集/指标/报表骨架 | 零行为变化，纯基建 | — |
| **S1** | **混合式**：agent 只接管 Plan，SVG 仍走管线 | 只测"规划是否变强" | Plan 阶段 L1/L2 无提升 → 规划已够好，停 |
| **S2** | **逐页 authoring loop**：写页 → check → 自选修法 | 只测"修复策略是否变强" | 成本超 2× 而 gate 提升 <10pp → 停 |
| **S3** | **全自主**：页数/结构/风格卡/重排版全放开 | 全部变量 | 前两阶段都赢才做 |

**强烈建议从 S1 开始，不要直接做 S3。** S1 最便宜、变量最干净，且能直接回答核心问题："模型更强了，规划还需要 hand-holding 吗？" 若 S1 打平，则 S2/S3 的收益空间主要在修复侧，设计重点完全不同。

### 13.1 Engine 接口

```python
# engines/base.py
@dataclass(frozen=True)
class GenerateSpec:
    prompt: str; style: str; pages: int
    with_images: bool; budget: Budget

@dataclass
class EngineResult:
    template_id: str | None
    status: str            # accepted / soft-pass / failed / partial
    usage: dict
    trace_path: Path
    steps: int

class TemplateEngine(Protocol):
    def run(self, spec: GenerateSpec, ctx: RunContext) -> EngineResult: ...
```

```python
# engines/pipeline_engine.py —— 薄包装，一行不改
class PipelineEngine:
    def run(self, spec, ctx):
        row = run_one_package(spec.prompt, pages=spec.pages, ...)
        return EngineResult.from_row(row)
```

CLI 加 `--engine pipeline|agent`，Admin 加引擎选择。**旧引擎零改动，这是敢上线对比的前提**——否则无法判断差异来自引擎还是来自顺手改坏的其他东西。

### 13.2 目录结构与实现状态

```
backend/ppt_master/engines/
├── __init__.py                 # 对外契约 + build_engine 工厂        ✅
├── base.py                     # GenerateSpec / Budget / EngineResult  ✅
│                               # SkillBridge 抽象 / TemplateEngine 协议
├── pipeline_engine.py          # 薄包装 run_one_package（零行为变化）  ✅
├── skill_bridge.py             # LocalSkillBridge：Skill 唯一访问通道  ✅
└── agent/
    ├── __init__.py             # 导出 AgentEngine                    ✅
    ├── loop.py                 # Loop：主循环 / 预算 / 停滞 / finish   ✅
    ├── tools.py                # Harness：工具表 + 门禁               ✅
    ├── acceptance.py           # Harness：唯一裁判                    ✅
    ├── style_guard.py          # Harness：四道样式闸门                ✅
    ├── workspace.py            # Harness：状态/快照/回滚/trace        ✅
    └── prompts.py              # Harness：精简 system prompt         ✅
```

配套改动（4 个既有文件，共 +532/-26 行）：

| 文件 | 改动 |
|---|---|
| `pipeline.py` | `run_one_package` / `run_ppt_master_pipeline` 增加 `preset_plan` 注入点；仍走 `_validate_plan` |
| `llm.py` | 新增 `chat_tools` 双模（原生 tools + 伪协议）、`tool_result_messages` |
| `cli.py` | `--engine {pipeline,agent}` / `--agent-full` / `--agent-max-steps` |
| `admin/jobs.py` | job 字段 `engine`/`agentFull`/`agentMaxSteps`；`[agent-*]` 进度解析 |

测试（2066 行，93 个新增用例，全部通过）：

| 文件 | 覆盖 |
|---|---|
| `test_engines_base.py` | 契约、形状适配、`to_row` 回写保真 |
| `test_agent_workspace.py` | 快照/回滚/停滞检测/trace |
| `test_agent_style_guard.py` | 四道闸门的判定与误杀防护 |
| `test_agent_acceptance.py` | 独立裁决、不接受 soft-pass |
| `test_agent_tools.py` | 门禁拒绝且不落盘、模式隔离 |
| `test_agent_loop.py` | 预算/停滞/降级/finish 强制复检 |
| `test_llm_tools.py` | 伪协议容错、降级边界 |
| `test_preset_plan.py` | **注入点端到端**（stub skill 真跑流水线） |

### 13.3 使用方式

```bash
# 旧行为，完全不变
ai-prept-backend ppt-master --pages 7 --style dark-tech "主题"

# S1：agent 只接管规划，SVG/样式/导出仍走 PPT Master 流水线
ai-prept-backend ppt-master --engine agent --pages 7 --style dark-tech "主题"

# S2/S3：agent 接管规划 + 逐页 SVG（页数可自由增减）
ai-prept-backend ppt-master --engine agent --agent-full --pages 7 "主题"
```

Admin 侧：`start_generate_job` 接受 `engine` / `agentFull` / `agentMaxSteps`，
job 对象与日志已带引擎信息，前端进度条可复用既有解析。

### 13.4 已知边界

- **`ppt-master/` 未解压时 agent 引擎直接拒绝启动**（`EngineError`，给可操作提示），
  这是刻意设计：没有 Skill 就没有样式与验收，不容许降级。
- `preset_plan` 仅对 `count == 1` 生效；批量的差异化来自内部创意种子。
- 伪协议是兜底，不是首选；`prefer="auto"` 才会先试原生 tool calling。

---

## 14. 风险清单

| 风险 | 影响 | 对策 |
|---|---|---|
| `ppt-master/` 不在仓库 | **整条线跑不起来** | 先解压 Skill 并验证基线 |
| tool calling 网关不兼容 | agent 无法运转 | 双模：原生 + 伪协议 |
| 上下文膨胀 | 成本失控 / 提前截断 | 小步编辑 + 状态外置 + 旧步压缩 |
| 样式漂移 | 技术上合格、风格平庸，**且质检全绿** | 四道样式闸门 |
| agent 学会 soft-pass 逃逸 | 带病出厂 | agent 默认 `strict`，soft 需显式开 |
| 一页崩 vs 部分交付 | 12 页成 10 页 | **这是优势**：`degrade()` 带产物 + 缺陷清单返回 |
| Admin 进度条失效 | 前端一片空白 | 每步打同格式 `[agent-*]` 日志 |
| 不可复现 | 无法归因 / 无法复核 A/B | `trace.jsonl` + `plan_lock.json` |
| 质检器是黑盒 | "你的检查器放行、质检器拒绝"的割裂 | 自建检查器**只做更严**，绝不更松 |

### 14.1 一个必须知道的耦合

`style_author.py` 的 `ensure_style` 会**往 Skill 目录写文件**：

```python
visual_styles_dir() = skill_dir() / "references" / "visual-styles"
# 写 <id>.md，然后 rebuild _catalog.json
```

即**代码在改外部 Skill 的资产**。后果：Skill 升级会丢自动生成的风格卡，且这些卡不在版本控制里，容易变孤儿。

---

## 15. 结论

1. **Agent Loop 不替换 PPT Master**，只是把它的样式从"被硬编码流程调用"升级成"被 agent 消费的只读资源 + 不可绕过的编译器与裁判"。
2. **prompt 限制可以大幅削减（27 → 6~8）**，因为错误信息终于能回流；但**工具门禁一条不减，最终验收反而更严**。
3. **真正被替换的只有 5 个决策**：页数、结构、region 划分、修复策略、风格选择。
4. **必须新增四道样式闸门**，否则会得到"质检全绿但风格平庸"的产出。
5. **先做 S0 + S1**，用 hard 子集验证，不赢就停。

---

## 附录 A：关键代码位置

| 位置 | 内容 |
|---|---|
| `backend/ppt_master/pipeline.py:2070` | `run_one_package`（8 阶段） |
| `backend/ppt_master/pipeline.py:940` | `_validate_plan`（几何契约） |
| `backend/ppt_master/pipeline.py:1146` | `_creative_score`（启发式打分） |
| `backend/ppt_master/pipeline.py:1381` | `_build_plan`（best-of-3） |
| `backend/ppt_master/pipeline.py:2261` | `gen_one`（逐页 SVG） |
| `backend/ppt_master/pipeline.py:458` | `_repair_failed_svgs`（2 轮修复） |
| `backend/ppt_master/pipeline.py:1616` | `_export_pptx` |
| `backend/ppt_master/prompts.py:97` | `SYSTEM_SVG`（27 条） |
| `backend/ppt_master/prompts.py:9` | `SYSTEM_PLAN` |
| `backend/ppt_master/sanitize.py:870` | `sanitize_svg_text`（35 个函数入口） |
| `backend/ppt_master/styles.py:91` | `is_paper_warm_style` |
| `backend/ppt_master/styles.py:112` | `style_title_ban_tokens` |
| `backend/llm.py:387` | `_create_chat`（需加 tools 支持） |
| `backend/templates/render_check.py:345` | `check_package_render` |
| `backend/admin/jobs.py:297` | `_append_log`（进度解析） |

## 附录 B：Skill 依赖边界

代码只从 `ppt-master/skills/ppt-master/` 取 5 样东西：

| Skill 资产 | 用途 | 调用点 |
|---|---|---|
| `SKILL.md` | **只检查存在，从不读内容** | `paths.py:44`、`jobs.py:903` |
| `scripts/project_manager.py` | 只调 `init` 建工程目录 | `pipeline.py:1581` |
| `scripts/svg_to_pptx.py` | 导出 PPTX | `pipeline.py:1703` |
| `scripts/svg_quality_checker.py` | 质检门禁 | `pipeline.py:320,345` |
| `references/visual-styles/*.md` | 风格卡正文 | `styles.py:162` |

**所有 27 条 prompt 规则、35 个 sanitize 函数、几何契约、审美护栏，全部在 `backend/ppt_master/`（版本控制内），不在 Skill 里。** 唯一真正"加在 Skill 上"的是风格卡里的散文描述。

**推论**：靠 prompt 猜测质检器在意什么是不可靠的——`svg_quality_checker.py` 是黑盒，看不到源码。规则下沉时自建检查器应只做"比质检器更严"的判定。
