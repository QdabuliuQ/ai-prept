import { inchToPx } from "./config";
import { rasterizeClippedImage, rasterizeRoundedImage } from "./lib/clip";
import { rasterizeSvgMarkup } from "./lib/svg";
import type { ImageNode, ImageSizing, SlideNode } from "./types";

async function toDataUrl(src: string): Promise<string | null> {
  if (!src) return null;
  if (src.startsWith("data:")) return src;
  try {
    const res = await fetch(src, { mode: "cors", credentials: "omit" });
    if (!res.ok) return null;
    const blob = await res.blob();
    return await new Promise<string | null>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || null));
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(blob);
    });
  } catch {
    // fallback: draw via Image (may taint)
    try {
      return await loadImageDataUrl(src);
    } catch {
      return null;
    }
  }
}

function loadImageElement(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

async function loadImageDataUrl(src: string): Promise<string | null> {
  const img = await loadImageElement(src);
  if (!img) return null;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth || 1;
    canvas.height = img.naturalHeight || 1;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(img, 0, 0);
    return canvas.toDataURL("image/png");
  } catch {
    return null;
  }
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
    // contain
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

/**
 * Bake CSS object-fit into a bitmap matching the PPT frame.
 * Avoids stretch distortion when the source aspect ≠ the element box.
 */
async function rasterizeFitted(
  src: string,
  boxWIn: number,
  boxHIn: number,
  sizing: ImageSizing,
  objectPosition?: { x: number; y: number },
): Promise<string | null> {
  const img = await loadImageElement(src);
  if (!img || !img.naturalWidth || !img.naturalHeight) return null;

  const boxW = Math.max(1, Math.round(inchToPx(boxWIn)));
  const boxH = Math.max(1, Math.round(inchToPx(boxHIn)));
  const canvas = document.createElement("canvas");
  canvas.width = boxW;
  canvas.height = boxH;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  const posX = objectPosition?.x ?? 0.5;
  const posY = objectPosition?.y ?? 0.5;
  const { dx, dy, dw, dh } = fitDrawRect(
    img.naturalWidth,
    img.naturalHeight,
    boxW,
    boxH,
    sizing,
    posX,
    posY,
  );
  ctx.clearRect(0, 0, boxW, boxH);
  ctx.drawImage(img, dx, dy, dw, dh);
  try {
    return canvas.toDataURL("image/png");
  } catch {
    return null;
  }
}

/** Fetch/rasterize image nodes to data URLs for pptxgenjs. */
export async function materializeImages(nodes: SlideNode[]): Promise<SlideNode[]> {
  const out: SlideNode[] = [];
  for (const node of nodes) {
    if (node.kind !== "image") {
      out.push(node);
      continue;
    }
    const img = node as ImageNode;
    const sizing = img.sizing || "stretch";

    if (img.svgMarkup) {
      const wPx = Math.max(1, inchToPx(img.w));
      const hPx = Math.max(1, inchToPx(img.h));
      const dataUrl = await rasterizeSvgMarkup(img.svgMarkup, wPx, hPx, {
        localW: img.svgLocalW,
        localH: img.svgLocalH,
        matrix: img.svgMatrix,
      });
      if (!dataUrl) continue;
      out.push({
        ...img,
        dataUrl,
        src: dataUrl,
        svgMarkup: undefined,
        svgMatrix: undefined,
        svgLocalW: undefined,
        svgLocalH: undefined,
        // Transform already baked into pixels
        rotate: img.svgMatrix ? undefined : img.rotate,
        sizing: "stretch",
        intrinsicSize: {
          width: Math.max(1, Math.round(wPx)),
          height: Math.max(1, Math.round(hPx)),
        },
      });
      continue;
    }

    if (img.clipPolygon?.length && img.clipDraw && img.clipHostPx) {
      const dataUrl = await rasterizeClippedImage(
        img.src,
        img.w,
        img.h,
        img.clipPolygon,
        img.clipDraw,
        img.clipHostPx.w,
        img.clipHostPx.h,
      );
      if (!dataUrl) continue;
      const wPx = Math.max(1, Math.round(inchToPx(img.w)));
      const hPx = Math.max(1, Math.round(inchToPx(img.h)));
      out.push({
        ...img,
        dataUrl,
        src: dataUrl,
        sizing: "stretch",
        rotate: undefined,
        clipPolygon: undefined,
        clipDraw: undefined,
        clipHostPx: undefined,
        intrinsicSize: { width: wPx, height: hPx },
      });
      continue;
    }

    if (img.roundClipCss && img.clipDraw && img.clipHostPx) {
      const dataUrl = await rasterizeRoundedImage(
        img.src,
        img.w,
        img.h,
        img.roundClipCss,
        img.clipDraw,
        img.clipHostPx.w,
        img.clipHostPx.h,
        sizing,
        img.objectPosition,
      );
      if (!dataUrl) continue;
      const wPx = Math.max(1, Math.round(inchToPx(img.w)));
      const hPx = Math.max(1, Math.round(inchToPx(img.h)));
      out.push({
        ...img,
        dataUrl,
        src: dataUrl,
        sizing: "stretch",
        rotate: undefined,
        roundClipCss: undefined,
        clipDraw: undefined,
        clipHostPx: undefined,
        intrinsicSize: { width: wPx, height: hPx },
      });
      continue;
    }

    // Already baked (e.g. CSS gradient → PNG) — keep as-is.
    if (img.dataUrl?.startsWith("data:") && sizing === "stretch") {
      out.push(img);
      continue;
    }

    if (sizing === "cover" || sizing === "contain") {
      const fitted = await rasterizeFitted(
        img.src,
        img.w,
        img.h,
        sizing,
        img.objectPosition,
      );
      if (fitted) {
        // Already cropped/letterboxed to the frame — stretch into the box is correct.
        out.push({
          ...img,
          dataUrl: fitted,
          sizing: "stretch",
          intrinsicSize: {
            width: Math.max(1, Math.round(inchToPx(img.w))),
            height: Math.max(1, Math.round(inchToPx(img.h))),
          },
        });
        continue;
      }
    }

    const dataUrl = await toDataUrl(img.src);
    if (!dataUrl) continue;

    let intrinsicSize = img.intrinsicSize;
    if (
      (sizing === "cover" || sizing === "contain") &&
      (!intrinsicSize || !intrinsicSize.width || !intrinsicSize.height)
    ) {
      const loaded = await loadImageElement(dataUrl);
      if (loaded?.naturalWidth && loaded.naturalHeight) {
        intrinsicSize = {
          width: loaded.naturalWidth,
          height: loaded.naturalHeight,
        };
      }
    }

    out.push({ ...img, dataUrl, intrinsicSize });
  }
  return out;
}
