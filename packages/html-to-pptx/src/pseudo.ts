/**
 * Turn decorative ::before / ::after into real DOM nodes (shapes / text).
 *
 * - Out-of-flow (absolute/fixed): place without retargeting absolute descendants.
 * - In-flow (flex item bullets, inline markers): insert as a real child so flex/gap
 *   layout is preserved — common for `li::before` dots with `content:""`.
 */

import { computedStyle, isHTMLElement, parsePx } from "./lib/dom";

function hasPaint(cs: CSSStyleDeclaration): boolean {
  if (!isTransparentBg(cs.backgroundColor)) return true;
  if (cs.backgroundImage && cs.backgroundImage !== "none") return true;
  if (cs.boxShadow && cs.boxShadow !== "none") return true;
  return (
    parsePx(cs.borderTopWidth) > 0 ||
    parsePx(cs.borderRightWidth) > 0 ||
    parsePx(cs.borderBottomWidth) > 0 ||
    parsePx(cs.borderLeftWidth) > 0
  );
}

function isTransparentBg(bg: string): boolean {
  const c = (bg || "").trim().toLowerCase();
  if (!c || c === "transparent") return true;
  if (c === "rgba(0, 0, 0, 0)") return true;
  // Modern: rgba(0 0 0 / 0) or rgb(0 0 0 / 0%)
  if (c.endsWith(", 0)") || /\/\s*0%?\s*\)$/.test(c)) return true;
  return false;
}

function contentIsNone(content: string): boolean {
  const c = (content || "").trim().toLowerCase();
  return !c || c === "none" || c === "normal" || c === "initial";
}

/** `content:""` still generates a box — browsers report `""`, `''`, or empty. */
function isEmptyGeneratedContent(content: string): boolean {
  const c = (content || "").trim();
  if (!c) return true;
  if (c === '""' || c === "''") return true;
  if (
    (c.startsWith('"') && c.endsWith('"') && c.length === 2) ||
    (c.startsWith("'") && c.endsWith("'") && c.length === 2)
  ) {
    return true;
  }
  return false;
}

/** Parse CSS content string → visible text (or null for empty / none). */
export function parseContentValue(content: string): string | null {
  let value = (content || "").trim();
  if (contentIsNone(value)) return null;
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    value = value.slice(1, -1);
  }
  if (!value) return null;
  // CSS escapes like \2022
  if (value.startsWith("\\")) {
    const hex = value.slice(1).replace(/\s.*/, "");
    const codePoint = Number.parseInt(hex, 16);
    if (!Number.isNaN(codePoint)) return String.fromCodePoint(codePoint);
  }
  return value;
}

/** Used size from width/height or flex-basis (common for `flex:0 0 10px` bullets). */
function resolvePseudoSize(cs: CSSStyleDeclaration): { w: number; h: number } {
  let w = cs.width === "auto" ? 0 : parsePx(cs.width);
  let h = cs.height === "auto" ? 0 : parsePx(cs.height);
  const basis = cs.flexBasis && cs.flexBasis !== "auto" ? parsePx(cs.flexBasis) : 0;
  if (w <= 0 && basis > 0) w = basis;
  if (h <= 0 && basis > 0) h = basis;
  // min-width / min-height fallbacks
  if (w <= 0) w = parsePx(cs.minWidth);
  if (h <= 0) h = parsePx(cs.minHeight);
  return { w, h };
}

/**
 * Flex containers with a fixed height can shrink ::before/::after to used
 * height 0px even when the rule says `height: 2px`. Recover non-% lengths
 * from matching stylesheet rules so we don't bake a collapsed size.
 */
