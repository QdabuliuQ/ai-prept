/**
 * Text extraction: bake browser visual lines into one PPT text frame.
 * Geometry prefers ink (Range client rects) over oversized flex parents.
 * Mixed inline styles (e.g. KPI value + unit) become pptxgen rich-text runs.
 */

import { pxToInch } from "../config";
import { textColor } from "../lib/color";
import {
  ancestorCssScale,
  computedStyle,
  effectiveRotateDeg,
  isDefaultInlineTag,
  isElementNode,
  isHTMLElement,
  isInlineishDisplay,
  layoutBoxRelativeTo,
  parsePx,
} from "../lib/dom";
import { resolveTypeface } from "../lib/font";
import type { DomSnapshot, TextNode, TextRun } from "../types";

type LineRect = { left: number; right: number; top: number; bottom: number };
type RunStyle = {
  color: string;
  transparency?: number;
  outline?: { color: string; size: number; transparency?: number };
  fontSizePt: number;
  fontFace: string;
  bold: boolean;
  italic: boolean;
  charSpacingPt?: number;
};
type FlowPiece = { kind: "text"; node: Text; style: RunStyle } | { kind: "br" };
type BakedRun = { text: string; rect?: LineRect; style: RunStyle };
type BakedLine = { runs: BakedRun[]; rect?: LineRect };

function effectiveOpacity(el: Element): number {
  let alpha = 1;
  let node: Element | null = el;
  while (node) {
    const value = Number.parseFloat(computedStyle(node).opacity || "1");
    if (Number.isFinite(value)) alpha *= Math.max(0, Math.min(1, value));
    node = node.parentElement;
  }
  return alpha;
}

function styleKey(s: RunStyle): string {
  return [
    s.color,
    s.transparency ?? "",
    s.outline?.color ?? "",
    s.outline?.size ?? "",
    s.fontSizePt,
    s.fontFace,
    s.bold ? 1 : 0,
    s.italic ? 1 : 0,
    s.charSpacingPt ?? "",
  ].join("|");
}

function runStyleFromElement(el: Element, scale = 1): RunStyle {
  const styles = computedStyle(el);
  const fontSizePx = (parsePx(styles.fontSize) || 16) * scale;
  const typeface = resolveTypeface(
    styles.fontFamily || "",
    styles.fontWeight || ""
  );
  const color = textColor(styles.color, effectiveOpacity(el));
  const outline = textOutline(styles, scale);
  return {
    ...color,
    outline,
    fontSizePt: fontSizePx * 0.75,
    fontFace: typeface.fontFace,
    bold: typeface.bold,
    italic: /italic/i.test(styles.fontStyle),
    charSpacingPt: parseLetterSpacingPt(styles.letterSpacing, fontSizePx),
  };
}

function textOutline(
  styles: CSSStyleDeclaration,
  scale = 1
): { color: string; size: number; transparency?: number } | undefined {
  const width = parsePx(
    styles.getPropertyValue("-webkit-text-stroke-width") ||
      styles.getPropertyValue("text-stroke-width")
  );
  if (width <= 0) return undefined;
  const rawColor =
    styles.getPropertyValue("-webkit-text-stroke-color") ||
    styles.getPropertyValue("text-stroke-color");
  const color = textColor(rawColor);
  if (!color.color || color.transparency === 100) return undefined;
  return {
    color: color.color,
    size: width * scale * 0.75,
    transparency: color.transparency,
  };
}

function runStyleFromTextNode(
  node: Text,
  fallback: Element,
  scale = 1
): RunStyle {
  const parent = node.parentElement;
  return runStyleFromElement(
    parent && isElementNode(parent) ? parent : fallback,
    scale
  );
}

function measureRange(
  doc: Document,
  textNode: Text,
  start: number,
  end: number
): LineRect[] {
  const range = doc.createRange();
  range.setStart(textNode, start);
  range.setEnd(textNode, end);
  const rects = Array.from(range.getClientRects())
    .filter((r) => r.width > 0 && r.height > 0)
    .map((r) => ({
      left: r.left,
      right: r.right,
      top: r.top,
      bottom: r.bottom,
    }));
  range.detach?.();
  return rects;
}

