import type { ThemeToken } from "@/theme/types";
import { MAX_PAGES } from "@/constants/limits";
import i18n from "@/i18n";
import { applyDocumentTheme, DEFAULT_PPT_THEME, toThemeToken } from "@/theme";
import type { TemplateTreeNode } from "@/utils/templateTree";
import { getRandomId } from "@/utils";
import { toast } from "sonner";
import { create } from "zustand";

export type Page = {
  id: string;
  /**
   * 页级 HTML（画布用沙箱 iframe 渲染的主内容）。
   * 缺省时由 `buildBlankSlideHtml` 生成空白页。
   */
  html?: string;
  /** 来自模板包的相对路径，如 slides/cover.html */
  sourceFile?: string;
  visible: boolean;
  toggleInAnimation: string;
  toggleInDuration: string;
  toggleInDelay: string;
  autoToggle: boolean;
  autoToggleTime: number;
  backgroundType: string;
  background: string;
  bgColor: string;
  fgColor: string;
  bgOpacity: number;
  /** 纹理背景选中的纹理 id */
  selectedTexture?: string;
  /** 图片背景：base64 / data URL */
  backgroundImage?: string;
  remark: string;
};

type IPage = Array<Page>;

function createBlankPage(): Page {
  return {
    id: `page_${getRandomId()}`,
    html: undefined,
    visible: true,
    toggleInAnimation: "backInLeft",
    toggleInDuration: "default",
    toggleInDelay: "0s",
    autoToggle: false,
    autoToggleTime: 5,
    backgroundType: "solidColor",
    background: "#fff",
    bgColor: "#e4e4e4",
    fgColor: "#9C92AC",
    bgOpacity: 0.4,
    remark: "",
  };
}

interface PPTState {
  name: string;
  /** 当前文档来源的模板 id（agent-output/<id>）；非模板文档为 null */
  templateId: string | null;
  /** 打开模板时附带的文件树（可被 /tree 刷新） */
  templateTree: TemplateTreeNode[];
  theme: ThemeToken;
  gridSize: number;
  gridType: "grid" | "line" | "none";
  verticalLine: Array<number>;
  horizontalLine: Array<number>;
  rule: boolean;
  guideLineShow: boolean;
  keyboardToggle: boolean;
  pages: IPage;

  setKeyboardToggle: (value: boolean) => void;
  getKeyboardToggle: () => boolean;

  setGuideLineShow: (value: boolean) => void;
  getGuideLineShow: () => boolean;

  setGridType: (type: "grid" | "line" | "none") => void;
  getGridType: () => "grid" | "line" | "none";

  setGridSize: (value: number) => void;
  getGridSize: () => number;

  setVerticalLine: (lines: Array<number>) => void;
  getVerticalLine: () => Array<number>;

  setHorizontalLine: (lines: Array<number>) => void;
  getHorizontalLine: () => Array<number>;

  setRule: (value: boolean) => void;
  getRule: () => boolean;

  setName: (value: string) => void;
  getName: () => string;

  setTemplateId: (templateId: string | null) => void;
  getTemplateId: () => string | null;
  setTemplateTree: (tree: TemplateTreeNode[]) => void;

  setTheme: (theme: ThemeToken) => void;
  getTheme: () => ThemeToken;
  /** 切换主题色并重映射当前文档配色 */
  applyTheme: (theme: ThemeToken) => void;

  setPages: (pages: IPage) => void;
  getActivePage: (pageId: string) => Page | undefined;
  getPages: () => IPage;
  resetPages: () => void;

  addPage: (afterPageId?: string) => string | null;
  duplicatePage: (pageId: string) => string | null;
  deletePage: (pageId: string) => boolean;
  movePage: (pageId: string, direction: "up" | "down" | "first" | "last") => void;
  togglePageVisible: (pageId: string) => void;

  updatePageProperty: (
    pageId: string,
    property: keyof Page,
    value: unknown,
  ) => void;
  /** 更新页级 HTML（画布 iframe 主内容） */
  setPageHtml: (pageId: string, html: string) => void;
}

