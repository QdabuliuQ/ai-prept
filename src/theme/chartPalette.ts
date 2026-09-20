import type { ThemeToken } from "./types";

function parseHex(hex: string): { r: number; g: number; b: number } | null {
  const h = hex.replace("#", "").trim();
  const full =
    h.length === 3
      ? h
          .split("")
          .map((c) => c + c)
          .join("")
      : h;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return null;
  const n = parseInt(full, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function mixHex(a: string, b: string, amount: number): string {
  const pa = parseHex(a);
  const pb = parseHex(b);
  if (!pa || !pb) return a;
  const t = Math.min(1, Math.max(0, amount));
  const r = Math.round(pa.r + (pb.r - pa.r) * t);
  const g = Math.round(pa.g + (pb.g - pa.g) * t);
  const bl = Math.round(pa.b + (pb.b - pa.b) * t);
  return `#${[r, g, bl].map((n) => n.toString(16).padStart(2, "0")).join("")}`;
}

/** 图表系列色：由主题派生 */
export function themeChartPalette(theme: ThemeToken): string[] {
  const { primary, secondary } = theme;
  return [
    primary,
    secondary,
    mixHex(primary, secondary, 0.35),
    mixHex(secondary, "#FFFFFF", 0.28),
    mixHex(primary, "#FFFFFF", 0.4),
    mixHex(secondary, primary, 0.55),
    mixHex(primary, theme.textOnLight || "#1A1A1A", 0.25),
  ];
}
