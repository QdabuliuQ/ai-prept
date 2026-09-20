/**
 * CSS linear-gradient → PNG data URL (pptxgen has no native gradient fill).
 */

import { parsePx } from "./dom";
import { parseRgba, type Rgba } from "./color";

export type GradientStop = Rgba & { offset: number };

export type ParsedLinearGradient = {
  /** CSS degrees: 0 = to top, 90 = to right. */
  angleDeg: number;
  stops: GradientStop[];
};

function parseHexColor(token: string): Rgba | null {
  const m = token.trim().match(/^#([0-9a-fA-F]{3,8})$/);
  if (!m) return null;
  let h = m[1];
  if (h.length === 3) {
    h = h
      .split("")
      .map((c) => c + c)
      .join("");
  }
  if (h.length === 6) {
    return {
      r: Number.parseInt(h.slice(0, 2), 16),
      g: Number.parseInt(h.slice(2, 4), 16),
      b: Number.parseInt(h.slice(4, 6), 16),
      a: 1,
    };
  }
  if (h.length === 8) {
    return {
      r: Number.parseInt(h.slice(0, 2), 16),
      g: Number.parseInt(h.slice(2, 4), 16),
      b: Number.parseInt(h.slice(4, 6), 16),
      a: Number.parseInt(h.slice(6, 8), 16) / 255,
    };
  }
  return null;
}

function parseColorToken(token: string): Rgba | null {
  const t = token.trim();
  if (!t || /^transparent$/i.test(t)) return { r: 0, g: 0, b: 0, a: 0 };
  return parseRgba(t) || parseHexColor(t);
}

/** Extract balanced `(...)` body after `linear-gradient`. */
function extractLinearGradientBody(css: string): string | null {
  const idx = css.search(/linear-gradient\s*\(/i);
  if (idx < 0) return null;
  const start = css.indexOf("(", idx);
  if (start < 0) return null;
  let depth = 0;
  for (let i = start; i < css.length; i++) {
    const ch = css[i];
    if (ch === "(") depth += 1;
    else if (ch === ")") {
      depth -= 1;
      if (depth === 0) return css.slice(start + 1, i);
    }
  }
  return null;
}

function parseDirectionAngle(head: string): number | null {
  const t = head.trim().toLowerCase();
  if (!t) return null;
  const deg = t.match(/^(-?[\d.]+)(deg|rad|turn|grad)$/);
  if (deg) {
    const n = Number(deg[1]);
    if (!Number.isFinite(n)) return null;
    const unit = deg[2];
    if (unit === "rad") return (n * 180) / Math.PI;
    if (unit === "turn") return n * 360;
    if (unit === "grad") return n * 0.9;
    return n;
  }
  if (!t.startsWith("to ")) return null;
  const parts = new Set(t.slice(3).trim().split(/\s+/));
  // Corners: average of the two axes
  const top = parts.has("top");
  const bottom = parts.has("bottom");
  const left = parts.has("left");
  const right = parts.has("right");
  if (top && right) return 45;
  if (bottom && right) return 135;
  if (bottom && left) return 225;
  if (top && left) return 315;
  if (right) return 90;
  if (bottom) return 180;
  if (left) return 270;
  if (top) return 0;
  return null;
}

/**
 * Split top-level comma-separated gradient args (ignore commas inside rgba()).
 */
function splitGradientArgs(body: string): string[] {
  const out: string[] = [];
  let cur = "";
  let depth = 0;
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (ch === "(") depth += 1;
    else if (ch === ")") depth = Math.max(0, depth - 1);
    if (ch === "," && depth === 0) {
      if (cur.trim()) out.push(cur.trim());
      cur = "";
      continue;
    }
    cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

function parseStop(arg: string): { color: Rgba; offset?: number } | null {
  const m = arg
    .trim()
    .match(
      /^(rgba?\([^)]+\)|hsla?\([^)]+\)|#[0-9a-fA-F]{3,8}|transparent)(?:\s+(-?[\d.]+%?))?$/i,
    );
  if (!m) return null;
  const color = parseColorToken(m[1]);
  if (!color) return null;
  let offset: number | undefined;
  if (m[2] != null) {
    const raw = m[2];
    offset = raw.endsWith("%")
      ? Number.parseFloat(raw) / 100
      : Number.parseFloat(raw);
    if (!Number.isFinite(offset)) offset = undefined;
    else offset = Math.max(0, Math.min(1, offset));
  }
  return { color, offset };
}

export function parseLinearGradient(css: string): ParsedLinearGradient | null {
  const body = extractLinearGradientBody(css || "");
  if (!body) return null;
  const args = splitGradientArgs(body);
  if (!args.length) return null;

  let angleDeg = 180; // CSS default: to bottom
  let start = 0;
  const dir = parseDirectionAngle(args[0]);
  if (dir != null) {
    angleDeg = dir;
    start = 1;
  }

  const parsed: Array<{ color: Rgba; offset?: number }> = [];
  for (let i = start; i < args.length; i++) {
    const stop = parseStop(args[i]);
    if (stop) parsed.push(stop);
  }
  if (parsed.length < 1) return null;

  // Assign missing offsets (CSS-like even distribution of gaps)
  const stops: GradientStop[] = parsed.map((p, i) => ({
    ...p.color,
    offset:
      p.offset != null
        ? p.offset
        : parsed.length === 1
          ? 0
          : i / (parsed.length - 1),
  }));
  // Ensure monotonic offsets
  for (let i = 1; i < stops.length; i++) {
    if (stops[i].offset < stops[i - 1].offset) {
      stops[i].offset = stops[i - 1].offset;
    }
  }
  return { angleDeg, stops };
}

function cssAngleToLine(
  angleDeg: number,
  w: number,
  h: number,
): { x0: number; y0: number; x1: number; y1: number } {
  // CSS: 0deg = up, 90deg = right
  const rad = (angleDeg * Math.PI) / 180;
  const dx = Math.sin(rad);
  const dy = -Math.cos(rad);
  const half = (Math.abs(w * dx) + Math.abs(h * dy)) / 2;
  const cx = w / 2;
  const cy = h / 2;
  return {
    x0: cx - dx * half,
    y0: cy - dy * half,
    x1: cx + dx * half,
    y1: cy + dy * half,
  };
}

function cornerRadiusPx(
  borderRadius: string,
  w: number,
  h: number,
): number {
  const br = (borderRadius || "").trim();
  if (!br || br === "0px") return 0;
  const first = br.split(/\s+/)[0] || "";
  if (first.includes("%")) {
    const pct = Number.parseFloat(first);
    if (!Number.isFinite(pct) || pct <= 0) return 0;
    return Math.min(w, h) * Math.min(1, pct / 100);
  }
  const px = parsePx(first);
  if (px <= 0) return 0;
  return Math.min(px, w / 2, h / 2);
}

/**
 * Rasterize a CSS `linear-gradient(...)` (optionally clipped to border-radius)
 * into a PNG data URL sized to the layout box.
 */
export function rasterizeLinearGradientBackground(
  backgroundImage: string,
  widthPx: number,
  heightPx: number,
  opts: {
    doc: Document;
    borderRadius?: string;
    opacity?: number;
  },
): string | null {
  const parsed = parseLinearGradient(backgroundImage);
  if (!parsed) return null;

  const w = Math.max(1, Math.ceil(widthPx));
  const h = Math.max(1, Math.ceil(heightPx));
  const canvas = opts.doc.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  const opacity =
    Number.isFinite(opts.opacity) && opts.opacity != null
      ? Math.max(0, Math.min(1, opts.opacity))
      : 1;
  ctx.clearRect(0, 0, w, h);
  ctx.globalAlpha = opacity;

  const r = cornerRadiusPx(opts.borderRadius || "", w, h);
  if (r > 0.5) {
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
      ctx.roundRect(0, 0, w, h, r);
    } else {
      // Fallback arc path
      const rr = Math.min(r, w / 2, h / 2);
      ctx.moveTo(rr, 0);
      ctx.arcTo(w, 0, w, h, rr);
      ctx.arcTo(w, h, 0, h, rr);
      ctx.arcTo(0, h, 0, 0, rr);
      ctx.arcTo(0, 0, w, 0, rr);
      ctx.closePath();
    }
    ctx.clip();
  }

  const { x0, y0, x1, y1 } = cssAngleToLine(parsed.angleDeg, w, h);
  const grad = ctx.createLinearGradient(x0, y0, x1, y1);
  for (const stop of parsed.stops) {
    grad.addColorStop(
      stop.offset,
      `rgba(${stop.r}, ${stop.g}, ${stop.b}, ${stop.a})`,
    );
  }
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, w, h);

  try {
    return canvas.toDataURL("image/png");
  } catch {
    return null;
  }
}

export function isCssLinearGradient(backgroundImage: string): boolean {
  return /linear-gradient\s*\(/i.test(backgroundImage || "");
}
