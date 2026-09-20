import type { ExportHandle, ExportOptions } from "./options";
import { runExport } from "./export";

export type { ExportOptions, ExportHandle } from "./options";
export type { SlideConfig } from "./config";
export { DEFAULT_CONFIG, pxToInch, inchToPx } from "./config";
export type { SlideNode, PreparedSlide } from "./types";
export { runExport } from "./export";
export { materializePseudos } from "./pseudo";
export { collectAndTransform } from "./transform";

function triggerDownload(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName.endsWith(".pptx") ? fileName : `${fileName}.pptx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function withCancel<T>(run: (signal: AbortSignal) => Promise<T>): ExportHandle<T> {
  const ac = new AbortController();
  return {
    promise: run(ac.signal),
    cancel: () => ac.abort(),
  };
}

/** Build PPTX Blob from one HTML string or a list of page HTML strings. */
export function generatePPTX(
  htmlOrPages: string | string[],
  options: ExportOptions = {},
): ExportHandle<Blob> {
  const pages = Array.isArray(htmlOrPages) ? htmlOrPages : [htmlOrPages];
  return withCancel(async (signal) => {
    const merged: ExportOptions = {
      ...options,
      signal: options.signal ?? signal,
    };
    return runExport(pages, merged);
  });
}

/** Same as generatePPTX, then trigger browser download. */
export function exportPPTX(
  htmlOrPages: string | string[],
  options: ExportOptions = {},
): ExportHandle<{ blob: Blob; fileName: string }> {
  const fileName = options.fileName || "presentation.pptx";
  return withCancel(async (signal) => {
    const merged: ExportOptions = {
      ...options,
      fileName,
      signal: options.signal ?? signal,
    };
    const pages = Array.isArray(htmlOrPages) ? htmlOrPages : [htmlOrPages];
    const blob = await runExport(pages, merged);
    triggerDownload(blob, fileName);
    return { blob, fileName };
  });
}
