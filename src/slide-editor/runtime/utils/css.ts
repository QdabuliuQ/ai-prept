/**
 * CSS utility functions (minimal)
 */

export function rgbToHex(rgb: string): string {
  if (rgb.startsWith("#")) return rgb;

  const match = rgb.match(
    /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*[\d.]+)?\)/,
  );
  if (!match) return rgb;

  const toHex = (n: number) => {
    const hex = n.toString(16);
    return hex.length === 1 ? "0" + hex : hex;
  };

  return `#${toHex(parseInt(match[1], 10))}${toHex(parseInt(match[2], 10))}${toHex(parseInt(match[3], 10))}`;
}

export function normalizeColor(color: string): string {
  if (!color || color === "transparent" || color === "none") {
    return "#000000";
  }
  if (color.startsWith("rgb")) {
    return rgbToHex(color);
  }
  return color;
}

export function normalizeTextAlign(textAlign: string): string {
  if (textAlign === "start") return "left";
  if (textAlign === "end") return "right";
  if (["left", "center", "right", "justify"].includes(textAlign)) {
    return textAlign;
  }
  return "left";
}
