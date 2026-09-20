/**
 * Admin-selectable LLM providers for webppt-agent PPT Master generation.
 * Child process receives LLM_* overrides; Python load_env must not clobber them.
 *
 * Key lookup order: non-empty process.env → agent/.env → (DeepSeek) LLM_* fallbacks.
 * Next.js only auto-loads repo-root .env.local; many keys live in agent/.env.
 */

import { readFileSync, existsSync } from "fs";
import path from "path";

export type LlmProviderId =
  | "deepseek"
  | "sensenova"
  | "siliconflow"
  | "cloudflare"
  | "pollinations";

export type LlmModelOption = {
  id: string;
  label: string;
};

/** heavy = Theme/HTML 等复杂任务；light = Plan 等轻量任务 */
export type LlmProviderTier = "heavy" | "light";

export type LlmProviderOption = {
  id: LlmProviderId;
  label: string;
  tier: LlmProviderTier;
  baseUrl: string;
  models: LlmModelOption[];
  /** Env vars that hold API keys for this provider (first non-empty wins). */
  keyEnvNames: string[];
};

const CLOUDFLARE_AI_RUN_BASE =
  "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run";

export const LLM_PROVIDERS: LlmProviderOption[] = [
  {
    id: "deepseek",
    label: "DeepSeek",
    tier: "heavy",
    baseUrl: "https://api.deepseek.com",
    models: [
      { id: "deepseek-v4-flash", label: "deepseek-v4-flash（默认）" },
      { id: "deepseek-chat", label: "deepseek-chat" },
    ],
    keyEnvNames: [
      "DEEPSEEK_API_KEYS",
      "DEEPSEEK_API_KEY",
      "LLM_API_KEYS",
      "LLM_API_KEY",
    ],
  },
  {
    id: "sensenova",
    label: "商汤 SenseNova",
    tier: "heavy",
    baseUrl: "https://token.sensenova.cn/v1",
    models: [
      { id: "deepseek-v4-flash", label: "deepseek-v4-flash" },
      { id: "DeepSeek-V3.2", label: "DeepSeek-V3.2" },
      { id: "SenseChat-5", label: "SenseChat-5" },
    ],
    keyEnvNames: ["SENSENOVA_API_KEYS", "SENSENOVA_API_KEY"],
  },
  {
    id: "cloudflare",
    label: "Cloudflare Workers AI",
    tier: "heavy",
    // 直连 /ai/run/@cf/...，走每日免费神经元；勿用 AI Gateway / 第三方 alibaba/* 模型
    baseUrl: CLOUDFLARE_AI_RUN_BASE,
    models: [
      {
        id: "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
        label: "DeepSeek-R1 Distill Qwen 32B（CF 托管）",
      },
      {
        id: "@cf/moonshotai/kimi-k2.7-code",
        label: "Kimi K2.7 Code（最强写码，需 Workers Paid）",
      },
      {
        id: "@cf/moonshotai/kimi-k2.6",
        label: "Kimi K2.6（需 Paid / Gateway）",
      },
      {
        id: "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        label: "Llama 3.3 70B Fast",
      },
      {
        id: "@cf/qwen/qwen3-30b-a3b-fp8",
        label: "Qwen3 30B-A3B",
      },
      {
        id: "@cf/qwen/qwen2.5-coder-32b-instruct",
        label: "Qwen2.5 Coder 32B（结构稳，审美一般）",
      },
    ],
    keyEnvNames: [
      "CLOUDFLARE_API_TOKENS",
      "CLOUDFLARE_API_TOKEN",
      "CLOUDFLARE_API_KEYS",
      "CLOUDFLARE_API_KEY",
    ],
  },
  {
    id: "pollinations",
    label: "Pollinations.ai",
    tier: "heavy",
    baseUrl: "https://gen.pollinations.ai/v1",
    models: [
      { id: "openai", label: "openai（默认）" },
      { id: "openai-fast", label: "openai-fast" },
      { id: "openai-large", label: "openai-large" },
      { id: "qwen-coder", label: "qwen-coder" },
      { id: "mistral", label: "mistral" },
      { id: "gemini", label: "gemini" },
      { id: "gemini-fast", label: "gemini-fast" },
      { id: "deepseek", label: "deepseek" },
      { id: "claude-fast", label: "claude-fast" },
      { id: "grok", label: "grok" },
    ],
    keyEnvNames: [
      "POLLINATIONS_API_KEYS",
      "POLLINATIONS_API_KEY",
      "LLM_API_KEYS",
      "LLM_API_KEY",
    ],
  },
  {
    id: "siliconflow",
    label: "硅基流动",
    tier: "light",
    baseUrl: "https://api.siliconflow.cn/v1",
    models: [
      { id: "Qwen/Qwen3-8B", label: "Qwen3-8B" },
      { id: "Qwen/Qwen2.5-7B-Instruct", label: "Qwen2.5-7B-Instruct" },
      { id: "THUDM/GLM-4-9B-0414", label: "GLM-4-9B-0414" },
    ],
    keyEnvNames: ["SILICONFLOW_API_KEYS", "SILICONFLOW_API_KEY"],
  },
];

