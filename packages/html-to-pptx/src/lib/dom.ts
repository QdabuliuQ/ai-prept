export function parsePx(v: string | undefined | null): number {
  if (!v) return 0;
  const n = Number.parseFloat(v);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Cross-realm safe: iframe nodes fail `instanceof HTMLElement` against the
 * parent window's constructors (export sandbox uses a hidden iframe).
 */
export function isHTMLElement(node: Node | null | undefined): node is HTMLElement {
  if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
  const view = node.ownerDocument?.defaultView;
  if (view?.HTMLElement) {
    try {
      return node instanceof view.HTMLElement;
    } catch {
      /* fall through */
    }
  }
  return "tagName" in node && "style" in node;
}

export function isElementNode(node: Node | null | undefined): node is Element {
  if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
  const view = node.ownerDocument?.defaultView;
  if (view?.Element) {
    try {
      return node instanceof view.Element;
    } catch {
      /* fall through */
    }
  }
  return "tagName" in node;
}

/** Prefer the element's document view — required for ::before/::after in iframes. */
export function computedStyle(
  el: Element,
  pseudoElt?: string | null,
): CSSStyleDeclaration {
  const view = el.ownerDocument.defaultView;
  if (!view) {
    throw new Error("Element has no defaultView for getComputedStyle");
  }
  return pseudoElt
    ? view.getComputedStyle(el, pseudoElt)
    : view.getComputedStyle(el);
}

export function boxRelativeTo(
  el: Element,
  root: HTMLElement,
): { x: number; y: number; w: number; h: number } {
  const er = el.getBoundingClientRect();
  const rr = root.getBoundingClientRect();
  return {
    x: er.left - rr.left,
    y: er.top - rr.top,
    w: er.width,
    h: er.height,
  };
}

/**
 * CSS transform rotate → degrees (CSS / pptxgen both use clockwise).
 * Handles `rotate(...)` and 2D `matrix` / `matrix3d`.
 */
export function parseCssRotateDeg(transform: string): number | undefined {
  const t = (transform || "").trim();
  if (!t || t === "none") return undefined;

  const rotateMatch = t.match(
    /rotate\(\s*(-?[\d.]+)\s*(deg|rad|turn|grad)?\s*\)/i,
  );
  if (rotateMatch) {
    const n = Number(rotateMatch[1]);
    if (!Number.isFinite(n)) return undefined;
    const unit = (rotateMatch[2] || "deg").toLowerCase();
    if (unit === "rad") return (n * 180) / Math.PI;
    if (unit === "turn") return n * 360;
    if (unit === "grad") return n * 0.9;
    return n;
  }

  const splitNums = (raw: string): number[] =>
    raw
      .split(/[,\s]+/)
      .map((s) => Number(s.trim()))
      .filter((x) => Number.isFinite(x));

  const m2 = t.match(/matrix\(\s*([^)]+)\)/i);
  if (m2) {
    const parts = splitNums(m2[1]);
    // matrix(a, b, c, d, e, f) — atan2(b, a)
    if (parts.length >= 4) {
      return (Math.atan2(parts[1], parts[0]) * 180) / Math.PI;
    }
  }

  const m3 = t.match(/matrix3d\(\s*([^)]+)\)/i);
  if (m3) {
    const parts = splitNums(m3[1]);
    // matrix3d m11,m12,... → atan2(m12, m11)
    if (parts.length >= 2) {
      return (Math.atan2(parts[1], parts[0]) * 180) / Math.PI;
    }
  }

  return undefined;
}

/** Nearest ancestor (incl. self) with a meaningful CSS rotate. */
export function effectiveRotateDeg(
  el: Element,
  maxDepth = 8,
): number | undefined {
  let node: Element | null = el;
  for (let i = 0; i < maxDepth && node; i++) {
    const deg = parseCssRotateDeg(computedStyle(node).transform);
    if (deg != null && Math.abs(deg) >= 0.5) return deg;
    const attr = node.getAttribute("data-rotate");
    if (attr != null && attr !== "") {
      const n = Number(attr);
      if (Number.isFinite(n) && Math.abs(n) >= 0.5) return n;
    }
    node = node.parentElement;
  }
  return undefined;
}

/** Linear part of CSS matrix(a, b, c, d, tx, ty) / canvas transform(). */
export type CssLinear = { a: number; b: number; c: number; d: number };

export function mulCssLinear(p: CssLinear, q: CssLinear): CssLinear {
  return {
    a: p.a * q.a + p.c * q.b,
    b: p.b * q.a + p.d * q.b,
    c: p.a * q.c + p.c * q.d,
    d: p.b * q.c + p.d * q.d,
  };
}

