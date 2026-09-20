import {
  parsePx,
  computedStyle,
  effectiveRotateDeg,
  layoutBoxRelativeTo,
  combinedCssLinear,
  isIdentityLinear,
  boxRelativeTo,
  findClipPathHost,
  imageDrawInClipHost,
  isHTMLElement,
} from "../lib/dom";
import {
  applyElementOpacity,
  parseRgba,
  resolveBackgroundFill,
  rgbToHex,
  rgbToHexBytes,
  solidFill,
} from "../lib/color";
import {
  isCssLinearGradient,
  rasterizeLinearGradientBackground,
} from "../lib/gradient";
import { serializeSvg, svgStrokePadPx } from "../lib/svg";
import { pxToInch } from "../config";
import type {
  BorderLineNode,
  DomSnapshot,
  ImageNode,
  Line,
  ShapeNode,
  Shadow,
} from "../types";

function mapDash(style: string): Line["dashType"] {
  const s = (style || "").toLowerCase();
  if (s === "dashed") return "dash";
  if (s === "dotted") return "sysDot";
  return "solid";
}

function parseShadow(boxShadow: string): Shadow | undefined {
  if (!boxShadow || boxShadow === "none") return undefined;
  // rough: color + offsets + blur
  const colorMatch = boxShadow.match(/rgba?\([^)]+\)|#[0-9a-fA-F]{3,8}/);
  const nums = [...boxShadow.matchAll(/-?[\d.]+px/g)].map((m) => parsePx(m[0]));
  if (!nums.length) return undefined;
  const color = rgbToHex(colorMatch?.[0] || "#000000") || "000000";
  const offsetX = nums[0] ?? 0;
  const offsetY = nums[1] ?? 0;
  const blur = nums[2] ?? 0;
  const offset = Math.hypot(offsetX, offsetY);
  const angle =
    offset < 0.01 ? 0 : (Math.atan2(offsetY, offsetX) * 180) / Math.PI;
  const rgba = colorMatch?.[0] ? parseRgba(colorMatch[0]) : null;
  return {
    color,
    blurPt: blur * 0.75,
    offsetPt: offset * 0.75,
    angle,
    opacity: rgba && rgba.a < 0.999 ? rgba.a : 0.35,
  };
}

function radiusRatio(borderRadius: string, h: number): number | undefined {
  const br = (borderRadius || "").trim();
  if (!br || br === "0px") return undefined;
  // Percentage radii (e.g. 50%) — used value may stay as % in some engines
  if (br.includes("%")) {
    const pct = Number.parseFloat(br);
    if (!Number.isFinite(pct) || pct <= 0) return undefined;
    return Math.min(1, pct / 100);
  }
  const n = parsePx(br);
  if (!Number.isFinite(n) || n <= 0 || h <= 0) return undefined;
  return Math.min(1, n / h);
}

function shapeName(
  borderRadius: string,
  ratio: number | undefined,
  box: { w: number; h: number },
): "rect" | "roundRect" | "ellipse" {
  const br = (borderRadius || "").toLowerCase();
  if (br === "50%" || br === "100%") return "ellipse";
  if (ratio != null && ratio >= 0.49) {
    const r = box.w / Math.max(box.h, 1);
    if (r > 0.85 && r < 1.15) return "ellipse";
  }
  if (ratio != null && ratio > 0) return "roundRect";
  return "rect";
}

function sideWidth(styles: CSSStyleDeclaration, side: "Top" | "Right" | "Bottom" | "Left") {
  return parsePx(styles[`border${side}Width` as keyof CSSStyleDeclaration] as string);
}

function sideStyle(styles: CSSStyleDeclaration, side: "Top" | "Right" | "Bottom" | "Left") {
  return String(styles[`border${side}Style` as keyof CSSStyleDeclaration] || "none");
}

type SidePaint = {
  color: string;
  transparency?: number;
  width: number;
  alpha: number;
};

