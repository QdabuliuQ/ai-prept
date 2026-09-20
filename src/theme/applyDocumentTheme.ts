import type { Page } from "@/store/zustand/pptStore";
import { DEFAULT_PPT_THEME, THEME_PRESETS, toThemeToken } from "./presets";
import { deriveSurfaceTokens } from "./surface";
import type { ThemeToken } from "./types";

function normHex(input: string): string | null {
  const c = input.trim();
  const m3 = /^#?([0-9a-fA-F]{3})$/.exec(c);
  if (m3) {
    const h = m3[1];
    return `#${h[0]}${h[0]}${h[1]}${h[1]}${h[2]}${h[2]}`.toLowerCase();
  }
  const m6 = /^#?([0-9a-fA-F]{6})$/.exec(c);
  if (m6) return `#${m6[1].toLowerCase()}`;
  return null;
}

function parseRgb(color: string): { r: number; g: number; b: number } | null {
  const hex = normHex(color);
  if (hex) {
    const n = parseInt(hex.slice(1), 16);
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
  }
  const rgb = color.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
  if (rgb) {
    return { r: Number(rgb[1]), g: Number(rgb[2]), b: Number(rgb[3]) };
  }
  return null;
}

function colorDist(
  a: { r: number; g: number; b: number },
  b: { r: number; g: number; b: number },
): number {
  const dr = a.r - b.r;
  const dg = a.g - b.g;
  const db = a.b - b.b;
  return Math.sqrt(dr * dr + dg * dg + db * db);
}

function buildColorMap(from: ThemeToken, to: ThemeToken): Map<string, string> {
  const fs = deriveSurfaceTokens(from);
  const ts = deriveSurfaceTokens(to);
  const pairs: Array<[string, string]> = [
    [from.primary, to.primary],
    [from.secondary, to.secondary],
    [from.background, to.background],
    [from.textOnLight, to.textOnLight],
    [from.textOnDark, to.textOnDark],
    [fs.surface, ts.surface],
    [fs.surfaceAlt, ts.surfaceAlt],
    [fs.muted, ts.muted],
    [fs.border, ts.border],
    [fs.cardFill, ts.cardFill],
  ];

  const map = new Map<string, string>();
  for (const [a, b] of pairs) {
    const na = normHex(a);
    const nb = normHex(b);
    if (na && nb) map.set(na, nb);
  }
  return map;
}

function mapHexInString(value: string, map: Map<string, string>): string {
  let out = value.replace(/#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b/g, (m) => {
    const n = normHex(m);
    if (!n) return m;
    const next = map.get(n);
    return next || m;
  });

  out = out.replace(
    /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(\s*,\s*[\d.]+\s*)?\)/gi,
    (full, r, g, b, a) => {
      const key = normHex(
        `#${Number(r).toString(16).padStart(2, "0")}${Number(g)
          .toString(16)
          .padStart(2, "0")}${Number(b).toString(16).padStart(2, "0")}`,
      );
      if (!key) return full;
      const next = map.get(key);
      if (!next) return full;
      const rgb = parseRgb(next);
      if (!rgb) return full;
      if (a != null) return `rgba(${rgb.r},${rgb.g},${rgb.b}${a})`;
      return `rgb(${rgb.r},${rgb.g},${rgb.b})`;
    },
  );
  return out;
}

const SKIP_KEYS = new Set([
  "id",
  "src",
  "backgroundImage",
  "html",
  "remark",
  "type",
]);

function remapValue(value: unknown, map: Map<string, string>): unknown {
  if (typeof value === "string") return mapHexInString(value, map);
  if (Array.isArray(value)) return value.map((v) => remapValue(v, map));
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const next: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) {
      if (SKIP_KEYS.has(k)) {
        next[k] = v;
        continue;
      }
      next[k] = remapValue(v, map);
    }
    return next;
  }
  return value;
}

function touchPageBackground(page: Page, to: ThemeToken): Page {
  if (page.backgroundType === "image") {
    return {
      ...page,
      fgColor: to.secondary,
    };
  }
  if (page.backgroundType === "solidColor" || page.backgroundType === "texture") {
    return {
      ...page,
      background: to.background,
      bgColor: to.background,
      fgColor: to.secondary,
    };
  }
  return page;
}

/** 主题五色：主色 / 辅色 / 背景 / 浅底字 / 深底字 */
export function themeSwatchColors(theme: ThemeToken): string[] {
  return [
    theme.primary,
    theme.secondary,
    theme.background,
    theme.textOnLight,
    theme.textOnDark,
  ];
}

/** 从页面背景推断最接近的预设主题（HTML 页不再扫 JSON 元素） */
export function inferThemeFromPages(pages: Page[]): ThemeToken {
  let bgSample: string | null = null;
  for (const page of pages) {
    if (page.backgroundType === "solidColor" && page.background) {
      bgSample = page.background;
      break;
    }
  }
  if (!bgSample) return toThemeToken(DEFAULT_PPT_THEME);
  const b = parseRgb(bgSample);
  if (!b) return toThemeToken(DEFAULT_PPT_THEME);

  let best = THEME_PRESETS[0];
  let bestScore = Number.POSITIVE_INFINITY;
  for (const preset of THEME_PRESETS) {
    const bb = parseRgb(preset.background);
    if (!bb) continue;
    const score = colorDist(b, bb);
    if (score < bestScore) {
      bestScore = score;
      best = preset;
    }
  }
  return toThemeToken(best);
}

/**
 * 将文档页面从 prevTheme 换到 nextTheme（页面背景色映射；不改 HTML 正文）
 */
export function applyDocumentTheme(
  pages: Page[],
  nextTheme: ThemeToken,
  prevTheme?: ThemeToken | null,
): Page[] {
  const from = prevTheme || inferThemeFromPages(pages);
  const map = buildColorMap(from, nextTheme);

  return pages.map((page) => {
    let next = remapValue(page, map) as Page;
    next = touchPageBackground(next, nextTheme);
    return next;
  });
}
