import type { TemplateFormat } from "@/types/templateFormat";

export type TemplateStatus = "draft" | "pending" | "approved" | "rejected";

export type TemplateSummary = {
  id: string;
  templateId: string;
  /** 稳定对外 ID（优先于中文目录名） */
  publicId?: string;
  label: { zh_CN?: string; en_US?: string };
  description: { zh_CN?: string; en_US?: string };
  slideCount: number;
  previewFile: string | null;
  previewPages?: string[];
  format?: TemplateFormat;
  /** 页面渲染：html-slide | svg | svg-fallback */
  render?: string;
  /** true = 未能转为标准 html-slide，仅为 SVG 兜底包 */
  htmlConvertFailed?: boolean;
  reviewNote?: string | null;
  status: TemplateStatus;
  storageBackend: string;
  featured?: boolean;
  /** 类型 = 视觉风格 id（如 dark-tech）；other 为未知/旧数据 */
  category?: string;
  mtimeMs: number;
  sourceTemplateId?: string | null;
  /** 本地是否已有非空 visual-spec.md */
  hasVisualSpec?: boolean;
  hasPreviewPack?: boolean;
  hasPackageZip?: boolean;
  pageTokens?: number | null;
  imageTokens?: number | null;
  imageCalls?: number | null;
  imageCount?: number | null;
  pageCostCny?: number | null;
  imageCostCny?: number | null;
  totalCostCny?: number | null;
};

export type GenerateJobProgress = {
  total: number;
  done: number;
  ok: number;
  fail: number;
  skip: number;
  lastId?: string;
  percent: number;
};

export type GeneratePipeline = "html-slide" | "ppt-master" | "rewrite-page";

export type GenerateJob = {
  id: string;
  prompt: string;
  mock: boolean;
  skipImage: boolean;
  paletteRefine?: boolean;
  packageFormat?: TemplateFormat;
  pipeline?: GeneratePipeline;
  visualStyle?: string;
  styleIntent?: string;
  ensureStyle?: boolean;
  randomTheme?: boolean;
  randomStyle?: boolean;
  randomStyleMode?: "catalog" | "invent";
  /** 数量>1 时：true=主题共用同一次随机；false=每包重随主题 */
  reuseRandomTheme?: boolean | null;
  /** 数量>1 时：true=风格共用同一次随机；false=每包重随风格 */
  reuseRandomStyle?: boolean | null;
  /** @deprecated 旧字段；读写时拆成 theme/style */
  reuseRandom?: boolean | null;
  sourceTemplateId?: string;
  /** rewrite-page：目标页相对路径 */
  slideFile?: string | null;
  /** rewrite-page：0-based 页码 */
  pageIndex?: number | null;
  /** rewrite-page：问题描述（与 prompt 同义） */
  issue?: string;
  /** 历史任务可能带 html；新任务一律 svg */
  pptMasterRender?: "svg" | "html";
  templateId?: string;
  count?: number;
  concurrency?: number;
  pages?: number;
  planRefine?: boolean;
  repairOnFail?: boolean;
  qualityGate?: "soft" | "strict" | "skip";
  stripUnsupported?: boolean;
  /** DeepSeek / Gemini 思考；默认关（省费用）。Gemini 关时仍为 minimal/low 底噪 */
  llmThinking?: boolean;
  templateIds?: string[];
  /** PPTX 已就绪，等待浏览器 PPTX→HTML */
  needsBrowserConvert?: boolean;
  pptxPath?: string;
  convertTemplateId?: string;
  llmProvider?: string;
  llmModel?: string;
  llmLabel?: string;
  llmLightProvider?: string;
  llmLightModel?: string;
  llmLightLabel?: string;
  imageProvider?: string;
  imageModel?: string;
  imageLabel?: string;
  /** running | queued | succeeded | failed | cancelled | awaiting_html */
  status: string;
  createdAt: string;
  finishedAt?: string;
  error?: string;
  log: string;
  outputDir?: string;
  progress?: GenerateJobProgress;
};

export type LlmProviderPublic = {
  id: string;
  label: string;
  tier?: "heavy" | "light";
  baseUrl: string;
  models: { id: string; label: string }[];
  configured: boolean;
  keyCount?: number;
  keyHint?: string;
};

export type ImageProviderPublic = {
  id: string;
  label: string;
  baseUrl: string;
  models: { id: string; label: string }[];
  configured: boolean;
  keyCount?: number;
  keyHint?: string;
  transport?: string;
};

export const STATUS_LABEL: Record<TemplateStatus, string> = {
  draft: "草稿",
  pending: "待审批",
  approved: "已通过",
  rejected: "已驳回",
};

export const PREVIEW_SCALE = 0.5; // 960×540