function specifiedPseudoLength(
  host: Element,
  which: "::before" | "::after",
  prop: "width" | "height",
): number {
  const doc = host.ownerDocument;
  if (!doc) return 0;
  let found = 0;
  for (const sheet of Array.from(doc.styleSheets)) {
    let rules: CSSRuleList;
    try {
      rules = sheet.cssRules;
    } catch {
      continue;
    }
    for (const rule of Array.from(rules)) {
      if (!(rule instanceof CSSStyleRule)) continue;
      const sel = rule.selectorText || "";
      if (!sel.includes(which)) continue;
      const hostSel = sel
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s.includes(which))
        .map((s) => s.replace(which, "").trim())
        .find(Boolean);
      if (!hostSel) continue;
      try {
        if (!host.matches(hostSel)) continue;
      } catch {
        continue;
      }
      const raw = rule.style.getPropertyValue(prop)?.trim();
      if (!raw || raw === "auto" || raw.includes("%")) continue;
      const px = parsePx(raw);
      if (px > 0) found = px;
    }
  }
  return found;
}

function resolvePseudoSizeForHost(
  cs: CSSStyleDeclaration,
  host: Element,
  which: "::before" | "::after",
): { w: number; h: number } {
  const size = resolvePseudoSize(cs);
  if (size.w <= 0) {
    const specW = specifiedPseudoLength(host, which, "width");
    if (specW > 0) size.w = specW;
  }
  if (size.h <= 0) {
    const specH = specifiedPseudoLength(host, which, "height");
    if (specH > 0) size.h = specH;
  }
  return size;
}

function shouldMaterialize(cs: CSSStyleDeclaration): boolean {
  if (cs.display === "none") return false;
  const raw = (cs.content || "").trim();
  // No box at all
  if (contentIsNone(raw) && !isEmptyGeneratedContent(raw)) return false;

  const text = parseContentValue(raw);
  const { w, h } = resolvePseudoSize(cs);
  const hasSize = w > 0 || h > 0;
  const hasInset =
    cs.top !== "auto" ||
    cs.left !== "auto" ||
    cs.right !== "auto" ||
    cs.bottom !== "auto";
  const radius = parsePx(cs.borderRadius) || parsePx(cs.borderTopLeftRadius);
  const looksLikeBullet = hasSize || radius > 0;

  // Textual content (•, icons, counters)
  if (text != null) return true;
  // Empty content "" with paint / size / inset — custom bullets & deco blocks
  if (isEmptyGeneratedContent(raw) || !contentIsNone(raw)) {
    if (hasPaint(cs) || hasSize || hasInset || looksLikeBullet) return true;
  }
  // Some engines report content as none/normal while still painting ::before
  if (hasPaint(cs) && (hasSize || hasInset)) return true;
  return false;
}

function hasAbsDescendant(el: HTMLElement): boolean {
  for (const child of Array.from(el.querySelectorAll("*"))) {
    if (!isHTMLElement(child)) continue;
    const p = computedStyle(child).position;
    if (p === "absolute" || p === "fixed") return true;
  }
  return false;
}

function findPositionedAncestor(el: HTMLElement): HTMLElement | null {
  let p: HTMLElement | null = el.parentElement;
  while (p) {
    if (!isHTMLElement(p)) {
      p = (p as Element).parentElement;
      continue;
    }
    const pos = computedStyle(p).position;
    if (pos !== "static") return p;
    p = p.parentElement;
  }
  return null;
}

function applyPaintStyles(deco: HTMLElement, cs: CSSStyleDeclaration) {
  const bg =
    cs.getPropertyValue("background-color")?.trim() ||
    cs.backgroundColor ||
    "";
  if (bg && !isTransparentBg(bg)) {
    deco.style.setProperty("background-color", bg);
  }
  if (cs.backgroundImage && cs.backgroundImage !== "none") {
    deco.style.backgroundImage = cs.backgroundImage;
    deco.style.backgroundSize = cs.backgroundSize;
    deco.style.backgroundPosition = cs.backgroundPosition;
    deco.style.backgroundRepeat = cs.backgroundRepeat;
  }
  const radius =
    cs.borderRadius ||
    cs.getPropertyValue("border-radius") ||
    cs.borderTopLeftRadius ||
    "";
  if (radius) deco.style.borderRadius = radius;
  if (parsePx(cs.borderTopWidth) > 0) deco.style.borderTop = cs.borderTop;
  if (parsePx(cs.borderRightWidth) > 0) deco.style.borderRight = cs.borderRight;
  if (parsePx(cs.borderBottomWidth) > 0) deco.style.borderBottom = cs.borderBottom;
  if (parsePx(cs.borderLeftWidth) > 0) deco.style.borderLeft = cs.borderLeft;
  if (cs.boxShadow && cs.boxShadow !== "none") deco.style.boxShadow = cs.boxShadow;
  if (cs.opacity && cs.opacity !== "1") deco.style.opacity = cs.opacity;
}

