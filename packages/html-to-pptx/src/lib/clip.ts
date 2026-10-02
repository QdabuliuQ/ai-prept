import { inchToPx } from "../config";
import type { ImageSizing } from "../types";

function loadImageElement(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

function fitDrawRect(
  srcW: number,
  srcH: number,
  boxW: number,
  boxH: number,
  sizing: ImageSizing,
  posX: number,
  posY: number,
): { dx: number; dy: number; dw: number; dh: number } {
  if (sizing === "stretch" || srcW <= 0 || srcH <= 0 || boxW <= 0 || boxH <= 0) {
    return { dx: 0, dy: 0, dw: boxW, dh: boxH };
  }
  const srcRatio = srcW / srcH;
  const boxRatio = boxW / boxH;
  let dw: number;
  let dh: number;
  if (sizing === "cover") {
    if (srcRatio > boxRatio) {
      dh = boxH;
      dw = boxH * srcRatio;
    } else {
      dw = boxW;
      dh = boxW / srcRatio;
    }
  } else {
    if (srcRatio > boxRatio) {
      dw = boxW;
      dh = boxW / srcRatio;
    } else {
      dh = boxH;
      dw = boxH * srcRatio;
    }
  }
  const x = Math.min(1, Math.max(0, posX));
  const y = Math.min(1, Math.max(0, posY));
  return {
    dx: (boxW - dw) * x,
    dy: (boxH - dh) * y,
    dw,
    dh,
  };
}

function cornerRadiusPx(borderRadius: string, w: number, h: number): number {
  const br = (borderRadius || "").trim();
  if (!br || br === "0px") return 0;
  const first = br.split(/\s+/)[0] || "";
  if (first.includes("%")) {
    const pct = Number.parseFloat(first);
    if (!Number.isFinite(pct) || pct <= 0) return 0;
    return Math.min(w, h) * Math.min(1, pct / 100);
  }
  const px = Number.parseFloat(first);
  if (!Number.isFinite(px) || px <= 0) return 0;
  return Math.min(px, w / 2, h / 2);
}

function pathRoundedRect(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  r: number,
): void {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
  if (radius <= 0.5) {
    ctx.rect(0, 0, w, h);
    return;
  }
  if (typeof ctx.roundRect === "function") {
    ctx.roundRect(0, 0, w, h, radius);
    return;
  }
  ctx.moveTo(radius, 0);
  ctx.arcTo(w, 0, w, h, radius);
  ctx.arcTo(w, h, 0, h, radius);
  ctx.arcTo(0, h, 0, 0, radius);
  ctx.arcTo(0, 0, w, 0, radius);
  ctx.closePath();
}

/** Bake CSS clip-path polygon + positioned img into a frame-sized bitmap. */
export async function rasterizeClippedImage(
  src: string,
  frameWIn: number,
  frameHIn: number,
  polygon: { x: number; y: number }[],
  draw: { drawX: number; drawY: number; drawW: number; drawH: number },
  hostW: number,
  hostH: number,
): Promise<string | null> {
  const img = await loadImageElement(src);
  if (!img) return null;

  const boxW = Math.max(1, Math.round(inchToPx(frameWIn)));
  const boxH = Math.max(1, Math.round(inchToPx(frameHIn)));
  const refW = Math.max(1, hostW);
  const refH = Math.max(1, hostH);
  const scaleX = boxW / refW;
  const scaleY = boxH / refH;

  const canvas = document.createElement("canvas");
  canvas.width = boxW;
  canvas.height = boxH;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  ctx.beginPath();
  for (let i = 0; i < polygon.length; i++) {
    const px = polygon[i].x * boxW;
    const py = polygon[i].y * boxH;
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.closePath();
  ctx.clip();

  const dx = draw.drawX * scaleX;
  const dy = draw.drawY * scaleY;
  const dw = Math.max(1, draw.drawW * scaleX);
  const dh = Math.max(1, draw.drawH * scaleY);
  ctx.drawImage(img, dx, dy, dw, dh);

  try {
    return canvas.toDataURL("image/png");
  } catch {
    return null;
  }
}

/**
 * Bake overflow:hidden + border-radius host crop (parent or self) into a PNG
 * with transparent corners — PPTX pictures are rectangular frames.
 */
export async function rasterizeRoundedImage(
  src: string,
  frameWIn: number,
  frameHIn: number,
  borderRadius: string,
  draw: { drawX: number; drawY: number; drawW: number; drawH: number },
  hostW: number,
  hostH: number,
  sizing: ImageSizing = "stretch",
  objectPosition?: { x: number; y: number },
): Promise<string | null> {
  const img = await loadImageElement(src);
  if (!img) return null;

  const boxW = Math.max(1, Math.round(inchToPx(frameWIn)));
  const boxH = Math.max(1, Math.round(inchToPx(frameHIn)));
  const refW = Math.max(1, hostW);
  const refH = Math.max(1, hostH);
  const scaleX = boxW / refW;
  const scaleY = boxH / refH;
  const r = cornerRadiusPx(borderRadius, boxW, boxH);

  const canvas = document.createElement("canvas");
  canvas.width = boxW;
  canvas.height = boxH;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  ctx.beginPath();
  pathRoundedRect(ctx, boxW, boxH, r);
  ctx.clip();

  const dx = draw.drawX * scaleX;
  const dy = draw.drawY * scaleY;
  const dw = Math.max(1, draw.drawW * scaleX);
  const dh = Math.max(1, draw.drawH * scaleY);
  const posX = objectPosition?.x ?? 0.5;
  const posY = objectPosition?.y ?? 0.5;
  const fit = fitDrawRect(
    img.naturalWidth || dw,
    img.naturalHeight || dh,
    dw,
    dh,
    sizing,
    posX,
    posY,
  );
  ctx.drawImage(img, dx + fit.dx, dy + fit.dy, fit.dw, fit.dh);

  try {
    return canvas.toDataURL("image/png");
  } catch {
    return null;
  }
}
