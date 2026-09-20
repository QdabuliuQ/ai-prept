/** Canvas & slide geometry (CSS px @ 96 DPI). */

export const HTML_DPI = 96;

export type SlideConfig = {
  htmlWidth: number;
  htmlHeight: number;
  slideWidthIn: number;
  slideHeightIn: number;
};

/** html-slide default: 1920×1080 → 20 × 11.25 in */
export const DEFAULT_CONFIG: SlideConfig = {
  htmlWidth: 1920,
  htmlHeight: 1080,
  slideWidthIn: 1920 / HTML_DPI,
  slideHeightIn: 1080 / HTML_DPI,
};

export function pxToInch(px: number, dpi = HTML_DPI): number {
  return px / dpi;
}

export function inchToPx(inch: number, dpi = HTML_DPI): number {
  return inch * dpi;
}