function placeDecoAbsolute(
  deco: HTMLElement,
  host: HTMLElement,
  cs: CSSStyleDeclaration,
  slideRoot: HTMLElement,
) {
  const hostRect = host.getBoundingClientRect();
  const anchor = findPositionedAncestor(host) || slideRoot;
  const aRect = anchor.getBoundingClientRect();
  const top = cs.top !== "auto" ? parsePx(cs.top) : 0;
  const left = cs.left !== "auto" ? parsePx(cs.left) : 0;
  const size = resolvePseudoSize(cs);
  const width = size.w > 0 ? size.w : 8;
  const height = size.h > 0 ? size.h : 8;

  deco.style.position = "absolute";
  deco.style.left = `${hostRect.left - aRect.left + left}px`;
  deco.style.top = `${hostRect.top - aRect.top + top}px`;
  deco.style.width = `${width}px`;
  deco.style.height = `${height}px`;
  deco.style.right = "auto";
  deco.style.bottom = "auto";
  deco.style.margin = "0";
  deco.style.pointerEvents = "none";
  deco.style.boxSizing = "border-box";
  // Keep CSS stacking; "auto" → 0 so content with z-index:2 paints above
  deco.style.zIndex = cs.zIndex === "auto" ? "0" : cs.zIndex;
  applyPaintStyles(deco, cs);
  anchor.appendChild(deco);
}

/** In-flow stand-in (flex bullet, inline marker). */
function placeDecoInFlow(
  deco: HTMLElement,
  host: HTMLElement,
  cs: CSSStyleDeclaration,
  which: "::before" | "::after",
  text: string | null,
) {
  deco.style.pointerEvents = "none";
  deco.style.boxSizing = "border-box";
  deco.style.flexShrink = "0";
  deco.style.flexGrow = "0";

  const size = resolvePseudoSizeForHost(cs, host, which);
  // Force block-level box so width/height paint as a shape (not inline collapsed)
  if (text) {
    deco.style.display =
      cs.display === "block" || cs.display === "flex" ? cs.display : "inline-block";
  } else {
    deco.style.display = "block";
  }

  if (size.w > 0) deco.style.width = `${size.w}px`;
  else if (cs.width !== "auto" && parsePx(cs.width) > 0) deco.style.width = cs.width;
  if (size.h > 0) {
    deco.style.height = `${size.h}px`;
    deco.style.minHeight = `${size.h}px`;
  } else if (cs.height !== "auto" && parsePx(cs.height) > 0) {
    deco.style.height = cs.height;
  }

  // flex-basis is the MAIN axis. In row flex that's width (bullets); in column
  // flex it's height — never set basis=width there or a 100%-wide 2px rule
  // becomes a huge square (agenda-header::after).
  const hostDir = (computedStyle(host).flexDirection || "row").toLowerCase();
  const columnHost = hostDir === "column" || hostDir === "column-reverse";
  if (columnHost) {
    if (size.h > 0) deco.style.flexBasis = `${size.h}px`;
  } else if (size.w > 0) {
    deco.style.flexBasis = `${size.w}px`;
  }

  // Margins (li::before often uses margin-top to optically center the dot)
  if (cs.margin && cs.margin !== "0px") deco.style.margin = cs.margin;
  if (parsePx(cs.marginTop)) deco.style.marginTop = cs.marginTop;
  if (parsePx(cs.marginRight)) deco.style.marginRight = cs.marginRight;
  if (parsePx(cs.marginBottom)) deco.style.marginBottom = cs.marginBottom;
  if (parsePx(cs.marginLeft)) deco.style.marginLeft = cs.marginLeft;

  if (cs.alignSelf && cs.alignSelf !== "auto") deco.style.alignSelf = cs.alignSelf;
  applyPaintStyles(deco, cs);

  // Last-resort: empty sized deco with radius but no paint — use host text color
  if (
    !text &&
    size.w > 0 &&
    size.h > 0 &&
    isTransparentBg(deco.style.backgroundColor || "") &&
    isTransparentBg(cs.backgroundColor)
  ) {
    const hostColor = computedStyle(host).color;
    if (hostColor && !isTransparentBg(hostColor)) {
      deco.style.backgroundColor = hostColor;
    }
  }

  if (text) {
    deco.textContent = text;
    deco.style.color = cs.color;
    deco.style.fontSize = cs.fontSize;
    deco.style.fontFamily = cs.fontFamily;
    deco.style.fontWeight = cs.fontWeight;
    deco.style.lineHeight = cs.lineHeight || "1";
    deco.style.whiteSpace = "pre";
  }

  if (which === "::before") host.insertBefore(deco, host.firstChild);
  else host.appendChild(deco);
}

