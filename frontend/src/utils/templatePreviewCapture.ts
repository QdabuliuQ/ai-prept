/**
 * 在当前浏览器里离屏加载模板页，用 snapdom 截成 WebP。
 * 供 Admin 上传前生成预览图，替代服务端 Puppeteer。
 *
 * svg-fallback 整页（data-pptx-export-fallback="svg"）含 SVG <image>，
 * snapdom 对其外链/大 data URL 常抛 EncodingError；这类页改走 SVG→canvas 栅格化。
 */

import { SLIDE_HTML_HEIGHT, SLIDE_HTML_WIDTH } from "@/utils/slideHtml";
import { buildTemplateSlideEmbedSrc } from "@/utils/templateEmbed";

/** 按设计稿 1:1 截图；服务端再压成 WebP。半分辨率全屏会明显发糊。 */
const PREVIEW_SCALE = 1;
const WEBP_QUALITY = 0.9;
const PNG_QUALITY = 0.95;
const XLINK_NS = "http://www.w3.org/1999/xlink";

function padIndex(n: number): string {
  return String(n).padStart(2, "0");
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function canvasToBlob(
  canvas: HTMLCanvasElement,
  type: string,
  quality: number,
): Promise<Blob | null> {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), type, quality);
  });
}

function mimeFromUrl(url: string): string | null {
  const path = url.split("?")[0].toLowerCase();
  if (path.endsWith(".png")) return "image/png";
  if (path.endsWith(".jpg") || path.endsWith(".jpeg")) return "image/jpeg";
  if (path.endsWith(".webp")) return "image/webp";
  if (path.endsWith(".gif")) return "image/gif";
  if (path.endsWith(".svg")) return "image/svg+xml";
  return null;
}

function mimeFromMagic(bytes: Uint8Array): string | null {
  if (
    bytes.length >= 8 &&
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47
  ) {
    return "image/png";
  }
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "image/jpeg";
  }
  if (
    bytes.length >= 12 &&
    bytes[0] === 0x52 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x46 &&
    bytes[8] === 0x57 &&
    bytes[9] === 0x45 &&
    bytes[10] === 0x42 &&
    bytes[11] === 0x50
  ) {
    return "image/webp";
  }
  if (bytes.length >= 6 && bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46) {
    return "image/gif";
  }
  return null;
}

async function blobToImageDataUrl(blob: Blob, sourceUrl: string): Promise<string> {
  const buf = await blob.arrayBuffer();
  const bytes = new Uint8Array(buf);
  if (bytes.length < 24) {
    throw new Error("image too small");
  }
  const mime =
    mimeFromMagic(bytes) ||
    (blob.type && blob.type.startsWith("image/") ? blob.type : null) ||
    mimeFromUrl(sourceUrl) ||
    "image/png";
  if (!mime.startsWith("image/")) {
    throw new Error(`not an image mime: ${mime}`);
  }
  const typed = new Blob([bytes], { type: mime });
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () =>
      reject(reader.error || new Error("readAsDataURL failed"));
    reader.readAsDataURL(typed);
  });
  await new Promise<void>((resolve, reject) => {
    const probe = new Image();
    const timer = window.setTimeout(() => {
      probe.src = "";
      reject(new Error("image probe timeout"));
    }, 8000);
    probe.onload = () => {
      window.clearTimeout(timer);
      if (probe.naturalWidth < 1 || probe.naturalHeight < 1) {
        reject(new Error("image probe empty"));
        return;
      }
      resolve();
    };
    probe.onerror = () => {
      window.clearTimeout(timer);
      reject(new Error("image probe failed"));
    };
    probe.src = dataUrl;
  });
  return dataUrl;
}

function svgImageHref(el: Element): string {
  return (
    el.getAttribute("href") ||
    el.getAttribute("xlink:href") ||
    el.getAttributeNS(XLINK_NS, "href") ||
    ""
  );
}

function isSvgFallbackStage(root: HTMLElement): boolean {
  if (root.getAttribute("data-pptx-export-fallback") === "svg") return true;
  if (root.querySelector('[data-pptx-export-fallback="svg"]')) return true;
  // Whole-slide SVG with embedded raster <image>
  const svg = root.matches("svg")
    ? root
    : (root.querySelector(":scope > svg, .stage > svg, svg") as SVGSVGElement | null);
  if (!svg) return false;
  return Boolean(svg.querySelector("image"));
}

