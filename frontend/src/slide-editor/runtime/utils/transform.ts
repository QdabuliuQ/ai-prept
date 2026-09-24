/**
 * Free-move transforms for slide editing.
 * Keep elements in document flow: position:relative + left/top offsets
 * (never promote to absolute / reparent).
 */

export type ElementTransform = {
  left: number;
  top: number;
  width: number;
  height: number;
  rotation?: number;
  /** When false, keep current width/height (move/rotate only) */
  resize?: boolean;
};

const ATTR_REL = "data-editor-rel";
const ATTR_ORIGIN_LEFT = "data-editor-ox";
const ATTR_ORIGIN_TOP = "data-editor-oy";
const ATTR_ROTATION = "data-editor-rotation";
const ATTR_BASE = "data-editor-base-tf";
/** Legacy — cleaned on persist; no longer written */
const ATTR_PROMOTED = "data-editor-promoted";
/** Ancestors whose overflow was forced visible during edit */
const ATTR_OVERFLOW = "data-editor-overflow";

function stripEditorBits(transform: string): string {
  if (!transform || transform === "none") return "";
  return transform
    .replace(/translate3d\([^)]*\)/gi, "")
    .replace(/translateZ\([^)]*\)/gi, "")
    .replace(/translateY\([^)]*\)/gi, "")
    .replace(/translateX\([^)]*\)/gi, "")
    .replace(/translate\([^)]*\)/gi, "")
    .replace(/rotate\([^)]*\)/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

function extractTransformScale(element: HTMLElement): {
  scaleX: number;
  scaleY: number;
} {
  const styles = window.getComputedStyle(element);
  const transform = styles.transform || "";
  if (!transform || transform === "none") {
    return { scaleX: 1, scaleY: 1 };
  }
  if (transform.startsWith("matrix3d(")) {
    const values = transform
      .match(/matrix3d\(([^)]+)\)/)?.[1]
      .split(",")
      .map(parseFloat);
    if (values && values.length >= 16) {
      const scaleX = Math.hypot(values[0], values[1], values[2]);
      const scaleY = Math.hypot(values[4], values[5], values[6]);
      return { scaleX: scaleX || 1, scaleY: scaleY || 1 };
    }
  }
  if (transform.startsWith("matrix(")) {
    const values = transform
      .match(/matrix\(([^)]+)\)/)?.[1]
      .split(",")
      .map(parseFloat);
    if (values && values.length >= 6) {
      const [a, b, c, d] = values;
      return {
        scaleX: Math.hypot(a, b) || 1,
        scaleY: Math.hypot(c, d) || 1,
      };
    }
  }
  return { scaleX: 1, scaleY: 1 };
}

export function extractRotationDeg(element: HTMLElement): number {
  const styles = window.getComputedStyle(element);
  const transform = styles.transform || "";
  if (!transform || transform === "none") return 0;
  if (transform.startsWith("matrix(")) {
    const values = transform
      .match(/matrix\(([^)]+)\)/)?.[1]
      .split(",")
      .map(parseFloat);
    if (values && values.length >= 6) {
      const [a, b] = values;
      return (Math.atan2(b, a) * 180) / Math.PI;
    }
  }
  if (transform.startsWith("matrix3d(")) {
    const values = transform
      .match(/matrix3d\(([^)]+)\)/)?.[1]
      .split(",")
      .map(parseFloat);
    if (values && values.length >= 16) {
      return (Math.atan2(values[1], values[0]) * 180) / Math.PI;
    }
  }
  return 0;
}

/**
 * Unrotated layout box in viewport coords — must match SelectionOverlay / drag box.
 * Do NOT use getBoundingClientRect AABB here when the element is rotated; AABB ≠ box.
 */