export function parseCssMatrix2d(transform: string): CssLinear | null {
  const t = (transform || "").trim();
  if (!t || t === "none") return null;
  const m2 = t.match(/matrix\(\s*([^)]+)\)/i);
  if (m2) {
    const parts = m2[1]
      .split(/[,\s]+/)
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n));
    if (parts.length >= 4) {
      return { a: parts[0], b: parts[1], c: parts[2], d: parts[3] };
    }
  }
  const m3 = t.match(/matrix3d\(\s*([^)]+)\)/i);
  if (m3) {
    const parts = m3[1]
      .split(/[,\s]+/)
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n));
    // m11, m12, m13, m14, m21, m22 → a=m11, b=m12, c=m21, d=m22
    if (parts.length >= 6) {
      return { a: parts[0], b: parts[1], c: parts[4], d: parts[5] };
    }
  }
  return null;
}

export function isIdentityLinear(m: CssLinear, eps = 0.002): boolean {
  return (
    Math.abs(m.a - 1) < eps &&
    Math.abs(m.b) < eps &&
    Math.abs(m.c) < eps &&
    Math.abs(m.d - 1) < eps
  );
}

/**
 * Combined 2D CSS transform (linear part) from `el` up through `root`.
 * Parent matrices multiply on the left (same as CSS paint).
 */
export function combinedCssLinear(el: Element, root: Element): CssLinear {
  let m: CssLinear = { a: 1, b: 0, c: 0, d: 1 };
  const chain: Element[] = [];
  let node: Element | null = el;
  while (node) {
    chain.push(node);
    if (node === root) break;
    node = node.parentElement;
  }
  for (const item of chain.reverse()) {
    try {
      const next = parseCssMatrix2d(computedStyle(item).transform);
      if (next) m = mulCssLinear(m, next);
    } catch {
      /* ignore */
    }
  }
  return m;
}

/** Uniform CSS transform scale (ignore rotate/flip). matrix(a,b,…) → hypot(a,b). */
export function cssTransformScale(transform: string): number {
  const t = (transform || "").trim();
  if (!t || t === "none") return 1;

  const m2 = t.match(/matrix\(\s*([^)]+)\)/i);
  if (m2) {
    const parts = m2[1]
      .split(/[,\s]+/)
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n));
    if (parts.length >= 4) {
      const s = Math.hypot(parts[0], parts[1]);
      return s > 0.01 ? s : 1;
    }
  }

  const m3 = t.match(/matrix3d\(\s*([^)]+)\)/i);
  if (m3) {
    const parts = m3[1]
      .split(/[,\s]+/)
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n));
    if (parts.length >= 2) {
      const s = Math.hypot(parts[0], parts[1]);
      return s > 0.01 ? s : 1;
    }
  }

  const sc = t.match(/scale\(\s*(-?[\d.]+)/i);
  if (sc) {
    const n = Math.abs(Number(sc[1]));
    return n > 0.01 ? n : 1;
  }
  return 1;
}

/**
 * Product of CSS transform scales from `el` up through `root`.
 * Transforms do not change computed font-size / offsetWidth — export must
 * multiply those by this factor (e.g. converted decks wrap 1280 in scale(1.5)).
 */
export function ancestorCssScale(el: Element, root: Element): number {
  let s = 1;
  let node: Element | null = el;
  while (node) {
    try {
      const k = cssTransformScale(computedStyle(node).transform);
      if (Math.abs(k - 1) > 0.001) s *= k;
    } catch {
      /* no view */
    }
    if (node === root) break;
    node = node.parentElement;
  }
  return s > 0.01 ? s : 1;
}

/**
 * Layout box relative to slide root. When rotated, returns the *unrotated*
 * size/position (center-preserving) so pptxgen `rotate` is not double-applied
 * on top of getBoundingClientRect's AABB.
 */
export function layoutBoxRelativeTo(
  el: Element,
  root: HTMLElement,
  rotateDeg?: number,
): { x: number; y: number; w: number; h: number } {
  const er = el.getBoundingClientRect();
  const rr = root.getBoundingClientRect();
  const rot =
    rotateDeg ?? parseCssRotateDeg(computedStyle(el).transform);
  if (rot == null || Math.abs(rot) < 0.5) {
    return {
      x: er.left - rr.left,
      y: er.top - rr.top,
      w: er.width,
      h: er.height,
    };
  }

  const html = isHTMLElement(el) ? el : null;
  const scale = ancestorCssScale(el, root);
  let w = (html?.offsetWidth ?? 0) * scale;
  let h = (html?.offsetHeight ?? 0) * scale;
  if (w < 0.5 || h < 0.5) {
    const rad = (Math.abs(rot) * Math.PI) / 180;
    const c = Math.abs(Math.cos(rad));
    const s = Math.abs(Math.sin(rad));
    const denom = c * c - s * s;
    if (Math.abs(denom) > 0.05) {
      w = (er.width * c - er.height * s) / denom;
      h = (er.height * c - er.width * s) / denom;
    } else {
      w = er.width / Math.max(c + s, 0.01);
      h = er.height / Math.max(c + s, 0.01);
    }
    w = Math.max(1, w);
    h = Math.max(1, h);
  }

  const cx = er.left + er.width / 2;
  const cy = er.top + er.height / 2;
  return {
    x: cx - w / 2 - rr.left,
    y: cy - h / 2 - rr.top,
    w,
    h,
  };
}

