/**
 * Parent-side slide editor protocol (mirrors iframe EditorBridge).
 */

import {
  MESSAGE_PROTOCOL_VERSION,
  MessageCategory,
  type CommandMessage,
  type EventMessage,
  type RequestMessage,
  type ResponseMessage,
} from "@/slide-editor/protocol";

export type SlideRect = {
  top: number;
  left: number;
  width: number;
  height: number;
};

export type SelectedElementInfo = {
  selector: string;
  editorId?: string;
  tagName: string;
  rect: SlideRect;
  rotation?: number;
  isTextElement?: boolean;
  textContent?: string;
  computedStyles?: Record<string, string>;
};

export type ElementTransformBox = {
  left: number;
  top: number;
  width: number;
  height: number;
  rotation?: number;
  /** false = move/rotate only, keep intrinsic size */
  resize?: boolean;
};

type Pending = {
  resolve: (value: unknown) => void;
  reject: (reason?: unknown) => void;
  timer: ReturnType<typeof setTimeout>;
};

function newRequestId(): string {
  return `req_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export type SlideEditorParentHandlers = {
  onReady?: () => void;
  onHover?: (rect: SlideRect | null) => void;
  onSelect?: (info: SelectedElementInfo | null) => void;
  onMultiSelect?: (elements: SelectedElementInfo[]) => void;
  onContentChanged?: (html?: string) => void;
};

/**
 * Talk to the slide iframe editor runtime via postMessage.
 */
export class SlideEditorParentBridge {
  private iframe: HTMLIFrameElement | null = null;
  private pending = new Map<string, Pending>();
  private handlers: SlideEditorParentHandlers;
  private listener: ((event: MessageEvent) => void) | null = null;
  /** While true, ignore hover/select events from iframe (local overlay owns geometry). */
  private suppressSelectionEvents = false;

  constructor(handlers: SlideEditorParentHandlers = {}) {
    this.handlers = handlers;
    this.listener = (event: MessageEvent) => this.onMessage(event);
    window.addEventListener("message", this.listener);
  }

  setIframe(iframe: HTMLIFrameElement | null) {
    this.iframe = iframe;
  }

  setHandlers(handlers: SlideEditorParentHandlers) {
    this.handlers = handlers;
  }

  setSuppressSelectionEvents(suppress: boolean) {
    this.suppressSelectionEvents = suppress;
  }

  destroy() {
    if (this.listener) {
      window.removeEventListener("message", this.listener);
      this.listener = null;
    }
    this.pending.forEach((p) => {
      clearTimeout(p.timer);
      p.reject(new Error("bridge destroyed"));
    });
    this.pending.clear();
    this.iframe = null;
  }

  private onMessage(event: MessageEvent) {
    if (!this.iframe || event.source !== this.iframe.contentWindow) return;
    const message = event.data;
    if (!message || message.version !== MESSAGE_PROTOCOL_VERSION) return;

    if (message.category === MessageCategory.RESPONSE) {
      const res = message as ResponseMessage;
      const pending = this.pending.get(res.requestId);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.pending.delete(res.requestId);
      if (res.success) pending.resolve(res.payload);
      else pending.reject(res.error || new Error("request failed"));
      return;
    }

    if (message.category === MessageCategory.EVENT) {
      this.handleEvent(message as EventMessage);
    }
  }

  private handleEvent(event: EventMessage) {
    switch (event.type) {
      case "EDITOR_READY":
        this.handlers.onReady?.();
        break;
      case "ELEMENT_HOVERED": {
        if (this.suppressSelectionEvents) return;
        const payload = event.payload as { rect?: SlideRect } | undefined;
        this.handlers.onHover?.(payload?.rect ?? null);
        break;
      }
      case "ELEMENT_HOVER_END":
        if (this.suppressSelectionEvents) return;
        this.handlers.onHover?.(null);
        break;
      case "ELEMENT_SELECTED":
        if (this.suppressSelectionEvents) return;
        this.handlers.onSelect?.(event.payload as SelectedElementInfo);
        break;
      case "ELEMENTS_SELECTED": {
        if (this.suppressSelectionEvents) return;
        const payload = event.payload as { elements?: SelectedElementInfo[] };
        this.handlers.onMultiSelect?.(payload?.elements ?? []);
        this.handlers.onSelect?.(null);
        break;
      }
      case "ELEMENTS_DESELECTED":
        if (this.suppressSelectionEvents) return;
        this.handlers.onSelect?.(null);
        this.handlers.onMultiSelect?.([]);
        this.handlers.onHover?.(null);
        break;
      case "CONTENT_CHANGED": {
        const payload = event.payload as { html?: string } | undefined;
        this.handlers.onContentChanged?.(payload?.html);
        break;
      }
      default:
        break;
    }
  }

  request<T = unknown>(type: string, payload?: unknown, timeoutMs = 5000): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      if (!this.iframe?.contentWindow) {
        reject(new Error("iframe not ready"));
        return;
      }
      const requestId = newRequestId();
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error(`timeout: ${type}`));
      }, timeoutMs);

      this.pending.set(requestId, {
        resolve: resolve as (v: unknown) => void,
        reject,
        timer,
      });

      const message: RequestMessage = {
        version: MESSAGE_PROTOCOL_VERSION,
        category: MessageCategory.REQUEST,
        type,
        requestId,
        payload,
        timestamp: Date.now(),
        source: "parent",
      };
      this.iframe.contentWindow.postMessage(message, "*");
    });
  }

  /** Fire-and-forget command — no pending map, no lag from await. */
  notifyCommand(commandType: string, payload?: unknown) {
    if (!this.iframe?.contentWindow) return;
    const message: CommandMessage = {
      version: MESSAGE_PROTOCOL_VERSION,
      category: MessageCategory.COMMAND,
      type: commandType,
      commandType,
      payload,
      timestamp: Date.now(),
      source: "parent",
    };
    this.iframe.contentWindow.postMessage(message, "*");
  }

  enterSelectionMode() {
    return this.request("ENTER_SELECTION_MODE");
  }

  exitSelectionMode() {
    return this.request("EXIT_SELECTION_MODE");
  }

  setElementTransform(
    selector: string,
    box: ElementTransformBox,
    editorId?: string,
  ) {
    this.notifyCommand("SET_ELEMENT_TRANSFORM", { selector, editorId, box });
  }

  applyTextStyle(patch: {
    bold?: boolean | "toggle";
    italic?: boolean | "toggle";
    underline?: boolean | "toggle";
    strike?: boolean | "toggle";
    textAlign?: "left" | "center" | "right";
    color?: string;
    fontSize?: number | "increase" | "decrease";
  }, target?: { selector?: string; editorId?: string }) {
    return this.request<{ success: boolean; applied: number; html?: string }>(
      "APPLY_TEXT_STYLE",
      { ...patch, ...target },
    );
  }

  refreshSelection() {
    return this.request("REFRESH_SELECTION");
  }

  commitContent() {
    return this.request<{ html?: string }>("COMMIT_CONTENT");
  }

  getContent() {
    return this.request<{ html?: string }>("GET_CONTENT");
  }
}