/** Border paint with alpha preserved (rgbToHex alone drops alpha → solid black frames). */
function sidePaint(
  styles: CSSStyleDeclaration,
  side: "Top" | "Right" | "Bottom" | "Left",
): SidePaint | null {
  const width = sideWidth(styles, side);
  const styleName = sideStyle(styles, side);
  if (width <= 0 || styleName === "none") return null;
  const raw = String(
    styles[`border${side}Color` as keyof CSSStyleDeclaration] || "",
  ).trim();
  const rgba = parseRgba(raw);
  if (rgba) {
    if (rgba.a < 0.04) return null;
    return {
      color: rgbToHexBytes(rgba),
      transparency: rgba.a < 0.999 ? Math.round((1 - rgba.a) * 100) : undefined,
      width,
      alpha: rgba.a,
    };
  }
  const hex = rgbToHex(raw);
  if (!hex) return null;
  return { color: hex, width, alpha: 1 };
}

/**
 * Classic CSS triangle: one opaque border + transparent wedges.
 * Exporting as borderLine rects yields “line + square” arrowheads.
 */
function detectCssBorderTriangle(
  paints: Record<"top" | "right" | "bottom" | "left", SidePaint | null>,
  box: { w: number; h: number },
): { color: string; rotate: number } | null {
  const opaque = (["top", "right", "bottom", "left"] as const).filter(
    (s) => paints[s] && paints[s]!.alpha >= 0.2,
  );
  if (opaque.length !== 1) return null;
  const solid = opaque[0];
  const solidPaint = paints[solid]!;

  const pair: Array<"top" | "right" | "bottom" | "left"> =
    solid === "left" || solid === "right"
      ? ["top", "bottom"]
      : ["left", "right"];
  const wedgesOk = pair.every((s) => {
    const p = paints[s];
    if (!p) return true;
    return p.alpha < 0.15 && Math.abs(p.width - solidPaint.width) < 2;
  });
  if (!wedgesOk) return null;

  const maxBorder = Math.max(
    paints.top?.width || 0,
    paints.right?.width || 0,
    paints.bottom?.width || 0,
    paints.left?.width || 0,
  );
  if (maxBorder < 2) return null;
  if (box.w > maxBorder * 4 && box.h > maxBorder * 4) return null;

  // pptxgen triangle points UP; rotate to match CSS tip direction
  const rotate =
    solid === "left" ? 90 : solid === "right" ? 270 : solid === "top" ? 180 : 0;
  return { color: solidPaint.color, rotate };
}

