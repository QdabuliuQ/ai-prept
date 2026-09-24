/**
 * Browser-side PPTX → html-slide package conversion via @aiden0z/pptx-renderer.
 * Mirrors backend/scripts/pptx-to-template-package.mjs (without Puppeteer).
 */

import {
  parseZip,
  buildPresentation,
  renderSlide,
  serializePresentation,
  RECOMMENDED_ZIP_LIMITS,
} from "@aiden0z/pptx-renderer/browser";
import type { SlideHandle } from "@aiden0z/pptx-renderer/browser";

import {
  classifyLayout,
  uniquifyLayouts,
  describeLayout,
  flattenNodes,
} from "@/utils/pptx-convert/layout";
import { slotAttrsForNode, guessSlideTitle } from "@/utils/pptx-convert/slots";
import {
  postprocessSlideHtml,
  type ConvertImagePayload,
} from "@/utils/pptx-convert/postprocess";

const CANVAS_W = 1920;
const CANVAS_H = 1080;
const COMPLEX_TYPES = new Set(["chart", "table"]);

const DEFAULT_CONVERT_ZIP_LIMITS = {
  maxEntries: 8000,
  maxEntryUncompressedBytes: 256 * 1024 * 1024,
  maxTotalUncompressedBytes: 1024 * 1024 * 1024,
  maxMediaBytes: 768 * 1024 * 1024,
  maxConcurrency: 8,
};

export type BrowserConvertSlide = {
  file: string;
  title: string;
  layout: string;
  description: string;
  html: string;
};

export type BrowserConvertResult = {
  slides: BrowserConvertSlide[];
  images: ConvertImagePayload[];
  warnings: string[];
  labelZh: string;
  theme?: { bg?: string; text?: string; accent?: string };
};

type SlotPlanItem = {
  nodeId?: string;
  flatIndex: number;
  attrs: Record<string, string>;
  complex: boolean;
  assetStem: string | null;
  slotType?: string;
  slotRole?: string;
  slot?: string;
  rotation: number;
  flipH: boolean;
  flipV: boolean;
};

type SerializedSlideLike = {
  nodes?: unknown[];
};

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function ensureMount(): HTMLDivElement {
  let mount = document.getElementById("webppt-pptx-convert-mount") as
    | HTMLDivElement
    | null;
  if (!mount) {
    mount = document.createElement("div");
    mount.id = "webppt-pptx-convert-mount";
    mount.setAttribute("aria-hidden", "true");
    Object.assign(mount.style, {
      position: "fixed",
      left: "-10000px",
      top: "0",
      width: `${CANVAS_W}px`,
      height: `${CANVAS_H}px`,
      overflow: "hidden",
      pointerEvents: "none",
      zIndex: "-1",
    });
    document.body.appendChild(mount);
  }
  return mount;
}

function approxMatch(
  el: HTMLElement,
  node: {
    position?: { x?: number; y?: number };
    size?: { w?: number; h?: number };
  },
): boolean {
  const st = el.style;
  const left = parseFloat(st.left) || 0;
  const top = parseFloat(st.top) || 0;
  const w = parseFloat(st.width) || el.offsetWidth || 0;
  const h = parseFloat(st.height) || el.offsetHeight || 0;
  const nx = node.position?.x || 0;
  const ny = node.position?.y || 0;
  const nw = node.size?.w || 0;
  const nh = node.size?.h || 0;
  const tol = 6;
  return (
    Math.abs(left - nx) <= tol &&
    Math.abs(top - ny) <= tol &&
    (nw < 4 || Math.abs(w - nw) <= Math.max(tol, nw * 0.08)) &&
    (nh < 4 || Math.abs(h - nh) <= Math.max(tol, nh * 0.08))
  );
}

function applyAttrs(
  el: Element,
  attrs: Record<string, string> | null | undefined,
) {
  if (!el || !attrs) return;
  for (const [k, v] of Object.entries(attrs)) {
    if (v != null && v !== "") el.setAttribute(k, String(v));
  }
}

function parseRotateDeg(transform: string): number | null {
  const m = String(transform || "").match(
    /rotate\(\s*(-?[\d.]+)\s*deg\s*\)/i,
  );
  return m ? Number(m[1]) : null;
}

