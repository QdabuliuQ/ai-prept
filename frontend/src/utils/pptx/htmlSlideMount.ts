import type { Page } from "@/store/zustand/pptStore";
import {
  SLIDE_HTML_HEIGHT,
  SLIDE_HTML_WIDTH,
} from "@/utils/slideHtml";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";

function delay(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}

export async function waitForImages(root: ParentNode, timeoutMs = 8000) {
  const images = Array.from(root.querySelectorAll("img")) as HTMLImageElement[];
  await Promise.all(
    images.map(
      (img) =>
        new Promise<void>((resolve) => {
          if (img.complete && img.naturalHeight !== 0) {
            resolve();
            return;
          }
          const t = setTimeout(() => resolve(), timeoutMs);
          img.onload = () => {
            clearTimeout(t);
            resolve();
          };
          img.onerror = () => {
            clearTimeout(t);
            resolve();
          };
        }),
    ),
  );
}

async function waitForFonts(doc: Document, timeoutMs = 8000) {
  const fonts = doc.fonts;
  if (!fonts) return;
  await Promise.race([
    fonts.ready.then(() => undefined),
    delay(timeoutMs),
  ]);
}

/** 固定导出帧，避免动画、光标和异步字体造成截图漂移。 */
function freezeForExport(doc: Document) {
  const style = doc.createElement("style");
  style.setAttribute("data-webppt-export-freeze", "true");
  style.textContent = `
    *, *::before, *::after {
      animation: none !important;
      transition: none !important;
      caret-color: transparent !important;
      scroll-behavior: auto !important;
    }
    html, body {
      width: ${SLIDE_HTML_WIDTH}px !important;
      height: ${SLIDE_HTML_HEIGHT}px !important;
      overflow: hidden !important;
    }
  `;
  doc.head?.appendChild(style);
}

/** 读取 body 可见文案，排除 <script>/<style>，避免 boot 壳源码误触发失败检测 */
function bodyVisibleText(doc: Document): string {
  const body = doc.body;
  if (!body) return "";
  const clone = body.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("script, style, noscript").forEach((el) => el.remove());
  return (clone.textContent || "").trim();
}

function readEmbedFailure(doc: Document): string | null {
  const body = doc.body;
  if (!body) return null;
  if (body.getAttribute("data-webppt-embed-error") === "1") {
    return bodyVisibleText(doc) || "幻灯片 embed 失败";
  }
  // 兼容旧壳：无 script、短文案且命中固定失败句
  if (doc.querySelector("script")) return null;
  const text = bodyVisibleText(doc);
  if (
    text === "无法从编辑器读取页面内容" ||
    text === "缺少访问令牌" ||
    text === "缺少 pageId"
  ) {
    return text;
  }
  return null;
}

function isEmbedBootShell(doc: Document): boolean {
  // /embed/slide 初始壳：尚未 document.write 幻灯片
  if (doc.body?.getAttribute("data-webppt-embed-error") === "1") return false;
  const hasBootScript =
    !!doc.querySelector("script") &&
    !doc.querySelector(".slide-container, .slide");
  return hasBootScript && (doc.body?.children.length || 0) <= 2;
}

function findSlideRoot(doc: Document): HTMLElement | null {
  const body = doc.body;
  if (!body) return null;
  const slide =
    (body.querySelector(".slide-container") as HTMLElement | null) ||
    (body.querySelector(".slide") as HTMLElement | null) ||
    (body.firstElementChild as HTMLElement | null);
  return slide;
}

function isSlideDocumentReady(doc: Document, slide: HTMLElement | null): boolean {
  const body = doc.body;
  if (!body || !slide) return false;
  if (isEmbedBootShell(doc)) return false;

  const hasThemeOrVendor = !!doc.querySelector(
    'link[href*="theme.css"], link[href*="slide-vendor"], link[href*="/assets/"]',
  );
  const richDom = body.querySelectorAll("*").length > 8;
  const wideEnough = slide.clientWidth >= 800 || slide.scrollWidth >= 800;
  const substantialHtml = body.innerHTML.length > 800;

  return hasThemeOrVendor || (richDom && (wideEnough || substantialHtml));
}

/**
 * 等 /embed/slide 完成 document.write，返回可测量的幻灯片根节点。
 * detectTimeoutMs：找到 DOM 的上限；资源等待另计，不挤占探测时间。
 */