/** Uniform border → shape.line; else emit borderLine nodes. */
export function parseShapeAndBorders(
  snap: DomSnapshot,
  slideRoot: HTMLElement,
): Array<ShapeNode | BorderLineNode | ImageNode> {
  const { styles, z, el } = snap;
  const out: Array<ShapeNode | BorderLineNode | ImageNode> = [];
  const ownRotate = effectiveRotateDeg(el);
  const rotated =
    ownRotate != null && Math.abs(ownRotate) >= 0.5 ? ownRotate : undefined;
  const box = rotated
    ? layoutBoxRelativeTo(el, slideRoot, rotated)
    : snap.box;
  const bgImage = (styles.backgroundImage || "").trim();
  const hasBgImage = bgImage !== "" && bgImage !== "none";
  const opacity = Number.parseFloat(styles.opacity || "1") || 1;
  const isPseudo = el.hasAttribute("data-h2p-pseudo");
  const pos = styles.position || "";
  const outOfFlow = pos === "absolute" || pos === "fixed";
  const shapeZ = isPseudo && !outOfFlow ? z + 0.5 : z;

  // pptxgen has no CSS gradient fill — bake linear-gradient to a PNG so title
  // washes (opaque → transparent) survive export.
  let gradientImage: ImageNode | null = null;
  if (hasBgImage && isCssLinearGradient(bgImage) && box.w >= 1 && box.h >= 1) {
    const dataUrl = rasterizeLinearGradientBackground(bgImage, box.w, box.h, {
      doc: el.ownerDocument,
      borderRadius: styles.borderRadius,
      opacity,
    });
    if (dataUrl) {
      gradientImage = {
        kind: "image",
        x: pxToInch(box.x),
        y: pxToInch(box.y),
        w: pxToInch(box.w),
        h: pxToInch(box.h),
        z: shapeZ,
        src: dataUrl,
        dataUrl,
        sizing: "stretch",
        rotate: rotated,
      };
    }
  }

  let fill = gradientImage
    ? null
    : applyElementOpacity(resolveBackgroundFill(styles), opacity);
  const looksLikeBullet =
    el.hasAttribute("data-h2p-pseudo") &&
    !hasBgImage &&
    box.w > 0 &&
    box.h > 0 &&
    box.w <= 48 &&
    box.h <= 48;
  if (!fill && !gradientImage && looksLikeBullet && el.parentElement) {
    fill = applyElementOpacity(
      solidFill(computedStyle(el.parentElement).color),
      opacity,
    );
  }
  const ratio = radiusRatio(styles.borderRadius, box.h);
  const shadow = parseShadow(styles.boxShadow);

  const paints = {
    top: sidePaint(styles, "Top"),
    right: sidePaint(styles, "Right"),
    bottom: sidePaint(styles, "Bottom"),
    left: sidePaint(styles, "Left"),
  };

  const tri = detectCssBorderTriangle(paints, box);
  if (tri && !fill && !gradientImage) {
    out.push({
      kind: "shape",
      x: pxToInch(box.x),
      y: pxToInch(box.y),
      w: pxToInch(Math.max(box.w, 1)),
      h: pxToInch(Math.max(box.h, 1)),
      z: el.hasAttribute("data-h2p-pseudo") ? z + 0.5 : z,
      fill: { type: "solid", color: tri.color },
      shapeName: "triangle",
      rotate: tri.rotate,
    });
    return out;
  }

  // Soft elevation: faint hairlines + shadow → hard frames if alpha is dropped.
  const skipFaintOutline =
    !!shadow &&
    (["top", "right", "bottom", "left"] as const).every((s) => {
      const p = paints[s];
      return !p || (p.alpha < 0.25 && p.width <= 1.25);
    });

  const sides = (["top", "right", "bottom", "left"] as const).filter((s) => {
    const p = paints[s];
    if (!p) return false;
    if (skipFaintOutline && p.alpha < 0.25 && p.width <= 1.25) return false;
    return true;
  });

  const uniform =
    sides.length === 4 &&
    sides.every((s) => Math.abs(paints[s]!.width - paints.top!.width) < 0.5) &&
    sides.every((s) => paints[s]!.color === paints.top!.color) &&
    sides.every(
      (s) => (paints[s]!.transparency ?? 0) === (paints.top!.transparency ?? 0),
    );

  let line: Line | undefined;
  if (uniform && paints.top) {
    line = {
      color: paints.top.color,
      widthPt: paints.top.width * 0.75,
      transparency: paints.top.transparency,
      dashType: mapDash(sideStyle(styles, "Top")),
    };
  }

  if (gradientImage) {
    out.push(gradientImage);
    // Outline / shadow still need a shape shell (fill none).
    if (line || shadow) {
      const name = shapeName(styles.borderRadius, ratio, box);
      out.push({
        kind: "shape",
        x: pxToInch(box.x),
        y: pxToInch(box.y),
        w: pxToInch(box.w),
        h: pxToInch(box.h),
        z: shapeZ + 0.01,
        fill: { type: "none" },
        line,
        rectRadius: name === "roundRect" ? ratio : undefined,
        shapeName: name,
        rotate: rotated,
        shadow,
      });
    }
  } else if (fill || line) {
    const name = shapeName(styles.borderRadius, ratio, box);
    out.push({
      kind: "shape",
      x: pxToInch(box.x),
      y: pxToInch(box.y),
      w: pxToInch(box.w),
      h: pxToInch(box.h),
      z: shapeZ,
      fill: fill || { type: "none" },
      line,
      rectRadius: name === "roundRect" ? ratio : undefined,
      shapeName: name,
      rotate: rotated,
      shadow,
    });
  }

  if (!uniform) {
    for (const side of sides) {
      const paint = paints[side]!;
      const wPx = paint.width;
      const wIn = pxToInch(wPx);
      let x = box.x;
      let y = box.y;
      let w = box.w;
      let h = box.h;
      if (side === "top") {
        h = wPx;
      } else if (side === "bottom") {
        y = box.y + box.h - wPx;
        h = wPx;
      } else if (side === "left") {
        w = wPx;
      } else {
        x = box.x + box.w - wPx;
        w = wPx;
      }
      const sideKey =
        side === "top"
          ? "Top"
          : side === "right"
            ? "Right"
            : side === "bottom"
              ? "Bottom"
              : "Left";
      out.push({
        kind: "borderLine",
        x: pxToInch(x),
        y: pxToInch(y),
        w: pxToInch(w),
        h: pxToInch(h),
        z: z + 0.01,
        side,
        color: paint.color,
        widthIn: wIn,
        dashType: mapDash(sideStyle(styles, sideKey)),
      });
    }
  }

  return out;
}

