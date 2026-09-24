# Learned Lessons（质检沉淀 · 自动追加）

机器在质检硬失败 / 重修后，把可迁移规则追加到本节。人工可将成熟条目升格进 `VISUAL_QA.md`。

- 每条以 `### \`id\`` 开头；**同 id 不重复追加**。
- `track:` 为 `both` / `html` / `pptxgen`。
- 生成时注入 Plan / Slide；保持条目短、可执行。

## Lessons

<!-- 自动追加区：勿删本行 -->

### `export-bg-url` · track:both
避免质检硬失败 `export-bg-url`：生成时自检对照 VISUAL_QA 同类规则。


### `cover-image-check` · track:both
封面页必须包含符合全出血或至少70%占比的主视觉图


### `export-text-clip` · track:both
避免质检硬失败 `export-text-clip`：生成时自检对照 VISUAL_QA 同类规则。


### `text-clip-avoid` · track:both
避免使用-webkit-line-clamp截断文字，应减短文案、加高卡壳或拆页以保证全文可见


### `export-emoji` · track:both
避免质检硬失败 `export-emoji`：生成时自检对照 VISUAL_QA 同类规则。

### `export-bounds-measured` · track:both
避免质检硬失败 `export-bounds-measured`：生成时自检对照 VISUAL_QA 同类规则。


### `no-emoji-in-shape` · track:both
禁止使用emoji作为圆芯片图标，应改用本地图片或实色椭圆加短字母

### `unicode-decor-check` · track:both
避免使用Unicode几何符装饰，应使用标准图形或文字标注


### `absolute-bounds-check` · track:both
使用绝对定位的元素需确保其位置和尺寸不超出画布边界

### `emoji-in-shape` · track:both
禁止使用emoji作为圆芯片图标，应改用本地图片或实色椭圆加短字母

### `visual-shell-check` · track:both
确保所有内容卡内有文字中心，禁止空卡和文字超出内容卡范围

### `shape-content-check` · track:pptxgen
内容卡应包含实际内容，避免仅作为形状底板

### `text-placement-check` · track:pptxgen
文字应放置在内容卡内部，确保视觉可读性


### `visual-shell-cross-overlap` · track:both
避免文字跨多个内容卡重叠，应使用分区壳内flex布局进行排列

### `cover-image-main-visual` · track:both
封面页必须包含符合全出血或至少70%占比的主视觉图


### `visual-overlap` · track:both
避免文字重叠，确保各元素之间有足够的间距

### `visual-occlude` · track:both
不透明内容卡/图不得盖住可读标题或正文；卡顶边放在标题底边之下，或把标题放进分区壳流式区，禁止只在缝里露出一两个字


### `text-contrast-check` · track:both
确保所有文字与背景的对比度符合高对比色方案要求，避免低对比度导致的辨识困难


### `premium-cover-image` · track:both
封面页必须包含符合全出血或至少70%占比的主视觉图


### `card-footer-shapes` · track:pptxgen
卡内页脚圆点/短条须为真实 DOM `data-element="shape"`（ellipse/roundRect）+ 实色 background；禁止 `::before`/`::after`。未标记实色小子节点在 shape 卡内也会被测量收进 JSON。

### `divider-line-shape` · track:pptxgen
水平/垂直分隔色条（如 `height:2px;background:#…`）必须 `data-element="shape"` + `data-fill`（opacity 与 data-transparency 镜像）；禁止裸 `class="divider-line"` 无标记 div。

### `ellipse-not-roundrect` · track:pptxgen
HTML 正圆（border-radius:50% 或半径≥短边45%）必须导出 `shapeName:"ellipse"`。勿用 roundRect+小 data-border-radius 冒充圆；pptxgenjs 支持 ellipse 全圆。

### `no-text-inside-shape` · track:pptxgen
禁止把可见文案（chip/pill 标签）写进 `data-element="shape"` 内。色块与文字拆开：壳或空 shape + 兄弟 `data-element="text"`，否则 JSON 只有色块没有字。

### `shell-needs-absolute` · track:html
凡 CSS/内联写了 left/top 的分区壳/卡，必须同节点或同规则带 `position:absolute`。常见翻车：`.card-b{top;left}` 挂在无 absolute 的 `.sticky-note` 上 → 便签掉回文档流叠到左上角。壳 height 须装下字号与行数，勿矮壳大字。

### `visual-shell` · track:both
确保所有内容卡内有文字中心，禁止空卡和文字超出内容卡范围

### `visual-contrast` · track:both
使用高对比色方案确保文字清晰可辨

### `flex-layout` · track:pptxgen
使用flex布局合理分配内容卡内的文字空间

### `absolute-positioning` · track:both
避免在内容卡外使用绝对定位的文字

### `shape-content` · track:pptxgen
内容卡应包含实际内容，避免仅作为形状底板

### `text-placement` · track:pptxgen
文字应放置在内容卡内部，确保视觉可读性

