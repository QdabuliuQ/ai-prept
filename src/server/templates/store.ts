/**
 * Template store — local disk implementation; swap for OSS later.
 */

import { rm, writeFile } from "fs/promises";
import path from "path";
import {
  TEMPLATES_ROOT,
  listTemplateDirs,
  pathExists,
  readTemplateMeta,
  resolveUnderTemplate,
  templateMtime,
} from "@/server/htmlTemplates";
import {
  effectiveFormat,
  effectiveStatus,
  isPubliclyVisible,
  usageFromMeta,
  type TemplateMeta,
  type TemplateStatus,
  type TemplateStorageBackend,
  type TemplateSummary,
} from "@/server/templates/types";

export type ListTemplatesOptions = {
  /** 不传则返回全部（管理端）；公开端传 ['approved'] */
  statuses?: TemplateStatus[];
};

export interface TemplateStore {
  readonly backend: TemplateStorageBackend;
  list(options?: ListTemplatesOptions): Promise<TemplateSummary[]>;
  getMeta(id: string): Promise<TemplateMeta | null>;
  setStatus(
    id: string,
    status: TemplateStatus,
    opts?: { note?: string; reviewedBy?: string },
  ): Promise<TemplateMeta>;
  /** 新生成包写入 pending 状态 */
  markPending(id: string): Promise<void>;
  delete(id: string): Promise<void>;
  /** 批量删除本地目录；返回成功/失败明细 */
  deleteMany(ids: string[]): Promise<{
    deleted: string[];
    failed: Array<{ id: string; error: string }>;
  }>;
}

function toSummary(
  id: string,
  meta: TemplateMeta,
  mtimeMs: number,
): TemplateSummary {
  const first = meta.slides?.[0];
  const usage = usageFromMeta(meta);
  const format = effectiveFormat(meta);
  const previewFile = first?.file?.replace(/^\/+/, "") || null;
  const previewPages = Array.isArray(meta.preview?.pages)
    ? meta.preview!.pages!.filter((u): u is string => typeof u === "string" && !!u)
    : [];
  const remix = (meta as { remix?: { source_template_id?: string } }).remix;
  const sourceTemplateId =
    (meta as { source_template_id?: string }).source_template_id ||
    remix?.source_template_id ||
    null;
  return {
    id,
    /** 文件夹名即唯一 template id */
    templateId: id,
    label: meta.label || { zh_CN: id, en_US: id },
    description: meta.description || { zh_CN: "", en_US: "" },
    slideCount: meta.slides?.length ?? 0,
    previewFile,
    previewPages,
    format,
    status: effectiveStatus(meta),
    storageBackend: meta.storage?.backend || "local",
    mtimeMs,
    sourceTemplateId,
    pageTokens: usage.pageTokens,
    imageTokens: usage.imageTokens,
    imageCalls: usage.imageCalls,
    imageCount: usage.imageCount,
    pageCostCny: usage.pageCostCny,
    imageCostCny: usage.imageCostCny,
    totalCostCny: usage.totalCostCny,
  };
}

export class LocalTemplateStore implements TemplateStore {
  readonly backend = "local" as const;

  async list(options?: ListTemplatesOptions): Promise<TemplateSummary[]> {
    const dirs = await listTemplateDirs();
    const out: TemplateSummary[] = [];
    for (const id of dirs) {
      const meta = await readTemplateMeta(id);
      if (!meta) continue;
      const status = effectiveStatus(meta);
      if (options?.statuses && !options.statuses.includes(status)) continue;
      out.push(toSummary(id, meta, await templateMtime(id)));
    }
    return out.sort((a, b) => b.mtimeMs - a.mtimeMs);
  }

  async getMeta(id: string): Promise<TemplateMeta | null> {
    return readTemplateMeta(id);
  }

  async setStatus(
    id: string,
    status: TemplateStatus,
    opts?: { note?: string; reviewedBy?: string },
  ): Promise<TemplateMeta> {
    const meta = await readTemplateMeta(id);
    if (!meta) throw new Error(`模板不存在: ${id}`);
    const next: TemplateMeta = {
      ...meta,
      status,
      review: {
        ...(meta.review || {}),
        updated_at: new Date().toISOString(),
        note: opts?.note ?? meta.review?.note,
        reviewed_by: opts?.reviewedBy ?? meta.review?.reviewed_by,
      },
      storage: {
        backend: "local",
        path: path.posix.join("agent-output", id),
        ...(meta.storage || {}),
      },
    };
    const p = resolveUnderTemplate(id, "template.json");
    if (!p) throw new Error("非法模板 id");
    await writeFile(p, JSON.stringify(next, null, 2) + "\n", "utf-8");
    return next;
  }

  async markPending(id: string): Promise<void> {
    await this.setStatus(id, "pending", {
      note: "agent 生成，等待人工审批",
    });
  }

  async delete(id: string): Promise<void> {
    const root = path.join(TEMPLATES_ROOT, id);
    if (!(await pathExists(root))) throw new Error(`模板不存在: ${id}`);
    await rm(root, { recursive: true, force: true });
  }

  async deleteMany(ids: string[]): Promise<{
    deleted: string[];
    failed: Array<{ id: string; error: string }>;
  }> {
    const deleted: string[] = [];
    const failed: Array<{ id: string; error: string }> = [];
    const unique = Array.from(new Set(ids.map((id) => id.trim()).filter(Boolean)));
    for (const id of unique) {
      try {
        await this.delete(id);
        deleted.push(id);
      } catch (e) {
        failed.push({
          id,
          error: e instanceof Error ? e.message : String(e),
        });
      }
    }
    return { deleted, failed };
  }
}

/** 当前默认：本地。后续接 OSS 时在此切换实现。 */
let storeSingleton: TemplateStore | null = null;

export function getTemplateStore(): TemplateStore {
  if (!storeSingleton) {
    // TODO: if (process.env.TEMPLATE_STORAGE === 'oss') return new OssTemplateStore(...)
    storeSingleton = new LocalTemplateStore();
  }
  return storeSingleton;
}

export { isPubliclyVisible, effectiveStatus };