export function parseImage(
  snap: DomSnapshot,
  slideRoot?: HTMLElement,
): import("../types").ImageNode | null {
  if (snap.tag !== "IMG" || !snap.src) return null;
  const { box, z, el, styles } = snap;
  const img = el as HTMLImageElement;

  const objectFit = (styles.objectFit || "").trim().toLowerCase();
  const dataSizing = (el.getAttribute("data-sizing") || "").trim().toLowerCase();
  const fit = objectFit || dataSizing;
  let sizing: import("../types").ImageSizing = "stretch";
  if (fit === "cover") sizing = "cover";
  else if (fit === "contain" || fit === "scale-down" || fit === "none") sizing = "contain";
  else if (fit === "fill") sizing = "stretch";

  const nw = img.naturalWidth || 0;
  const nh = img.naturalHeight || 0;
  const intrinsicSize =
    nw > 0 && nh > 0 ? { width: nw, height: nh } : undefined;

  const clip =
    slideRoot && isHTMLElement(el)
      ? findClipPathHost(el as HTMLElement, slideRoot)
      : null;
  if (clip) {
    const hostBox = boxRelativeTo(clip.host, slideRoot!);
    const hostW = clip.host.offsetWidth || hostBox.w;
    const hostH = clip.host.offsetHeight || hostBox.h;
    return {
      kind: "image",
      x: pxToInch(hostBox.x),
      y: pxToInch(hostBox.y),
      w: pxToInch(hostBox.w),
      h: pxToInch(hostBox.h),
      z,
      src: snap.src,
      sizing: "stretch",
      clipPolygon: clip.polygon,
      clipDraw: imageDrawInClipHost(img, clip.host),
      clipHostPx: { w: Math.max(1, hostW), h: Math.max(1, hostH) },
    };
  }

  const ownRotate = effectiveRotateDeg(el);
  const rotated =
    ownRotate != null && Math.abs(ownRotate) >= 0.5 ? ownRotate : undefined;
  const layoutBox =
    rotated && slideRoot
      ? layoutBoxRelativeTo(el, slideRoot, rotated)
      : box;

  return {
    kind: "image",
    x: pxToInch(layoutBox.x),
    y: pxToInch(layoutBox.y),
    w: pxToInch(layoutBox.w),
    h: pxToInch(layoutBox.h),
    z,
    src: snap.src,
    sizing,
    intrinsicSize,
    objectPosition: parseObjectPosition(styles.objectPosition || "50% 50%"),
    rotate: rotated,
  };
}