export function getUnrotatedViewportBox(element: HTMLElement | SVGSVGElement): {
  left: number;
  top: number;
  width: number;
  height: number;
  rotation: number;
} {
  const el = element as HTMLElement;
  const { scaleX, scaleY } = extractTransformScale(el);
  const boundingRect = element.getBoundingClientRect();
  const ow = element instanceof HTMLElement ? element.offsetWidth : 0;
  const oh = element instanceof HTMLElement ? element.offsetHeight : 0;
  const width = ow > 0 ? ow * scaleX : boundingRect.width;
  const height = oh > 0 ? oh * scaleY : boundingRect.height;
  const centerX = boundingRect.left + boundingRect.width / 2;
  const centerY = boundingRect.top + boundingRect.height / 2;
  return {
    left: centerX - width / 2,
    top: centerY - height / 2,
    width,
    height,
    rotation: extractRotationDeg(el),
  };
}

/** Slide root: prefer .slide / [data-slide] / large first child, else body. */
export function getSlideRoot(): HTMLElement {
  const doc = document;
  const explicit =
    (doc.querySelector(".slide-container") as HTMLElement | null) ||
    (doc.querySelector(".slide") as HTMLElement | null) ||
    (doc.querySelector("[data-slide]") as HTMLElement | null) ||
    (doc.querySelector("main") as HTMLElement | null);
  if (explicit) return explicit;

  const body = doc.body;
  const first = body?.firstElementChild as HTMLElement | null;
  if (
    first &&
    (first.offsetWidth >= 800 || first.getBoundingClientRect().width >= 800)
  ) {
    return first;
  }
  return body;
}

/**
 * Outermost canvas / document chrome — must not be selected or free-transformed.
 */
export function isSlideShellElement(
  element: Element | null | undefined,
): boolean {
  if (!element) return true;
  if (element === document.documentElement || element === document.body) {
    return true;
  }

  let root: HTMLElement;
  try {
    root = getSlideRoot();
  } catch {
    return false;
  }

  if (element === root) return true;

  const parent = element.parentElement;
  if (parent === document.body || parent === root) {
    const er = element.getBoundingClientRect();
    const rr = root.getBoundingClientRect();
    if (rr.width >= 800 && rr.height >= 450 && er.width > 0 && er.height > 0) {
      const coverage = (er.width * er.height) / (rr.width * rr.height);
      if (coverage >= 0.9) {
        const siblings = Array.from(parent.children).filter((child) => {
          if (child === element || !(child instanceof Element)) return false;
          if (child.getAttribute("data-injected") === "true") return false;
          if (child.getAttribute("data-editor-placeholder") === "true") {
            return false;
          }
          const r = child.getBoundingClientRect();
          return r.width > 24 && r.height > 24;
        });
        if (siblings.length === 0) return true;
      }
    }
  }

  return false;
}

/**
 * Cards / layout containers with overflow:hidden clip relative-offset children.
 * Force ancestors (below slide root) to overflow:visible so drag stays visible.
 * Slide root / body / html keep their clip (1920×1080 canvas).
 */
function releaseAncestorOverflow(element: HTMLElement): void {
  const root = getSlideRoot();
  let node: HTMLElement | null = element.parentElement;

  while (
    node &&
    node !== root &&
    node !== document.body &&
    node !== document.documentElement
  ) {
    if (node.getAttribute(ATTR_OVERFLOW) !== "1") {
      const cs = window.getComputedStyle(node);
      const ox = cs.overflowX;
      const oy = cs.overflowY;
      const needsRelease =
        ox === "hidden" ||
        ox === "auto" ||
        ox === "scroll" ||
        oy === "hidden" ||
        oy === "auto" ||
        oy === "scroll" ||
        cs.overflow === "hidden" ||
        cs.overflow === "auto" ||
        cs.overflow === "scroll";

      if (needsRelease) {
        node.setAttribute(ATTR_OVERFLOW, "1");
        node.style.overflow = "visible";
        node.style.overflowX = "visible";
        node.style.overflowY = "visible";
      }
    }
    node = node.parentElement;
  }
}

