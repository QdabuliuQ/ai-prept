/**
 * DOM utility functions
 */

function escapeCssIdentifier(value: string): string {
  const cssEscape = globalThis.CSS?.escape;
  if (cssEscape) return cssEscape(value);
  return value.replace(/[^a-zA-Z0-9_-]/g, (char) => `\\${char}`);
}

export const EDITOR_EID_ATTR = "data-editor-eid";

/** HTML nodes + root <svg> (SVG shapes are not HTMLElement). */
export type EditableElement = HTMLElement | SVGSVGElement;

let eidSeq = 0;

export function isEditableElement(
  el: EventTarget | null | undefined,
): el is EditableElement {
  return !!el && (el instanceof HTMLElement || el instanceof SVGSVGElement);
}

/**
 * Map a click/hover target to the editable host.
 * SVG internals (polygon/path/…) resolve to the root <svg>.
 */
export function resolveEditableHost(
  target: EventTarget | null | undefined,
): EditableElement | null {
  if (!target || !(target instanceof Element)) return null;
  if (isInjectedElement(target)) return null;

  if (target instanceof SVGElement) {
    const svg =
      target instanceof SVGSVGElement ? target : target.ownerSVGElement;
    if (svg) return svg;
  }

  if (target instanceof HTMLElement) return target;
  return null;
}

function elementClassName(el: Element): string {
  const cn = el.className as string | SVGAnimatedString;
  if (typeof cn === "string") return cn;
  if (cn && typeof (cn as SVGAnimatedString).baseVal === "string") {
    return (cn as SVGAnimatedString).baseVal;
  }
  return "";
}

/** Stable id so transforms survive across selection refresh. */
export function ensureEditorId(element: Element): string {
  let id = element.getAttribute(EDITOR_EID_ATTR);
  if (id) return id;
  eidSeq += 1;
  id = `eid_${eidSeq}_${Date.now().toString(36)}`;
  element.setAttribute(EDITOR_EID_ATTR, id);
  return id;
}

export function getElementSelector(element: Element): string {
  if (!element || element.nodeType !== Node.ELEMENT_NODE) {
    return "";
  }

  // Prefer stable editor id when present
  const eid = element.getAttribute(EDITOR_EID_ATTR);
  if (eid) {
    return `[${EDITOR_EID_ATTR}="${CSS.escape ? CSS.escape(eid) : eid}"]`;
  }

  if (element === document.documentElement) {
    return "html";
  }

  if (element === document.body) {
    return "body";
  }

  const path: string[] = [];
  let current: Element | null = element;

  while (
    current &&
    current.nodeType === Node.ELEMENT_NODE &&
    current !== document.documentElement &&
    current !== document.body
  ) {
    const currentElement = current;
    let selector = currentElement.tagName.toLowerCase();

    if (currentElement.id) {
      selector += `#${escapeCssIdentifier(currentElement.id)}`;
      path.unshift(selector);
      break;
    }

    const className = elementClassName(currentElement);
    const classes: string[] = [];
    if (className) {
      const classList = className
        .trim()
        .split(/\s+/)
        .filter((cls) => cls && !cls.startsWith("__editor-"));
      classes.push(...classList);
    }

    let baseSelector = selector;
    if (classes.length > 0) {
      baseSelector += classes
        .map((cls) => `.${escapeCssIdentifier(cls)}`)
        .join("");
    }

    const parentElement = currentElement.parentElement;
    if (parentElement) {
      const sameTagSiblings = Array.from(
        parentElement.children as HTMLCollectionOf<Element>,
      ).filter(
        (child) =>
          child.tagName.toLowerCase() === currentElement.tagName.toLowerCase(),
      );

      if (sameTagSiblings.length > 1) {
        const index = sameTagSiblings.indexOf(currentElement) + 1;
        selector = `${baseSelector}:nth-of-type(${index})`;
      } else {
        selector = baseSelector;
      }
    } else {
      selector = baseSelector;
    }

    path.unshift(selector);
    current = parentElement;
  }

  const selectorPath = path.join(" > ");
  if (element.parentElement === document.body && selectorPath) {
    return `body > ${selectorPath}`;
  }

  return selectorPath;
}

export function isInjectedElement(element: Element): boolean {
  if (element.getAttribute("data-injected") === "true") return true;
  if (element.closest('[data-injected="true"]')) return true;
  // 生成中骨架 / 占位 UI：不可选、不可改
  if (element.getAttribute("data-editor-placeholder") === "true") return true;
  if (element.closest('[data-editor-placeholder="true"]')) return true;
  return false;
}

const elementByEid = new Map<string, EditableElement>();

export function rememberEditorElement(element: EditableElement): string {
  const id = ensureEditorId(element);
  elementByEid.set(id, element);
  return id;
}

export function findElement(
  selector?: string | null,
  editorId?: string | null,
): Element | null {
  if (editorId) {
    const cached = elementByEid.get(editorId);
    if (cached && cached.isConnected) return cached;
    try {
      const byAttr = document.querySelector(
        `[${EDITOR_EID_ATTR}="${CSS.escape ? CSS.escape(editorId) : editorId}"]`,
      );
      if (isEditableElement(byAttr)) {
        elementByEid.set(editorId, byAttr);
        return byAttr;
      }
    } catch {
      /* ignore */
    }
  }

  if (!selector) return null;
  try {
    const el = document.querySelector(selector);
    if (isEditableElement(el)) {
      rememberEditorElement(el);
    }
    return el;
  } catch {
    return null;
  }
}