function processPseudo(
  el: HTMLElement,
  which: "::before" | "::after",
  slideRoot: HTMLElement,
): HTMLElement | null {
  let cs: CSSStyleDeclaration;
  try {
    cs = computedStyle(el, which);
  } catch {
    return null;
  }
  if (!shouldMaterialize(cs)) return null;

  const text = parseContentValue(cs.content);
  // Prefer <div> for paint-only bullets so collectors treat them as shapes
  const deco = el.ownerDocument.createElement(text ? "span" : "div");
  deco.setAttribute(
    "data-h2p-pseudo",
    which === "::before" ? "before" : "after",
  );

  const pseudoPos = cs.position;
  const outOfFlow = pseudoPos === "absolute" || pseudoPos === "fixed";

  if (!outOfFlow) {
    placeDecoInFlow(deco, el, cs, which, text);
    return deco;
  }

  const hostPos = computedStyle(el).position;
  const safeToNest = hostPos !== "static" && !hasAbsDescendant(el);

  if (safeToNest) {
    deco.style.position = pseudoPos;
    if (cs.top !== "auto") deco.style.top = cs.top;
    if (cs.left !== "auto") deco.style.left = cs.left;
    if (cs.right !== "auto") deco.style.right = cs.right;
    if (cs.bottom !== "auto") deco.style.bottom = cs.bottom;
    const size = resolvePseudoSize(cs);
    if (size.w > 0) deco.style.width = `${size.w}px`;
    else if (cs.width !== "auto") deco.style.width = cs.width;
    if (size.h > 0) deco.style.height = `${size.h}px`;
    else if (cs.height !== "auto") deco.style.height = cs.height;
    deco.style.pointerEvents = "none";
    deco.style.boxSizing = "border-box";
    deco.style.zIndex = cs.zIndex === "auto" ? "0" : cs.zIndex;
    applyPaintStyles(deco, cs);
    if (text) {
      deco.textContent = text;
      deco.style.color = cs.color;
      deco.style.fontSize = cs.fontSize;
      deco.style.whiteSpace = "pre";
    }
    if (which === "::before") el.insertBefore(deco, el.firstChild);
    else el.appendChild(deco);
  } else {
    if (text) {
      deco.textContent = text;
      deco.style.color = cs.color;
      deco.style.fontSize = cs.fontSize;
      deco.style.whiteSpace = "pre";
    }
    placeDecoAbsolute(deco, el, cs, slideRoot);
  }
  return deco;
}

