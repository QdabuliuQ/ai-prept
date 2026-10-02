import { toast } from "sonner";
import { loadDocument, type PPTDocumentJSON } from "@/utils/loadDocument";
import { installSlideEmbedBridge } from "@/utils/slideEmbedBridge";
import { pageActiveStore, pptStore, useGalleryRemixStore } from "@/store";
import type { Page } from "@/store/ppt";

export const PENDING_REMIX_JOB_KEY = "webppt:pending-remix-job";

export type PendingRemixJob = {
  jobId: string;
  sourceTemplateId?: string;
  prompt?: string;
};

type GalleryJob = {
  id?: string;
  status?: string;
  templateId?: string;
  pagesReady?: Array<{ index?: number; file?: string } | number>;
  pageTotal?: number;
  progress?: { done?: number; total?: number; percent?: number };
  error?: string;
};

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** 生成中占位：16:9 幻灯片骨架屏 + shimmer，避免纯文本空页 */
function placeholderPage(label: string): Page {
  const safeLabel = escapeHtml(label || "正在根据模板生成内容…");
  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=1920"/>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body {
    width: 1920px;
    height: 1080px;
    overflow: hidden;
    background: #f4f2ef;
    font-family: "PingFang SC", "Noto Sans SC", "Hiragino Sans GB",
      "Microsoft YaHei", system-ui, sans-serif;
    color: #6b6560;
  }
  @keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  @keyframes pulse-dot {
    0%, 80%, 100% { opacity: 0.28; transform: scale(0.85); }
    40% { opacity: 1; transform: scale(1); }
  }
  @keyframes fade-in {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .bone {
    background: linear-gradient(
      105deg,
      #e8e4df 0%,
      #e8e4df 38%,
      #f7f4f0 50%,
      #e8e4df 62%,
      #e8e4df 100%
    );
    background-size: 220% 100%;
    animation: shimmer 1.65s ease-in-out infinite;
    border-radius: 10px;
  }
  .stage {
    position: relative;
    width: 1920px;
    height: 1080px;
    padding: 88px 96px 80px;
    animation: fade-in 0.45s ease-out both;
  }
  .accent {
    position: absolute;
    left: 0;
    top: 0;
    width: 14px;
    height: 100%;
    background: linear-gradient(180deg, #f25f00 0%, #ffb07a 55%, #f4d2b8 100%);
    opacity: 0.85;
  }
  .kicker {
    width: 220px;
    height: 28px;
    margin-bottom: 28px;
  }
  .title {
    width: 920px;
    height: 72px;
    margin-bottom: 22px;
    border-radius: 14px;
  }
  .subtitle {
    width: 640px;
    height: 36px;
    margin-bottom: 64px;
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr 720px;
    gap: 48px;
    align-items: stretch;
    height: 620px;
  }
  .col {
    display: flex;
    flex-direction: column;
    gap: 28px;
  }
  .line { height: 28px; border-radius: 8px; }
  .line.w90 { width: 90%; }
  .line.w75 { width: 75%; }
  .line.w60 { width: 60%; }
  .card {
    flex: 1;
    border-radius: 22px;
    min-height: 140px;
  }
  .media {
    height: 100%;
    border-radius: 28px;
  }
  .status {
    position: absolute;
    left: 50%;
    bottom: 56px;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 22px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.72);
    border: 1px solid rgba(0, 0, 0, 0.06);
    box-shadow: 0 8px 28px rgba(60, 50, 40, 0.06);
    backdrop-filter: blur(10px);
    font-size: 22px;
    letter-spacing: 0.02em;
    white-space: nowrap;
  }
  .dots { display: inline-flex; gap: 6px; }
  .dots i {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #f25f00;
    display: block;
    animation: pulse-dot 1.1s ease-in-out infinite;
  }
  .dots i:nth-child(2) { animation-delay: 0.15s; }
  .dots i:nth-child(3) { animation-delay: 0.3s; }
</style>
</head>
<body>
  <div class="stage" role="status" aria-live="polite" aria-label="${safeLabel}" data-editor-placeholder="true" data-injected="true">
    <div class="accent" aria-hidden="true"></div>
    <div class="bone kicker" aria-hidden="true"></div>
    <div class="bone title" aria-hidden="true"></div>
    <div class="bone subtitle" aria-hidden="true"></div>
    <div class="grid" aria-hidden="true">
      <div class="col">
        <div class="bone line w90"></div>
        <div class="bone line w75"></div>
        <div class="bone line w60"></div>
        <div class="bone card"></div>
        <div class="bone card"></div>
      </div>
      <div class="bone media"></div>
    </div>
    <div class="status" aria-hidden="false">
      <span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>
      <span>${safeLabel}</span>
    </div>
  </div>
</body>
</html>`;
  return {
    id: "remix_pending",
    html,
    visible: true,
    toggleInAnimation: "none",
    toggleInDuration: "0.5s",
    toggleInDelay: "0s",
    autoToggle: false,
    autoToggleTime: 0,
    backgroundType: "color",
    background: "#f4f2ef",
    bgColor: "#f4f2ef",
    fgColor: "#6b6560",
    bgOpacity: 1,
    remark: "生成中",
  };
}

function humanizeRemixError(raw: string, cancelled = false): string {
  const text = String(raw || "").trim();
  if (cancelled) return text || "生成已取消";
  if (!text) return "生成失败，请返回首页重试";
  const lower = text.toLowerCase();
  if (
    lower.includes("quota") ||
    lower.includes("billing") ||
    lower.includes("resource_exhausted") ||
    /\b429\b/.test(text)
  ) {
    return "API 额度已用尽，请检查套餐与计费后重试";
  }
  if (
    lower === "forbidden" ||
    lower.includes("'message': 'forbidden'") ||
    lower.includes('"message":"forbidden"') ||
    /\berror code:\s*403\b/.test(lower) ||
    /\b403\b/.test(text)
  ) {
    return "当前所选模型拒绝访问（403 Forbidden），请更换文案模型或检查对应 API Key 权限后重试";
  }
  if (
    lower.includes("connection error") ||
    lower.includes("connecterror") ||
    lower.includes("connection refused")
  ) {
    return "无法连接模型服务，请检查网络与模型配置后重试";
  }
  if (
    lower.includes("high demand") ||
    lower.includes("unavailable") ||
    /\b503\b/.test(text)
  ) {
    return "模型服务繁忙，请稍后返回首页重试";
  }
  if (lower.includes("timeout") || lower.includes("timed out")) {
    return "生成超时，请返回首页重试";
  }
  if (/^exit\s+\d+$/i.test(text) || /^ok=\d+\s+fail=\d+$/i.test(text)) {
    return "生成失败，请返回首页重试";
  }
  // 去掉超长官方文档链接，保留可读句子
  const withoutUrl = text.replace(/https?:\/\/\S+/gi, "").trim();
  const cleaned = withoutUrl || text;
  if (cleaned.length > 120) return `${cleaned.slice(0, 117)}…`;
  return cleaned;
}

/** 失败后画布留白，错误改由编辑器壳层 Modal 展示 */
function idleBlankPage(): Page {
  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=1920"/>
<style>
  html, body {
    width: 1920px;
    height: 1080px;
    margin: 0;
    background: #f4f2ef;
  }
</style>
</head>
<body data-editor-placeholder="true" data-injected="true"></body>
</html>`;
  return {
    id: "remix_idle",
    html,
    visible: true,
    toggleInAnimation: "none",
    toggleInDuration: "0.5s",
    toggleInDelay: "0s",
    autoToggle: false,
    autoToggleTime: 0,
    backgroundType: "color",
    background: "#f4f2ef",
    bgColor: "#f4f2ef",
    fgColor: "#6b6560",
    bgOpacity: 1,
    remark: "",
  };
}

