import type { Page } from "@/store/ppt";
import {
  SLIDE_HTML_HEIGHT,
  SLIDE_HTML_WIDTH,
} from "@/utils/slideHtml";
import { snapdom } from "@zumer/snapdom";
import { createElement, useEffect, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
const DEBOUNCE_MS = 400;
/** 离屏截图并发：保持较低，避免同时挂载过多 /embed iframe */
const CONCURRENCY = 2;
const SNAP_SCALE = 0.25;
const JPEG_QUALITY = 0.72;

type CacheEntry = {
  url: string;
  fingerprint: string;
};

const cache = new Map<string, CacheEntry>();
const listeners = new Set<() => void>();
const debounceTimers = new Map<string, ReturnType<typeof setTimeout>>();
/** 防抖期间的最新 page 快照，避免反复重置计时器 */
const debouncePages = new Map<string, Page>();
const queue: Page[] = [];
const queuedIds = new Set<string>();
const generatingIds = new Set<string>();
const pendingRegen = new Map<string, Page>();
let activeJobs = 0;
let version = 0;

function notify() {
  version += 1;
  listeners.forEach((listener) => listener());
}

export function isThumbnailPending(pageId: string): boolean {
  return (
    debounceTimers.has(pageId) ||
    queuedIds.has(pageId) ||
    generatingIds.has(pageId)
  );
}

/**
 * 仅在「还没有可用缩略图」且正在生成时视为 loading。
 * 已有缓存图时后台刷新不再转圈，避免图已出来仍一直 loading。
 */
export function isThumbnailLoading(page: Page): boolean {
  if (getCachedThumbnail(page.id)) return false;
  return isThumbnailPending(page.id);
}

export function getPageFingerprint(page: Page): string {
  return JSON.stringify({
    html: page.html ?? "",
    backgroundType: page.backgroundType,
    background: page.background,
    bgColor: page.bgColor,
    fgColor: page.fgColor,
    bgOpacity: page.bgOpacity,
    selectedTexture: (page as Page & { selectedTexture?: string })
      .selectedTexture,
    backgroundImage: (page as Page & { backgroundImage?: string })
      .backgroundImage,
    visible: page.visible,
  });
}

export function subscribeThumbnails(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getThumbnailVersion() {
  return version;
}

export function getCachedThumbnail(pageId: string): string | null {
  return cache.get(pageId)?.url ?? null;
}

export function isThumbnailFresh(page: Page): boolean {
  const entry = cache.get(page.id);
  if (!entry) return false;
  return entry.fingerprint === getPageFingerprint(page);
}

function delay(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

/**
 * 离屏渲染轻量 PreviewCanvas（1920×1080 原尺寸），生成缩略图。
 * 不用 CSS transform 缩小后再截：snapdom 等会忽略 transform，导致只剩左上角。
 */
export async function generatePageThumbnail(
  page: Page
): Promise<string | null> {
  const fingerprint = getPageFingerprint(page);
  const existing = cache.get(page.id);
  if (existing?.fingerprint === fingerprint) {
    return existing.url;
  }

  const { PreviewCanvas } = await import("@/views/Canvas/PreviewCanvas");
  const { installSlideEmbedBridge } = await import("@/utils/slideEmbedBridge");
  installSlideEmbedBridge();

  const tempContainer = document.createElement("div");
  tempContainer.style.position = "fixed";
  tempContainer.style.left = "-9999px";
  tempContainer.style.top = "0";
  tempContainer.style.width = `${SLIDE_HTML_WIDTH}px`;
  tempContainer.style.height = `${SLIDE_HTML_HEIGHT}px`;
  tempContainer.style.backgroundColor = "#fff";
  tempContainer.style.overflow = "hidden";
  tempContainer.style.pointerEvents = "none";
  document.body.appendChild(tempContainer);

  const canvasWrapper = document.createElement("div");
  canvasWrapper.style.width = `${SLIDE_HTML_WIDTH}px`;
  canvasWrapper.style.height = `${SLIDE_HTML_HEIGHT}px`;
  canvasWrapper.style.position = "relative";
  canvasWrapper.style.backgroundColor = "#fff";
  tempContainer.appendChild(canvasWrapper);

  const root = createRoot(canvasWrapper);
  root.render(createElement(PreviewCanvas, { page, fit: "design" }));

  try {
    await delay(50);
    const iframe = canvasWrapper.querySelector("iframe");
    const canvasElement = canvasWrapper.querySelector(
      `#preview-canvas-container-${page.id}`
    ) as HTMLElement | null;

    if (!canvasElement) {
      return null;
    }

    /** 优先截 iframe 内幻灯片根节点（same-origin），比只截外壳更稳 */
    let captureTarget: HTMLElement = canvasElement;
    if (iframe) {
      try {
        const { waitForSlideRoot } = await import(
          "@/utils/pptx/htmlSlideMount"
        );
        const slideRoot = await waitForSlideRoot(iframe);
        captureTarget = slideRoot;
      } catch {
        await delay(200);
      }
    } else {
      await delay(200);
    }

    const images = captureTarget.querySelectorAll("img");
    await Promise.all(
      Array.from(images).map(
        (img) =>
          new Promise<void>((resolve) => {
            const htmlImg = img as HTMLImageElement;
            if (htmlImg.complete && htmlImg.naturalHeight !== 0) {
              resolve();
              return;
            }
            const timeout = setTimeout(() => resolve(), 2000);
            htmlImg.onload = () => {
              clearTimeout(timeout);
              resolve();
            };
            htmlImg.onerror = () => {
              clearTimeout(timeout);
              resolve();
            };
          })
      )
    );

    await delay(80);

    const canvas = await snapdom.toCanvas(captureTarget, {
      scale: SNAP_SCALE,
      backgroundColor: "#fff",
      width: SLIDE_HTML_WIDTH,
      height: SLIDE_HTML_HEIGHT,
      cache: "disabled",
    });

    const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
    cache.set(page.id, { url: dataUrl, fingerprint });
    const timer = debounceTimers.get(page.id);
    if (timer) clearTimeout(timer);
    debounceTimers.delete(page.id);
    debouncePages.delete(page.id);
    notify();
    return dataUrl;
  } catch (error) {
    console.error("生成缩略图失败:", error);
    return null;
  } finally {
    root.unmount();
    if (tempContainer.parentNode) {
      document.body.removeChild(tempContainer);
    }
  }
}

function enqueue(page: Page, priority: boolean) {
  if (generatingIds.has(page.id)) {
    // 生成中内容又变了：完成后用最新 page 再跑一遍
    pendingRegen.set(page.id, page);
    return;
  }

  if (queuedIds.has(page.id)) {
    const existingIndex = queue.findIndex((item) => item.id === page.id);
    if (existingIndex >= 0) {
      queue[existingIndex] = page;
      if (priority && existingIndex > 0) {
        queue.splice(existingIndex, 1);
        queue.unshift(page);
      }
    }
    return;
  }

  if (priority) {
    queue.unshift(page);
  } else {
    queue.push(page);
  }
  queuedIds.add(page.id);
  notify();
  processQueue();
}

function processQueue() {
  while (activeJobs < CONCURRENCY && queue.length > 0) {
    const page = queue.shift()!;
    queuedIds.delete(page.id);

    if (isThumbnailFresh(page)) {
      continue;
    }

    activeJobs += 1;
    generatingIds.add(page.id);
    notify();

    generatePageThumbnail(page)
      .catch(() => null)
      .finally(() => {
        activeJobs -= 1;
        generatingIds.delete(page.id);
        notify();

        const pending = pendingRegen.get(page.id);
        if (pending) {
          pendingRegen.delete(page.id);
          if (!isThumbnailFresh(pending)) {
            enqueue(pending, true);
          }
        }

        processQueue();
      });
  }
}

/**
 * 脏页防抖调度：仅 fingerprint 变化时重新生成。
 * 已在防抖中时只更新 page 快照，不重置计时器（否则会永远 pending）。
 */
export function scheduleThumbnailUpdate(
  page: Page,
  options?: { immediate?: boolean; priority?: boolean }
) {
  if (isThumbnailFresh(page)) return;

  if (options?.immediate) {
    const prev = debounceTimers.get(page.id);
    if (prev) clearTimeout(prev);
    debounceTimers.delete(page.id);
    debouncePages.delete(page.id);
    enqueue(page, Boolean(options?.priority));
    return;
  }

  debouncePages.set(page.id, page);

  // 已在防抖窗口内：不重置 timer，避免被频繁 schedule 卡死
  if (debounceTimers.has(page.id)) {
    return;
  }

  debounceTimers.set(
    page.id,
    setTimeout(() => {
      debounceTimers.delete(page.id);
      const latest = debouncePages.get(page.id) ?? page;
      debouncePages.delete(page.id);
      enqueue(latest, Boolean(options?.priority));
      notify();
    }, DEBOUNCE_MS)
  );
  notify();
}

/** 优先为可视区页生成缩略图 */
export function scheduleVisibleThumbnails(
  pages: Page[],
  options?: { immediate?: boolean }
) {
  pages.forEach((page, index) => {
    scheduleThumbnailUpdate(page, {
      immediate: Boolean(options?.immediate) && index < 6,
      priority: true,
    });
  });
}

export function pruneThumbnailCache(validIds: Set<string>) {
  let changed = false;
  for (const id of cache.keys()) {
    if (!validIds.has(id)) {
      cache.delete(id);
      changed = true;
    }
  }
  if (changed) notify();
}

export function usePageThumbnail(page: Page): string | null {
  useSyncExternalStore(
    subscribeThumbnails,
    getThumbnailVersion,
    getThumbnailVersion
  );

  const fingerprint = getPageFingerprint(page);

  useEffect(() => {
    scheduleThumbnailUpdate(page);
    // fingerprint 变化才调度；page 取最新引用
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page.id, fingerprint]);

  return getCachedThumbnail(page.id);
}

/** 当前页缩略图是否处于加载/重新生成中 */
export function usePageThumbnailLoading(page: Page): boolean {
  useSyncExternalStore(
    subscribeThumbnails,
    getThumbnailVersion,
    getThumbnailVersion
  );
  return isThumbnailLoading(page);
}

/** 订阅整表缩略图缓存变更（虚拟列表父级用） */
export function useThumbnailCacheVersion() {
  return useSyncExternalStore(
    subscribeThumbnails,
    getThumbnailVersion,
    getThumbnailVersion
  );
}

/** 页面增删改时：清理失效缓存，并为脏页防抖调度生成 */
export function usePagesThumbnailSync(pages: Page[]) {
  useThumbnailCacheVersion();

  useEffect(() => {
    const validIds = new Set(pages.map((p) => p.id));
    pruneThumbnailCache(validIds);
    pages.forEach((page) => {
      if (!isThumbnailFresh(page)) {
        scheduleThumbnailUpdate(page);
      }
    });
  }, [pages]);
}
