import { inchToPx } from "../config";

function loadImageElement(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
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