async function resolveImageDataUrl(
  href: string,
  baseHref: string,
): Promise<string | null> {
  if (!href || href.startsWith("blob:")) return null;
  if (href.startsWith("data:image/")) return href;
  try {
    const abs = new URL(href, baseHref).href;
    const res = await fetch(abs, { credentials: "same-origin" });
    if (!res.ok) return null;
    return await blobToImageDataUrl(await res.blob(), abs);
  } catch {
    return null;
  }
}

/**
 * HTML <img> 外链 → data URL（snapdom 更稳）。
 * 不往 SVG <image> 写大 data URL（易触发 EncodingError）。
 */
async function inlineHtmlImagesForCapture(
  root: ParentNode,
  baseHref: string,
): Promise<void> {
  const jobs = Array.from(root.querySelectorAll("img")).map((img) => async () => {
    const src = img.getAttribute("src") || img.currentSrc || "";
    if (!src || src.startsWith("data:") || src.startsWith("blob:")) return;
    const dataUrl = await resolveImageDataUrl(src, baseHref);
    if (!dataUrl) return;
    img.removeAttribute("srcset");
    img.src = dataUrl;
  });
  if (!jobs.length) return;
  await Promise.allSettled(
    jobs.map((job) =>
      Promise.race([job().catch(() => undefined), delay(12000)]),
    ),
  );
}

type SvgBox = { x: number; y: number; w: number; h: number };

function readSvgBox(el: Element, fallbackW = 0, fallbackH = 0): SvgBox {
  return {
    x: parseFloat(el.getAttribute("x") || "0") || 0,
    y: parseFloat(el.getAttribute("y") || "0") || 0,
    w: parseFloat(el.getAttribute("width") || String(fallbackW)) || fallbackW,
    h: parseFloat(el.getAttribute("height") || String(fallbackH)) || fallbackH,
  };
}

function isOpaqueSvgFill(fill: string | null | undefined): boolean {
  if (!fill) return false;
  const v = fill.trim().toLowerCase();
  if (!v || v === "none" || v === "transparent") return false;
  if (/^rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*0\s*\)$/.test(v)) {
    return false;
  }
  return true;
}

/** rect 盖住 image 面积比例（intersection / image） */
function coverRatio(rect: SvgBox, image: SvgBox): number {
  const x0 = Math.max(rect.x, image.x);
  const y0 = Math.max(rect.y, image.y);
  const x1 = Math.min(rect.x + rect.w, image.x + image.w);
  const y1 = Math.min(rect.y + rect.h, image.y + image.h);
  const iw = Math.max(0, x1 - x0);
  const ih = Math.max(0, y1 - y0);
  const area = Math.max(1, image.w * image.h);
  return (iw * ih) / area;
}

/**
 * PPTX→SVG 常在 <image> 下垫同尺寸灰 rect；分层栅格时若先画图再叠整页矢量，
 * 这些垫层会把插图盖掉。只去掉「出现在 image 之前且大面积盖住它」的不透明 rect。
 */