export async function waitForSlideRoot(
  iframe: HTMLIFrameElement,
  detectTimeoutMs = 30000,
): Promise<HTMLElement> {
  const start = Date.now();
  let embedErrorSince: number | null = null;

  while (Date.now() - start < detectTimeoutMs) {
    try {
      const doc = iframe.contentDocument;
      if (doc?.body) {
        const failText = readEmbedFailure(doc);
        if (failText) {
          // Strict Mode / src 切换时可能先失败再成功，宽限后再抛
          if (embedErrorSince == null) embedErrorSince = Date.now();
          if (Date.now() - embedErrorSince > 1200) {
            throw new Error(`幻灯片 iframe 加载失败：${failText}`);
          }
        } else {
          embedErrorSince = null;

          const slide = findSlideRoot(doc);
          if (isSlideDocumentReady(doc, slide) && slide) {
            await waitForImages(doc, 12000);
            await waitForFonts(doc, 5000);
            freezeForExport(doc);
            await delay(120);
            return slide.tagName.toLowerCase() === "html"
              ? (doc.documentElement as HTMLElement)
              : slide;
          }

          if (
            !isEmbedBootShell(doc) &&
            doc.body.childElementCount > 0 &&
            doc.body.innerHTML.length > 800
          ) {
            await waitForImages(doc, 12000);
            await waitForFonts(doc, 5000);
            freezeForExport(doc);
            await delay(120);
            return (doc.documentElement as HTMLElement) || doc.body;
          }
        }
      }
    } catch (err) {
      if (
        err instanceof Error &&
        err.message.startsWith("幻灯片 iframe 加载失败")
      ) {
        throw err;
      }
      /* ignore cross-document transient errors */
    }
    await delay(100);
  }
  throw new Error("幻灯片 iframe 渲染超时");
}

/** 等待 ECharts canvas 有像素（或超时） */
export async function waitForCharts(doc: Document, timeoutMs = 4000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const canvases = Array.from(doc.querySelectorAll("canvas"));
    if (canvases.length === 0) return;
    const ready = canvases.every((c) => c.width > 0 && c.height > 0);
    if (ready) {
      await delay(120);
      return;
    }
    await delay(100);
  }
}

export type MountedHtmlSlide = {
  doc: Document;
  slideRoot: HTMLElement;
  iframe: HTMLIFrameElement;
};

function iframeHasRealSrc(iframe: HTMLIFrameElement): boolean {
  const attr = iframe.getAttribute("src") || "";
  if (!attr || attr === "about:blank") return false;
  try {
    const u = new URL(iframe.src, window.location.href);
    return u.pathname.includes("/embed/slide");
  } catch {
    return attr.includes("/embed/slide");
  }
}

/** 等 React 把 /embed/slide src 写上 */
async function waitForIframeSrc(
  iframe: HTMLIFrameElement,
  timeoutMs = 8000,
) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (iframeHasRealSrc(iframe)) return;
    await delay(40);
  }
  throw new Error("幻灯片 iframe 未设置 embed 地址");
}

async function waitForIframeLoad(iframe: HTMLIFrameElement, timeoutMs = 10000) {
  await new Promise<void>((resolve) => {
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    const t = setTimeout(done, timeoutMs);
    iframe.addEventListener(
      "load",
      () => {
        clearTimeout(t);
        done();
      },
      { once: true },
    );
    try {
      if (
        iframeHasRealSrc(iframe) &&
        iframe.contentDocument?.readyState === "complete"
      ) {
        clearTimeout(t);
        setTimeout(done, 50);
      }
    } catch {
      /* ignore */
    }
  });
}

async function mountSlideFromWrap(
  wrap: HTMLElement,
  remark?: string,
): Promise<MountedHtmlSlide> {
  const iframe = wrap.querySelector("iframe");
  if (!iframe) {
    throw new Error("未找到幻灯片 iframe");
  }

  await waitForIframeSrc(iframe);
  await waitForIframeLoad(iframe);
  const slideRoot = await waitForSlideRoot(iframe);
  const doc = iframe.contentDocument!;
  await waitForCharts(doc);

  if (remark?.trim()) {
    slideRoot.setAttribute("data-pptx-notes", remark.trim());
  }

  return { doc, slideRoot, iframe };
}

