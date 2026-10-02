import type { SelectedElementInfo } from "@/slide-editor/parent/SlideEditorParentBridge";
import type { AssistElementTarget } from "@/utils/editorAiChat";

/** Compact label for the chat attachment chip. */
export function elementChipLabel(el: SelectedElementInfo): string {
  if (el.isTextElement) {
    const text = (el.textContent || "").replace(/\s+/g, " ").trim();
    if (text) return text.length > 28 ? `${text.slice(0, 28)}…` : text;
  }
  if (el.dataSlot) return el.dataSlot;
  if (el.isImageElement || el.imageSrc) {
    const name = (el.imageSrc || "").split("/").pop() || "image";
    return name;
  }
  return el.tagName || "element";
}

export function toAssistElementTarget(
  el: SelectedElementInfo,
): AssistElementTarget {
  return {
    selector: el.selector,
    editorId: el.editorId,
    tagName: el.tagName,
    isTextElement: el.isTextElement,
    isImageElement: el.isImageElement,
    textContent: el.textContent
      ? el.textContent.replace(/\s+/g, " ").trim().slice(0, 200)
      : undefined,
    dataSlot: el.dataSlot,
    dataSlotType: el.dataSlotType,
    dataSlotRole: el.dataSlotRole,
    dataElement: el.dataElement,
    imageSrc: el.imageSrc,
  };
}
