import type { SlideConfig } from "./config";
import type { ExportOptions } from "./options";
import { isHTMLElement, waitFrames } from "./lib/dom";

export type Sandbox = {
  doc: Document;
  slideRoot: HTMLElement;
  dispose: () => void;
};

function rewriteHtml(
  html: string,
  options: ExportOptions,
  config: SlideConfig,
): string {
  let body = html.trim();
  // Accept full documents or fragment
  if (!/<html[\s>]/i.test(body) && !/<body[\s>]/i.test(body)) {
    body = `<!doctype html><html><head><meta charset="utf-8"/></head><body>${body}</body></html>`;
  }

  const base =
    options.baseHref != null
      ? `<base href="${options.baseHref.replace(/"/g, "")}">`
      : "";

  // Do NOT force background:transparent — many decks put the canvas color on
  // html/body; wiping it makes PPT slide.background fall back to white.
  const canvasCss = `
<style id="html-to-pptx-canvas">
  html, body {
    margin: 0 !important;
    padding: 0 !important;
    width: ${config.htmlWidth}px !important;
    height: ${config.htmlHeight}px !important;
    overflow: hidden !important;
  }
  [data-slide], .slide, #slide, .ppt-slide, .canvas {
    box-sizing: border-box;
  }
</style>`;

  if (/<\/head>/i.test(body)) {
    body = body.replace(/<\/head>/i, `${base}${canvasCss}</head>`);
  } else if (/<body[\s>]/i.test(body)) {
    body = body.replace(/<body([^>]*)>/i, `<head>${base}${canvasCss}</head><body$1>`);
  }

  if (options.resolveAssetUrl) {
    const resolve = options.resolveAssetUrl;
    body = body.replace(
      /(src|href)=["']([^"']+)["']/gi,
      (full, attr: string, url: string) => {
        // Skip scheme URLs and root-absolute paths (already site-absolute).
        if (/^(data:|https?:|blob:|#|\/\/|mailto:|\/)/i.test(url)) return full;
        try {
          return `${attr}="${resolve(url)}"`;
        } catch {
          return full;
        }
      },
    );
    body = body.replace(
      /url\(\s*(['"]?)([^)'"]+)\1\s*\)/gi,
      (full, _q: string, url: string) => {
        if (/^(data:|https?:|blob:|#|\/\/|\/)/i.test(url)) return full;
        try {
          return `url("${resolve(url)}")`;
        } catch {
          return full;
        }
      },
    );
  }

  return body;
}

function findSlideRoot(doc: Document, config: SlideConfig): HTMLElement {
  const candidates = [
    doc.querySelector("[data-slide]"),
    doc.querySelector(".slide"),
    doc.querySelector("#slide"),
    doc.querySelector(".ppt-slide"),
    doc.querySelector(".canvas"),
    doc.body,
  ];
  for (const el of candidates) {
    if (isHTMLElement(el)) {
      // Force canvas size so absolute layouts resolve against 1920×1080
      const cs = el.ownerDocument.defaultView?.getComputedStyle(el);
      if (el === doc.body || !cs || parseFloat(cs.width) < 8) {
        el.style.width = `${config.htmlWidth}px`;
        el.style.height = `${config.htmlHeight}px`;
        el.style.position = el.style.position || "relative";
        el.style.overflow = "hidden";
      }
      return el;
    }
  }
  return doc.body;
}

/**
 * Render one HTML page into a hidden iframe and return the slide root.
 */
export async function renderInSandbox(
  html: string,
  config: SlideConfig,
  options: ExportOptions,
): Promise<Sandbox> {
  const iframe = document.createElement("iframe");
  iframe.setAttribute("sandbox", "allow-same-origin allow-scripts");
  iframe.style.cssText =
    "position:fixed;left:-100000px;top:0;width:0;height:0;opacity:0;pointer-events:none;border:0;";
  document.body.appendChild(iframe);

  const doc = iframe.contentDocument;
  if (!doc) {
    iframe.remove();
    throw new Error("Sandbox iframe has no document");
  }

  const rewritten = rewriteHtml(html, options, config);
  doc.open();
  doc.write(rewritten);
  doc.close();

  // Wait stylesheets
  const links = Array.from(doc.querySelectorAll('link[rel="stylesheet"]'));
  await Promise.all(
    links.map(
      (link) =>
        new Promise<void>((resolve) => {
          const el = link as HTMLLinkElement;
          if (el.sheet) {
            resolve();
            return;
          }
          el.addEventListener("load", () => resolve(), { once: true });
          el.addEventListener("error", () => resolve(), { once: true });
          setTimeout(() => resolve(), 1500);
        }),
    ),
  );

  // Wait images (best-effort)
  const imgs = Array.from(doc.images);
  await Promise.all(
    imgs.map(
      (img) =>
        new Promise<void>((resolve) => {
          if (img.complete) {
            resolve();
            return;
          }
          img.addEventListener("load", () => resolve(), { once: true });
          img.addEventListener("error", () => resolve(), { once: true });
          setTimeout(() => resolve(), 2000);
        }),
    ),
  );

  await waitFrames(2);

  const slideRoot = findSlideRoot(doc, config);
  // Expand iframe to canvas so getBoundingClientRect is accurate
  iframe.style.width = `${config.htmlWidth}px`;
  iframe.style.height = `${config.htmlHeight}px`;
  await waitFrames(1);

  return {
    doc,
    slideRoot,
    dispose: () => {
      try {
        iframe.remove();
      } catch {
        /* ignore */
      }
    },
  };
}