export function isInlineishDisplay(display: string): boolean {
  return (
    display === "inline" ||
    display === "inline-block" ||
    display === "inline-flex" ||
    display === "inline-grid" ||
    display === "contents"
  );
}

const INLINE_TAGS = new Set([
  "SPAN",
  "STRONG",
  "EM",
  "B",
  "I",
  "U",
  "SMALL",
  "MARK",
  "A",
  "LABEL",
  "CODE",
  "S",
  "SUB",
  "SUP",
]);

export function isDefaultInlineTag(tag: string): boolean {
  return INLINE_TAGS.has(tag.toUpperCase());
}

function parseClipCoord(
  token: string,
  axisSize: number,
): number | null {
  const t = token.trim();
  if (!t) return null;
  if (t.endsWith("%")) {
    const n = Number.parseFloat(t);
    return Number.isFinite(n) ? n / 100 : null;
  }
  const n = Number.parseFloat(t);
  if (!Number.isFinite(n)) return null;
  if (t.endsWith("px") || axisSize <= 0) {
    return axisSize > 0 ? n / axisSize : null;
  }
  return axisSize > 0 ? n / axisSize : null;
}

/** Parse CSS `clip-path: polygon(...)` into normalized 0–1 points. */
export function parseCssClipPolygon(
  clipPath: string,
  refW: number,
  refH: number,
): { x: number; y: number }[] | null {
  const raw = (clipPath || "").trim();
  if (!raw || raw === "none") return null;
  const match = raw.match(/polygon\s*\(\s*([^)]+)\s*\)/i);
  if (!match) return null;

  const pts: { x: number; y: number }[] = [];
  for (const pair of match[1].split(",")) {
    const parts = pair.trim().split(/\s+/).filter(Boolean);
    if (parts.length < 2) continue;
    const x = parseClipCoord(parts[0], refW);
    const y = parseClipCoord(parts[1], refH);
    if (x == null || y == null) continue;
    pts.push({ x, y });
  }
  return pts.length >= 3 ? pts : null;
}

function cssClipPathValue(styles: CSSStyleDeclaration): string {
  const clip = (styles.clipPath || "").trim();
  if (clip && clip !== "none") return clip;
  const webkit = (styles as CSSStyleDeclaration & { webkitClipPath?: string })
    .webkitClipPath;
  return (webkit || "").trim();
}

/** Nearest ancestor (or self) with a polygon clip-path, up to slide root. */
export function findClipPathHost(
  el: HTMLElement,
  slideRoot: HTMLElement,
): { host: HTMLElement; polygon: { x: number; y: number }[] } | null {
  let cur: HTMLElement | null = el;
  while (cur && cur !== slideRoot) {
    const styles = computedStyle(cur);
    const hostW = cur.offsetWidth || cur.clientWidth;
    const hostH = cur.offsetHeight || cur.clientHeight;
    const polygon = parseCssClipPolygon(
      cssClipPathValue(styles),
      hostW,
      hostH,
    );
    if (polygon) return { host: cur, polygon };
    cur = cur.parentElement;
  }
  return null;
}

/** Position/size of an img inside its clip host (layout px, includes absolute offset). */
export function imageDrawInClipHost(
  img: HTMLImageElement,
  host: HTMLElement,
): { drawX: number; drawY: number; drawW: number; drawH: number } {
  const styles = computedStyle(img);
  const hostRect = host.getBoundingClientRect();
  const imgRect = img.getBoundingClientRect();
  const drawW =
    imgRect.width || parsePx(styles.width) || img.offsetWidth || hostRect.width;
  const drawH =
    imgRect.height || parsePx(styles.height) || img.offsetHeight || hostRect.height;
  return {
    drawX: imgRect.left - hostRect.left,
    drawY: imgRect.top - hostRect.top,
    drawW: Math.max(1, drawW),
    drawH: Math.max(1, drawH),
  };
}

export function waitFrames(n = 1): Promise<void> {
  return new Promise((resolve) => {
    const step = (left: number) => {
      if (left <= 0) {
        resolve();
        return;
      }
      requestAnimationFrame(() => step(left - 1));
    };
    step(n);
  });
}