function promoteMediaTransforms(root: HTMLElement) {
  root.querySelectorAll("*").forEach((el) => {
    const htmlEl = el as HTMLElement;
    const tf = htmlEl.style?.transform || "";
    if (!/rotate\(|scaleX\(|scaleY\(/i.test(tf)) return;
    htmlEl.style.transformOrigin =
      htmlEl.style.transformOrigin || "center center";
    const deg = parseRotateDeg(tf);
    if (deg != null && Math.abs(deg) >= 0.5) {
      htmlEl.setAttribute("data-rotate", String(Number(deg.toFixed(4))));
    }
  });

  root.querySelectorAll("img").forEach((img) => {
    if (img.getAttribute("data-rotate")) return;
    let host: HTMLElement | null = img.parentElement;
    for (let d = 0; d < 6 && host && host !== root; d++) {
      const deg =
        parseRotateDeg(host.style.transform) ??
        (host.getAttribute("data-rotate")
          ? Number(host.getAttribute("data-rotate"))
          : null);
      if (deg != null && Math.abs(deg) >= 0.5) {
        img.setAttribute("data-rotate", String(Number(deg.toFixed(4))));
        break;
      }
      host = host.parentElement;
    }
  });
}

function applyNodeTransform(
  el: HTMLElement,
  plan: { rotation?: number; flipH?: boolean; flipV?: boolean },
) {
  if (!el || !plan) return;
  const rot = Number(plan.rotation) || 0;
  const parts: string[] = [];
  if (Math.abs(rot) >= 0.05) parts.push(`rotate(${rot}deg)`);
  if (plan.flipH) parts.push("scaleX(-1)");
  if (plan.flipV) parts.push("scaleY(-1)");
  if (!parts.length) return;
  const existing = String(el.style.transform || "").trim();
  if (!existing || existing === "none") {
    el.style.transform = parts.join(" ");
  } else if (!/rotate\(/i.test(existing) && Math.abs(rot) >= 0.05) {
    el.style.transform = `${existing} ${parts.join(" ")}`.trim();
  }
  el.style.transformOrigin = "center center";
  if (Math.abs(rot) >= 0.05) {
    el.setAttribute("data-rotate", String(Number(rot.toFixed(4))));
  }
}

function buildSlotPlan(
  serializedSlide: SerializedSlideLike,
  complexAsImage: boolean,
): SlotPlanItem[] {
  const flat = flattenNodes(
    (serializedSlide.nodes || []) as Parameters<typeof flattenNodes>[0],
  );
  const plan: SlotPlanItem[] = [];
  let textI = 0;
  let imageI = 0;
  let chartI = 0;
  let tableI = 0;

  for (let i = 0; i < flat.length; i++) {
    const node = flat[i] as {
      id?: string;
      nodeType?: string;
      name?: string;
      textBody?: { totalText?: string };
      rotation?: number;
      flipH?: boolean;
      flipV?: boolean;
    };
    const text = node.textBody?.totalText || "";
    let index = 0;
    if (node.nodeType === "picture") {
      index = imageI++;
    } else if (node.nodeType === "chart") {
      index = chartI++;
    } else if (node.nodeType === "table") {
      index = tableI++;
    } else if (node.nodeType === "shape" && text.trim()) {
      index = textI++;
    } else {
      continue;
    }

    const attrs = slotAttrsForNode(node.nodeType, {
      name: node.name,
      text,
      index,
    });
    if (!attrs) continue;

    const complex =
      complexAsImage && COMPLEX_TYPES.has(node.nodeType || "");
    plan.push({
      nodeId: node.id,
      flatIndex: i,
      attrs,
      complex,
      assetStem:
        node.nodeType === "chart"
          ? `chart-${chartI}`
          : node.nodeType === "table"
            ? `table-${tableI}`
            : null,
      slotType: attrs["data-slot-type"],
      slotRole: attrs["data-slot-role"],
      slot: attrs["data-slot"],
      rotation: Number(node.rotation) || 0,
      flipH: Boolean(node.flipH),
      flipV: Boolean(node.flipV),
    });
  }
  return plan;
}

function exportScaledHtml(root: HTMLElement, layout: string): string {
  promoteMediaTransforms(root);
  const w = parseFloat(root.style.width) || root.offsetWidth || CANVAS_W;
  const h = parseFloat(root.style.height) || root.offsetHeight || CANVAS_H;
  const scale = Math.min(CANVAS_W / w, CANVAS_H / h);
  const clone = root.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("[data-pptx-complex]").forEach((el) => {
    el.removeAttribute("data-pptx-complex");
    el.removeAttribute("data-pptx-complex-name");
  });

  const scaleCss = (css: string, k: number) =>
    String(css || "").replace(/(-?[\d.]+)(px|pt)\b/gi, (_, n, u) => {
      const x = parseFloat(n) * k;
      return `${Number(x.toFixed(4))}${u}`;
    });
  const flatten = (el: Element, k: number) => {
    if (!el || el.nodeType !== 1) return;
    const htmlEl = el as HTMLElement;
    if (htmlEl.style && htmlEl.style.cssText) {
      htmlEl.style.cssText = scaleCss(htmlEl.style.cssText, k);
    }
    const tag = (el.tagName || "").toLowerCase();
    if (tag === "svg") {
      for (const a of ["width", "height", "x", "y"]) {
        const v = el.getAttribute(a);
        if (v && /^-?[\d.]+(px)?$/.test(String(v).trim())) {
          el.setAttribute(
            a,
            String(Number((parseFloat(v) * k).toFixed(4))),
          );
        }
      }
    }
    for (const c of el.children || []) flatten(c, k);
  };
  if (Math.abs(scale - 1) > 0.001) flatten(clone, scale);

  clone.classList.add("slide", "slide-container", `layout-${layout}`);
  clone.style.position = "relative";
  clone.style.overflow = "hidden";
  clone.style.width = `${CANVAS_W}px`;
  clone.style.height = `${CANVAS_H}px`;
  const bg = clone.style.backgroundColor || "#fff";
  clone.style.background = bg;
  return clone.outerHTML;
}

async function blobSrcToBase64(
  src: string,
): Promise<{ mime: string; b64: string }> {
  const res = await fetch(src);
  const blob = await res.blob();
  const ab = await blob.arrayBuffer();
  const bytes = new Uint8Array(ab);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return {
    mime: blob.type || "image/png",
    b64: btoa(binary),
  };
}

function extFromMime(mime: string): string {
  if (/jpeg|jpg/i.test(mime)) return "jpg";
  if (/webp/i.test(mime)) return "webp";
  if (/svg/i.test(mime)) return "svg";
  return "png";
}

async function rasterizeComplex(
  el: HTMLElement,
): Promise<string | null> {
  try {
    const { snapdom } = await import("@zumer/snapdom");
    const canvas = await snapdom.toCanvas(el, {
      scale: 2,
      backgroundColor: "transparent",
      cache: "disabled",
    });
    return canvas.toDataURL("image/png");
  } catch {
    try {
      // Fallback: element may expose toDataURL (canvas/svg foreignObject hosts)
      const anyEl = el as HTMLElement & {
        toDataURL?: (t?: string) => string;
      };
      if (typeof anyEl.toDataURL === "function") {
        return anyEl.toDataURL("image/png");
      }
      const canvas = el.querySelector("canvas");
      if (canvas) return canvas.toDataURL("image/png");
    } catch {
      /* ignore */
    }
  }
  return null;
}

function dataUrlToBase64(dataUrl: string): { mime: string; b64: string } {
  const m = dataUrl.match(/^data:([^;]+);base64,(.+)$/);
  if (m) return { mime: m[1], b64: m[2] };
  return { mime: "image/png", b64: dataUrl };
}

const XLINK_NS = "http://www.w3.org/1999/xlink";

function isEphemeralImageSrc(src: string): boolean {
  return src.startsWith("blob:") || src.startsWith("data:");
}

function getSvgImageHref(el: Element): string {
  return (
    el.getAttribute("href") ||
    el.getAttribute("xlink:href") ||
    el.getAttributeNS(XLINK_NS, "href") ||
    ""
  );
}

function setSvgImageHref(el: Element, href: string) {
  el.setAttribute("href", href);
  el.setAttribute("xlink:href", href);
  try {
    el.setAttributeNS(XLINK_NS, "href", href);
  } catch {
    /* older hosts may reject NS set */
  }
}

/**
 * Persist renderer blob:/data: media into package images/.
 * Covers HTML <img> and SVG <image> (clipped pictures use the latter).
 */
async function materializeEphemeralImages(
  root: HTMLElement,
  layout: string,
  images: ConvertImagePayload[],
  warnings: string[],
): Promise<void> {
  let assetI = 0;

  const persist = async (
    src: string,
    apply: (nextSrc: string) => void,
    label: string,
  ) => {
    if (!isEphemeralImageSrc(src)) return;
    assetI += 1;
    try {
      const result = src.startsWith("data:")
        ? dataUrlToBase64(src)
        : await blobSrcToBase64(src);
      const ext = extFromMime(result.mime);
      const file = `${layout}-asset-${assetI}.${ext}`;
      images.push({ path: `images/${file}`, dataBase64: result.b64 });
      apply(`../images/${file}`);
    } catch (e) {
      warnings.push(
        `${layout}: materialize ${label} failed: ${
          e instanceof Error ? e.message : String(e)
        }`,
      );
    }
  };

  const imgs = [...root.querySelectorAll("img")];
  for (let idx = 0; idx < imgs.length; idx++) {
    const img = imgs[idx];
    if (img.getAttribute("data-webppt-materialized") === "1") continue;
    const src = img.getAttribute("src") || "";
    await persist(src, (next) => img.setAttribute("src", next), `img#${idx}`);
  }

  // pptx-renderer clipped pictures → <svg><image href="blob:…">
  const svgImages = [...root.querySelectorAll("image")];
  for (let svgIdx = 0; svgIdx < svgImages.length; svgIdx++) {
    const el = svgImages[svgIdx];
    const src = getSvgImageHref(el);
    await persist(
      src,
      (next) => setSvgImageHref(el, next),
      `svg-image#${svgIdx}`,
    );
  }
}

/** Infer CSS border-radius from SVG clipPath (circle / rounded rect). */
function borderRadiusFromClipPath(
  clipPathEl: Element | null,
  vbW: number,
  vbH: number,
): string {
  if (!clipPathEl || !(vbW > 0) || !(vbH > 0)) return "";
  const shape =
    clipPathEl.querySelector("circle, ellipse, path") ||
    clipPathEl.firstElementChild;
  if (!shape) return "";
  const tag = shape.tagName.toLowerCase();
  if (tag === "circle" || tag === "ellipse") return "50%";
  const d = shape.getAttribute("d") || "";
  // Circle expressed as two arcs with equal radii ≈ half the shorter side
  const arcs = [...d.matchAll(/A\s*([\d.]+)\s*,\s*([\d.]+)/gi)];
  if (
    arcs.length >= 2 &&
    Math.abs(Number(arcs[0][1]) - Number(arcs[0][2])) < 0.5
  ) {
    const r = Number(arcs[0][1]);
    if (Math.abs(r * 2 - Math.min(vbW, vbH)) < Math.max(2, vbW * 0.02)) {
      return "50%";
    }
  }
  if (arcs.length >= 1) {
    const rx = Number(arcs[0][1]);
    const ry = Number(arcs[0][2]);
    if (Number.isFinite(rx) && Number.isFinite(ry) && rx > 0 && ry > 0) {
      const xPct = ((rx / vbW) * 100).toFixed(2);
      const yPct = ((ry / vbH) * 100).toFixed(2);
      return `${xPct}% / ${yPct}%`;
    }
  }
  return "";
}

/**
 * SVG <image href> often fails in Admin preview / snapdom screenshot.
 * Promote clipped picture SVGs to HTML <img> with CSS overflow + border-radius.
 */
function promoteSvgImagesToImg(root: HTMLElement): number {
  let count = 0;
  const list = [...root.querySelectorAll("image")];
  for (const imageEl of list) {
    const href = getSvgImageHref(imageEl);
    if (!href || isEphemeralImageSrc(href)) continue;
    const svg = imageEl.closest("svg");
    if (!svg) continue;

    const vbParts = String(svg.getAttribute("viewBox") || "")
      .trim()
      .split(/[\s,]+/)
      .map(Number);
    const vbW = vbParts[2] || 0;
    const vbH = vbParts[3] || 0;

    let clipEl: Element | null = null;
    const clipped =
      imageEl.closest("[clip-path]") ||
      (imageEl.getAttribute("clip-path") ? imageEl : null);
    const clipRef =
      clipped?.getAttribute("clip-path") ||
      imageEl.getAttribute("clip-path") ||
      "";
    const idMatch = clipRef.match(/url\(\s*#([^)\s]+)\s*\)/i);
    if (idMatch) {
      clipEl =
        svg.querySelector(`clipPath#${CSS.escape(idMatch[1])}`) ||
        root.querySelector(`clipPath#${CSS.escape(idMatch[1])}`);
    }

    const radius = borderRadiusFromClipPath(clipEl, vbW, vbH);
    const host = (svg.parentElement as HTMLElement | null) || null;

    const img = document.createElement("img");
    img.src = href;
    img.alt = "";
    img.setAttribute("data-webppt-materialized", "1");

    const slotHost =
      (host?.closest("[data-slot]") as HTMLElement | null) ||
      (svg.closest("[data-slot]") as HTMLElement | null);
    if (slotHost) {
      for (const a of [
        "data-slot",
        "data-slot-type",
        "data-slot-role",
        "data-rotate",
      ]) {
        const v = slotHost.getAttribute(a);
        if (v) img.setAttribute(a, v);
      }
    }

    img.style.cssText =
      "width:100%;height:100%;object-fit:fill;display:block;border:0";

    if (host && host !== root) {
      if (radius) host.style.borderRadius = radius;
      host.style.overflow = "hidden";
      svg.replaceWith(img);
    } else {
      if (radius) img.style.borderRadius = radius;
      img.style.overflow = "hidden";
      svg.replaceWith(img);
    }
    count += 1;
  }
  return count;
}

/**
 * Convert a PPTX ArrayBuffer into slide HTML + image payloads for import-html-package.
 */
export async function pptxBrowserConvert(
  buffer: ArrayBuffer,
  options: {
    labelZh?: string;
    complexAsImage?: boolean;
    preserveSourceDataAttrs?: boolean;
    svgInlineMaxChars?: number;
    onProgress?: (info: { index: number; total: number; layout: string }) => void;
  } = {},
): Promise<BrowserConvertResult> {
  const complexAsImage = options.complexAsImage !== false;
  const warnings: string[] = [];
  const images: ConvertImagePayload[] = [];
  const mount = ensureMount();
  const handles: SlideHandle[] = [];

  const zipLimits = {
    ...RECOMMENDED_ZIP_LIMITS,
    ...DEFAULT_CONVERT_ZIP_LIMITS,
  };
  const files = await parseZip(buffer, zipLimits);
  const presentation = buildPresentation(files);
  const serialized = serializePresentation(presentation);
  const slideCount = presentation.slides.length;
  const width = presentation.width;
  const height = presentation.height;

  const bases: string[] = [];
  const classified = [];
  for (let i = 0; i < slideCount; i++) {
    const slideSer = serialized.slides[i] as SerializedSlideLike;
    const c = classifyLayout({
      nodes: (slideSer.nodes || []) as Parameters<typeof classifyLayout>[0]["nodes"],
      index: i,
      slideCount,
      slideW: width,
      slideH: height,
    });
    bases.push(c.base);
    classified.push(c);
  }
  const layouts = uniquifyLayouts(bases);

  const slidesOut: BrowserConvertSlide[] = [];

  try {
    for (let i = 0; i < slideCount; i++) {
      const layout = layouts[i];
      options.onProgress?.({ index: i, total: slideCount, layout });

      const slideSer = serialized.slides[i] as SerializedSlideLike;
      const title = guessSlideTitle(
        (slideSer.nodes || []) as Parameters<typeof guessSlideTitle>[0],
      );
      const plan = buildSlotPlan(slideSer, complexAsImage);

      for (const h of handles) {
        try {
          h.dispose();
        } catch {
          /* */
        }
      }
      handles.length = 0;
      mount.innerHTML = "";

      const slide = presentation.slides[i];
      const handle = renderSlide(presentation, slide, {});
      handles.push(handle);
      mount.appendChild(handle.element);
      await handle.ready;
      await delay(120);
      if (document.fonts?.ready) {
        try {
          await document.fonts.ready;
        } catch {
          /* */
        }
      }

      const root = handle.element as HTMLElement;
      root.classList.add("pptx-slide-root");
      root.style.position = "relative";
      root.style.overflow = "hidden";

      const flat = flattenNodes(
        (slideSer.nodes || []) as Parameters<typeof flattenNodes>[0],
      );
      const candidates = [...root.querySelectorAll(":scope > *")] as HTMLElement[];
      const used = new Set<number>();

      for (const planItem of plan) {
        const node =
          (flat.find(
            (n) => (n as { id?: string }).id === planItem.nodeId,
          ) as
            | {
                position?: { x?: number; y?: number };
                size?: { w?: number; h?: number };
                nodeType?: string;
                id?: string;
              }
            | undefined) ||
          (flat[planItem.flatIndex] as
            | {
                position?: { x?: number; y?: number };
                size?: { w?: number; h?: number };
                nodeType?: string;
                id?: string;
              }
            | undefined);
        if (!node) continue;
        let el = candidates.find(
          (c, ci) => !used.has(ci) && approxMatch(c, node),
        );
        if (!el) {
          el = [...root.querySelectorAll("*")].find((c) => {
            if (c === root) return false;
            return approxMatch(c as HTMLElement, node);
          }) as HTMLElement | undefined;
        }
        if (!el) continue;
        const ci = candidates.indexOf(el);
        if (ci >= 0) used.add(ci);
        applyAttrs(el, planItem.attrs);
        el.setAttribute("data-pptx-node-type", node.nodeType || "");
        el.setAttribute("data-pptx-node-id", node.id || "");
        applyNodeTransform(el, planItem);
        if (planItem.complex) {
          el.setAttribute("data-pptx-complex", "1");
          el.setAttribute(
            "data-pptx-complex-name",
            planItem.assetStem || "complex",
          );
        }
      }

      let imgI = 0;
      for (const img of root.querySelectorAll("img")) {
        if (img.hasAttribute("data-slot")) continue;
        imgI += 1;
        applyAttrs(img, {
          "data-slot": `image-${imgI}`,
          "data-slot-type": "image",
          "data-slot-role": imgI === 1 ? "hero-image" : "image",
        });
      }

      // Rasterize complex chart/table nodes (best-effort)
      if (complexAsImage) {
        const complexEls = [
          ...root.querySelectorAll("[data-pptx-complex='1']"),
        ] as HTMLElement[];
        for (let ci = 0; ci < complexEls.length; ci++) {
          const el = complexEls[ci];
          const name =
            el.getAttribute("data-pptx-complex-name") || `complex-${ci + 1}`;
          try {
            const dataUrl = await rasterizeComplex(el);
            if (!dataUrl) {
              warnings.push(
                `${layout}: complex screenshot skipped (${name})`,
              );
              continue;
            }
            const { mime, b64 } = dataUrlToBase64(dataUrl);
            const file = `${layout}-${name}.png`;
            images.push({ path: `images/${file}`, dataBase64: b64 });
            const planItem =
              plan.find((p) => p.assetStem === name) || ({} as SlotPlanItem);
            const img = document.createElement("img");
            img.src = `../images/${file}`;
            img.alt = title;
            img.setAttribute(
              "data-slot",
              planItem.slot || el.getAttribute("data-slot") || `complex-${ci + 1}`,
            );
            img.setAttribute(
              "data-slot-type",
              planItem.slotType === "chart" ? "chart" : "image",
            );
            img.setAttribute(
              "data-slot-role",
              planItem.slotRole || "chart",
            );
            img.style.cssText = el.style.cssText || "";
            if (!img.style.position) img.style.position = "absolute";
            if (!img.style.left) img.style.left = el.style.left || "0px";
            if (!img.style.top) img.style.top = el.style.top || "0px";
            if (!img.style.width)
              img.style.width = el.style.width || `${el.offsetWidth}px`;
            if (!img.style.height)
              img.style.height = el.style.height || `${el.offsetHeight}px`;
            img.style.objectFit = "contain";
            // Keep data URL temporarily so materialize loop can skip; we already stored base64
            img.setAttribute("data-webppt-materialized", "1");
            el.replaceWith(img);
            void mime;
          } catch (e) {
            warnings.push(
              `${layout}: complex screenshot failed (${name}): ${
                e instanceof Error ? e.message : String(e)
              }`,
            );
          }
        }
      }

      // Materialize remaining blob:/data: images (HTML <img> + SVG <image>)
      await materializeEphemeralImages(root, layout, images, warnings);
      const promoted = promoteSvgImagesToImg(root);
      if (promoted) {
        warnings.push(
          `${layout}: SVG <image> ×${promoted} → HTML <img>（预览/截图更稳）`,
        );
      }

      const rawHtml = exportScaledHtml(root, layout);
      const processed = postprocessSlideHtml({
        html: rawHtml,
        slideStem: layout,
        preserveSourceDataAttrs: options.preserveSourceDataAttrs,
        svgInlineMaxChars: options.svgInlineMaxChars ?? 2500,
      });
      images.push(...processed.images);
      warnings.push(...processed.warnings);

      slidesOut.push({
        file: `slides/${layout}.html`,
        title,
        layout,
        description: describeLayout(layout, classified[i].stats, title),
        html: processed.html,
      });
    }
  } finally {
    for (const h of handles) {
      try {
        h.dispose();
      } catch {
        /* */
      }
    }
    mount.innerHTML = "";
  }

  warnings.unshift(
    `pptx-renderer → html-slide；画布缩放 ${width}×${height} → ${CANVAS_W}×${CANVAS_H}`,
  );

  return {
    slides: slidesOut,
    images,
    warnings,
    labelZh: options.labelZh || "浏览器转换模板",
    theme: { bg: "#ffffff", text: "#111111", accent: "#2563eb" },
  };
}