function readyIndices(pagesReady: GalleryJob["pagesReady"]): number[] {
  if (!Array.isArray(pagesReady)) return [];
  const out: number[] = [];
  for (const item of pagesReady) {
    if (typeof item === "number" && Number.isFinite(item)) {
      out.push(item);
      continue;
    }
    if (item && typeof item === "object" && Number.isFinite(item.index)) {
      out.push(Number(item.index));
    }
  }
  return [...new Set(out)].sort((a, b) => a - b);
}

async function fetchEditorDoc(templateId: string): Promise<PPTDocumentJSON> {
  const res = await fetch(
    `/api/html-templates/${encodeURIComponent(templateId)}?t=${Date.now()}`,
  );
  const doc = (await res.json().catch(() => ({}))) as PPTDocumentJSON & {
    error?: string;
    message?: string;
  };
  if (!res.ok) {
    throw new Error(doc.message || doc.error || `加载失败（${res.status}）`);
  }
  if (!Array.isArray(doc.pages) || doc.pages.length === 0) {
    throw new Error("结果文档为空");
  }
  return doc;
}

function applyPartialDoc(doc: PPTDocumentJSON, indices: number[]) {
  const pages = indices
    .map((i) => doc.pages[i])
    .filter((p): p is Page => Boolean(p && (p as Page).html));
  if (!pages.length) return 0;
  loadDocument({
    ...doc,
    pages,
  });
  installSlideEmbedBridge();
  return pages.length;
}

/**
 * 同步写入生成中骨架（首帧前调用，避免先进编辑器先闪 mock 页）。
 */
export function applyRemixPlaceholder(label = "正在根据模板生成内容…"): void {
  useGalleryRemixStore.getState().clearFailure();
  useGalleryRemixStore.getState().setBusy(true);
  try {
    loadDocument({
      name: "正在生成…",
      pages: [placeholderPage(label)],
    });
    installSlideEmbedBridge();
    const pages = pptStore.getPages();
    if (pages[0]) pageActiveStore.setPageActive(pages[0].id);
  } catch {
    pptStore.resetPages();
  }
}

