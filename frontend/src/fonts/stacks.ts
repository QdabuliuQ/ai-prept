/**
 * 测量 HTML 与编辑器共用的字体栈。
 * 默认统一使用 Noto Serif SC，并保留系统衬线字体回退，
 * 保证 Puppeteer 量框与浏览器渲染字宽一致。
 */

export const WEB_FONT_STYLESHEET_HREF =
  "https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;500;600;700&display=swap";

/** 标题/数字衬线：主题名 + 可加载的 Noto 回退 */
export const FONT_STACK_SERIF =
  '"Noto Serif SC","Source Han Serif SC","Songti SC","STSong",serif';

/** 默认正文也统一使用衬线字体 */
export const FONT_STACK_SANS = FONT_STACK_SERIF;

/** 当前全局字体策略：忽略主题/data 的字体名，统一使用 Noto Serif SC */
export function resolveFontStack(_fontFamily?: string | null): string {
  return FONT_STACK_SERIF;
}

/** 注入到测量页 <head> 的样式（与编辑器 globals 对齐） */
export function buildSharedFontCss(): string {
  return `
@import url('${WEB_FONT_STYLESHEET_HREF}');
:root {
  --webppt-font-serif: ${FONT_STACK_SERIF};
  --webppt-font-sans: ${FONT_STACK_SANS};
}
html, body {
  font-family: var(--webppt-font-sans);
}
`.trim();
}
