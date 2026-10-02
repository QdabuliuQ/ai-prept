function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Reveal markdown/text in small chunks for a streaming feel.
 * Cancels cleanly when signal aborts.
 */
export async function streamText(
  full: string,
  onChunk: (visible: string) => void,
  options?: { signal?: AbortSignal; cps?: number },
): Promise<void> {
  const text = String(full || "");
  if (!text) {
    onChunk("");
    return;
  }

  const cps = Math.max(20, options?.cps ?? 72);
  const stepMs = Math.max(8, Math.round(1000 / cps));
  // Prefer larger steps for CJK / long lines to finish sooner.
  const chunkSize = text.length > 180 ? 4 : text.length > 80 ? 3 : 2;

  let i = 0;
  while (i < text.length) {
    if (options?.signal?.aborted) {
      throw new Error("ABORTED");
    }
    i = Math.min(text.length, i + chunkSize);
    onChunk(text.slice(0, i));
    if (i < text.length) {
      await sleep(stepMs);
    }
  }
}
