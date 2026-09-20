/**
 * Template catalog types — local filesystem now, OSS later via TemplateStore.
 */

import { estimateUsageCost } from "@/server/templates/pricing";

export type TemplateStatus = "draft" | "pending" | "approved" | "rejected";

export type TemplateStorageBackend = "local" | "oss" | "qiniu";

/** html-slide 直出，或 ppt-master 转成的 html 包 */
export type TemplateFormat = "html-slide" | "ppt-master";

export type TemplateUsageBucket = {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  calls?: number;
  images?: number;
  reasoning_tokens?: number;
  cache_hit_tokens?: number;
  cache_miss_tokens?: number;
};

export type TemplateUsageCost = {
  currency?: string;
  estimated?: boolean;
  page_cny?: number | null;
  image_cny?: number | null;
  total_cny?: number | null;
  page_model?: string | null;
  image_model?: string | null;
  note?: string;
  rates?: Record<string, number>;
};

export type TemplateUsage = {
  page_tokens?: number;
  image_tokens?: number;
  page?: TemplateUsageBucket;
  image?: TemplateUsageBucket;
  cost?: TemplateUsageCost;
};

export type TemplateMeta = {
  schema_version?: string;
  template_id?: string;
  /** 缺省 / 历史包一律按 html-slide */
  format?: TemplateFormat | string;
  label?: { zh_CN?: string; en_US?: string };
  description?: { zh_CN?: string; en_US?: string };
  /** 审批状态；缺省视为 approved（兼容旧包） */
  status?: TemplateStatus;
  review?: {
    updated_at?: string;
    note?: string;
    reviewed_by?: string;
  };
  storage?: {
    backend?: TemplateStorageBackend;
    /** local 相对路径、或七牛/OSS object key */
    path?: string;
    /** 七牛公开访问 URL（zip） */
    url?: string;
    uploaded_at?: string;
    zip_bytes?: number;
    images_compressed?: number;
    html_compressed?: number;
    css_compressed?: number;
    json_compressed?: number;
    /** 预览图目录前缀，如 webppt/{id}/ */
    preview_prefix?: string;
  };
  /** 七牛逐页预览图（webppt/{id}/01.webp…） */
  preview?: {
    pages?: string[];
    generated_at?: string;
  };
  files?: {
    theme_css?: string;
    visual_spec?: string;
    slides_dir?: string;
    images_dir?: string;
  };
  slides?: Array<{
    /** html 相对路径（slides/*.html） */
    file: string;
    title?: string;
    layout?: string;
    description?: string;
  }>;
  /** agent 生成用量：页面 LLM / 图片 */
  usage?: TemplateUsage;
};

export type TemplateSummary = {
  id: string;
  templateId: string;
  label: { zh_CN?: string; en_US?: string };
  description: { zh_CN?: string; en_US?: string };
  slideCount: number;
  previewFile: string | null;
  /** 七牛预览图 URL 列表（01.webp…）；未上传则为空 */
  previewPages: string[];
  /** html-slide 直出 / ppt-master 转换包 */
  format: TemplateFormat;
  status: TemplateStatus;
  storageBackend: TemplateStorageBackend;
  mtimeMs: number;
  /** 套用模板时的源包 id */
  sourceTemplateId?: string | null;
  pageTokens: number | null;
  imageTokens: number | null;
  imageCalls: number | null;
  imageCount: number | null;
  pageCostCny: number | null;
  imageCostCny: number | null;
  totalCostCny: number | null;
};

export function effectiveFormat(
  meta?: TemplateMeta | null,
): TemplateFormat {
  const raw = String(meta?.format || "").trim();
  if (raw === "ppt-master") return "ppt-master";
  return "html-slide";
}

export function effectiveStatus(meta: TemplateMeta | null | undefined): TemplateStatus {
  if (!meta?.status) return "approved";
  return meta.status;
}

export function isPubliclyVisible(meta: TemplateMeta | null | undefined): boolean {
  return effectiveStatus(meta) === "approved";
}

export function usageFromMeta(meta: TemplateMeta | null | undefined): {
  pageTokens: number | null;
  imageTokens: number | null;
  imageCalls: number | null;
  imageCount: number | null;
  pageCostCny: number | null;
  imageCostCny: number | null;
  totalCostCny: number | null;
} {
  const empty = {
    pageTokens: null,
    imageTokens: null,
    imageCalls: null,
    imageCount: null,
    pageCostCny: null,
    imageCostCny: null,
    totalCostCny: null,
  };
  const u = meta?.usage;
  if (!u || typeof u !== "object") {
    return empty;
  }
  const pageTotal =
    typeof u.page_tokens === "number"
      ? u.page_tokens
      : typeof u.page?.total_tokens === "number"
        ? u.page.total_tokens
        : null;
  const imageTotal =
    typeof u.image_tokens === "number"
      ? u.image_tokens
      : typeof u.image?.total_tokens === "number"
        ? u.image.total_tokens
        : null;

  // 无 usage.cost 时按 bucket 用 DeepSeek Flash 默认价重算（兼容旧包）
  const cost = estimateUsageCost(u);

  return {
    pageTokens: pageTotal,
    imageTokens: imageTotal,
    imageCalls: typeof u.image?.calls === "number" ? u.image.calls : null,
    imageCount: typeof u.image?.images === "number" ? u.image.images : null,
    pageCostCny: cost?.pageCny ?? null,
    imageCostCny: cost?.imageCny ?? null,
    totalCostCny: cost?.totalCny ?? null,
  };
}