function groupByLine(rects: LineRect[], tol = 0.75): LineRect[] {
  const rows: LineRect[] = [];
  for (const rect of rects) {
    const cur = rows[rows.length - 1];
    if (cur && Math.abs(cur.top - rect.top) <= tol + 1) {
      rows[rows.length - 1] = {
        left: Math.min(cur.left, rect.left),
        right: Math.max(cur.right, rect.right),
        top: Math.min(cur.top, rect.top),
        bottom: Math.max(cur.bottom, rect.bottom),
      };
    } else {
      rows.push({ ...rect });
    }
  }
  return rows;
}

function graphemeEnds(raw: string): number[] {
  const ends: number[] = [0];
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const Seg = (Intl as any).Segmenter;
    if (Seg) {
      const seg = new Seg(undefined, { granularity: "grapheme" });
      let offset = 0;
      for (const s of seg.segment(raw)) {
        offset += s.segment.length;
        ends.push(offset);
      }
      return ends;
    }
  } catch {
    /* fall through */
  }
  for (let i = 0; i < raw.length; ) {
    const cp = raw.codePointAt(i)!;
    i += cp > 0xffff ? 2 : 1;
    ends.push(i);
  }
  return ends;
}

type VisualPiece = { text: string; rect?: LineRect };

type PptVert = "eaVert" | "vert" | "vert270";

/** CSS writing-mode → pptxgen vert. CJK vertical-rl keeps glyphs upright (`eaVert`). */
function cssWritingVert(el: Element): PptVert | undefined {
  let node: Element | null = el;
  for (let i = 0; i < 12 && node; i++) {
    const wm = (computedStyle(node).writingMode || "").toLowerCase();
    if (
      wm.includes("vertical-rl") ||
      wm.includes("vertical-lr") ||
      wm === "tb-rl" ||
      wm === "tb-lr"
    ) {
      return "eaVert";
    }
    if (wm.includes("sideways-rl")) return "vert";
    if (wm.includes("sideways-lr")) return "vert270";
    node = node.parentElement;
  }
  return undefined;
}

function unionLineRects(rects: LineRect[]): LineRect | undefined {
  if (!rects.length) return undefined;
  return rects.reduce((a, b) => ({
    left: Math.min(a.left, b.left),
    right: Math.max(a.right, b.right),
    top: Math.min(a.top, b.top),
    bottom: Math.max(a.bottom, b.bottom),
  }));
}

function splitTextNode(
  doc: Document,
  textNode: Text,
  asVertical = false
): VisualPiece[] {
  const raw = textNode.textContent ?? "";
  const start = meaningfulTextStart(raw);
  const end = meaningfulTextEnd(raw);
  if (end <= start) return [];

  const rects = measureRange(doc, textNode, start, end);
  if (!rects.length) return [];

  // Vertical-rl stacks glyphs along Y. Horizontal line-splitting would turn
  // each character into a PPT paragraph (a new column under eaVert).
  if (asVertical) {
    return [
      {
        text: trimLine(raw.slice(start, end)),
        rect: unionLineRects(rects),
      },
    ];
  }

  const full = groupByLine(rects);
  if (!full.length) return [];
  if (full.length === 1) {
    return [{ text: trimLine(raw.slice(start, end)), rect: full[0] }];
  }

  const absStarts = findLineStartsInSpan(
    doc,
    textNode,
    start,
    end,
    full.length
  );
  const lines: VisualPiece[] = [];
  for (let i = 0; i < absStarts.length; i++) {
    const a = absStarts[i];
    const b = i + 1 < absStarts.length ? absStarts[i + 1] : end;
    const slice = trimLine(raw.slice(a, b));
    if (!slice) continue;
    const rects = groupByLine(measureRange(doc, textNode, a, b));
    lines.push({
      text: slice,
      rect: rects[0] || full[Math.min(i, full.length - 1)],
    });
  }
  return lines;
}