function cloudflareAccountId(): string | undefined {
  return envGet("CLOUDFLARE_ACCOUNT_ID");
}

/** 原生 Workers AI：/ai/run — 不经 AI Gateway，消耗免费神经元 */
function cloudflareBaseUrl(accountId?: string): string {
  const id = (accountId || cloudflareAccountId() || "{account_id}").trim();
  return `https://api.cloudflare.com/client/v4/accounts/${id}/ai/run`;
}

export type LlmSelection = {
  provider: LlmProviderId;
  model: string;
  label: string;
  baseUrl: string;
};

export type LlmProviderPublic = LlmProviderOption & {
  configured: boolean;
  /** 去重后的 key 数量（多 key 轮询） */
  keyCount: number;
  /** Masked hint, e.g. sk-…abcd */
  keyHint?: string;
};

let agentEnvCache: Record<string, string> | null = null;

function loadAgentEnvFile(): Record<string, string> {
  if (agentEnvCache) return agentEnvCache;
  const file = path.resolve(process.cwd(), "agent", ".env");
  const out: Record<string, string> = {};
  if (!existsSync(file)) {
    agentEnvCache = out;
    return out;
  }
  try {
    const text = readFileSync(file, "utf-8");
    for (const line of text.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eq = trimmed.indexOf("=");
      if (eq <= 0) continue;
      const key = trimmed.slice(0, eq).trim();
      let value = trimmed.slice(eq + 1).trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      if (key) out[key] = value;
    }
  } catch {
    /* ignore unreadable agent/.env */
  }
  agentEnvCache = out;
  return out;
}

/** Non-empty process.env wins; else agent/.env (empty string counts as missing). */
export function envGet(name: string): string | undefined {
  const fromProcess = process.env[name]?.trim();
  if (fromProcess) return fromProcess;
  const fromAgent = loadAgentEnvFile()[name]?.trim();
  if (fromAgent) return fromAgent;
  return undefined;
}

export function parseKeys(...rawValues: Array<string | undefined>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of rawValues) {
    if (!raw) continue;
    for (const part of raw.replace(/;/g, ",").replace(/\n/g, ",").split(",")) {
      const key = part.trim();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(key);
    }
  }
  return out;
}

export function maskKey(key: string): string {
  if (key.length <= 8) return "***";
  return `${key.slice(0, 4)}…${key.slice(-4)}`;
}

