import { boxRelativeTo, isDefaultInlineTag, isElementNode, isInlineishDisplay, parsePx } from "./lib/dom";
import { isTransparent } from "./lib/color";
import type { DomSnapshot } from "./types";

/** True inline flow only — NOT flex/grid items that were blockified. */
function isTrueInline(el: Element, win: Window): boolean {
  const display = win.getComputedStyle(el).display;
  if (display === "none") return false;
  if (isInlineishDisplay(display)) return true;
  // Tag defaults to inline but flex/grid item computes as block — treat as independent
  if (display === "block" || display === "flex" || display === "grid" || display === "table") {
    return false;
  }
  return isDefaultInlineTag(el.tagName);
}

function hasDirectText(el: Element): boolean {
  for (const child of Array.from(el.childNodes)) {
    if (child.nodeType === Node.TEXT_NODE && (child.textContent || "").trim()) {
      return true;
    }
  }
  return false;
}

function hasTextThroughInlines(el: Element, win: Window, depth = 0): boolean {
  if (depth > 6) return false;
  for (const child of Array.from(el.childNodes)) {
    if (child.nodeType === Node.TEXT_NODE && (child.textContent || "").trim()) {
      return true;
    }
    if (child.nodeType !== Node.ELEMENT_NODE) continue;
    const childEl = child as Element;
    const tag = childEl.tagName.toUpperCase();
    if (tag === "BR" || tag === "IMG" || tag === "SVG" || tag === "CANVAS") continue;
    if (!isTrueInline(childEl, win)) continue;
    if (hasTextThroughInlines(childEl, win, depth + 1)) return true;
  }
  return false;
}

function isRenderable(el: Element, styles: CSSStyleDeclaration, win: Window): boolean {
  const tag = el.tagName.toUpperCase();
  if (tag === "IMG" || tag === "SVG" || tag === "CANVAS" || tag === "VIDEO") return true;
  // Materialized ::before/::after stand-ins (flex bullets etc.)
  if (el.hasAttribute("data-h2p-pseudo")) {
    if (!isTransparent(styles.backgroundColor)) return true;
    if (styles.backgroundImage && styles.backgroundImage !== "none") return true;
    if (
      parsePx(styles.borderTopWidth) > 0 ||
      parsePx(styles.borderRightWidth) > 0 ||
      parsePx(styles.borderBottomWidth) > 0 ||
      parsePx(styles.borderLeftWidth) > 0
    ) {
      return true;
    }
    // Sized deco with radius but unresolved paint — still emit as shape host
    const w = el.getBoundingClientRect().width;
    const h = el.getBoundingClientRect().height;
    if (w >= 0.5 && h >= 0.5) return true;
  }
  if (!isTransparent(styles.backgroundColor)) return true;
  if (styles.backgroundImage && styles.backgroundImage !== "none") return true;
  if (styles.boxShadow && styles.boxShadow !== "none") return true;
  if (
    parsePx(styles.borderTopWidth) > 0 ||
    parsePx(styles.borderRightWidth) > 0 ||
    parsePx(styles.borderBottomWidth) > 0 ||
    parsePx(styles.borderLeftWidth) > 0
  ) {
    return true;
  }
  if (hasDirectText(el)) return true;
  if (hasTextThroughInlines(el, win)) return true;
  return false;
}

function isVisible(
  box: { w: number; h: number },
  styles: CSSStyleDeclaration,
): boolean {
  if (box.w < 0.5 || box.h < 0.5) return false;
  if (styles.display === "none") return false;
  if (styles.visibility === "hidden") return false;
  if (Number.parseFloat(styles.opacity || "1") <= 0.01) return false;
  return true;
}

/**
 * Effective CSS z-index for paint order.
 * Descendants of a positioned z-index:N ancestor must sort with that stack
 * level — otherwise static text inside a z-index:1 card paints under the card fill.
 */
function effectiveCssZ(el: Element, styles: CSSStyleDeclaration): number {
  let best = 0;
  const consider = (s: CSSStyleDeclaration) => {
    const pos = s.position || "static";
    if (
      pos !== "relative" &&
      pos !== "absolute" &&
      pos !== "fixed" &&
      pos !== "sticky"
    ) {
      return;
    }
    const raw = s.zIndex;
    if (!raw || raw === "auto") return;
    const n = Number.parseInt(raw, 10);
    if (Number.isFinite(n)) best = Math.max(best, n);
  };
  consider(styles);
  let p = el.parentElement;
  const doc = el.ownerDocument;
  const win = doc.defaultView;
  while (p && win) {
    consider(win.getComputedStyle(p));
    p = p.parentElement;
  }
  return best;
}

