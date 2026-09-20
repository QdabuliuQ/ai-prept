/** Color helpers for CSS → pptxgen hex. */

import { computedStyle } from "./dom";

export type Rgb = { r: number; g: number; b: number };
export type Rgba = Rgb & { a: number };

/** Preserve CSS alpha when exporting text colors to pptxgenjs. */
export function textColor(
  color: string | undefined | null,
  opacity = 1
): { color: string; transparency?: number } {
  if ((color || "").trim().toLowerCase() === "transparent") {
    return { color: "000000", transparency: 100 };
  }
  const rgba = color ? parseRgba(color) : null;
  if (rgba) {
    const alpha = Math.max(0, Math.min(1, rgba.a * opacity));
    return {
      color: rgbToHexBytes(rgba),
      transparency: alpha < 0.999 ? Math.round((1 - alpha) * 100) : undefined,
    };
  }
  return { color: rgbToHex(color) || "000000" };
}

export function parseRgba(color: string): Rgba | null {
  const trimmed = color.trim();
  // Legacy: rgb(255, 255, 255) / rgba(255, 255, 255, 0.55)
  const comma = trimmed.match(
    /rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)/i
  );
  if (comma) {
    return {
      r: Number(comma[1]),
      g: Number(comma[2]),
      b: Number(comma[3]),
      a: comma[4] != null ? Number(comma[4]) : 1,
    };
  }
  // Modern: rgb(255 255 255 / 0.55)
  const space = trimmed.match(
    /rgba?\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+%?))?\s*\)/i
  );
  if (space) {
    let a = 1;
    if (space[4] != null) {
      a = space[4].endsWith("%")
        ? Number.parseFloat(space[4]) / 100
        : Number(space[4]);
    }
    return { r: Number(space[1]), g: Number(space[2]), b: Number(space[3]), a };
  }
  return null;
}

function clampByte(n: number): number {
  return Math.max(0, Math.min(255, Math.round(n)));
}

export function rgbToHex(color: string | undefined | null): string | undefined {
  if (!color) return undefined;
  const trimmed = color.trim();
  if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(trimmed)) {
    const h = trimmed.slice(1);
    if (h.length === 3) {
      return h
        .split("")
        .map((c) => c + c)
        .join("")
        .toUpperCase();
    }
    return h.toUpperCase();
  }
  const rgba = parseRgba(trimmed);
  if (!rgba || rgba.a < 0.02) return undefined;
  // Semi-transparent without a backdrop: report the RGB only (caller may composite)
  return [rgba.r, rgba.g, rgba.b]
    .map((x) => clampByte(x).toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase();
}

export function hexToRgb(hex: string): Rgb | null {
  const h = hex.replace("#", "").trim();
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
  return {
    r: Number.parseInt(h.slice(0, 2), 16),
    g: Number.parseInt(h.slice(2, 4), 16),
    b: Number.parseInt(h.slice(4, 6), 16),
  };
}

/** Porter-Duff "source over" — match CSS alpha over an opaque backdrop. */
export function compositeOver(fg: Rgba, bg: Rgb): Rgb {
  const a = Math.max(0, Math.min(1, fg.a));
  return {
    r: clampByte(fg.r * a + bg.r * (1 - a)),
    g: clampByte(fg.g * a + bg.g * (1 - a)),
    b: clampByte(fg.b * a + bg.b * (1 - a)),
  };
}

