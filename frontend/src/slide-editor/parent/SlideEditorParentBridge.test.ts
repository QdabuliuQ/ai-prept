import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import {
  SlideEditorParentBridge,
  type SelectedElementInfo,
} from "./SlideEditorParentBridge";
import {
  MESSAGE_PROTOCOL_VERSION,
  MessageCategory,
} from "@/slide-editor/protocol";

function createIframe() {
  const contentWindow = {
    postMessage: vi.fn(),
  };

  return {
    contentWindow,
  } as unknown as HTMLIFrameElement & {
    contentWindow: typeof contentWindow;
  };
}

function dispatchMessage(
  source: object,
  data: unknown,
) {
  window.dispatchEvent(new MessageEvent("message", { source, data }));
}

function responseMessage(
  requestId: string,
  payload: unknown,
  success = true,
) {
  return {
    version: MESSAGE_PROTOCOL_VERSION,
    category: MessageCategory.RESPONSE,
    requestId,
    success,
    payload: success ? payload : undefined,
    error: success ? undefined : new Error("request failed by iframe"),
  };
}

function eventMessage(type: string, payload?: unknown) {
  return {
    version: MESSAGE_PROTOCOL_VERSION,
    category: MessageCategory.EVENT,
    type,
    payload,
  };
}

describe("SlideEditorParentBridge", () => {
  let iframe: ReturnType<typeof createIframe>;
  let bridge: SlideEditorParentBridge;

  beforeEach(() => {
    vi.useFakeTimers();
    iframe = createIframe();
    bridge = new SlideEditorParentBridge();
    bridge.setIframe(iframe);
  });

  afterEach(() => {
    bridge.destroy();
    vi.useRealTimers();
  });

  it("sends a request and resolves it from a matching response", async () => {
    const promise = bridge.request<{ html: string }>("GET_CONTENT", {
      includeMetadata: true,
    });

    expect(iframe.contentWindow.postMessage).toHaveBeenCalledTimes(1);
    const [message, targetOrigin] = iframe.contentWindow.postMessage.mock.calls[0];

    expect(targetOrigin).toBe("*");
    expect(message).toMatchObject({
      version: MESSAGE_PROTOCOL_VERSION,
      category: MessageCategory.REQUEST,
      type: "GET_CONTENT",
      payload: { includeMetadata: true },
      source: "parent",
    });
    expect(typeof message.requestId).toBe("string");
    expect(typeof message.timestamp).toBe("number");

    dispatchMessage(
      iframe.contentWindow,
      responseMessage(message.requestId, { html: "<p>Hello</p>" }),
    );

    await expect(promise).resolves.toEqual({ html: "<p>Hello</p>" });
  });

  it("rejects requests when the iframe is not ready", async () => {
    const notReadyBridge = new SlideEditorParentBridge();

    await expect(notReadyBridge.request("GET_CONTENT")).rejects.toThrow(
      "iframe not ready",
    );

    expect(iframe.contentWindow.postMessage).not.toHaveBeenCalled();
    notReadyBridge.destroy();
  });

  it("rejects a request when the iframe returns an error", async () => {
    const promise = bridge.request("COMMIT_CONTENT");
    const [message] = iframe.contentWindow.postMessage.mock.calls[0];

    dispatchMessage(
      iframe.contentWindow,
      responseMessage(message.requestId, undefined, false),
    );

    await expect(promise).rejects.toThrow("request failed by iframe");
  });

  it("rejects a request after the configured timeout", async () => {
    const promise = bridge.request("REFRESH_SELECTION", undefined, 250);

    vi.advanceTimersByTime(249);
    await Promise.resolve();
    expect(iframe.contentWindow.postMessage).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(1);

    await expect(promise).rejects.toThrow("timeout: REFRESH_SELECTION");
  });

  it("ignores responses from another window, unsupported versions, and unknown request ids", async () => {
    const promise = bridge.request("GET_CONTENT");
    const [message] = iframe.contentWindow.postMessage.mock.calls[0];
    const otherWindow = {};

    dispatchMessage(
      otherWindow,
      responseMessage(message.requestId, { html: "wrong source" }),
    );
    dispatchMessage(otherWindow, {
      ...responseMessage(message.requestId, { html: "wrong version" }),
      version: "unsupported-version",
    });
    dispatchMessage(
      iframe.contentWindow,
      responseMessage("unknown-request", { html: "unknown" }),
    );

    let settled = false;
    void promise.finally(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);

    dispatchMessage(
      iframe.contentWindow,
      responseMessage(message.requestId, { html: "valid" }),
    );

    await expect(promise).resolves.toEqual({ html: "valid" });
  });

  it("notifies the iframe with a fire-and-forget command", () => {
    bridge.notifyCommand("SET_ELEMENT_TRANSFORM", {
      selector: ".title",
      box: { left: 1, top: 2, width: 300, height: 80 },
    });

    const [message, targetOrigin] = iframe.contentWindow.postMessage.mock.calls[0];

    expect(targetOrigin).toBe("*");
    expect(message).toMatchObject({
      version: MESSAGE_PROTOCOL_VERSION,
      category: MessageCategory.COMMAND,
      type: "SET_ELEMENT_TRANSFORM",
      commandType: "SET_ELEMENT_TRANSFORM",
      payload: {
        selector: ".title",
        box: { left: 1, top: 2, width: 300, height: 80 },
      },
      source: "parent",
    });
    expect(message.timestamp).toEqual(expect.any(Number));
  });

  it("does nothing when notifying a command before the iframe is ready", () => {
    const notReadyBridge = new SlideEditorParentBridge();

    expect(() => notReadyBridge.notifyCommand("UNKNOWN_COMMAND")).not.toThrow();
    notReadyBridge.destroy();
  });

  it("handles ready, hover, selection, multi-selection, and content events", () => {
    const onReady = vi.fn();
    const onHover = vi.fn();
    const onSelect = vi.fn();
    const onMultiSelect = vi.fn();
    const onContentChanged = vi.fn();
    bridge.setHandlers({
      onReady,
      onHover,
      onSelect,
      onMultiSelect,
      onContentChanged,
    });

    const selectedElement: SelectedElementInfo = {
      selector: ".heading",
      tagName: "h1",
      rect: { top: 10, left: 20, width: 300, height: 50 },
      isTextElement: true,
      textContent: "Title",
    };

    dispatchMessage(iframe.contentWindow, eventMessage("EDITOR_READY"));
    dispatchMessage(iframe.contentWindow, eventMessage("ELEMENT_HOVERED", {
      rect: selectedElement.rect,
    }));
    dispatchMessage(iframe.contentWindow, eventMessage("ELEMENT_HOVER_END"));
    dispatchMessage(iframe.contentWindow, eventMessage("ELEMENT_SELECTED", selectedElement));
    dispatchMessage(iframe.contentWindow, eventMessage("ELEMENTS_SELECTED", {
      elements: [selectedElement],
    }));
    dispatchMessage(iframe.contentWindow, eventMessage("ELEMENTS_DESELECTED"));
    dispatchMessage(iframe.contentWindow, eventMessage("CONTENT_CHANGED", {
      html: "<h1>Updated</h1>",
    }));

    expect(onReady).toHaveBeenCalledTimes(1);
    expect(onHover).toHaveBeenNthCalledWith(1, selectedElement.rect);
    expect(onHover).toHaveBeenNthCalledWith(2, null);
    expect(onHover).toHaveBeenLastCalledWith(null);
    expect(onSelect).toHaveBeenCalledWith(selectedElement);
    expect(onSelect).toHaveBeenCalledWith(null);
    expect(onMultiSelect).toHaveBeenCalledWith([selectedElement]);
    expect(onMultiSelect).toHaveBeenLastCalledWith([]);
    expect(onContentChanged).toHaveBeenCalledWith("<h1>Updated</h1>");
  });

  it("uses safe defaults for incomplete event payloads", () => {
    const onHover = vi.fn();
    const onMultiSelect = vi.fn();
    const onContentChanged = vi.fn();
    bridge.setHandlers({ onHover, onMultiSelect, onContentChanged });

    dispatchMessage(iframe.contentWindow, eventMessage("ELEMENT_HOVERED"));
    dispatchMessage(iframe.contentWindow, eventMessage("ELEMENTS_SELECTED"));
    dispatchMessage(iframe.contentWindow, eventMessage("CONTENT_CHANGED"));

    expect(onHover).toHaveBeenCalledWith(null);
    expect(onMultiSelect).toHaveBeenCalledWith([]);
    expect(onContentChanged).toHaveBeenCalledWith(undefined);
  });

  it("suppresses selection-related events while suppression is enabled", () => {
    const onHover = vi.fn();
    const onSelect = vi.fn();
    const onMultiSelect = vi.fn();
    bridge.setHandlers({ onHover, onSelect, onMultiSelect });
    bridge.setSuppressSelectionEvents(true);

    dispatchMessage(iframe.contentWindow, eventMessage("ELEMENT_HOVERED", {
      rect: { top: 0, left: 0, width: 1, height: 1 },
    }));
    dispatchMessage(iframe.contentWindow, eventMessage("ELEMENT_HOVER_END"));
    dispatchMessage(iframe.contentWindow, eventMessage("ELEMENT_SELECTED", {}));
    dispatchMessage(iframe.contentWindow, eventMessage("ELEMENTS_SELECTED", {
      elements: [],
    }));
    dispatchMessage(iframe.contentWindow, eventMessage("ELEMENTS_DESELECTED"));

    expect(onHover).not.toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
    expect(onMultiSelect).not.toHaveBeenCalled();
  });

  it("continues handling content changes while selection events are suppressed", () => {
    const onContentChanged = vi.fn();
    bridge.setHandlers({ onContentChanged });
    bridge.setSuppressSelectionEvents(true);

    dispatchMessage(iframe.contentWindow, eventMessage("CONTENT_CHANGED", {
      html: "<p>Changed</p>",
    }));

    expect(onContentChanged).toHaveBeenCalledWith("<p>Changed</p>");
  });

  it("supports the convenience methods with the expected request and command payloads", async () => {
    const enterPromise = bridge.enterSelectionMode();
    let [enterMessage] = iframe.contentWindow.postMessage.mock.calls[0];
    dispatchMessage(
      iframe.contentWindow,
      responseMessage(enterMessage.requestId, { success: true }),
    );
    await expect(enterPromise).resolves.toEqual({ success: true });

    const exitPromise = bridge.exitSelectionMode();
    let [exitMessage] = iframe.contentWindow.postMessage.mock.calls[1];
    dispatchMessage(
      iframe.contentWindow,
      responseMessage(exitMessage.requestId, { success: true }),
    );
    await expect(exitPromise).resolves.toEqual({ success: true });

    bridge.setElementTransform(
      ".shape",
      { left: 5, top: 6, width: 100, height: 90, rotation: 15 },
      "editor-1",
    );
    const [transformMessage] = iframe.contentWindow.postMessage.mock.calls[2];
    expect(transformMessage.payload).toEqual({
      selector: ".shape",
      editorId: "editor-1",
      box: { left: 5, top: 6, width: 100, height: 90, rotation: 15 },
    });

    const stylePromise = bridge.applyTextStyle(
      { bold: true, color: "#123456" },
      { selector: ".heading", editorId: "editor-2" },
    );
    const [styleMessage] = iframe.contentWindow.postMessage.mock.calls[3];
    expect(styleMessage.payload).toEqual({
      bold: true,
      color: "#123456",
      selector: ".heading",
      editorId: "editor-2",
    });
    dispatchMessage(
      iframe.contentWindow,
      responseMessage(styleMessage.requestId, { success: true, applied: 1 }),
    );
    await expect(stylePromise).resolves.toEqual({ success: true, applied: 1 });
  });

  it("rejects all pending requests and removes its message listener when destroyed", async () => {
    const firstPromise = bridge.request("GET_CONTENT");
    const secondPromise = bridge.request("COMMIT_CONTENT");

    bridge.destroy();

    await expect(firstPromise).rejects.toThrow("bridge destroyed");
    await expect(secondPromise).rejects.toThrow("bridge destroyed");

    dispatchMessage(
      iframe.contentWindow,
      responseMessage("request-that-no-longer-exists", { ok: true }),
    );
    expect(iframe.contentWindow.postMessage).toHaveBeenCalledTimes(2);

    bridge.notifyCommand("AFTER_DESTROY");
    expect(iframe.contentWindow.postMessage).toHaveBeenCalledTimes(2);
  });
});
