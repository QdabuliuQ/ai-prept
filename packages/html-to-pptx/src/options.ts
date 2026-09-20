import type { SlideConfig } from "./config";
import { DEFAULT_CONFIG } from "./config";

export type ExportOptions = {
  fileName?: string;
  config?: Partial<SlideConfig>;
  skipFailedPages?: boolean;
  onSlideProgress?: (info: {
    current: number;
    total: number;
    phase?: string;
  }) => void;
  signal?: AbortSignal;
  /** Rewrite relative asset urls before sandbox fetch. */
  resolveAssetUrl?: (url: string) => string;
  /** Optional `<base href>` inside the iframe. */
  baseHref?: string;
};

export type ExportHandle<T> = {
  promise: Promise<T>;
  cancel: () => void;
};

export function mergeConfig(partial?: Partial<SlideConfig>): SlideConfig {
  return { ...DEFAULT_CONFIG, ...partial };
}

export function throwIfAborted(signal?: AbortSignal) {
  if (signal?.aborted) {
    const err = new Error("Export cancelled");
    err.name = "AbortError";
    throw err;
  }
}