function processListMarker(li: HTMLElement): HTMLElement | null {
  if (li.hasAttribute("data-h2p-pseudo-host")) return null;
  const cs = computedStyle(li);
  if (cs.position === "absolute" || cs.position === "fixed") return null;
  const type = cs.listStyleType;
  if (!type || type === "none") return null;

  // Skip if ::before already provides a custom bullet
  try {
    const before = computedStyle(li, "::before");
    if (shouldMaterialize(before)) return null;
  } catch {
    /* continue */
  }

  const color = cs.color || "#000";
  const fontSize = parsePx(cs.fontSize) || 16;
  const size = Math.max(6, fontSize * 0.35);
  const doc = li.ownerDocument;

  if (type === "disc" || type === "circle" || type === "square") {
    const mark = doc.createElement("div");
    mark.setAttribute("data-h2p-pseudo", "marker");
    mark.style.display = "block";
    mark.style.width = `${size}px`;
    mark.style.height = `${size}px`;
    mark.style.marginRight = `${fontSize * 0.35}px`;
    mark.style.flexShrink = "0";
    if (type === "disc") {
      mark.style.borderRadius = "50%";
      mark.style.backgroundColor = color;
    } else if (type === "circle") {
      mark.style.borderRadius = "50%";
      mark.style.border = `1px solid ${color}`;
      mark.style.backgroundColor = "transparent";
    } else {
      mark.style.backgroundColor = color;
    }
    li.insertBefore(mark, li.firstChild);
    li.setAttribute("data-h2p-marker-host", "1");
    return mark;
  }

  const parent = li.parentElement;
  if (!parent) return null;
  const siblings = Array.from(parent.children).filter((c) => c.tagName === "LI");
  const idx = siblings.indexOf(li);
  if (idx < 0) return null;
  const start = Number.parseInt(parent.getAttribute("start") || "1", 10) || 1;
  const span = doc.createElement("span");
  span.setAttribute("data-h2p-pseudo", "marker");
  span.textContent = `${start + idx}.`;
  span.style.color = color;
  span.style.fontSize = cs.fontSize;
  span.style.marginRight = `${fontSize * 0.35}px`;
  span.style.display = "inline-block";
  span.style.flexShrink = "0";
  li.insertBefore(span, li.firstChild);
  li.setAttribute("data-h2p-marker-host", "1");
  return span;
}

/** @returns restore function */
export function materializePseudos(slideRoot: HTMLElement): () => void {
  const created: HTMLElement[] = [];
  const doc = slideRoot.ownerDocument;
  const styleId = "html-to-pptx-pseudo-hide";
  if (doc && !doc.getElementById(styleId)) {
    const style = doc.createElement("style");
    style.id = styleId;
    style.textContent = `
[data-h2p-pseudo-host]::before,
[data-h2p-pseudo-host]::after {
  content: none !important;
  display: none !important;
}
[data-h2p-marker-host] {
  list-style: none !important;
}`;
    (doc.head || doc.documentElement).appendChild(style);
  }

  const list = [slideRoot, ...Array.from(slideRoot.querySelectorAll("*"))];
  for (const el of list) {
    if (!isHTMLElement(el)) continue;
    if (el.hasAttribute("data-h2p-pseudo")) continue;

    const before = processPseudo(el, "::before", slideRoot);
    const after = processPseudo(el, "::after", slideRoot);
    if (before || after) {
      el.setAttribute("data-h2p-pseudo-host", "1");
      if (before) created.push(before);
      if (after) created.push(after);
    }

    if (el.tagName === "LI") {
      const mark = processListMarker(el);
      if (mark) created.push(mark);
    }
  }

  return () => {
    for (const node of created) {
      try {
        node.remove();
      } catch {
        /* ignore */
      }
    }
    for (const host of Array.from(
      slideRoot.querySelectorAll(
        "[data-h2p-pseudo-host], [data-h2p-marker-host]",
      ),
    )) {
      host.removeAttribute("data-h2p-pseudo-host");
      host.removeAttribute("data-h2p-marker-host");
    }
  };
}
