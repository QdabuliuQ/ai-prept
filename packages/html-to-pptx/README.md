# `@webppt/html-to-pptx`

从零实现的浏览器端 **HTML 幻灯片 → 可编辑 PPTX** 库。打包层只用 **pptxgenjs**。

## 公共 API

```ts
import { exportPPTX, generatePPTX } from "@webppt/html-to-pptx";

await exportPPTX(pages, { fileName: "deck.pptx" }).promise;
const blob = await generatePPTX(pages, opts).promise;
```

## 流水线

```text
HTML
  → iframe sandbox（固定 1920×1080）
  → 伪元素落地（装饰盒）
  → DOM collect（可见可绘节点）
  → parse（shape / text / image / border）
  → 图片 dataURL 物化
  → pptxgenjs 组包 Blob
```

## 设计约束

- 坐标：CSS px @ 96DPI → inch（默认页 20" × 11.25"）
- 文本：按浏览器视觉行烘焙，`wrap: false`，几何优先用字形 ink bounds
- 独立实现，不依赖其它 HTML→PPTX 实验包