function markImageUnderlayRects(svg: SVGSVGElement, vbW: number, vbH: number) {
  const images = Array.from(svg.querySelectorAll("image"));
  for (const img of images) {
    const imgBox = readSvgBox(img, vbW, vbH);
    if (imgBox.w < 1 || imgBox.h < 1) continue;
    for (const rect of Array.from(svg.querySelectorAll("rect"))) {
      if (!isOpaqueSvgFill(rect.getAttribute("fill"))) continue;
      // rect 在 document 中位于 image 之前（垫在下面）
      const pos = rect.compareDocumentPosition(img);
      if (!(pos & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
      const rectBox = readSvgBox(rect);
      if (coverRatio(rectBox, imgBox) >= 0.55) {
        rect.setAttribute("data-webppt-capture-underlay", "1");
      }
    }
  }
}

/**
 * 把 SVG 画到 canvas。
 * 大图不塞进 SVG data URL（会 svg raster failed）；先 drawImage 配图，再叠矢量层。
 */
async function rasterizeSvgElement(
  svg: SVGSVGElement,
  baseHref: string,
): Promise<HTMLCanvasElement> {
  const vb = String(svg.getAttribute("viewBox") || "")
    .trim()
    .split(/[\s,]+/)
    .map(Number);
  const vbX = Number.isFinite(vb[0]) ? vb[0] : 0;
  const vbY = Number.isFinite(vb[1]) ? vb[1] : 0;
  const vbW = vb[2] > 0 ? vb[2] : SLIDE_HTML_WIDTH;
  const vbH = vb[3] > 0 ? vb[3] : SLIDE_HTML_HEIGHT;
  const scaleX = SLIDE_HTML_WIDTH / vbW;
  const scaleY = SLIDE_HTML_HEIGHT / vbH;

  const canvas = document.createElement("canvas");
  canvas.width = Math.round(SLIDE_HTML_WIDTH * PREVIEW_SCALE);
  canvas.height = Math.round(SLIDE_HTML_HEIGHT * PREVIEW_SCALE);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2d context");
  ctx.setTransform(PREVIEW_SCALE, 0, 0, PREVIEW_SCALE, 0, 0);

  // 底色：优先用全幅 background rect
  let bg = "#ffffff";
  const bgRect = svg.querySelector(
    'rect[data-pptx-role="background"], rect#bg',
  ) as SVGRectElement | null;
  const bgFill = bgRect?.getAttribute("fill");
  if (bgFill && /^#|^rgb/i.test(bgFill)) bg = bgFill;
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, SLIDE_HTML_WIDTH, SLIDE_HTML_HEIGHT);

  // 1) 配图直接画到 canvas（避开 SVG-in-Image 对内嵌 raster 的限制）
  const images = Array.from(svg.querySelectorAll("image"));
  for (const el of images) {
    const href = svgImageHref(el);
    const dataUrl = await resolveImageDataUrl(href, baseHref);
    if (!dataUrl) continue;
    let bitmap: HTMLImageElement;
    try {
      bitmap = await loadHtmlImage(dataUrl);
    } catch {
      continue;
    }
    const box = readSvgBox(el, vbW, vbH);
    const par = (el.getAttribute("preserveAspectRatio") || "").toLowerCase();
    const dx = (box.x - vbX) * scaleX;
    const dy = (box.y - vbY) * scaleY;
    const dw = box.w * scaleX;
    const dh = box.h * scaleY;
    if (/slice/.test(par)) {
      drawImageCover(ctx, bitmap, dx, dy, dw, dh);
    } else if (/none/.test(par)) {
      ctx.drawImage(bitmap, dx, dy, dw, dh);
    } else {
      drawImageContain(ctx, bitmap, dx, dy, dw, dh);
    }
  }

  // 2) 矢量/文字层：去掉 <image> 与其下垫 rect，再栅格化叠上去
  markImageUnderlayRects(svg, vbW, vbH);
  let clone: SVGSVGElement;
  try {
    clone = svg.cloneNode(true) as SVGSVGElement;
  } finally {
    svg
      .querySelectorAll("[data-webppt-capture-underlay]")
      .forEach((el) => el.removeAttribute("data-webppt-capture-underlay"));
  }
  if (!clone.getAttribute("xmlns")) {
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  }
  clone.setAttribute("xmlns:xlink", XLINK_NS);
  clone.querySelectorAll("image").forEach((el) => el.remove());
  clone
    .querySelectorAll("[data-webppt-capture-underlay]")
    .forEach((el) => el.remove());
  // 全幅底 rect 已在 canvas 填过，去掉以免盖住配图
  clone
    .querySelectorAll('rect[data-pptx-role="background"], rect#bg')
    .forEach((el) => {
      const width = parseFloat(el.getAttribute("width") || "0");
      const height = parseFloat(el.getAttribute("height") || "0");
      if (width >= vbW * 0.95 && height >= vbH * 0.95) el.remove();
    });

  clone.setAttribute("width", String(SLIDE_HTML_WIDTH));
  clone.setAttribute("height", String(SLIDE_HTML_HEIGHT));
  if (!clone.getAttribute("viewBox")) {
    clone.setAttribute("viewBox", `${vbX} ${vbY} ${vbW} ${vbH}`);
  }

  const raw = new XMLSerializer().serializeToString(clone);
  // HTML 解析进 DOM 的 SVG 序列化时偶发缺 xmlns；中文需 XML 声明才稳
  const xml = raw.includes("xmlns=")
    ? raw
    : raw.replace(/^<svg\b/i, '<svg xmlns="http://www.w3.org/2000/svg"');
  const withDecl = xml.startsWith("<?xml")
    ? xml
    : `<?xml version="1.0" encoding="UTF-8"?>${xml}`;

  let overlay: HTMLImageElement | null = null;
  let blobUrl: string | null = null;
  try {
    // 1) blob: 对非 ASCII / 长串最稳
    blobUrl = URL.createObjectURL(
      new Blob([withDecl], { type: "image/svg+xml;charset=utf-8" }),
    );
    overlay = await loadHtmlImage(blobUrl);
  } catch {
    overlay = null;
  } finally {
    if (blobUrl) URL.revokeObjectURL(blobUrl);
  }
  if (!overlay) {
    try {
      // 2) data: + encodeURIComponent 兜底
      overlay = await loadHtmlImage(
        "data:image/svg+xml;charset=utf-8," + encodeURIComponent(withDecl),
      );
    } catch {
      overlay = null;
    }
  }
  if (overlay) {
    ctx.drawImage(overlay, 0, 0, SLIDE_HTML_WIDTH, SLIDE_HTML_HEIGHT);
  } else if (images.length === 0) {
    // 无配图且矢量层也挂了，才算失败
    throw new Error("svg raster failed");
  }
  // 有配图时：矢量层失败仍交配图+底色，避免整页截图中断
  return canvas;
}

function loadHtmlImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const timer = window.setTimeout(() => {
      img.src = "";
      reject(new Error("image load timeout"));
    }, 20000);
    img.onload = () => {
      window.clearTimeout(timer);
      if (img.naturalWidth < 1) {
        reject(new Error("image empty"));
        return;
      }
      resolve(img);
    };
    img.onerror = () => {
      window.clearTimeout(timer);
      reject(new Error("image load failed"));
    };
    img.decoding = "async";
    img.src = src;
  });
}

