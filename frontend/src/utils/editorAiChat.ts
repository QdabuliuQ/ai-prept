import type { Page } from "@/store";
import { pageActiveStore, usePPTStore } from "@/store";
import { getRandomId } from "@/utils";
import type { TemplateTreeNode } from "@/utils/templateTree";

export type EditorAiMode = "rewrite" | "generate" | "delete";

export type EditorJobStatus = {
  id: string;
  status: string;
  pipeline?: string;
  templateId?: string | null;
  workspaceId?: string | null;
  slideFile?: string | null;
  pageIndex?: number | null;
  error?: string | null;
  resultFile?: string | null;
  resultTitle?: string | null;
  insertAt?: number | null;
  activateFile?: string | null;
  deletedFiles?: string[];
  changedFiles?: string[];
  regeneratedImages?: string[];
  summary?: string | null;
  summaryMarkdown?: string | null;
  intent?: string | null;
};

type EditorDocPage = {
  id: string;
  html?: string;
  sourceFile?: string;
  remark?: string;
};

type EditorDoc = {
  templateId?: string;
  workspaceId?: string;
  tree?: TemplateTreeNode[];
  pages: EditorDocPage[];
};

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

async function readError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { error?: string; message?: string };
    return data.message || data.error || `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

function workspaceBase(id: string) {
  return `/api/editor/workspaces/${encodeURIComponent(id)}`;
}

export async function startEditorRewrite(options: {
  templateId: string;
  issue: string;
  file?: string;
  pageIndex?: number;
}): Promise<{ jobId: string }> {
  const res = await fetch(`${workspaceBase(options.templateId)}/rewrite-page`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      issue: options.issue,
      file: options.file,
      pageIndex: options.pageIndex,
    }),
  });
  if (!res.ok) throw new Error(await readError(res));
  const data = (await res.json()) as { job?: { id?: string } };
  const jobId = String(data.job?.id || "");
  if (!jobId) throw new Error("未返回任务 id");
  return { jobId };
}

export async function startEditorGenerate(options: {
  templateId: string;
  issue: string;
  afterFile?: string;
  afterPageIndex?: number;
}): Promise<{ jobId: string }> {
  const res = await fetch(`${workspaceBase(options.templateId)}/generate-page`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      issue: options.issue,
      afterFile: options.afterFile,
      afterPageIndex: options.afterPageIndex,
    }),
  });
  if (!res.ok) throw new Error(await readError(res));
  const data = (await res.json()) as { job?: { id?: string } };
  const jobId = String(data.job?.id || "");
  if (!jobId) throw new Error("未返回任务 id");
  return { jobId };
}

export async function startEditorDelete(options: {
  templateId: string;
  file?: string;
  pageIndex?: number;
}): Promise<{ jobId: string }> {
  const res = await fetch(`${workspaceBase(options.templateId)}/delete-page`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file: options.file,
      pageIndex: options.pageIndex,
    }),
  });
  if (!res.ok) throw new Error(await readError(res));
  const data = (await res.json()) as { job?: { id?: string } };
  const jobId = String(data.job?.id || "");
  if (!jobId) throw new Error("未返回任务 id");
  return { jobId };
}

export type AssistElementTarget = {
  selector?: string;
  editorId?: string;
  tagName?: string;
  isTextElement?: boolean;
  isImageElement?: boolean;
  textContent?: string;
  dataSlot?: string;
  dataSlotType?: string;
  dataSlotRole?: string;
  dataElement?: string;
  imageSrc?: string;
};

export async function startEditorAssist(options: {
  templateId: string;
  issue: string;
  file?: string;
  pageIndex?: number;
  llmProvider?: string;
  llmModel?: string;
  imageProvider?: string;
  imageModel?: string;
  element?: AssistElementTarget | null;
}): Promise<{
  jobId: string;
  intent: EditorAiMode | "assist";
  reason?: string;
  mode?: string;
}> {
  const res = await fetch(`${workspaceBase(options.templateId)}/assist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      issue: options.issue,
      file: options.file,
      pageIndex: options.pageIndex,
      llmProvider: options.llmProvider,
      llmModel: options.llmModel,
      imageProvider: options.imageProvider,
      imageModel: options.imageModel,
      element: options.element || undefined,
    }),
  });
  if (!res.ok) throw new Error(await readError(res));
  const data = (await res.json()) as {
    job?: { id?: string };
    intent?: string;
    reason?: string;
    mode?: string;
  };
  const jobId = String(data.job?.id || "");
  if (!jobId) throw new Error("未返回任务 id");
  const raw = String(data.intent || "assist").toLowerCase();
  const intent: EditorAiMode | "assist" =
    raw === "generate" || raw === "delete" || raw === "rewrite" || raw === "assist"
      ? raw
      : "assist";
  return {
    jobId,
    intent,
    reason: data.reason ? String(data.reason) : undefined,
    mode: data.mode ? String(data.mode) : undefined,
  };
}

