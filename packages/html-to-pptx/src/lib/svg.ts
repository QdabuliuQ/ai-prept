/** Rasterize inline SVG (stroke paths, icons, deco) for pptxgen image frames. */

function loadSvgImage(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

function parseLen(raw: string | null): number {
  if (!raw) return 0;
  const n = Number.parseFloat(raw);
  return Number.isFinite(n) ? n : 0;
}

/** Stroke half-width in CSS pixels (viewBox user units → rendered px). */
export function svgStrokePadPx(svg: SVGSVGElement): number {
  let maxSw = 0;
  const nodes = [svg, ...Array.from(svg.querySelectorAll("*"))];
  for (const node of nodes) {
    const attr = node.getAttribute?.("stroke-width");
    if (attr) maxSw = Math.max(maxSw, parseLen(attr));
    const el = node as Element;
    const win = el.ownerDocument?.defaultView;
    if (win) {
      const sw = parseLen(win.getComputedStyle(el).strokeWidth);
      maxSw = Math.max(maxSw, sw);
    }
  }
  if (maxSw <= 0) return 1;

  const vb = svg.viewBox?.baseVal;
  const layoutW =
    svg.getBoundingClientRect().width ||
    parseLen(svg.getAttribute("width")) ||
    1;
  const vbW = vb && vb.width > 0 ? vb.width : layoutW;
  const unit = layoutW / vbW;
  return Math.max(1, Math.ceil((maxSw * unit) / 2) + 1);
}

function ensureSvgSize(markup: string, width: number, height: number): string {
  let svg = markup.trim();
  if (!/\sxmlns=/.test(svg)) {
    svg = svg.replace(/<svg\b/i, '<svg xmlns="http://www.w3.org/2000/svg"');
  }
  const w = Math.max(1, Math.round(width));
  const h = Math.max(1, Math.round(height));
  if (/\swidth\s*=/.test(svg)) {
    svg = svg.replace(/\swidth\s*=\s*(["']).*?\1/i, ` width="${w}"`);
  } else {
    svg = svg.replace(/<svg\b/i, `<svg width="${w}"`);
  }
  if (/\sheight\s*=/.test(svg)) {
    svg = svg.replace(/\sheight\s*=\s*(["']).*?\1/i, ` height="${h}"`);
  } else {
    svg = svg.replace(/<svg\b/i, `<svg height="${h}"`);
  }
  if (!/\soverflow\s*=/.test(svg)) {
    svg = svg.replace(/<svg\b/i, '<svg overflow="visible"');
  }
  return svg;
}

export async function rasterizeSvgMarkup(
  markup: string,
  widthPx: number,
  heightPx: number,
  opts?: {
    localW?: number;
    localH?: number;
    matrix?: { a: number; b: number; c: number; d: number };
  },
): Promise<string | null> {
  const w = Math.max(1, Math.ceil(widthPx));
  const h = Math.max(1, Math.ceil(heightPx));
  const localW = Math.max(1, Math.ceil(opts?.localW || w));
  const localH = Math.max(1, Math.ceil(opts?.localH || h));
  const svg = ensureSvgSize(markup, localW, localH);
  const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const img = await loadSvgImage(url);
    if (!img) return null;
    const dpr = 2;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.scale(dpr, dpr);
    const mat = opts?.matrix;
    const identity =
      !mat ||
      (Math.abs(mat.a - 1) < 0.002 &&
        Math.abs(mat.b) < 0.002 &&
        Math.abs(mat.c) < 0.002 &&
        Math.abs(mat.d - 1) < 0.002);
    if (identity) {
      ctx.drawImage(img, 0, 0, w, h);
    } else {
      ctx.translate(w / 2, h / 2);
      ctx.transform(mat.a, mat.b, mat.c, mat.d, 0, 0);
      ctx.translate(-localW / 2, -localH / 2);
      ctx.drawImage(img, 0, 0, localW, localH);
    }
    return canvas.toDataURL("image/png");
  } catch {
    return null;
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function serializeSvg(el: SVGSVGElement, padPx = 0): string {
  const clone = el.cloneNode(true) as SVGSVGElement;
  if (padPx > 0) {
    const layoutW =
      el.getBoundingClientRect().width || parseLen(el.getAttribute("width"));
    const layoutH =
      el.getBoundingClientRect().height || parseLen(el.getAttribute("height"));
    const vb = el.viewBox?.baseVal;
    const vbW = vb && vb.width > 0 ? vb.width : layoutW || 1;
    const vbH = vb && vb.height > 0 ? vb.height : layoutH || 1;
    const ux = padPx * (vbW / Math.max(layoutW, 1));
    const uy = padPx * (vbH / Math.max(layoutH, 1));
    const vx = vb ? vb.x : 0;
    const vy = vb ? vb.y : 0;
    clone.setAttribute(
      "viewBox",
      `${vx - ux} ${vy - uy} ${vbW + 2 * ux} ${vbH + 2 * uy}`,
    );
    clone.setAttribute("width", String(Math.max(1, layoutW + padPx * 2)));
    clone.setAttribute("height", String(Math.max(1, layoutH + padPx * 2)));
  }
  const xml = new XMLSerializer().serializeToString(clone);
  if (/\sxmlns=/.test(xml)) return xml;
  return xml.replace(/<svg\b/i, '<svg xmlns="http://www.w3.org/2000/svg"');
}