export function rgbToHexBytes(rgb: Rgb): string {
  return [rgb.r, rgb.g, rgb.b]
    .map((x) => clampByte(x).toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase();
}

/**
 * CSS background → PPT solid fill.
 * Keep alpha as pptxgen `transparency` (0=opaque … 100=invisible) so washes /
 * overlays match HTML. Pass `backdrop` only when you explicitly want to bake.
 */
export function solidFill(
  color: string | undefined | null,
  backdrop?: Rgb | null
): {
  type: "solid";
  color: string;
  transparency?: number;
} | null {
  if (!color) return null;
  const rgba = parseRgba(color);
  if (rgba) {
    if (rgba.a < 0.02) return null;
    if (rgba.a < 0.999 && backdrop) {
      return {
        type: "solid",
        color: rgbToHexBytes(compositeOver(rgba, backdrop)),
      };
    }
    const hex = rgbToHexBytes(rgba);
    const transparency =
      rgba.a < 0.999 ? Math.round((1 - rgba.a) * 100) : undefined;
    return { type: "solid", color: hex, transparency };
  }
  const hex = rgbToHex(color);
  if (!hex) return null;
  return { type: "solid", color: hex };
}

/**
 * CSS linear-/radial-gradient → first opaque-enough stop as a solid fill.
 * pptxgen has no native CSS gradient; missing washes (title backdrops, pills)
 * is worse than a flat approximation of the dominant stop.
 */
export function gradientApproxFill(
  backgroundImage: string | undefined | null
): {
  type: "solid";
  color: string;
  transparency?: number;
} | null {
  const raw = (backgroundImage || "").trim();
  if (!raw || raw === "none") return null;
  if (!/gradient\s*\(/i.test(raw)) return null;

  const tokens = [
    ...raw.matchAll(
      /rgba?\(\s*[^)]+\)|hsla?\(\s*[^)]+\)|#[0-9a-fA-F]{3,8}\b/gi
    ),
  ];
  for (const m of tokens) {
    const token = m[0];
    // 8-digit hex: fold alpha into solidFill via rgba
    const hex8 = token.match(/^#([0-9a-fA-F]{8})$/);
    if (hex8) {
      const h = hex8[1];
      const r = Number.parseInt(h.slice(0, 2), 16);
      const g = Number.parseInt(h.slice(2, 4), 16);
      const b = Number.parseInt(h.slice(4, 6), 16);
      const a = Number.parseInt(h.slice(6, 8), 16) / 255;
      const fill = solidFill(`rgba(${r}, ${g}, ${b}, ${a})`);
      if (fill && (fill.transparency ?? 0) < 90) return fill;
      continue;
    }
    const fill = solidFill(token);
    if (fill && (fill.transparency ?? 0) < 90) return fill;
  }
  return null;
}

/** Prefer solid background-color; fall back to a gradient stop approximation. */
export function resolveBackgroundFill(
  styles: CSSStyleDeclaration,
  backdrop?: Rgb | null
): {
  type: "solid";
  color: string;
  transparency?: number;
} | null {
  return (
    solidFill(styles.backgroundColor, backdrop) ||
    gradientApproxFill(styles.backgroundImage)
  );
}

/** Fold CSS `opacity` into fill transparency (multiplicative with rgba alpha). */
export function applyElementOpacity(
  fill: { type: "solid"; color: string; transparency?: number } | null,
  opacity: number
): { type: "solid"; color: string; transparency?: number } | null {
  if (!fill) return null;
  const o = Number.isFinite(opacity) ? Math.max(0, Math.min(1, opacity)) : 1;
  if (o >= 0.999) return fill;
  if (o < 0.02) return null;
  const baseAlpha = fill.transparency != null ? 1 - fill.transparency / 100 : 1;
  const alpha = baseAlpha * o;
  if (alpha < 0.02) return null;
  return {
    type: "solid",
    color: fill.color,
    transparency: Math.round((1 - alpha) * 100),
  };
}

export function isTransparent(color: string | undefined | null): boolean {
  if (!color) return true;
  const c = color.trim().toLowerCase();
  if (c === "transparent" || c === "rgba(0, 0, 0, 0)") return true;
  const rgba = parseRgba(color);
  return !!rgba && rgba.a < 0.02;
}

/** Nearest opaque ancestor background (or slide root), for alpha compositing. */
export function resolveOpaqueBackdrop(
  el: Element,
  slideRoot: HTMLElement
): Rgb {
  let node: Element | null = el.parentElement;
  while (node) {
    const raw = computedStyle(node).backgroundColor;
    const rgba = parseRgba(raw);
    if (rgba && rgba.a >= 0.98) {
      return { r: rgba.r, g: rgba.g, b: rgba.b };
    }
    if (node === slideRoot) break;
    node = node.parentElement;
  }
  const rootRaw = computedStyle(slideRoot).backgroundColor;
  const root = parseRgba(rootRaw);
  if (root && root.a >= 0.02) {
    if (root.a >= 0.98) return { r: root.r, g: root.g, b: root.b };
    // Semi-transparent root: composite over white (last resort)
    return compositeOver(root, { r: 255, g: 255, b: 255 });
  }
  const body = slideRoot.ownerDocument?.body;
  if (body) {
    const bodyRgba = parseRgba(computedStyle(body).backgroundColor);
    if (bodyRgba && bodyRgba.a >= 0.98) {
      return { r: bodyRgba.r, g: bodyRgba.g, b: bodyRgba.b };
    }
  }
  return { r: 255, g: 255, b: 255 };
}