function findLineStartsInSpan(
  doc: Document,
  textNode: Text,
  start: number,
  end: number,
  totalLines: number
): number[] {
  const raw = (textNode.textContent ?? "").slice(start, end);
  const boundaries = graphemeEnds(raw).map((o) => start + o);
  const starts = [start];
  const cache = new Map<number, number>();
  const countAt = (absEnd: number) => {
    const hit = cache.get(absEnd);
    if (hit != null) return hit;
    const n = groupByLine(measureRange(doc, textNode, start, absEnd)).length;
    cache.set(absEnd, n);
    return n;
  };
  let prev = 0;
  for (let target = 2; target <= totalLines; target++) {
    let low = Math.max(prev + 1, 1);
    let high = boundaries.length - 1;
    while (low < high) {
      const mid = (low + high) >>> 1;
      if (countAt(boundaries[mid]) >= target) high = mid;
      else low = mid + 1;
    }
    if (countAt(boundaries[low]) < target) break;
    const startIdx = Math.max(0, low - 1);
    const abs = boundaries[startIdx];
    if (abs <= starts[starts.length - 1]) break;
    starts.push(abs);
    prev = startIdx;
  }
  return starts;
}

function trimLine(s: string): string {
  // Strip all Unicode space separators + ASCII ws (HTML indent / &nbsp; / 全角空格)
  return s
    .replace(/\r/g, "")
    .replace(/\t/g, " ")
    .replace(/^[\s\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]+/g, "")
    .replace(/[\s\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]+$/g, "");
}

/** Drop trailing whitespace from a DOM Text before measuring / exporting. */
function meaningfulTextEnd(raw: string): number {
  let end = raw.length;
  while (end > 0) {
    const ch = raw[end - 1];
    if (/[\s\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]/.test(ch)) {
      end -= 1;
      continue;
    }
    break;
  }
  return end;
}

function meaningfulTextStart(raw: string): number {
  let start = 0;
  while (start < raw.length) {
    const ch = raw[start];
    if (/[\s\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]/.test(ch)) {
      start += 1;
      continue;
    }
    break;
  }
  return start;
}

function collectFlow(el: Element, scale = 1): FlowPiece[] {
  const out: FlowPiece[] = [];
  const win = el.ownerDocument.defaultView;
  if (!win) return out;

  const visit = (parent: Element) => {
    for (const child of Array.from(parent.childNodes)) {
      if (child.nodeType === Node.TEXT_NODE) {
        const raw = child.textContent ?? "";
        // Drop indent-only whitespace nodes from pretty-printed HTML
        if (!raw.replace(/[\s\u00a0\u3000]/g, "").length) continue;
        out.push({
          kind: "text",
          node: child as Text,
          style: runStyleFromTextNode(child as Text, el, scale),
        });
        continue;
      }
      if (child.nodeType !== Node.ELEMENT_NODE) continue;
      const childEl = child as Element;
      const tag = childEl.tagName.toUpperCase();
      if (tag === "BR") {
        out.push({ kind: "br" });
        continue;
      }
      if (tag === "IMG" || tag === "SVG" || tag === "CANVAS" || tag === "VIDEO")
        continue;
      // Skip our own pseudo stand-ins when baking host text
      if (childEl.hasAttribute("data-h2p-pseudo")) continue;
      const display = win.getComputedStyle(childEl).display;
      if (display === "none") continue;
      // Only true inline / contents — never absorb flex/grid/block children
      if (isInlineishDisplay(display)) {
        visit(childEl);
        continue;
      }
      if (
        isDefaultInlineTag(tag) &&
        display !== "block" &&
        display !== "flex" &&
        display !== "grid" &&
        display !== "table"
      ) {
        visit(childEl);
      }
    }
  };
  visit(el);
  return out;
}

function mergeRunRect(a?: LineRect, b?: LineRect): LineRect | undefined {
  if (!a) return b ? { ...b } : undefined;
  if (!b) return { ...a };
  return {
    left: Math.min(a.left, b.left),
    right: Math.max(a.right, b.right),
    top: Math.min(a.top, b.top),
    bottom: Math.max(a.bottom, b.bottom),
  };
}

/** Mixed font sizes share a baseline but differ in glyph top — don't use top±2. */
function sameVisualLine(a: LineRect, b: LineRect): boolean {
  const overlap = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  const minH = Math.min(a.bottom - a.top, b.bottom - b.top);
  if (minH > 0 && overlap >= minH * 0.35) return true;
  const midA = (a.top + a.bottom) / 2;
  const midB = (b.top + b.bottom) / 2;
  return (
    Math.abs(midA - midB) <=
    Math.max(a.bottom - a.top, b.bottom - b.top, 4) * 0.55
  );
}