function drawImageCover(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  dx: number,
  dy: number,
  dw: number,
  dh: number,
) {
  const ir = img.naturalWidth / Math.max(1, img.naturalHeight);
  const br = dw / Math.max(1, dh);
  let sx = 0;
  let sy = 0;
  let sw = img.naturalWidth;
  let sh = img.naturalHeight;
  if (ir > br) {
    sw = img.naturalHeight * br;
    sx = (img.naturalWidth - sw) / 2;
  } else {
    sh = img.naturalWidth / br;
    sy = (img.naturalHeight - sh) / 2;
  }
  ctx.drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh);
}

function drawImageContain(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  dx: number,
  dy: number,
  dw: number,
  dh: number,
) {
  const ir = img.naturalWidth / Math.max(1, img.naturalHeight);
  const br = dw / Math.max(1, dh);
  let w = dw;
  let h = dh;
  let x = dx;
  let y = dy;
  if (ir > br) {
    h = dw / ir;
    y = dy + (dh - h) / 2;
  } else {
    w = dh * ir;
    x = dx + (dw - w) / 2;
  }
  ctx.drawImage(img, x, y, w, h);
}

async function canvasToPreviewBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  if (
    canvas.width < SLIDE_HTML_WIDTH * 0.9 ||
    canvas.height < SLIDE_HTML_HEIGHT * 0.9
  ) {
    throw new Error(`截图像素过小：${canvas.width}×${canvas.height}`);
  }
  const webp = await canvasToBlob(canvas, "image/webp", WEBP_QUALITY);
  if (webp && webp.size > 8_000) return webp;
  const png = await canvasToBlob(canvas, "image/png", PNG_QUALITY);
  if (png && png.size > 8_000) return png;
  throw new Error(`截图内容过空（${webp?.size ?? 0} bytes）`);
}

