/**
 * Slide editor iframe runtime entry.
 * Bundled to public/slide-editor/runtime.js and injected when embed?edit=1.
 */

import { EditorBridge } from "./core/EditorBridge";
import { EventType } from "./core/types";
import { ElementSelector } from "./ElementSelector";
import { ContentCleaner } from "./utils/ContentCleaner";
import { findElement } from "./utils/dom";
import {
  applyElementTransform,
  type ElementTransform,
} from "./utils/transform";

export type SlideEditorApi = {
  destroy: () => void;
};

let bridgeRef: EditorBridge | null = null;

function enableTextEditing(element: HTMLElement): void {
  element.contentEditable = "true";
  element.setAttribute("data-text-editing", "true");
  element.focus();

  const onBlur = () => {
    element.removeEventListener("blur", onBlur);
    bridgeRef?.sendEvent(EventType.CONTENT_CHANGED, {
      reason: "text-blur",
    });
  };
  element.addEventListener("blur", onBlur);
}

function serializeCleanHtml(): string {
  const raw = "<!DOCTYPE html>\n" + document.documentElement.outerHTML;
  return ContentCleaner.cleanDocument(raw);
}

function handleSetTransform(
  payload: unknown,
  elementSelector: ElementSelector,
  opts?: { refresh?: boolean },
): { success: boolean } {
  const data = payload as {
    selector?: string;
    editorId?: string;
    box?: ElementTransform;
    refresh?: boolean;
  };
  if (!data?.box) return { success: false };
  if (!data.editorId && !data.selector) return { success: false };
  const el = findElement(data.selector, data.editorId);
  if (!(el instanceof HTMLElement) && !(el instanceof SVGSVGElement)) {
    console.warn("[slide-editor] SET_ELEMENT_TRANSFORM miss", data);
    return { success: false };
  }
  applyElementTransform(el, data.box);
  if (opts?.refresh || data.refresh) {
    elementSelector.refreshSelection();
  }
  return { success: true };
}

function startSlideEditor(): SlideEditorApi {
  const existing = (
    window as Window & { __WEBPPT_SLIDE_EDITOR__?: SlideEditorApi }
  ).__WEBPPT_SLIDE_EDITOR__;
  if (existing) return existing;

  const bridge = new EditorBridge();
  bridgeRef = bridge;
  const elementSelector = new ElementSelector(bridge);

  elementSelector.setTextEditingCallback((selector) => {
    const el = findElement(selector);
    if (el instanceof HTMLElement) {
      enableTextEditing(el);
    }
  });

  bridge.onRequest("ENTER_SELECTION_MODE", async () => {
    elementSelector.enable();
    return { success: true };
  });

  bridge.onRequest("EXIT_SELECTION_MODE", async () => {
    elementSelector.disable();
    return { success: true };
  });

  bridge.onRequest("CLEAR_SELECTION", async () => {
    elementSelector.clearSelection();
    return { success: true };
  });

  bridge.onRequest("ENABLE_TEXT_EDITING", async (payload: unknown) => {
    const { selector, editorId } = (payload as {
      selector?: string;
      editorId?: string;
    }) || {};
    const el = findElement(selector, editorId);
    if (!(el instanceof HTMLElement)) return { success: false };
    enableTextEditing(el);
    return { success: true };
  });

  bridge.onRequest("GET_CONTENT", async () => {
    return { html: serializeCleanHtml() };
  });

  /** Absolute box write — silent by default (no selection refresh) for smooth drag */
  bridge.onRequest("SET_ELEMENT_TRANSFORM", async (payload: unknown) => {
    return handleSetTransform(payload, elementSelector);
  });

  bridge.onRequest("APPLY_TEXT_STYLE", async (payload: unknown) => {
    const data = (payload || {}) as {
      bold?: boolean | "toggle"
      italic?: boolean | "toggle"
      underline?: boolean | "toggle"
      strike?: boolean | "toggle"
      textAlign?: "left" | "center" | "right"
      color?: string
      fontSize?: number | "increase" | "decrease"
      selector?: string
      editorId?: string
    }
    const { selector, editorId, ...patch } = data
    const result = elementSelector.applyTextStyle(patch, { selector, editorId })
    if (result.success) {
      const html = serializeCleanHtml()
      bridge.sendEvent(EventType.CONTENT_CHANGED, {
        reason: "text-style",
        html,
      })
      return { ...result, html }
    }
    console.warn("[slide-editor] APPLY_TEXT_STYLE applied=0", data)
    return result
  })

  bridge.onRequest("REFRESH_SELECTION", async () => {
    elementSelector.refreshSelection();
    return { success: true };
  });

  bridge.onRequest("COMMIT_CONTENT", async () => {
    const html = serializeCleanHtml();
    bridge.sendEvent(EventType.CONTENT_CHANGED, { reason: "commit", html });
    return { html };
  });

  bridge.onCommand("SET_ELEMENT_TRANSFORM", async (payload: unknown) => {
    return handleSetTransform(payload, elementSelector);
  });

  elementSelector.enable();
  bridge.sendEvent(EventType.EDITOR_READY, {});

  const api: SlideEditorApi = {
    destroy() {
      elementSelector.destroy();
      bridge.destroy();
      bridgeRef = null;
      delete (window as Window & { __WEBPPT_SLIDE_EDITOR__?: SlideEditorApi })
        .__WEBPPT_SLIDE_EDITOR__;
    },
  };

  (
    window as Window & { __WEBPPT_SLIDE_EDITOR__?: SlideEditorApi }
  ).__WEBPPT_SLIDE_EDITOR__ = api;

  return api;
}

startSlideEditor();