function appendRunToLine(line: BakedLine, run: BakedRun): void {
  const last = line.runs[line.runs.length - 1];
  if (last && styleKey(last.style) === styleKey(run.style)) {
    // Preserve CSS margin gap between differently-spaced same-style… (none)
    // Same style: concatenate.
    if (
      last.rect &&
      run.rect &&
      run.rect.left - last.rect.right > 3 &&
      !/\s$/.test(last.text) &&
      !/^\s/.test(run.text)
    ) {
      last.text = `${last.text} ${run.text}`;
    } else {
      last.text = `${last.text}${run.text}`;
    }
    last.rect = mergeRunRect(last.rect, run.rect);
  } else {
    const text = run.text;
    if (
      last?.rect &&
      run.rect &&
      run.rect.left - last.rect.right > 3 &&
      !/\s$/.test(last.text) &&
      !/^\s/.test(text)
    ) {
      // Approximate span margin-left (e.g. .kpi-unit) with a space at unit size
      line.runs.push({ text: " ", style: run.style, rect: undefined });
    }
    line.runs.push({ text, rect: run.rect, style: run.style });
  }
  line.rect = mergeRunRect(line.rect, run.rect);
}

function bakeFlow(
  doc: Document,
  flow: FlowPiece[],
  asVertical = false
): BakedLine[] {
  const lines: BakedLine[] = [];
  let current: BakedLine | null = null;

  const flush = () => {
    if (current && current.runs.some((r) => trimLine(r.text).length > 0)) {
      current.runs = current.runs
        .map((r) => ({ ...r, text: r.text }))
        .filter((r) => r.text.length > 0);
      // Trim edges of the line without dropping intentional mid-line spaces
      if (current.runs.length) {
        current.runs[0].text = current.runs[0].text.replace(
          /^[\s\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]+/g,
          ""
        );
        const last = current.runs[current.runs.length - 1];
        last.text = last.text.replace(
          /[\s\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]+$/g,
          ""
        );
        current.runs = current.runs.filter((r) => r.text.length > 0);
      }
      if (current.runs.length) lines.push(current);
    }
    current = null;
  };

  for (const piece of flow) {
    if (piece.kind === "br") {
      flush();
      continue;
    }
    const visual = splitTextNode(doc, piece.node, asVertical);
    if (!visual.length) continue;
    for (let i = 0; i < visual.length; i++) {
      const v = visual[i];
      const run: BakedRun = {
        text: v.text,
        rect: v.rect,
        style: piece.style,
      };
      // New visual line inside one text node, or Y jump vs previous piece
      if (i > 0) flush();
      else if (
        current?.rect &&
        v.rect &&
        !sameVisualLine(current.rect, v.rect)
      ) {
        flush();
      }
      if (!current) current = { runs: [], rect: undefined };
      appendRunToLine(current, run);
    }
  }
  flush();
  return lines;
}

function unionInk(lines: BakedLine[]): LineRect | null {
  const withRect = lines.filter((l) => l.rect);
  if (!withRect.length) return null;
  return {
    left: Math.min(...withRect.map((l) => l.rect!.left)),
    right: Math.max(...withRect.map((l) => l.rect!.right)),
    top: Math.min(...withRect.map((l) => l.rect!.top)),
    bottom: Math.max(...withRect.map((l) => l.rect!.bottom)),
  };
}

function bakedToPlain(lines: BakedLine[]): string {
  return lines.map((l) => l.runs.map((r) => r.text).join("")).join("\n");
}

function bakedToRuns(lines: BakedLine[]): TextRun[] | undefined {
  const allRuns = lines.flatMap((l) => l.runs);
  if (!allRuns.length) return undefined;
  const firstKey = styleKey(allRuns[0].style);
  const mixed =
    lines.length > 1 || allRuns.some((r) => styleKey(r.style) !== firstKey);
  if (!mixed) return undefined;

  const out: TextRun[] = [];
  for (let li = 0; li < lines.length; li++) {
    const line = lines[li];
    for (let ri = 0; ri < line.runs.length; ri++) {
      const r = line.runs[ri];
      const isLastOnLine = ri === line.runs.length - 1;
      const breakLine = isLastOnLine && li < lines.length - 1;
      out.push({
        text: r.text,
        color: r.style.color,
        transparency: r.style.transparency,
        outline: r.style.outline,
        fontSizePt: r.style.fontSizePt,
        fontFace: r.style.fontFace,
        bold: r.style.bold,
        italic: r.style.italic,
        charSpacingPt: r.style.charSpacingPt,
        ...(breakLine ? { breakLine: true } : {}),
      });
    }
  }
  return out;
}