export const usePPTStore = create<PPTState>((set, get) => ({
  name: "",
  templateId: null,
  templateTree: [],
  theme: toThemeToken(DEFAULT_PPT_THEME),
  gridSize: 20,
  gridType: "grid",
  verticalLine: [],
  horizontalLine: [],
  rule: true,
  guideLineShow: true,
  keyboardToggle: true,
  pages: [],

  setKeyboardToggle: (value) => set({ keyboardToggle: value }),
  getKeyboardToggle: () => get().keyboardToggle,

  setGuideLineShow: (value) => set({ guideLineShow: value }),
  getGuideLineShow: () => get().guideLineShow,

  setGridType: (type) => set({ gridType: type }),
  getGridType: () => get().gridType,

  setGridSize: (value) => set({ gridSize: value }),
  getGridSize: () => get().gridSize,

  setVerticalLine: (lines) => set({ verticalLine: lines }),
  getVerticalLine: () => get().verticalLine,

  setHorizontalLine: (lines) => set({ horizontalLine: lines }),
  getHorizontalLine: () => get().horizontalLine,

  setRule: (value) => set({ rule: value }),
  getRule: () => get().rule,

  setName: (value) => set({ name: value }),
  getName: () => get().name,

  setTemplateId: (templateId) => set({ templateId }),
  getTemplateId: () => get().templateId,
  setTemplateTree: (tree) => set({ templateTree: Array.isArray(tree) ? tree : [] }),

  setTheme: (theme) => set({ theme }),
  getTheme: () => get().theme,
  applyTheme: (theme) => {
    const prev = get().theme;
    const pages = applyDocumentTheme(get().pages, theme, prev);
    set({ theme, pages });
  },

  setPages: (pages) => set({ pages: [...pages] }),

  getActivePage: (pageId) => {
    return get().pages.find((page) => page.id === pageId);
  },

  getPages: () => get().pages,

  resetPages: () => set({ pages: [] }),

  addPage: (afterPageId?) => {
    if (get().pages.length >= MAX_PAGES) {
      toast.warning(i18n.t("limits.maxPages", { count: MAX_PAGES }));
      return null;
    }

    const newPage = createBlankPage();
    const currentPages = get().pages;
    let newPages: IPage = [];

    if (afterPageId) {
      const index = currentPages.findIndex((page) => page.id === afterPageId);
      if (index !== -1) {
        newPages = [
          ...currentPages.slice(0, index + 1),
          newPage,
          ...currentPages.slice(index + 1),
        ];
      } else {
        newPages = [...currentPages, newPage];
      }
    } else {
      newPages = [...currentPages, newPage];
    }

    set({ pages: newPages });
    return newPage.id;
  },

  duplicatePage: (pageId) => {
    if (get().pages.length >= MAX_PAGES) {
      toast.warning(i18n.t("limits.maxPages", { count: MAX_PAGES }));
      return null;
    }

    const currentPages = get().pages;
    const pageIndex = currentPages.findIndex((page) => page.id === pageId);
    if (pageIndex === -1) return null;

    const originalPage = currentPages[pageIndex];
    const duplicatedPage: Page = {
      ...originalPage,
      id: `page_${getRandomId()}`,
      html: originalPage.html,
    };

    const newPages = [
      ...currentPages.slice(0, pageIndex + 1),
      duplicatedPage,
      ...currentPages.slice(pageIndex + 1),
    ];

    set({ pages: newPages });
    return duplicatedPage.id;
  },

  deletePage: (pageId) => {
    const currentPages = get().pages;
    if (currentPages.length <= 1) return false;

    const newPages = currentPages.filter((page) => page.id !== pageId);
    set({ pages: newPages });
    return true;
  },

  movePage: (pageId, direction) => {
    const currentPages = get().pages;
    const index = currentPages.findIndex((page) => page.id === pageId);
    if (index === -1) return;

    const newPages = [...currentPages];
    const [movedPage] = newPages.splice(index, 1);

    if (direction === "up" && index > 0) {
      newPages.splice(index - 1, 0, movedPage);
    } else if (direction === "down" && index < currentPages.length - 1) {
      newPages.splice(index + 1, 0, movedPage);
    } else if (direction === "first") {
      newPages.unshift(movedPage);
    } else if (direction === "last") {
      newPages.push(movedPage);
    } else {
      newPages.splice(index, 0, movedPage);
    }

    set({ pages: newPages });
  },

  togglePageVisible: (pageId) => {
    const currentPages = get().pages;
    const newPages = currentPages.map((page) =>
      page.id === pageId ? { ...page, visible: !page.visible } : page,
    );
    set({ pages: newPages });
  },

  updatePageProperty: (pageId, property, value) => {
    const currentPages = get().pages;
    const newPages = currentPages.map((page) =>
      page.id === pageId ? { ...page, [property]: value } : page,
    );
    set({ pages: newPages });
  },

  setPageHtml: (pageId, html) => {
    get().updatePageProperty(pageId, "html", html);
  },
}));