function keysForProvider(provider: LlmProviderOption): string[] {
  if (provider.id === "sensenova") {
    return parseKeys(
      envGet("SENSENOVA_API_KEYS"),
      envGet("SENSENOVA_API_KEY"),
    );
  }
  if (provider.id === "deepseek") {
    return parseKeys(
      envGet("DEEPSEEK_API_KEYS"),
      envGet("DEEPSEEK_API_KEY"),
      envGet("LLM_API_KEYS"),
      envGet("LLM_API_KEY"),
    );
  }
  if (provider.id === "cloudflare") {
    return parseKeys(
      envGet("CLOUDFLARE_API_TOKENS"),
      envGet("CLOUDFLARE_API_TOKEN"),
      envGet("CLOUDFLARE_API_KEYS"),
      envGet("CLOUDFLARE_API_KEY"),
    );
  }
  if (provider.id === "pollinations") {
    return parseKeys(
      envGet("POLLINATIONS_API_KEYS"),
      envGet("POLLINATIONS_API_KEY"),
      envGet("LLM_API_KEYS"),
      envGet("LLM_API_KEY"),
    );
  }
  if (provider.id === "siliconflow") {
    return parseKeys(
      envGet("SILICONFLOW_API_KEYS"),
      envGet("SILICONFLOW_API_KEY"),
    );
  }
  return [];
}

function isProviderConfigured(provider: LlmProviderOption, keys: string[]): boolean {
  if (keys.length === 0) return false;
  if (provider.id === "cloudflare") return Boolean(cloudflareAccountId());
  return true;
}

function resolveProviderBaseUrl(provider: LlmProviderOption): string {
  if (provider.id === "cloudflare") return cloudflareBaseUrl();
  if (provider.id === "sensenova") {
    return (
      envGet("SENSENOVA_BASE_URL") || provider.baseUrl
    ).replace(/\/+$/, "");
  }
  if (provider.id === "pollinations") {
    const raw = (
      envGet("POLLINATIONS_LLM_BASE_URL") ||
      envGet("POLLINATIONS_BASE_URL") ||
      provider.baseUrl
    ).replace(/\/+$/, "");
    return raw.endsWith("/v1") ? raw : `${raw}/v1`;
  }
  return provider.baseUrl;
}

export function invalidateAgentEnvCache(): void {
  agentEnvCache = null;
}

export function listLlmProvidersPublic(): LlmProviderPublic[] {
  // Re-read agent/.env each request so edits show up without restarting Next
  // (process.env from .env.local still needs restart).
  invalidateAgentEnvCache();
  return LLM_PROVIDERS.map((p) => {
    const keys = keysForProvider(p);
    return {
      ...p,
      baseUrl: resolveProviderBaseUrl(p),
      configured: isProviderConfigured(p, keys),
      keyCount: keys.length,
      keyHint: keys[0] ? maskKey(keys[0]) : undefined,
    };
  });
}

export function resolveLlmSelection(
  providerId?: string | null,
  modelId?: string | null,
): LlmSelection {
  const provider =
    (providerId
      ? LLM_PROVIDERS.find((p) => p.id === providerId)
      : undefined) ||
    LLM_PROVIDERS.find((p) => p.id === "deepseek") ||
    LLM_PROVIDERS[0];
  const model =
    provider.models.find((m) => m.id === modelId)?.id ||
    provider.models[0]?.id ||
    "deepseek-v4-flash";
  const modelLabel =
    provider.models.find((m) => m.id === model)?.label || model;
  return {
    provider: provider.id,
    model,
    label: `${provider.label} · ${modelLabel}`,
    baseUrl: resolveProviderBaseUrl(provider),
  };
}

/**
 * Env overrides injected into webppt-agent child process.
 * Always sets LLM_API_KEYS (even single key) so stale multi-key pools from
 * another provider cannot leak through.
 */
