/**
 * 按公开价目估算 LLM / 生图费用（CNY，非充值账单）。
 * 与 agent/src/webppt_agent/pricing.py 对齐。
 */

import type { TemplateUsage, TemplateUsageBucket } from "@/server/templates/types";

type RateTriple = { hit: number; miss: number; out: number };

const PAGE_RATES: Record<string, RateTriple> = {
  "deepseek-v4-flash": { hit: 0.2, miss: 1.0, out: 2.0 },
  "deepseek-chat": { hit: 0.2, miss: 1.0, out: 2.0 },
  "deepseek-reasoner": { hit: 0.2, miss: 1.0, out: 2.0 },
  "deepseek-v4-pro": { hit: 1.0, miss: 12.0, out: 24.0 },
};

const DEFAULT_PAGE: RateTriple = { hit: 0.2, miss: 1.0, out: 2.0 };

const IMAGE_PER_IMAGE_CNY: Record<string, number> = {
  "nano-banana-fast": 0.02,
  "nano-banana": 0.04,
};

export type UsageCost = {
  currency: "CNY";
  estimated: true;
  pageCny: number | null;
  imageCny: number | null;
  totalCny: number | null;
  pageModel?: string | null;
  note: string;
};

function normalizeModel(model?: string | null): string {
  return (model || "").trim().toLowerCase();
}

function resolvePageRates(model?: string | null): RateTriple {
  const key = normalizeModel(model);
  if (!key) return DEFAULT_PAGE;
  if (PAGE_RATES[key]) return PAGE_RATES[key];
  for (const [name, rates] of Object.entries(PAGE_RATES)) {
    if (key.includes(name) || name.includes(key)) return rates;
  }
  if (key.includes("deepseek") && key.includes("pro")) {
    return PAGE_RATES["deepseek-v4-pro"];
  }
  if (key.includes("deepseek")) return PAGE_RATES["deepseek-v4-flash"];
  return DEFAULT_PAGE;
}

function estimatePageCny(
  bucket?: TemplateUsageBucket | null,
  model?: string | null,
  fallbackTotal?: number | null,
): number | null {
  const rates = resolvePageRates(model);
  if (!bucket && fallbackTotal != null && fallbackTotal > 0) {
    // 旧包只有 total：半输入未命中 + 半输出
    const half = fallbackTotal / 2;
    return (
      Math.round(((half / 1e6) * rates.miss + (half / 1e6) * rates.out) * 1e6) /
      1e6
    );
  }
  if (!bucket) return null;
  const prompt = Number(bucket.prompt_tokens || 0);
  let completion = Number(bucket.completion_tokens || 0);
  const total = Number(bucket.total_tokens || fallbackTotal || 0);
  if (total <= 0 && prompt <= 0 && completion <= 0) return null;

  let hit = Number(bucket.cache_hit_tokens || 0);
  let miss = Number(bucket.cache_miss_tokens || 0);
  if (hit || miss) {
    if (miss <= 0 && prompt > hit) miss = prompt - hit;
  } else if (prompt > 0) {
    miss = Math.max(0, prompt);
    hit = 0;
  } else if (total > 0) {
    miss = Math.floor(total / 2);
    completion = total - miss;
  }
  if (completion <= 0 && total > prompt && prompt > 0) {
    completion = total - prompt;
  }

  const cost =
    (hit / 1e6) * rates.hit +
    (Math.max(0, miss) / 1e6) * rates.miss +
    (Math.max(0, completion) / 1e6) * rates.out;
  return Math.round(cost * 1e6) / 1e6;
}

function estimateImageCny(
  bucket?: TemplateUsageBucket | null,
  model?: string | null,
): number | null {
  if (!bucket) return null;
  const images = Number(bucket.images || 0);
  const key = normalizeModel(model);
  for (const [name, price] of Object.entries(IMAGE_PER_IMAGE_CNY)) {
    if (key.includes(name) && images > 0) {
      return Math.round(price * images * 1e6) / 1e6;
    }
  }
  return null;
}

/** 优先用 usage.cost；否则按 bucket + DeepSeek Flash 默认价重算（兼容旧包）。 */
export function estimateUsageCost(usage?: TemplateUsage | null): UsageCost | null {
  if (!usage || typeof usage !== "object") return null;

  const stored = usage.cost;
  if (stored && typeof stored === "object") {
    const page =
      typeof stored.page_cny === "number" ? stored.page_cny : null;
    const image =
      typeof stored.image_cny === "number" ? stored.image_cny : null;
    const total =
      typeof stored.total_cny === "number"
        ? stored.total_cny
        : [page, image].filter((n): n is number => n != null).length
          ? Math.round(
              ([page, image].filter((n): n is number => n != null) as number[]).reduce(
                (a, b) => a + b,
                0,
              ) * 1e6,
            ) / 1e6
          : null;
    if (page != null || image != null || total != null) {
      return {
        currency: "CNY",
        estimated: true,
        pageCny: page,
        imageCny: image,
        totalCny: total,
        pageModel:
          typeof stored.page_model === "string" ? stored.page_model : null,
        note:
          typeof stored.note === "string"
            ? stored.note
            : "按公开价目估算，非充值账单",
      };
    }
  }

  const pageModel =
    typeof usage.cost?.page_model === "string" ? usage.cost.page_model : null;
  const imageModel =
    typeof usage.cost?.image_model === "string" ? usage.cost.image_model : null;
  const pageTotal =
    typeof usage.page_tokens === "number"
      ? usage.page_tokens
      : typeof usage.page?.total_tokens === "number"
        ? usage.page.total_tokens
        : null;
  const pageCny = estimatePageCny(usage.page, pageModel, pageTotal);
  const imageCny = estimateImageCny(usage.image, imageModel);
  const parts = [pageCny, imageCny].filter((n): n is number => n != null);
  if (!parts.length) return null;
  return {
    currency: "CNY",
    estimated: true,
    pageCny,
    imageCny,
    totalCny: Math.round(parts.reduce((a, b) => a + b, 0) * 1e6) / 1e6,
    pageModel,
    note: "按公开价目估算，非充值账单",
  };
}

export function formatCny(amount: number | null | undefined): string {
  if (amount == null || Number.isNaN(amount)) return "";
  if (amount <= 0) return "¥0";
  if (amount < 0.01) return `¥${amount.toFixed(3)}`;
  if (amount < 1) return `¥${amount.toFixed(2)}`;
  return `¥${amount.toFixed(2)}`;
}
