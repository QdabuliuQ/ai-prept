import { menuActiveStore, pageActiveStore, pptStore } from "@/store";
import { buildBlankSlideHtml } from "@/utils/slideHtml";

/**
 * 新建页面（插入到指定页面之后），并切换到新页面。
 */
export function addPageAndActivate(
  afterPageId?: string | null,
  onSuccess?: (newPageId: string) => void,
) {
  const newPageId = pptStore.addPage(afterPageId || undefined);
  if (!newPageId) return null;
  menuActiveStore.resetMenu();
  pageActiveStore.setPageActive(newPageId);
  onSuccess?.(newPageId);
  return newPageId;
}

/**
 * 复制指定页面，并切换到新页面。
 */
export function duplicatePageAndActivate(
  pageId: string | null | undefined,
  onSuccess?: (newPageId: string) => void,
) {
  if (!pageId) return null;
  const newPageId = pptStore.duplicatePage(pageId);
  if (!newPageId) return null;

  menuActiveStore.resetMenu();
  pageActiveStore.setPageActive(newPageId);
  onSuccess?.(newPageId);
  return newPageId;
}

/**
 * 删除指定页面；成功后重置菜单，并切到剩余页面中的第一个。
 */
export function deletePageAndFallback(pageId: string | null | undefined) {
  if (!pageId) return;
  const success = pptStore.deletePage(pageId);
  if (!success) return;

  menuActiveStore.resetMenu();

  const remainingPages = pptStore.getPages();
  if (remainingPages.length > 0) {
    pageActiveStore.setPageActive(remainingPages[0].id);
  }
}

/**
 * 清空指定页面 HTML（保留页级背景等元数据）。
 */
export function resetPageElements(pageId: string | null | undefined) {
  if (!pageId) return;
  const page = pptStore.getActivePage(pageId);
  if (!page) return;
  pptStore.setPageHtml(pageId, buildBlankSlideHtml(page));
  menuActiveStore.resetMenu();
}
