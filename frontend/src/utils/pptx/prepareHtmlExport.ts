import type { Page } from "@/store/zustand/pptStore";

/** 页面是否含可导出的 HTML 幻灯片内容。 */
export function pageHasHtml(page: Page): boolean {
  return !!(page.html && page.html.trim());
}