/**
 * 离屏挂载 PreviewCanvas，在回调内访问已渲染的 HTML 幻灯片 DOM。
 */
export async function withMountedHtmlSlide<T>(
  page: Page,
  fn: (ctx: MountedHtmlSlide) => Promise<T>,
): Promise<T> {
  const { PreviewCanvas } = await import("@/views/Canvas/PreviewCanvas");
  const { installSlideEmbedBridge } = await import("@/utils/slideEmbedBridge");
  installSlideEmbedBridge();

  const tempContainer = document.createElement("div");
  tempContainer.style.position = "fixed";
  tempContainer.style.left = "-9999px";
  tempContainer.style.top = "0";
  tempContainer.style.width = `${SLIDE_HTML_WIDTH}px`;
  tempContainer.style.height = `${SLIDE_HTML_HEIGHT}px`;
  tempContainer.style.overflow = "hidden";
  tempContainer.style.background = "#fff";
  tempContainer.style.pointerEvents = "none";
  tempContainer.style.zIndex = "-1";
  document.body.appendChild(tempContainer);

  const wrap = document.createElement("div");
  wrap.style.width = `${SLIDE_HTML_WIDTH}px`;
  wrap.style.height = `${SLIDE_HTML_HEIGHT}px`;
  wrap.style.position = "relative";
  wrap.style.background = "#fff";
  tempContainer.appendChild(wrap);

  let root: Root | null = createRoot(wrap);
  root.render(createElement(PreviewCanvas, { page, fit: "design" }));

  try {
    await delay(80);
    return await fn(await mountSlideFromWrap(wrap, page.remark));
  } finally {
    root?.unmount();
    root = null;
    if (tempContainer.parentNode) {
      document.body.removeChild(tempContainer);
    }
  }
}

/** 多页导出时分批挂载，避免同时开太多 /embed/slide */
const EXPORT_MOUNT_BATCH = 3;

/**
 * 批量离屏挂载 HTML 幻灯片（缩略图 / 导出等）。
 */
export async function withMountedHtmlSlides<T>(
  pages: Page[],
  fn: (slides: MountedHtmlSlide[]) => Promise<T>,
): Promise<T> {
  if (pages.length === 0) {
    throw new Error("没有可挂载的 HTML 页面");
  }

  const { PreviewCanvas } = await import("@/views/Canvas/PreviewCanvas");
  const { installSlideEmbedBridge } = await import("@/utils/slideEmbedBridge");
  installSlideEmbedBridge();

  const tempContainer = document.createElement("div");
  tempContainer.style.position = "fixed";
  tempContainer.style.left = "-9999px";
  tempContainer.style.top = "0";
  tempContainer.style.pointerEvents = "none";
  tempContainer.style.zIndex = "-1";
  document.body.appendChild(tempContainer);

  const mounts: { root: Root; wrap: HTMLElement }[] = [];
  const slides: MountedHtmlSlide[] = new Array(pages.length);

  try {
    for (let start = 0; start < pages.length; start += EXPORT_MOUNT_BATCH) {
      const end = Math.min(start + EXPORT_MOUNT_BATCH, pages.length);
      const batchMounts: { root: Root; wrap: HTMLElement; index: number }[] =
        [];

      for (let i = start; i < end; i += 1) {
        const page = pages[i];
        const wrap = document.createElement("div");
        wrap.style.width = `${SLIDE_HTML_WIDTH}px`;
        wrap.style.height = `${SLIDE_HTML_HEIGHT}px`;
        wrap.style.position = "relative";
        wrap.style.background = "#fff";
        tempContainer.appendChild(wrap);

        const root = createRoot(wrap);
        root.render(createElement(PreviewCanvas, { page, fit: "design" }));
        mounts.push({ root, wrap });
        batchMounts.push({ root, wrap, index: i });
      }

      await delay(80);

      for (const m of batchMounts) {
        slides[m.index] = await mountSlideFromWrap(
          m.wrap,
          pages[m.index].remark,
        );
      }
    }

    return await fn(slides);
  } finally {
    for (const { root } of mounts) {
      root.unmount();
    }
    if (tempContainer.parentNode) {
      document.body.removeChild(tempContainer);
    }
  }
}
