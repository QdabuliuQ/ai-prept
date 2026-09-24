import { exportPPTX, generatePPTX } from "@webppt/html-to-pptx";
import type { Page } from "@/store/zustand/pptStore";
import { pageHasHtml } from "@/utils/pptx/prepareHtmlExport";

export type HtmlToPptxExportProgress = {
  current: number;
  total: number;
};

export type HtmlToPptxExportResult = {
  htmlPageCount: number;
  skippedLegacyCount: number;
};

function safeFileName(name?: string) {
  return `${(name || "未命名").replace(/[/\\?%*:|"<>]/g, "_")}-html-to-pptx.pptx`;
}

/**
 * Rewrite template-relative image paths for sandbox fetch.
 * `../images/x.png` / `images/x.png` → `{assetBaseUrl}/images/x.png`
 * Already-absolute `/api/...` (or full URL) left unchanged.
 */
export function makeTemplateAssetResolver(assetBaseUrl: string) {
  const base = assetBaseUrl.replace(/\/+$/, "");
  return (url: string) => {
    const trimmed = url.trim();
    if (!trimmed) return trimmed;
    if (/^(data:|https?:|blob:|#|\/\/)/i.test(trimmed)) return trimmed;
    // Root-absolute site paths (already rewritten by loadTemplatePages)
    if (trimmed.startsWith("/")) return trimmed;
    // Already pointed at this asset base (avoid double prefix)
    if (trimmed === base || trimmed.startsWith(`${base}/`)) return trimmed;

    const cleaned = trimmed
      .replace(/^\.\//, "")
      .replace(/^(?:\.\.\/)+/, "")
      .replace(/^\/+/, "");
    if (!cleaned) return base;
    if (cleaned.startsWith("images/")) return `${base}/${cleaned}`;
    if (cleaned.includes("/images/")) {
      const idx = cleaned.indexOf("images/");
      return `${base}/${cleaned.slice(idx)}`;
    }
    // Guard: accidental "api/html-templates/.../assets/..." without leading slash
    if (/^api\/html-templates\//i.test(cleaned)) return `/${cleaned}`;
    return `${base}/${cleaned}`;
  };
}

/**
 * Export HTML pages via @webppt/html-to-pptx (html-slide pipeline).
 */
export async function downloadHtmlToPptx(options: {
  name?: string;
  pages: Array<Pick<Page, "html" | "visible">>;
  assetBaseUrl?: string;
  onProgress?: (progress: HtmlToPptxExportProgress) => void;
}): Promise<HtmlToPptxExportResult> {
  const visible = options.pages.filter((p) => p.visible !== false);
  const htmlPages = visible.filter((p) => pageHasHtml(p as Page));
  const skippedLegacyCount = visible.length - htmlPages.length;
  if (!htmlPages.length) {
    throw new Error("没有可导出的 HTML 页面（html-to-pptx）");
  }

  const fileName = safeFileName(options.name);
  const htmlList = htmlPages.map((p) => String(p.html));
  const resolveAssetUrl = options.assetBaseUrl
    ? makeTemplateAssetResolver(options.assetBaseUrl)
    : undefined;

  const { promise } = exportPPTX(htmlList, {
    fileName,
    resolveAssetUrl,
    baseHref: options.assetBaseUrl
      ? `${options.assetBaseUrl.replace(/\/+$/, "")}/`
      : undefined,
    skipFailedPages: true,
    onSlideProgress: ({ current, total }) => {
      try {
        options.onProgress?.({ current, total });
      } catch {
        /* ignore */
      }
    },
  });

  await promise;
  return { htmlPageCount: htmlPages.length, skippedLegacyCount };
}

/** Blob only (no download) — for tests / custom UI. */
export async function generateHtmlToPptxBlob(options: {
  pages: Array<Pick<Page, "html" | "visible">>;
  assetBaseUrl?: string;
  fileName?: string;
}): Promise<Blob> {
  const htmlList = options.pages
    .filter((p) => p.visible !== false && pageHasHtml(p as Page))
    .map((p) => String(p.html));
  if (!htmlList.length) throw new Error("没有可导出的 HTML 页面");
  const { promise } = generatePPTX(htmlList, {
    fileName: options.fileName,
    resolveAssetUrl: options.assetBaseUrl
      ? makeTemplateAssetResolver(options.assetBaseUrl)
      : undefined,
    skipFailedPages: true,
  });
  return promise;
}