function lineHeightPx(styles: CSSStyleDeclaration, fontSize: number): number {
  const lh = styles.lineHeight;
  if (!lh || lh === "normal") return fontSize * 1.2;
  if (lh.endsWith("px")) return parsePx(lh);
  const n = Number.parseFloat(lh);
  if (Number.isFinite(n) && n > 0 && n < 10) return n * fontSize;
  return parsePx(lh) || fontSize * 1.2;
}

/**
 * CSS line-height → PPT lineSpacingMultiple (keep the authored number, e.g. 1.1).
 * getComputedStyle often returns px; convert with font-size.
 */
function parseLineSpacingMultiple(
  lineHeight: string,
  fontSizePx: number
): number | undefined {
  if (!lineHeight || lineHeight === "normal") return undefined;

  const trimmed = lineHeight.trim();
  const unitless = Number(trimmed);
  if (Number.isFinite(unitless) && trimmed === String(unitless)) {
    return Number(unitless.toFixed(3));
  }

  if (trimmed.endsWith("%")) {
    const pct = Number.parseFloat(trimmed);
    if (!Number.isFinite(pct)) return undefined;
    return Number((pct / 100).toFixed(3));
  }

  if (trimmed.endsWith("em") || trimmed.endsWith("rem")) {
    const em = Number.parseFloat(trimmed);
    if (!Number.isFinite(em)) return undefined;
    return Number(em.toFixed(3));
  }

  if (trimmed.endsWith("px") && fontSizePx > 0) {
    const px = parsePx(trimmed);
    if (px <= 0) return undefined;
    return Number((px / fontSizePx).toFixed(3));
  }

  return undefined;
}

/** CSS letter-spacing → pptxgenjs charSpacing (points). */
function parseLetterSpacingPt(
  letterSpacing: string,
  fontSizePx: number
): number | undefined {
  if (!letterSpacing || letterSpacing === "normal") return undefined;
  let px = 0;
  if (letterSpacing.endsWith("em")) {
    px = Number.parseFloat(letterSpacing) * fontSizePx;
  } else if (letterSpacing.endsWith("rem")) {
    px = Number.parseFloat(letterSpacing) * 16;
  } else {
    px = Number.parseFloat(letterSpacing);
  }
  if (!Number.isFinite(px) || px === 0) return undefined;
  return Number((px * 0.75).toFixed(3));
}

function resolveTextAlign(raw: string): "left" | "center" | "right" {
  const a = (raw || "").trim().toLowerCase();
  if (a === "center") return "center";
  if (a === "right" || a === "end") return "right";
  // left | start | justify | empty → left (chips must not default to center)
  return "left";
}

/**
 * Detect badge/pill hosts (e.g. .card-tag), NOT layout rows like .card-metric.
 * Bare padding alone is too loose — flex KPI rows with padding-top would steal
 * both the value and label into one shared content box + valign middle.
 */
function findChipHost(el: Element): HTMLElement | null {
  let node: HTMLElement | null = isHTMLElement(el)
    ? el
    : isHTMLElement(el.parentElement)
      ? el.parentElement
      : null;
  for (let depth = 0; depth < 3 && node; depth += 1) {
    const style = computedStyle(node);
    const display = style.display || "";
    // Multi-child flex/grid = layout container, never a text chip
    if (
      (display === "flex" ||
        display === "inline-flex" ||
        display === "grid" ||
        display === "inline-grid") &&
      node.children.length > 1
    ) {
      const parent = node.parentElement;
      node = isHTMLElement(parent) ? parent : null;
      continue;
    }
    const rect = node.getBoundingClientRect();
    const radius =
      parsePx(style.borderRadius) || parsePx(style.borderTopLeftRadius);
    const padY = parsePx(style.paddingTop) + parsePx(style.paddingBottom);
    const bg = style.backgroundColor;
    const hasBgImg =
      !!style.backgroundImage && style.backgroundImage !== "none";
    const hasBg =
      hasBgImg ||
      (!!bg &&
        !bg.endsWith(", 0)") &&
        bg !== "transparent" &&
        bg !== "rgba(0, 0, 0, 0)");
    const pill = radius >= Math.min(rect.height * 0.35, 12);
    const compact = rect.height > 0 && rect.height <= 96;
    // Require pill radius or filled+padded look — do not match padding-only rows
    if (compact && (pill || (hasBg && padY >= 4))) return node;
    const parent = node.parentElement;
    node = isHTMLElement(parent) ? parent : null;
  }
  return null;
}

