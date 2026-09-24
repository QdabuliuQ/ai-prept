import { pptStore } from "@/store";
import { normalizeSlideHtml } from "@/utils/slideHtml";
import type { Page } from "@/store/ppt";

export type SlideEmbedBridge = {
  /**
   * 仅当 pageId 持有有效 lease（token）时返回 HTML，
   * 防止任意同源 iframe 枚举读取其它页。
   */
  getPageHtml: (pageId: string, token?: string | null) => string | null;
};

declare global {
  interface Window {
    __WEBPPT_SLIDE_BRIDGE__?: SlideEmbedBridge;
    /** /embed/slide iframe 读取页 HTML（与 bridge.getPageHtml 同实现） */
    __webpptGetSlideHtml?: (
      pageId: string,
      token?: string | null,
    ) => string | null;
  }
}

type Lease = {
  token: string;
  refs: number;
  /** 挂载时快照，避免仅依赖 store 查找 / Strict Mode 竞态 */
  html?: string;
};

/** pageId → 当前渲染租约（编辑画布 / 离屏截图） */
const leases = new Map<string, Lease>();

/** Strict Mode 会先 cleanup 再 mount：延迟删除避免 iframe 读桥瞬时失败 */
const pendingReleaseTimers = new Map<string, ReturnType<typeof setTimeout>>();

const RELEASE_GRACE_MS = 200;

function findPage(pageId: string): Page | undefined {
  return (
    pptStore.getActivePage(pageId) ||
    pptStore.getPages().find((p) => p.id === pageId)
  );
}

function newToken(pageId: string): string {
  return `${pageId}_${Math.random().toString(36).slice(2, 10)}_${Date.now().toString(36)}`;
}

function cancelPendingRelease(pageId: string) {
  const timer = pendingReleaseTimers.get(pageId);
  if (timer != null) {
    clearTimeout(timer);
    pendingReleaseTimers.delete(pageId);
  }
}

/**
 * 声明某页即将在 iframe 中渲染；同页多次挂载复用 token（refs++）。
 * html 快照用于桥读取，不依赖 store 是否已同步。
 */
export function acquireSlideEmbedAccess(
  pageId: string,
  html?: string | null,
): string {
  cancelPendingRelease(pageId);

  const existing = leases.get(pageId);
  if (existing) {
    existing.refs = Math.max(0, existing.refs) + 1;
    if (html != null) existing.html = html;
    return existing.token;
  }

  const token = newToken(pageId);
  leases.set(pageId, {
    token,
    refs: 1,
    html: html != null ? html : undefined,
  });
  return token;
}

/** 更新已有租约中的 HTML 快照（同页内容变更但未换 token 时） */
export function touchSlideEmbedHtml(pageId: string, html: string | null | undefined) {
  const existing = leases.get(pageId);
  if (!existing || html == null) return;
  existing.html = html;
}

/** iframe / 离屏容器卸载时释放；refs 归零后宽限期内可被 remount 复活 */
export function releaseSlideEmbedAccess(pageId: string) {
  const existing = leases.get(pageId);
  if (!existing) return;
  existing.refs -= 1;
  if (existing.refs > 0) return;

  existing.refs = 0;
  cancelPendingRelease(pageId);
  const timer = setTimeout(() => {
    pendingReleaseTimers.delete(pageId);
    const cur = leases.get(pageId);
    if (cur && cur.refs <= 0) {
      leases.delete(pageId);
    }
  }, RELEASE_GRACE_MS);
  pendingReleaseTimers.set(pageId, timer);
}

/** 在编辑器顶层安装桥，供 /embed/slide iframe 取页 HTML */
export function installSlideEmbedBridge() {
  if (typeof window === "undefined") return;
  const getPageHtml = (pageId: string, token?: string | null) => {
    if (!pageId || !token) return null;
    const lease = leases.get(pageId);
    if (!lease || lease.token !== token) return null;

    const page = findPage(pageId);
    if (page) {
      // 优先页面最新 html；若为空则回落到租约快照
      const raw = (page.html && page.html.trim()) || lease.html || "";
      return normalizeSlideHtml(raw || page.html, page);
    }
    if (lease.html != null) {
      return normalizeSlideHtml(lease.html);
    }
    return null;
  };
  window.__WEBPPT_SLIDE_BRIDGE__ = { getPageHtml };
  // backend /embed/slide 壳调用此全局函数
  window.__webpptGetSlideHtml = getPageHtml;
}

/** 简易内容指纹，驱动 iframe 在 HTML 变化时刷新 */
export function slideContentVersion(html: string | undefined | null): string {
  const s = html || "";
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) | 0;
  }
  return `${s.length.toString(36)}_${(h >>> 0).toString(36)}`;
}

export function buildSlideEmbedSrc(
  pageId: string,
  html?: string | null,
  token?: string | null,
  options?: { edit?: boolean },
): string {
  const v = slideContentVersion(html);
  const params = new URLSearchParams({
    pageId,
    v,
  });
  if (token) params.set("t", token);
  if (options?.edit) params.set("edit", "1");
  return `/embed/slide?${params.toString()}`;
}

export { buildTemplateSlideEmbedSrc } from "@/utils/templateEmbed";
