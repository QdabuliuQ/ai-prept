/**
 * Map CSS font-weight → pptxgen fontFace + bold.
 * PPT only has boolean bold; keep the CSS family name and set bold for
 * Medium+ (500+) so export isn't thinner than the browser preview.
 *
 * Do NOT remap to "PingFang SC Bold" etc. — many PPT hosts don't resolve
 * those PostScript/style names and then render Regular with bold=false.
 */

export type ResolvedTypeface = {
  fontFace: string;
  bold: boolean;
};

/** CSS font-weight → numeric 100–900. */
export function resolveFontWeight(fontWeight: string): number {
  const w = (fontWeight || "").trim().toLowerCase();
  if (!w) return 400;
  if (w === "bold" || w === "bolder") return 700;
  if (w === "normal" || w === "lighter") return 400;
  const n = Number.parseInt(w, 10);
  return Number.isFinite(n) ? n : 400;
}

function primaryFontFamily(fontFamily: string): string {
  return (
    (fontFamily || "sans-serif")
      .split(",")[0]
      ?.replace(/["']/g, "")
      .trim() || "sans-serif"
  );
}

/**
 * Resolve CSS family + weight for pptxgen.
 * weight ≥ 500 → bold (captures Medium that browsers show as heavier).
 */
export function resolveTypeface(
  fontFamily: string,
  fontWeight: string,
): ResolvedTypeface {
  const fontFace = primaryFontFamily(fontFamily);
  const weight = resolveFontWeight(fontWeight);
  return { fontFace, bold: weight >= 500 };
}