/** Inline SVG → image node (rasterized later). Stroke-only paths have no CSS fill. */
export function parseSvg(
  snap: DomSnapshot,
  slideRoot?: HTMLElement,
): import("../types").ImageNode | null {
  if (snap.tag !== "SVG") return null;
  const el = snap.el as SVGSVGElement;

  const matrix = slideRoot
    ? combinedCssLinear(el, slideRoot)
    : { a: 1, b: 0, c: 0, d: 1 };
  const bakeTransform = !isIdentityLinear(matrix);

  const pad = svgStrokePadPx(el);
  const aabb = snap.box;
  const html = el as unknown as HTMLElement;
  // Prefer pre-transform layout size. getBoundingClientRect is the AABB and
  // would inflate localW/H under rotate, double-scaling the baked bitmap.
  const localW =
    html.offsetWidth ||
    html.clientWidth ||
    Number.parseFloat(el.getAttribute("width") || "0") ||
    aabb.w;
  const localH =
    html.offsetHeight ||
    html.clientHeight ||
    Number.parseFloat(el.getAttribute("height") || "0") ||
    aabb.h;

  // Bake CSS rotate/flip into the bitmap and place at the painted AABB.
  // Applying pptxgen rotate on top of an already-flipped raster mirrors the corner square.
  if (bakeTransform) {
    return {
      kind: "image",
      x: pxToInch(aabb.x - pad),
      y: pxToInch(aabb.y - pad),
      w: pxToInch(Math.max(aabb.w, 1) + pad * 2),
      h: pxToInch(Math.max(aabb.h, 1) + pad * 2),
      z: snap.z,
      src: "",
      svgMarkup: serializeSvg(el, 0),
      svgLocalW: Math.max(1, localW),
      svgLocalH: Math.max(1, localH),
      svgMatrix: matrix,
      sizing: "stretch",
    };
  }

  const ownRotate = effectiveRotateDeg(el);
  const rotated =
    ownRotate != null && Math.abs(ownRotate) >= 0.5 ? ownRotate : undefined;
  const layoutBox =
    rotated && slideRoot
      ? layoutBoxRelativeTo(el, slideRoot, rotated)
      : aabb;

  return {
    kind: "image",
    x: pxToInch(layoutBox.x - pad),
    y: pxToInch(layoutBox.y - pad),
    w: pxToInch(Math.max(layoutBox.w, 1) + pad * 2),
    h: pxToInch(Math.max(layoutBox.h, 1) + pad * 2),
    z: snap.z,
    src: "",
    svgMarkup: serializeSvg(el, pad),
    sizing: "stretch",
    rotate: rotated,
  };
}

/** CSS object-position → 0–1 anchor (simplified; covers % and common keywords). */
function parseObjectPosition(raw: string): { x: number; y: number } {
  const parts = (raw || "50% 50%").trim().toLowerCase().split(/\s+/).filter(Boolean);
  const mapKeyword = (token: string, axis: "x" | "y"): number | null => {
    if (token === "center") return 0.5;
    if (axis === "x") {
      if (token === "left") return 0;
      if (token === "right") return 1;
    } else {
      if (token === "top") return 0;
      if (token === "bottom") return 1;
    }
    return null;
  };
  const parseToken = (token: string | undefined, axis: "x" | "y", fallback: number) => {
    if (!token) return fallback;
    const kw = mapKeyword(token, axis);
    if (kw != null) return kw;
    if (token.endsWith("%")) {
      const n = Number.parseFloat(token);
      return Number.isFinite(n) ? Math.min(1, Math.max(0, n / 100)) : fallback;
    }
    return fallback;
  };
  if (parts.length === 1) {
    const t = parts[0];
    if (t === "center") return { x: 0.5, y: 0.5 };
    if (t === "left" || t === "right") return { x: parseToken(t, "x", 0.5), y: 0.5 };
    if (t === "top" || t === "bottom") return { x: 0.5, y: parseToken(t, "y", 0.5) };
    return { x: parseToken(t, "x", 0.5), y: 0.5 };
  }
  return {
    x: parseToken(parts[0], "x", 0.5),
    y: parseToken(parts[1], "y", 0.5),
  };
}
