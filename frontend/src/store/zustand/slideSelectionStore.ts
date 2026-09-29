import type { SelectedElementInfo } from "@/slide-editor/parent/SlideEditorParentBridge";
import { create } from "zustand";

export type TextStylePatch = {
  bold?: boolean | "toggle";
  italic?: boolean | "toggle";
  underline?: boolean | "toggle";
  strike?: boolean | "toggle";
  textAlign?: "left" | "center" | "right";
  color?: string;
  /** Absolute px size, or bump relative to current */
  fontSize?: number | "increase" | "decrease";
};

type TextStyleApi = {
  applyTextStyle: (
    patch: TextStylePatch,
    target?: { selector?: string; editorId?: string },
  ) => Promise<void>;
};

type SlideSelectionState = {
  selected: SelectedElementInfo | null;
  textApi: TextStyleApi | null;
  setSelected: (info: SelectedElementInfo | null) => void;
  clearSelection: () => void;
  bindTextApi: (api: TextStyleApi | null) => void;
  applyTextStyle: (patch: TextStylePatch) => Promise<void>;
  canFormatText: () => boolean;
};

export const useSlideSelectionStore = create<SlideSelectionState>((set, get) => ({
  selected: null,
  textApi: null,
  setSelected: (info) => set({ selected: info }),
  clearSelection: () => set({ selected: null }),
  bindTextApi: (api) => set({ textApi: api }),
  applyTextStyle: async (patch) => {
    const api = get().textApi;
    const selected = get().selected;
    if (!api || !selected || !get().canFormatText()) return;
    await api.applyTextStyle(patch, {
      selector: selected.selector,
      editorId: selected.editorId,
    });
  },
  canFormatText: () => Boolean(get().selected?.isTextElement),
}));