async function captureOneSlide(
  templateId: string,
  relFile: string,
): Promise<Blob> {
  const { waitForSlideRoot, waitForImages } = await import(
    "@/utils/pptx/htmlSlideMount"
  );

  const iframe = document.createElement("iframe");
  iframe.setAttribute("aria-hidden", "true");
  iframe.style.position = "fixed";
  iframe.style.left = "-10000px";
  iframe.style.top = "0";
  iframe.style.width = `${SLIDE_HTML_WIDTH}px`;
  iframe.style.height = `${SLIDE_HTML_HEIGHT}px`;
  iframe.style.border = "0";
  iframe.style.pointerEvents = "none";
  iframe.src = buildTemplateSlideEmbedSrc(templateId, relFile);
  document.body.appendChild(iframe);

  try {
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(
        () => reject(new Error(`页面加载超时：${relFile}`)),
        45000,
      );
      iframe.addEventListener(
        "load",
        () => {
          window.clearTimeout(timer);
          resolve();
        },
        { once: true },
      );
      iframe.addEventListener(
        "error",
        () => {
          window.clearTimeout(timer);
          reject(new Error(`页面加载失败：${relFile}`));
        },
        { once: true },
      );
    });

    const slideRoot = await waitForSlideRoot(iframe);
    const doc = iframe.contentDocument;
    const baseHref =
      doc?.defaultView?.location?.href ||
      new URL(iframe.src, window.location.href).href;

    if (doc) {
      await waitForImages(doc, 12000);
    }
    await delay(120);

    // svg-fallback：不要走 snapdom（会 EncodingError），直接栅格化 SVG
    if (isSvgFallbackStage(slideRoot)) {
      const svg =
        (slideRoot.matches("svg")
          ? slideRoot
          : slideRoot.querySelector(
              '[data-pptx-export-fallback="svg"] svg, .stage svg, :scope > svg, svg',
            )) as SVGSVGElement | null;
      if (!svg) {
        throw new Error(`SVG 预览页缺少 <svg>：${relFile}`);
      }
      const canvas = await rasterizeSvgElement(svg, baseHref);
      try {
        return await canvasToPreviewBlob(canvas);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        throw new Error(`${msg}（${relFile}）`);
      }
    }

    // 普通 html-slide：img 外链内联后 snapdom
    await inlineHtmlImagesForCapture(slideRoot, baseHref);
    if (doc) await waitForImages(doc, 8000);
    await delay(120);

    const { snapdom } = await import("@zumer/snapdom");
    let canvas: HTMLCanvasElement;
    try {
      canvas = await snapdom.toCanvas(slideRoot, {
        scale: PREVIEW_SCALE,
        backgroundColor: "#ffffff",
        width: SLIDE_HTML_WIDTH,
        height: SLIDE_HTML_HEIGHT,
        cache: "disabled",
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // 最后兜底：页内若仍有 svg>image，尝试 SVG 栅格化
      const svg = slideRoot.querySelector("svg image")
        ? (slideRoot.querySelector("svg") as SVGSVGElement | null)
        : null;
      if (
        svg &&
        /cannot be decoded|EncodingError|InvalidStateError/i.test(msg)
      ) {
        canvas = await rasterizeSvgElement(svg, baseHref);
      } else {
        throw new Error(
          `截图失败：${relFile}（${msg || "unknown"}）`,
        );
      }
    }
    try {
      return await canvasToPreviewBlob(canvas);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      throw new Error(`${msg}（${relFile}）`);
    }
  } finally {
    iframe.remove();
  }
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const raw = String(reader.result || "");
      const comma = raw.indexOf(",");
      resolve(comma >= 0 ? raw.slice(comma + 1) : raw);
    };
    reader.onerror = () => reject(reader.error || new Error("读取截图失败"));
    reader.readAsDataURL(blob);
  });
}

export async function previewBlobsToPayload(
  shots: Array<{ fileName: string; blob: Blob }>,
): Promise<{ previews: Array<{ fileName: string; dataBase64: string }> }> {
  const previews: Array<{ fileName: string; dataBase64: string }> = [];
  for (const shot of shots) {
    previews.push({
      fileName: shot.fileName,
      dataBase64: await blobToBase64(shot.blob),
    });
  }
  return { previews };
}

export async function captureTemplatePreviewBlobs(
  templateId: string,
  slideFiles: string[],
  onProgress?: (done: number, total: number) => void,
): Promise<Array<{ fileName: string; blob: Blob }>> {
  const files = slideFiles.map((f) => f.replace(/^\/+/, "")).filter(Boolean);
  if (files.length === 0) {
    throw new Error("模板没有可截图的页面");
  }
  const out: Array<{ fileName: string; blob: Blob }> = [];
  for (let i = 0; i < files.length; i += 1) {
    onProgress?.(i, files.length);
    const blob = await captureOneSlide(templateId, files[i]);
    const ext = blob.type === "image/png" ? "png" : "webp";
    out.push({ fileName: `${padIndex(i + 1)}.${ext}`, blob });
  }
  onProgress?.(files.length, files.length);
  return out;
}