export function llmEnvForSelection(selection: LlmSelection): Record<string, string> {
  invalidateAgentEnvCache();
  const provider = LLM_PROVIDERS.find((p) => p.id === selection.provider);
  if (!provider) {
    throw new Error(`未知 LLM 提供方: ${selection.provider}`);
  }
  const keys = keysForProvider(provider);
  if (keys.length === 0) {
    const names = provider.keyEnvNames.join(" / ");
    throw new Error(
      `${provider.label} 未配置 API Key。请在仓库根 .env.local 或 agent/.env 设置 ${names}`,
    );
  }
  if (provider.id === "cloudflare" && !cloudflareAccountId()) {
    throw new Error(
      "Cloudflare 未配置 Account ID。请在仓库根 .env.local 或 agent/.env 设置 CLOUDFLARE_ACCOUNT_ID",
    );
  }
  if (!provider.models.some((m) => m.id === selection.model)) {
    throw new Error(`${provider.label} 不支持模型 ${selection.model}`);
  }

  const baseUrl = resolveProviderBaseUrl(provider);

  const env: Record<string, string> = {
    LLM_BASE_URL: baseUrl,
    LLM_MODEL: selection.model,
    LLM_API_KEY: keys[0],
    LLM_API_KEYS: keys.join(","),
  };
  if (provider.id === "cloudflare") {
    const accountId = cloudflareAccountId();
    if (accountId) env.CLOUDFLARE_ACCOUNT_ID = accountId;
    // 强制走原生 /ai/run，避免 OpenAI 兼容层把第三方模型导到 AI Gateway
    env.CLOUDFLARE_AI_MODE = "run";
  }
  return env;
}

/**
 * 主力（Theme/Slide）+ 轻量（Plan/配方）。
 * - light=null → Plan 与主力相同（LLM_LIGHT_SAME=1）
 * - light=undefined → 不强制；agent 可按 DEEPSEEK_* / SENSENOVA_* / SILICONFLOW_* 自动选
 * - light=LlmSelection → 注入 LLM_LIGHT_*
 */
export function llmEnvForDual(
  heavy: LlmSelection,
  light?: LlmSelection | null,
): Record<string, string> {
  const env: Record<string, string> = { ...llmEnvForSelection(heavy) };

  if (light === null) {
    env.LLM_LIGHT_SAME = "1";
    env.LLM_LIGHT_ENABLED = "0";
    return env;
  }

  if (light === undefined) {
    // 交给 Python：优先官方 DeepSeek Plan，其次商汤 / 硅基
    env.LLM_LIGHT_SAME = "0";
    env.LLM_LIGHT_ENABLED = "1";
    return env;
  }

  if (light.provider === heavy.provider && light.model === heavy.model) {
    env.LLM_LIGHT_SAME = "1";
    env.LLM_LIGHT_ENABLED = "0";
    return env;
  }

  const provider = LLM_PROVIDERS.find((p) => p.id === light.provider);
  if (!provider) {
    throw new Error(`未知轻量 LLM 提供方: ${light.provider}`);
  }
  const keys = keysForProvider(provider);
  if (keys.length === 0) {
    const names = provider.keyEnvNames.join(" / ");
    throw new Error(
      `轻量模型 ${provider.label} 未配置 API Key。请设置 ${names}`,
    );
  }
  if (provider.id === "cloudflare" && !cloudflareAccountId()) {
    throw new Error(
      "轻量模型 Cloudflare 未配置 Account ID（CLOUDFLARE_ACCOUNT_ID）",
    );
  }
  if (!provider.models.some((m) => m.id === light.model)) {
    throw new Error(`${provider.label} 不支持轻量模型 ${light.model}`);
  }

  const baseUrl = resolveProviderBaseUrl(provider);

  env.LLM_LIGHT_SAME = "0";
  env.LLM_LIGHT_ENABLED = "1";
  env.LLM_LIGHT_BASE_URL = baseUrl;
  env.LLM_LIGHT_MODEL = light.model;
  env.LLM_LIGHT_API_KEY = keys[0];
  env.LLM_LIGHT_API_KEYS = keys.join(",");
  if (provider.id === "cloudflare") {
    const accountId = cloudflareAccountId();
    if (accountId) env.CLOUDFLARE_ACCOUNT_ID = accountId;
    env.CLOUDFLARE_AI_MODE = "run";
  }
  return env;
}