function applyRemixFailure(raw: string, cancelled = false): void {
  const detail = humanizeRemixError(raw, cancelled);
  useGalleryRemixStore.getState().setFailure(detail, cancelled);
  try {
    loadDocument({
      name: cancelled ? "生成已取消" : "未命名",
      pages: [idleBlankPage()],
    });
    installSlideEmbedBridge();
    const pages = pptStore.getPages();
    if (pages[0]) pageActiveStore.setPageActive(pages[0].id);
  } catch {
    pptStore.resetPages();
  }
}

/**
 * 编辑器内轮询 Gallery remix：任务就绪后按页写入画布。
 * 返回 cleanup。
 */
export function startGalleryRemixPoll(pending: PendingRemixJob): () => void {
  const jobId = String(pending.jobId || "").trim();
  if (!jobId) return () => undefined;

  let cancelled = false;
  let lastReadyCount = 0;
  const setRemixBusy = (busy: boolean) => {
    useGalleryRemixStore.getState().setBusy(busy);
  };

  // 若首帧已注入骨架则只保 busy；否则补一次
  setRemixBusy(true);
  if (pptStore.getPages()[0]?.id !== "remix_pending") {
    applyRemixPlaceholder();
  }

  const finish = () => {
    setRemixBusy(false);
  };

  const tick = async () => {
    if (cancelled) return;
    try {
      const jr = await fetch(`/api/gallery/jobs/${encodeURIComponent(jobId)}`);
      const jd = (await jr.json().catch(() => ({}))) as {
        job?: GalleryJob;
        error?: string;
        message?: string;
      };
      if (!jr.ok) {
        throw new Error(jd.message || jd.error || `查询失败（${jr.status}）`);
      }
      const job = jd.job || {};
      const st = String(job.status || "");
      const templateId = String(job.templateId || "").trim();
      const indices = readyIndices(job.pagesReady);

      if (st === "failed" || st === "cancelled") {
        if (cancelled) return;
        applyRemixFailure(
          job.error || (st === "cancelled" ? "生成已取消" : "生成失败"),
          st === "cancelled",
        );
        return;
      }

      if (templateId && indices.length > lastReadyCount) {
        const doc = await fetchEditorDoc(templateId);
        if (cancelled) return;
        const n = applyPartialDoc(doc, indices);
        if (n > 0) {
          lastReadyCount = indices.length;
          const pages = pptStore.getPages();
          if (pages[0]) pageActiveStore.setPageActive(pages[pages.length - 1].id);
        }
      }

      if (st === "succeeded") {
        if (!templateId) {
          throw new Error("生成完成但未返回模板 id");
        }
        const doc = await fetchEditorDoc(templateId);
        if (cancelled) return;
        loadDocument(doc);
        installSlideEmbedBridge();
        finish();
        toast.success(`已生成 ${doc.pages.length} 页`);
        return;
      }

      // awaiting_html：包已写完、等浏览器转 HTML，仍属进行中
      if (st === "queued" || st === "running" || st === "awaiting_html" || !st) {
        window.setTimeout(() => void tick(), 1500);
        return;
      }

      if (cancelled) return;
      applyRemixFailure(`未知任务状态：${st}`);
    } catch (e) {
      if (cancelled) return;
      applyRemixFailure(e instanceof Error ? e.message : "生成失败");
    }
  };

  void tick();

  return () => {
    cancelled = true;
    finish();
  };
}

/** Strict Mode 双挂载时复用同一次 handoff，避免第二次读不到 sessionStorage */
let consumedPendingRemix: PendingRemixJob | null | undefined;
let remixPlaceholderApplied = false;

export function consumePendingRemixJob(): PendingRemixJob | null {
  if (consumedPendingRemix !== undefined) {
    // Strict Mode 二次进入：骨架若被卸掉则再补一次
    if (consumedPendingRemix && !remixPlaceholderApplied) {
      applyRemixPlaceholder();
      remixPlaceholderApplied = true;
    }
    return consumedPendingRemix;
  }
  try {
    const raw = sessionStorage.getItem(PENDING_REMIX_JOB_KEY);
    if (!raw) {
      consumedPendingRemix = null;
      return null;
    }
    sessionStorage.removeItem(PENDING_REMIX_JOB_KEY);
    const data = JSON.parse(raw) as PendingRemixJob;
    if (!data?.jobId) {
      consumedPendingRemix = null;
      return null;
    }
    consumedPendingRemix = data;
    // 首帧前同步骨架，避免先闪 mock / 空白再跳变
    applyRemixPlaceholder();
    remixPlaceholderApplied = true;
    return data;
  } catch {
    sessionStorage.removeItem(PENDING_REMIX_JOB_KEY);
    consumedPendingRemix = null;
    return null;
  }
}
