/** Intermediate representation drawn by pptxgenjs. */

export type Fill =
  | { type: "solid"; color: string; transparency?: number }
  | { type: "none" };

export type Line = {
  color: string;
  widthPt: number;
  transparency?: number;
  dashType?: "solid" | "dash" | "sysDash" | "sysDot";
};

export type Shadow = {
  color: string;
  blurPt: number;
  offsetPt: number;
  angle: number;
  opacity?: number;
};

export type Box = { x: number; y: number; w: number; h: number };

export type DomSnapshot = {
  el: Element;
  tag: string;
  box: Box;
  z: number;
  styles: CSSStyleDeclaration;
  src?: string;
};

type NodeBase = Box & { z: number };

export type ShapeNode = NodeBase & {
  kind: "shape";
  fill: Fill;
  line?: Line;
  rectRadius?: number;
  shapeName?: "rect" | "roundRect" | "ellipse" | "triangle" | "rtTriangle";
  /** Degrees clockwise (CSS border-triangle orientation). */
  rotate?: number;
  shadow?: Shadow;
};

/** Per-run style inside one PPT text frame (mixed inline sizes/colors). */
export type TextRun = {
  text: string;
  color?: string;
  transparency?: number;
  outline?: { color: string; size: number; transparency?: number };
  fontSizePt?: number;
  fontFace?: string;
  bold?: boolean;
  italic?: boolean;
  charSpacingPt?: number;
  /** End of visual line — pptxgen soft break before the next run. */
  breakLine?: boolean;
};

export type TextNode = NodeBase & {
  kind: "text";
  text: string;
  /** When set, pptxgen receives rich runs; `text` stays as plain fallback. */
  runs?: TextRun[];
  color: string;
  transparency?: number;
  outline?: { color: string; size: number; transparency?: number };
  fontSizePt: number;
  fontFace: string;
  bold?: boolean;
  italic?: boolean;
  align?: "left" | "center" | "right";
  valign?: "top" | "middle" | "bottom";
  wrap?: boolean;
  /** Exact line spacing in points (CSS line box → pt). */
  lineSpacingPt?: number;
  /** CSS line-height multiplier (e.g. 1.1) → pptxgenjs lineSpacingMultiple */
  lineSpacingMultiple?: number;
  /** Character spacing in points (from CSS letter-spacing). */
  charSpacingPt?: number;
  /** Degrees clockwise (CSS transform rotate). */
  rotate?: number;
  /**
   * pptxgen `vert`. CSS `writing-mode: vertical-rl` → `eaVert` (CJK stays upright).
   * Do not also set `rotate` for the same node.
   */
  vert?: "eaVert" | "horz" | "mongolianVert" | "vert" | "vert270";
  /** Inches — pptxgen margin [top, right, bottom, left]. */
  margin?: [number, number, number, number];
};

export type ImageSizing = "cover" | "contain" | "stretch";

export type ImageNode = NodeBase & {
  kind: "image";
  src: string;
  dataUrl?: string;
  /** CSS object-fit → pptxgen sizing (default stretch). */
  sizing?: ImageSizing;
  /** Intrinsic pixel size — required for cover/contain (pptxgen source ratio). */
  intrinsicSize?: { width: number; height: number };
  /** CSS object-position as 0–1 fractions (default center). */
  objectPosition?: { x: number; y: number };
  /** Degrees clockwise (CSS transform rotate). */
  rotate?: number;
  /** Inline SVG markup — rasterized in materializeImages. */
  svgMarkup?: string;
  /** Untransformed SVG layout size (px) for baking CSS transform. */
  svgLocalW?: number;
  svgLocalH?: number;
  /** CSS matrix(a,b,c,d) linear part; baked when rasterizing SVG. */
  svgMatrix?: { a: number; b: number; c: number; d: number };
  /** Normalized 0–1 polygon from ancestor clip-path (relative to clip host). */
  clipPolygon?: { x: number; y: number }[];
  /** Image draw rect within clip host (CSS px). */
  clipDraw?: { drawX: number; drawY: number; drawW: number; drawH: number };
  /** Clip host layout size (CSS px) for scaling draw rect. */
  clipHostPx?: { w: number; h: number };
  /**
   * CSS border-radius on the img or an overflow:hidden ancestor.
   * Baked to a transparent-corner PNG in materializeImages.
   */
  roundClipCss?: string;
};

export type BorderLineNode = NodeBase & {
  kind: "borderLine";
  side: "top" | "right" | "bottom" | "left";
  color: string;
  widthIn: number;
  dashType?: Line["dashType"];
};

export type SlideNode = ShapeNode | TextNode | ImageNode | BorderLineNode;

export type PreparedSlide = {
  nodes: SlideNode[];
  backgroundColor?: string;
};