/**
 * Paint order key: stacking level dominates, then DOM order.
 * Matches HTML enough for slide deco (z-index:0) under content (z-index:1/2).
 */
function paintOrderKey(
  el: Element,
  styles: CSSStyleDeclaration,
  seq: number,
): number {
  return effectiveCssZ(el, styles) * 1_000_000 + seq;
}

/** Walk slide DOM → paint candidates (CSS z-index + document order). */
export function collectDom(slideRoot: HTMLElement): DomSnapshot[] {
  const out: DomSnapshot[] = [];
  const win = slideRoot.ownerDocument.defaultView;
  if (!win) return out;
  let seq = 0;

  const walk = (el: Element) => {
    const styles = win.getComputedStyle(el);
    if (styles.display === "none") return;

    if (styles.display === "contents") {
      for (const child of Array.from(el.children)) walk(child);
      return;
    }

    const box = boxRelativeTo(el, slideRoot);
    if (isVisible(box, styles) && isRenderable(el, styles, win)) {
      const tag = el.tagName.toUpperCase();
      out.push({
        el,
        tag,
        box,
        z: paintOrderKey(el, styles, seq++),
        styles,
        src:
          tag === "IMG"
            ? (el as HTMLImageElement).currentSrc || (el as HTMLImageElement).src
            : undefined,
      });
    }

    // Inline SVG is rasterized as a whole — don't collect inner <svg> fragments.
    if (el.tagName.toUpperCase() === "SVG") return;

    for (const child of Array.from(el.children)) walk(child);
  };

  walk(slideRoot);
  return out;
}

/**
 * Skip text on this node when an ancestor already owns the same inline flow,
 * OR when this is a flex/grid wrapper whose children export text themselves.
 */
export function shouldSkipTextExport(
  el: Element,
  collected: Set<Element>,
): boolean {
  const win = el.ownerDocument.defaultView;
  if (!win) return false;

  // Nested true-inline under a collected ancestor
  if (isTrueInline(el, win)) {
    let p = el.parentElement;
    while (p) {
      if (collected.has(p)) {
        // Chip / badge pattern: <div class="pill"><span>标签</span></div>
        // Parent skips its own text (delegates to children) AND child was skipped
        // because parent is collected → empty pink pill in PPTX.
        // Only skip when the ancestor will actually bake this text itself.
        if (skipsOwnTextAsWrapper(p, collected, win)) {
          return false;
        }
        return true;
      }
      p = p.parentElement;
    }
  }

  // Flex/grid/block wrappers: if every text-bearing child is separately
  // collected, do NOT also bake their text onto the parent (fixes card-metric).
  if (skipsOwnTextAsWrapper(el, collected, win)) return true;

  return false;
}

/**
 * Parent is a layout/chrome wrapper that will not emit text of its own
 * because every text-bearing child is collected separately.
 */
function skipsOwnTextAsWrapper(
  el: Element,
  collected: Set<Element>,
  win: Window,
): boolean {
  const display = win.getComputedStyle(el).display;
  if (
    display !== "flex" &&
    display !== "inline-flex" &&
    display !== "grid" &&
    display !== "inline-grid" &&
    display !== "block" &&
    display !== "inline-block"
  ) {
    return false;
  }
  if (hasDirectText(el)) return false;
  const kids = Array.from(el.children);
  if (!kids.length) return false;
  let textKids = 0;
  let covered = 0;
  for (const kid of kids) {
    if (!isElementNode(kid)) continue;
    const ks = win.getComputedStyle(kid);
    if (ks.display === "none") continue;
    const hasText =
      hasDirectText(kid) ||
      hasTextThroughInlines(kid, win) ||
      !!(kid.textContent || "").trim();
    if (!hasText) continue;
    textKids += 1;
    if (collected.has(kid)) covered += 1;
  }
  return textKids > 0 && covered === textKids;
}

/** @deprecated use shouldSkipTextExport */
export function isNestedInlineHost(el: Element, collected: Set<Element>): boolean {
  return shouldSkipTextExport(el, collected);
}

export { isTrueInline, hasDirectText };
