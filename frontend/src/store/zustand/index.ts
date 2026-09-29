/**
 * Admin template generation jobs — spawn webppt-backend CLI.
 * (compat layer for pptStore — page HTML only)
 */

// Export all Zustand stores
import { usePageActiveStore } from "./pageActiveStore";
import { usePPTStore } from "./pptStore";

export { usePPTStore } from "./pptStore";
export type { Page } from "./pptStore";

export { contextMenuStore, useContextMenuStore } from "./contextMenuStore";
export { fullscreenStore, useFullscreenStore } from "./fullscreenStore";
export { usePageActiveStore } from "./pageActiveStore";

export {
  displayStatusStore,
  menuActiveStore,
  remarkEditActiveStore,
  useDisplayStatusStore,
  useMenuActiveStore,
  useRemarkEditActiveStore,
} from "./allStores";

export { useCanvasZoomStore } from "./canvasZoomStore";

export { useChartInspectorStore } from "./chartInspectorStore";

export { useThemeStore, type ThemeMode } from "./themeStore";

export { useGalleryRemixStore } from "./galleryRemixStore";

export { useSlideSelectionStore } from "./slideSelectionStore";
export type { TextStylePatch } from "./slideSelectionStore";

class PageActiveStoreCompat {
  get pageActive() {
    return usePageActiveStore.getState().pageActive;
  }

  setPageActive = (pageActive: string | null) => {
    usePageActiveStore.getState().setPageActive(pageActive);
  };

  getPageActive = () => {
    return usePageActiveStore.getState().getPageActive();
  };

  isPageActive = (pageActive: string) => {
    return usePageActiveStore.getState().isPageActive(pageActive);
  };

  resetPageActive = () => {
    usePageActiveStore.getState().resetPageActive();
  };

  getPageIndex = (pages: any[]) => {
    return usePageActiveStore.getState().getPageIndex(pages);
  };

  goToPrevPage = () => {
    return usePageActiveStore.getState().goToPrevPage();
  };

  goToNextPage = () => {
    return usePageActiveStore.getState().goToNextPage();
  };
}

class PPTStoreCompat {
  get pages() {
    return usePPTStore.getState().pages;
  }

  set pages(value) {
    usePPTStore.getState().setPages(value);
  }

  setKeyboardToggle = (value: boolean) => {
    usePPTStore.getState().setKeyboardToggle(value);
  };

  getKeyboardToggle = () => {
    return usePPTStore.getState().getKeyboardToggle();
  };

  getActivePage = (pageId: string) => {
    return usePPTStore.getState().getActivePage(pageId);
  };

  getPages = () => {
    return usePPTStore.getState().getPages();
  };

  setPages = (pages: any[]) => {
    usePPTStore.getState().setPages(pages);
  };

  addPage = (afterPageId?: string) => {
    return usePPTStore.getState().addPage(afterPageId);
  };

  duplicatePage = (pageId: string) => {
    return usePPTStore.getState().duplicatePage(pageId);
  };

  deletePage = (pageId: string) => {
    return usePPTStore.getState().deletePage(pageId);
  };

  movePage = (pageId: string, direction: "up" | "down" | "first" | "last") => {
    usePPTStore.getState().movePage(pageId, direction);
  };

  togglePageVisible = (pageId: string) => {
    usePPTStore.getState().togglePageVisible(pageId);
  };

  setPageHtml = (pageId: string, html: string) => {
    usePPTStore.getState().setPageHtml(pageId, html);
  };

  updatePageProperty = (pageId: string, property: string, value: unknown) => {
    usePPTStore.getState().updatePageProperty(pageId, property as any, value);
  };

  setGridType = (type: "grid" | "line" | "none") => {
    usePPTStore.getState().setGridType(type);
  };

  getGridType = () => {
    return usePPTStore.getState().getGridType();
  };

  setGridSize = (size: number) => {
    usePPTStore.getState().setGridSize(size);
  };

  getGridSize = () => {
    return usePPTStore.getState().getGridSize();
  };

  setGuideLineShow = (show: boolean) => {
    usePPTStore.getState().setGuideLineShow(show);
  };

  getGuideLineShow = () => {
    return usePPTStore.getState().getGuideLineShow();
  };

  setName = (name: string) => {
    usePPTStore.getState().setName(name);
  };

  getName = () => {
    return usePPTStore.getState().getName();
  };

  setTheme = (theme: import("@/theme/types").ThemeToken) => {
    usePPTStore.getState().setTheme(theme);
  };

  getTheme = () => {
    return usePPTStore.getState().getTheme();
  };

  applyTheme = (theme: import("@/theme/types").ThemeToken) => {
    usePPTStore.getState().applyTheme(theme);
  };

  setRule = (rule: boolean) => {
    usePPTStore.getState().setRule(rule);
  };

  getRule = () => {
    return usePPTStore.getState().getRule();
  };

  setVerticalLine = (lines: number[]) => {
    usePPTStore.getState().setVerticalLine(lines);
  };

  getVerticalLine = () => {
    return usePPTStore.getState().getVerticalLine();
  };

  setHorizontalLine = (lines: number[]) => {
    usePPTStore.getState().setHorizontalLine(lines);
  };

  getHorizontalLine = () => {
    return usePPTStore.getState().getHorizontalLine();
  };
}

export const pageActiveStore = new PageActiveStoreCompat();
export const pptStore = new PPTStoreCompat();
