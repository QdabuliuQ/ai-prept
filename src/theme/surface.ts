import { contrastRatio } from "./contrast";
import type { ThemeToken } from "./types";

export type SurfaceTokens = {
  surface: string;
  surfaceAlt: string;
  muted: string;
  border: string;
  cardFill: string;
};

function parseHex(hex: string): { r: number; g: number; b: number } | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function to2(n: number): string {
  return n.toString(16).padStart(2, "0");
}

function mixToward(hex: string, toward: string, amount: number): string {
  const a = parseHex(hex);
  const b = parseHex(toward);
  if (!a || !b) return toward;
  const t = Math.min(1, Math.max(0, amount));
  const r = Math.round(a.r + (b.r - a.r) * t);
  const g = Math.round(a.g + (b.g - a.g) * t);
  const bl = Math.round(a.b + (b.b - a.b) * t);
  return `#${to2(r)}${to2(g)}${to2(bl)}`;
}

/** 从主题派生表面色 */
export function deriveSurfaceTokens(theme: ThemeToken): SurfaceTokens {
  const surface = theme.background || "#F7F8FA";
  const surfaceAlt = mixToward(theme.secondary, "#FFFFFF", 0.9) || "#FFFFFF";
  const muted = mixToward(theme.textOnLight, surface, 0.55) || "#6B7280";
  const border =
    contrastRatio(theme.secondary, surface) >= 1.4
      ? mixToward(theme.secondary, surface, 0.35)
      : "#D0D7DE";
  const cardFill = "#FFFFFF";
  return { surface, surfaceAlt, muted, border, cardFill };
}