export async function pollEditorJob(
  jobId: string,
  options?: { maxAttempts?: number; intervalMs?: number; signal?: AbortSignal },
): Promise<EditorJobStatus> {
  const maxAttempts = options?.maxAttempts ?? 90;
  const intervalMs = options?.intervalMs ?? 2000;
  for (let i = 0; i < maxAttempts; i++) {
    if (options?.signal?.aborted) {
      throw new Error("ABORTED");
    }
    if (i > 0) await sleep(intervalMs);
    const res = await fetch(`/api/editor/jobs/${encodeURIComponent(jobId)}`, {
      signal: options?.signal,
    });
    if (!res.ok) throw new Error(await readError(res));
    const data = (await res.json()) as { job?: EditorJobStatus };
    const job = data.job;
    if (!job) throw new Error("任务响应无效");
    const st = String(job.status || "");
    if (st === "succeeded") return job;
    if (st === "failed" || st === "cancelled") {
      throw new Error(String(job.error || st));
    }
  }
  throw new Error("任务超时：后台可能仍在处理，请稍候刷新画布，或改用更快的文本模型重试");
}

export async function fetchEditorTemplate(templateId: string): Promise<EditorDoc> {
  const res = await fetch(`${workspaceBase(templateId)}?t=${Date.now()}`);
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as EditorDoc;
}

function blankPageFields(): Omit<Page, "id" | "html" | "sourceFile"> {
  return {
    visible: true,
    toggleInAnimation: "none",
    toggleInDuration: "0.5s",
    toggleInDelay: "0s",
    autoToggle: false,
    autoToggleTime: 0,
    backgroundType: "color",
    background: "#ffffff",
    bgColor: "#ffffff",
    fgColor: "#111111",
    bgOpacity: 1,
    remark: "",
  };
}

/** Merge server pages into pptStore; preserve local ids when sourceFile matches. */
export function applyEditorDocToStore(
  doc: EditorDoc,
  options?: {
    activateSourceFile?: string | null;
    /** Bust browser cache for regenerated local images (same filename). */
    assetCacheToken?: string | number | null;
  },
): void {
  const store = usePPTStore.getState();
  const prev = store.pages;
  const byFile = new Map(
    prev
      .filter((p) => p.sourceFile)
      .map((p) => [p.sourceFile!.replace(/^\/+/, ""), p]),
  );

  const token = options?.assetCacheToken;
  const bustHtml = (html: string | undefined): string | undefined => {
    if (!html || token == null || token === "") return html;
    const q = `v=${encodeURIComponent(String(token))}`;
    return html.replace(
      /((?:src|href)=["'][^"']*?(?:\/images\/|\.\.\/images\/)[^"'?#]+?)(?:\?[^"']*)?(["'])/gi,
      `$1?${q}$2`,
    );
  };

  const nextPages: Page[] = (doc.pages || []).map((p) => {
    const file = (p.sourceFile || "").replace(/^\/+/, "");
    const existing = file ? byFile.get(file) : undefined;
    return {
      ...blankPageFields(),
      ...existing,
      id: existing?.id || p.id || `page_${getRandomId()}`,
      html: bustHtml(p.html),
      sourceFile: file || existing?.sourceFile,
      remark: p.remark ?? existing?.remark ?? "",
      visible: existing?.visible ?? true,
    };
  });

  if (nextPages.length === 0) {
    throw new Error("模板没有页面");
  }

  const prevActive = pageActiveStore.getPageActive();
  store.setPages(nextPages);
  if (Array.isArray(doc.tree)) {
    store.setTemplateTree(doc.tree);
  }
  if (doc.templateId || doc.workspaceId) {
    store.setTemplateId(doc.templateId || doc.workspaceId || null);
  }

  const activateFile = (options?.activateSourceFile || "").replace(/^\/+/, "");
  if (activateFile) {
    const hit = nextPages.find((p) => p.sourceFile === activateFile);
    if (hit) {
      pageActiveStore.setPageActive(hit.id);
      return;
    }
  }
  if (prevActive && nextPages.some((p) => p.id === prevActive)) {
    return;
  }
  pageActiveStore.setPageActive(nextPages[0]?.id ?? null);
}
