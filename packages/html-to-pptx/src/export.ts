import { mergeConfig, throwIfAborted, type ExportOptions } from "./options";
import type { SlideConfig } from "./config";
import { rgbToHex } from "./lib/color";
import { computedStyle, waitFrames } from "./lib/dom";
import { materializeImages } from "./images";
import { packagePresentation } from "./package";
import { materializePseudos } from "./pseudo";
import { renderInSandbox } from "./sandbox";
import { collectAndTransform } from "./transform";
import type { PreparedSlide } from "./types";

async function preparePage(
  html: string,
  config: SlideConfig,
  options: ExportOptions,
): Promise<PreparedSlide> {
  const sandbox = await renderInSandbox(html, config, options);
  let restore: (() => void) | null = null;
  try {
    throwIfAborted(options.signal);
    restore = materializePseudos(sandbox.slideRoot);
    await waitFrames(2);

    let nodes = collectAndTransform(sandbox.slideRoot);
    nodes = await materializeImages(nodes);

    const root = sandbox.slideRoot;
    const doc = sandbox.doc;
    const bg =
      rgbToHex(root.getAttribute("data-bg")) ||
      rgbToHex(computedStyle(root).backgroundColor) ||
      rgbToHex(computedStyle(doc.body).backgroundColor) ||
      rgbToHex(computedStyle(doc.documentElement).backgroundColor);

    return { nodes, backgroundColor: bg };
  } finally {
    try {
      restore?.();
    } catch {
      /* ignore */
    }
    sandbox.dispose();
  }
}

export async function runExport(
  pages: string[],
  options: ExportOptions = {},
): Promise<Blob> {
  if (!pages.length) throw new Error("No HTML pages to export");
  const config = mergeConfig(options.config);
  const prepared: PreparedSlide[] = [];
  const total = pages.length;

  for (let i = 0; i < pages.length; i++) {
    throwIfAborted(options.signal);
    try {
      prepared.push(await preparePage(pages[i], config, options));
    } catch (e) {
      if (!options.skipFailedPages) throw e;
      console.warn(`[html-to-pptx] skip failed page ${i + 1}`, e);
    }
    // Report completed count so UI can show moving %; yield for toast repaint
    options.onSlideProgress?.({
      current: i + 1,
      total,
      phase: "prepare",
    });
    await waitFrames(1);
  }

  if (!prepared.length) throw new Error("No slides prepared");

  options.onSlideProgress?.({
    current: total,
    total,
    phase: "package",
  });
  await waitFrames(1);
  return packagePresentation(prepared, config);
}