export function parseText(
  snap: DomSnapshot,
  slideRoot: HTMLElement,
  opts: { skip?: boolean } = {}
): TextNode[] {
  if (opts.skip) return [];
  const el = snap.el;
  const doc = el.ownerDocument;
  if (!doc) return [];

  const scale = ancestorCssScale(el, slideRoot);
  const vert = cssWritingVert(el);
  const flow = collectFlow(el, scale);
  if (!flow.some((p) => p.kind === "text")) return [];
  const bakedLines = bakeFlow(doc, flow, !!vert);
  const baked =
    vert && bakedLines.length > 1
      ? [
          {
            runs: bakedLines.flatMap((l) => l.runs),
            rect: unionInk(bakedLines) || bakedLines[0]?.rect,
          },
        ]
      : bakedLines;
  if (!baked.length) return [];

  const rootRect = slideRoot.getBoundingClientRect();
  const fontSizePx = (parsePx(snap.styles.fontSize) || 16) * scale;
  const lh = lineHeightPx(snap.styles, fontSizePx);
  const ink = unionInk(baked);
  const live = el.getBoundingClientRect();
  const elBox = {
    x: live.left - rootRect.left,
    y: live.top - rootRect.top,
    w: live.width,
    h: live.height,
  };

  const chip = findChipHost(el);
  const chipH = chip?.getBoundingClientRect().height ?? elBox.h;
  const isChip = !!(chip && chipH <= 96);

  const align = resolveTextAlign(snap.styles.textAlign);
  const justify = (snap.styles.justifyContent || "").trim();
  const alignItems = (snap.styles.alignItems || "").trim();
  const isFlexish = (snap.styles.display || "").includes("flex");
  // Do NOT force center/middle just because it's a chip — eyebrow pills are
  // usually left-aligned; forcing center shifts labels in PPTX vs HTML.
  const flexCenter =
    isFlexish &&
    (alignItems === "center" || alignItems === "middle") &&
    (justify === "center" || align === "center");

  const typeface = resolveTypeface(
    snap.styles.fontFamily || "",
    snap.styles.fontWeight || ""
  );

  const lineCount = baked.length;
  // Only multi-line paragraphs need PPT line-spacing; single-line + multiple
  // inflates the line box inside the shape and shifts glyphs down (≠ HTML ink).
  const lineSpacingMultiple =
    lineCount > 1
      ? parseLineSpacingMultiple(snap.styles.lineHeight, fontSizePx)
      : undefined;

  const baseStyle = {
    ...textColor(snap.styles.color, effectiveOpacity(el)),
    fontSizePt: fontSizePx * 0.75,
    fontFace: typeface.fontFace,
    bold: typeface.bold,
    italic: /italic/i.test(snap.styles.fontStyle),
    align,
    wrap: false as const,
    charSpacingPt: parseLetterSpacingPt(snap.styles.letterSpacing, fontSizePx),
    lineSpacingMultiple,
    outline: textOutline(snap.styles, scale),
  };

  // Geometry = DOM ink only (glyph client rects). Never grow to CSS line-height
  // — that makes the PPT text frame taller than the painted text and breaks
  // alignment vs HTML (e.g. KPI 68% + label under a rule).
  let frame: { x: number; y: number; w: number; h: number };
  let usedInk = false;
  let margin: [number, number, number, number] | undefined;
  let textAlign = align;
  const rotate = effectiveRotateDeg(chip || el);
  const hasRotate = rotate != null && Math.abs(rotate) >= 0.5;

  if (isChip && chip && hasRotate) {
    // Rotated chips: text + chrome MUST share the same x/y/w/h so pptxgen
    // rotates about one center. Inset CSS padding via margin (not a smaller
    // frame) — a smaller frame + rotate drifts the label vs the pill.
    const ub = layoutBoxRelativeTo(chip, slideRoot, rotate);
    const hs = computedStyle(chip);
    const padT = parsePx(hs.paddingTop) * scale;
    const padR = parsePx(hs.paddingRight) * scale;
    const padB = parsePx(hs.paddingBottom) * scale;
    const padL = parsePx(hs.paddingLeft) * scale;
    frame = { x: ub.x, y: ub.y, w: ub.w, h: ub.h };
    margin = [pxToInch(padT), pxToInch(padR), pxToInch(padB), pxToInch(padL)];
    const chipJustify = (hs.justifyContent || "").trim();
    const chipAlign = resolveTextAlign(hs.textAlign);
    if (chipJustify === "center" || chipAlign === "center" || flexCenter) {
      textAlign = "center";
    }
  } else if (isChip && chip) {
    const hr = chip.getBoundingClientRect();
    const hs = computedStyle(chip);
    const padT = parsePx(hs.paddingTop) * scale;
    const padR = parsePx(hs.paddingRight) * scale;
    const padB = parsePx(hs.paddingBottom) * scale;
    const padL = parsePx(hs.paddingLeft) * scale;
    const innerH = hr.height - padT - padB;
    const innerW = hr.width - padL - padR;
    // Left/right-aligned chips: hug glyph ink so PPT matches HTML (no forced
    // center in an oversized content box). Centered chips keep the pad box.
    if (ink && align !== "center") {
      usedInk = true;
      frame = {
        x: ink.left - rootRect.left,
        y: ink.top - rootRect.top,
        w: Math.max(0, ink.right - ink.left + 2),
        h: Math.max(0, ink.bottom - ink.top),
      };
    } else if (innerW >= 0.5 && innerH >= Math.min(fontSizePx * 0.6, 8)) {
      frame = {
        x: hr.left - rootRect.left + padL,
        y: hr.top - rootRect.top + padT,
        w: innerW,
        h: innerH,
      };
    } else if (ink) {
      usedInk = true;
      frame = {
        x: ink.left - rootRect.left,
        y: ink.top - rootRect.top,
        w: Math.max(0, ink.right - ink.left + 2),
        h: Math.max(0, ink.bottom - ink.top),
      };
    } else {
      frame = {
        x: hr.left - rootRect.left,
        y: hr.top - rootRect.top,
        w: Math.max(0, hr.width),
        h: Math.max(0, hr.height),
      };
    }
  } else if (hasRotate) {
    const ub = layoutBoxRelativeTo(el, slideRoot, rotate);
    frame = { x: ub.x, y: ub.y, w: ub.w, h: ub.h };
  } else if (ink) {
    usedInk = true;
    // +2px slack: subpixel ink vs pptxgen metrics must not force a wrap
    frame = {
      x: ink.left - rootRect.left,
      y: ink.top - rootRect.top,
      w: Math.max(0, ink.right - ink.left + 2),
      h: Math.max(0, ink.bottom - ink.top),
    };
  } else if (el.querySelector("[data-h2p-pseudo]")) {
    // Host has materialized bullets — elBox would cover them; skip rather than overlap
    return [];
  } else {
    frame = elBox;
  }

  if (frame.w < 0.5 || frame.h < 0.5) return [];

  // CJK/font clientRects often taller than CSS line-height; clamp single-line
  // frames so mixed value+unit boxes don't swallow the caption below.
  // Skip for vertical-rl — the ink box is supposed to be many ems tall.
  if (!vert && usedInk && lineCount === 1 && lh > 0 && frame.h > lh * 1.15) {
    frame = { ...frame, h: lh };
  }

  // Ink y is already glyph top — never valign middle (PPT font metrics ≠ browser).
  let valign: "top" | "middle" | "bottom" = "top";
  if (isChip && chip && hasRotate) {
    valign = "middle";
  } else if (!usedInk) {
    if (flexCenter && lineCount <= 1) valign = "middle";
    else if (lineCount === 1 && frame.h <= lh + 4) valign = "middle";
  }

  return [
    {
      kind: "text",
      x: pxToInch(frame.x),
      y: pxToInch(frame.y),
      w: pxToInch(frame.w),
      h: pxToInch(frame.h),
      // Just above host chrome; sibling deco/shapes collected later stay on top
      z: snap.z + 0.1,
      text: bakedToPlain(baked),
      runs: bakedToRuns(baked),
      valign,
      ...baseStyle,
      align: textAlign,
      margin,
      rotate: !vert && hasRotate ? rotate : undefined,
      vert,
    },
  ];
}
