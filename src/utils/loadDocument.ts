import type { ThemeToken } from "@/theme/types";
import type { Page } from "@/store";
import { inferThemeFromPages } from "@/theme";
import { cloneDeep } from "@/utils";
import {
  menuActiveStore,
  pageActiveStore,
  pptStore,
} from "@/store";

export type PPTDocumentJSON = {
  name?: string;
  theme?: ThemeToken;
  /** 模板包 format：html-slide / ppt-master 时编辑器导出走 html-to-pptx */
  format?: string;
  pages: Page[];
  gridSize?: number;
  gridType?: "grid" | "line" | "none";
  verticalLine?: number[];
  horizontalLine?: number[];
  rule?: boolean;
  guideLineShow?: boolean;
  keyboardToggle?: boolean;
};

/**
 * 临时：相对路径 assets/xxx → 本地代理 /api/pack-assets/xxx
 */
export function rewritePackAssetUrlsForLocalProxy<T>(doc: T): T {
  const rewrite = (u: string): string => {
    if (u.startsWith("/api/pack-assets/")) return u;
    const m = u.match(/^(?:\.\/)?assets\/([^/?#]+)$/);
    if (m?.[1]) return `/api/pack-assets/${m[1]}`;
    return u;
  };

  const walk = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(walk);
    if (!node || typeof node !== "object") return node;
    const obj = node as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) {
      if (
        (k === "src" || k === "backgroundImage" || k === "url") &&
        typeof v === "string"
      ) {
        out[k] = rewrite(v);
      } else {
        out[k] = walk(v);
      }
    }
    return out;
  };

  return walk(doc) as T;
}

function stripLegacyElements(page: Page & { elements?: unknown }): Page {
  const { elements: _drop, ...rest } = page as Page & { elements?: unknown };
  return rest as Page;
}

/**
 * 用 JSON 文档覆盖当前 PPT（支持导出的 { name, pages } 与完整 document）
 */
export function loadDocument(doc: PPTDocumentJSON) {
  if (!Array.isArray(doc.pages) || doc.pages.length === 0) {
    throw new Error("INVALID_PAGES");
  }

  const normalized = rewritePackAssetUrlsForLocalProxy(cloneDeep(doc));
  normalized.pages = normalized.pages.map((p) => stripLegacyElements(p as Page));
  pptStore.setPages(normalized.pages);

  if (doc.name != null) pptStore.setName(doc.name);
  if (doc.gridSize != null) pptStore.setGridSize(doc.gridSize);
  if (doc.gridType) pptStore.setGridType(doc.gridType);
  if (doc.verticalLine) pptStore.setVerticalLine(doc.verticalLine);
  if (doc.horizontalLine) pptStore.setHorizontalLine(doc.horizontalLine);
  if (doc.rule != null) pptStore.setRule(doc.rule);
  if (doc.guideLineShow != null) pptStore.setGuideLineShow(doc.guideLineShow);
  if (doc.keyboardToggle != null) pptStore.setKeyboardToggle(doc.keyboardToggle);

  const theme = doc.theme || inferThemeFromPages(normalized.pages);
  pptStore.setTheme(theme);

  menuActiveStore.resetMenu();
  pageActiveStore.setPageActive(normalized.pages[0]?.id ?? null);
}

export function parsePPTDocumentJSON(text: string): PPTDocumentJSON {
  const data = JSON.parse(text) as PPTDocumentJSON;
  if (!data || typeof data !== "object" || !Array.isArray(data.pages)) {
    throw new Error("INVALID_FORMAT");
  }
  if (data.pages.length === 0) {
    throw new Error("INVALID_PAGES");
  }
  return data;
}