/**
 * Enter relative-offset mode once.
 * Origin must be derived from the *same* unrotated viewport box that selection
 * reports — using AABB (getBoundingClientRect) breaks rotated / writing-mode nodes.
 *
 * Also bakes `top:50%` + `translateY(-50%)` (etc.) into plain left/top px so
 * stripping centering translates does not jump the element.
 */
function ensureRelativeOffsetMode(element: HTMLElement): void {
  if (element.getAttribute(ATTR_REL) === "true") return;

  const cs = window.getComputedStyle(element);
  const pos = cs.position;
  const before = getUnrotatedViewportBox(element);
  const base = stripEditorBits(element.style.transform || "");

  if (pos === "static") {
    element.style.position = "relative";
  }

  // Drop translate*/rotate from inline AND override stylesheet transform for bake.
  element.style.transform = base || "none";
  element.style.right = "auto";
  element.style.bottom = "auto";
  element.style.left = "0px";
  element.style.top = "0px";

  const afterZero = getUnrotatedViewportBox(element);
  const bakedLeft = before.left - afterZero.left;
  const bakedTop = before.top - afterZero.top;
  element.style.left = `${bakedLeft}px`;
  element.style.top = `${bakedTop}px`;
  // Restore base bits only; rotation re-applied from selection box
  element.style.transform = base;

  // origin so that box.left - origin === style.left
  const originLeft = before.left - bakedLeft;
  const originTop = before.top - bakedTop;

  element.setAttribute(ATTR_BASE, base);
  element.setAttribute(ATTR_ORIGIN_LEFT, String(originLeft));
  element.setAttribute(ATTR_ORIGIN_TOP, String(originTop));
  element.setAttribute(ATTR_REL, "true");
  element.style.transformOrigin = "center center";
}

function applyRelativeBox(element: HTMLElement, box: ElementTransform): void {
  ensureRelativeOffsetMode(element);
  releaseAncestorOverflow(element);

  const originLeft = Number.parseFloat(
    element.getAttribute(ATTR_ORIGIN_LEFT) || "0",
  );
  const originTop = Number.parseFloat(
    element.getAttribute(ATTR_ORIGIN_TOP) || "0",
  );

  const offsetLeft = box.left - originLeft;
  const offsetTop = box.top - originTop;

  element.style.left = `${offsetLeft}px`;
  element.style.top = `${offsetTop}px`;
  element.style.right = "auto";
  element.style.bottom = "auto";

  if (box.resize === true) {
    const cs = window.getComputedStyle(element);
    if (cs.display === "inline") {
      element.style.display = "inline-block";
    }
    element.style.width = `${Math.max(4, box.width)}px`;
    element.style.height = `${Math.max(4, box.height)}px`;
    element.style.boxSizing = "border-box";
  }

  const rotation = box.rotation ?? 0;
  const base =
    element.getAttribute(ATTR_BASE) ||
    stripEditorBits(element.style.transform || "");
  const parts: string[] = [];
  if (base) parts.push(base);
  if (Math.abs(rotation) > 0.01) parts.push(`rotate(${rotation}deg)`);
  element.style.transform = parts.length ? parts.join(" ") : "";
  element.style.transformOrigin = "center center";
  element.setAttribute(ATTR_ROTATION, String(rotation));
}

/**
 * Apply editor box via relative offsets (in-flow). Slide shell is ignored.
 */
export function applyElementTransform(
  element: HTMLElement | SVGSVGElement,
  box: ElementTransform,
): void {
  if (isSlideShellElement(element as HTMLElement)) {
    console.warn(
      "[slide-editor] refuse transform on slide shell",
      element.tagName,
      (element as HTMLElement).className,
    );
    return;
  }
  applyRelativeBox(element as HTMLElement, box);
}

export const EDITOR_TRANSFORM_ATTRS = [
  ATTR_ORIGIN_LEFT,
  ATTR_ORIGIN_TOP,
  ATTR_BASE,
  ATTR_ROTATION,
  ATTR_REL,
  ATTR_PROMOTED,
  ATTR_OVERFLOW,
  "data-editor-eid",
] as const;
