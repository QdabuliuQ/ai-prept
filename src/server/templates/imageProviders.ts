/**
 * Admin-selectable image providers for webppt-agent ppt-master generation.
 * Child process receives IMAGE_* overrides.
 */

import {
  envGet,
  invalidateAgentEnvCache,
  maskKey,
  parseKeys,
} from "@/server/templates/llmProviders";

export type ImageProviderId = "openai" | "pollinations";

export type ImageModelOption = {
  id: string;
  label: string;
};

export type ImageProviderOption = {
  id: ImageProviderId;
  label: string;
  /** OpenAI-compatible images base, or Pollinations gen root */
  baseUrl: string;
  models: ImageModelOption[];
  keyEnvNames: string[];
  /** How the Python agent should call the API */
  transport: "openai-images" | "pollinations-get";
};

export const IMAGE_PROVIDERS: ImageProviderOption[] = [
  {
    id: "openai",
    label: "OpenAI 兼容（Maizi 等）",
    baseUrl: "https://www.maizitech.xyz/v1",
    models: [
      { id: "nano-banana-fast", label: "nano-banana-fast" },
      { id: "nano-banana", label: "nano-banana" },
    ],
    keyEnvNames: ["IMAGE_API_KEYS", "IMAGE_API_KEY"],
    transport: "openai-images",
  },
  {
    id: "pollinations",
    label: "Pollinations.ai",
    baseUrl: "https://gen.pollinations.ai",
    models: [
      { id: "flux", label: "flux（默认）" },
      { id: "turbo", label: "turbo" },
      { id: "gptimage", label: "gptimage" },
      { id: "kontext", label: "kontext" },
      { id: "seedream", label: "seedream" },
      { id: "nanobanana", label: "nanobanana" },
      { id: "nanobanana-pro", label: "nanobanana-pro" },
    ],
    keyEnvNames: [
      "POLLINATIONS_API_KEYS",
      "POLLINATIONS_API_KEY",
      "IMAGE_API_KEYS",
      "IMAGE_API_KEY",
    ],
    transport: "pollinations-get",
  },
];

export type ImageSelection = {
  provider: ImageProviderId;
  model: string;
  label: string;
  baseUrl: string;
  transport: ImageProviderOption["transport"];
};

export type ImageProviderPublic = ImageProviderOption & {
  configured: boolean;
  keyCount: number;
  keyHint?: string;
};

function keysForImageProvider(provider: ImageProviderOption): string[] {
  if (provider.id === "pollinations") {
    return parseKeys(
      envGet("POLLINATIONS_API_KEYS"),
      envGet("POLLINATIONS_API_KEY"),
      envGet("IMAGE_API_KEYS"),
      envGet("IMAGE_API_KEY"),
    );
  }
  return parseKeys(envGet("IMAGE_API_KEYS"), envGet("IMAGE_API_KEY"));
}

function resolveBaseUrl(provider: ImageProviderOption): string {
  if (provider.id === "openai") {
    return (
      envGet("IMAGE_API_BASE_URL") ||
      envGet("OPENAI_BASE_URL") ||
      provider.baseUrl
    ).replace(/\/+$/, "");
  }
  return (
    envGet("POLLINATIONS_BASE_URL") || provider.baseUrl
  ).replace(/\/+$/, "");
}

export function listImageProvidersPublic(): ImageProviderPublic[] {
  invalidateAgentEnvCache();
  return IMAGE_PROVIDERS.map((p) => {
    const keys = keysForImageProvider(p);
    return {
      ...p,
      baseUrl: resolveBaseUrl(p),
      configured: keys.length > 0,
      keyCount: keys.length,
      keyHint: keys[0] ? maskKey(keys[0]) : undefined,
    };
  });
}

export function resolveImageSelection(
  providerId?: string | null,
  modelId?: string | null,
): ImageSelection {
  invalidateAgentEnvCache();
  const fromEnv = (envGet("IMAGE_API_PROVIDER") || "").trim().toLowerCase();
  const preferred =
    (providerId || "").trim() ||
    (fromEnv === "pollinations" ? "pollinations" : "") ||
    "openai";
  const provider =
    IMAGE_PROVIDERS.find((p) => p.id === preferred) || IMAGE_PROVIDERS[0];
  const envModel = (envGet("IMAGE_MODEL") || "").trim();
  const model =
    provider.models.find((m) => m.id === modelId)?.id ||
    provider.models.find((m) => m.id === envModel)?.id ||
    provider.models[0]?.id ||
    "flux";
  const modelLabel =
    provider.models.find((m) => m.id === model)?.label || model;
  return {
    provider: provider.id,
    model,
    label: `${provider.label} · ${modelLabel}`,
    baseUrl: resolveBaseUrl(provider),
    transport: provider.transport,
  };
}

/** Env overrides for webppt-agent child (IMAGE_*). */
export function imageEnvForSelection(
  selection: ImageSelection,
): Record<string, string> {
  invalidateAgentEnvCache();
  const provider = IMAGE_PROVIDERS.find((p) => p.id === selection.provider);
  if (!provider) {
    throw new Error(`未知文生图提供方: ${selection.provider}`);
  }
  const keys = keysForImageProvider(provider);
  if (keys.length === 0) {
    throw new Error(
      `${provider.label} 未配置 API Key。请设置 ${provider.keyEnvNames.join(" / ")}`,
    );
  }
  if (!provider.models.some((m) => m.id === selection.model)) {
    throw new Error(`${provider.label} 不支持模型 ${selection.model}`);
  }

  const baseUrl = resolveBaseUrl(provider);
  // OpenAI SDK wants …/v1; Pollinations GET uses gen root (no /v1).
  const openaiBase =
    provider.transport === "openai-images"
      ? baseUrl.endsWith("/v1")
        ? baseUrl
        : `${baseUrl}/v1`
      : `${baseUrl.replace(/\/v1\/?$/, "")}/v1`;

  return {
    IMAGE_API_PROVIDER: provider.id,
    IMAGE_API_BASE_URL:
      provider.transport === "pollinations-get" ? baseUrl : openaiBase,
    IMAGE_MODEL: selection.model,
    IMAGE_API_KEY: keys[0],
    IMAGE_API_KEYS: keys.join(","),
    IMAGE_TRANSPORT: provider.transport,
  };
}
