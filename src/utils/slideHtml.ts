import { CANVAS_HEIGHT, CANVAS_WIDTH } from "@/constants/canvas";
import type { Page } from "@/store/ppt";

/** HTML 幻灯片设计稿尺寸（16:9） */
export const SLIDE_HTML_WIDTH = 1920;
export const SLIDE_HTML_HEIGHT = 1080;

/** 画布相对设计稿的缩放 */
export const SLIDE_HTML_SCALE = CANVAS_WIDTH / SLIDE_HTML_WIDTH;

/**
 * 判断字符串是否已是完整 HTML 文档。
 */
export function isFullHtmlDocument(html: string): boolean {
  return /<html[\s>]/i.test(html) || /<!DOCTYPE\s+html/i.test(html);
}

/**
 * 按页面背景字段生成空白页 HTML（无 page.html 时的兜底）。
 */
export function buildBlankSlideHtml(page?: Partial<Page>): string {
  const bg =
    page?.backgroundType === "image" && page.backgroundImage
      ? `#fff`
      : page?.background || "#ffffff";
  const bgImage =
    page?.backgroundType === "image" && page.backgroundImage
      ? `background-image:url('${String(page.backgroundImage).replace(/'/g, "%27")}');background-size:cover;background-position:center;`
      : "";

  return `<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=${SLIDE_HTML_WIDTH}"/>
  <title>Slide</title>
  <style>
    html,body{margin:0;padding:0;width:${SLIDE_HTML_WIDTH}px;height:${SLIDE_HTML_HEIGHT}px;overflow:hidden;}
    body{background:${bg};${bgImage}}
  </style>
</head>
<body></body>
</html>`;
}

/**
 * 规范化幻灯片 HTML：片段包成完整文档；已是文档则原样。
 */
export function normalizeSlideHtml(
  html: string | undefined | null,
  page?: Partial<Page>,
): string {
  const trimmed = (html || "").trim();
  if (!trimmed) return buildBlankSlideHtml(page);

  if (isFullHtmlDocument(trimmed)) return trimmed;

  return `<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=${SLIDE_HTML_WIDTH}"/>
  <style>
    html,body{margin:0;padding:0;width:${SLIDE_HTML_WIDTH}px;height:${SLIDE_HTML_HEIGHT}px;overflow:hidden;box-sizing:border-box;}
    *,*::before,*::after{box-sizing:border-box;}
  </style>
</head>
<body>${trimmed}</body>
</html>`;
}

/**
 * 取页面用于 iframe 渲染的 HTML（优先 page.html）。
 */
export function resolvePageHtml(page: Page): string {
  return normalizeSlideHtml(page.html, page);
}

export { CANVAS_HEIGHT, CANVAS_WIDTH };
