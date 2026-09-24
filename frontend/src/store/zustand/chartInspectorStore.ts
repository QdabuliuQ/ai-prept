import { create } from "zustand";

interface ChartInspectorState {
  sectionKey: string | null;
  title: string;
  contentEl: HTMLElement | null;
  openSection: (sectionKey: string, title: string) => void;
  toggleSection: (sectionKey: string, title: string) => void;
  setContentEl: (el: HTMLElement | null) => void;
  close: () => void;
}

export const useChartInspectorStore = create<ChartInspectorState>((set, get) => ({
  sectionKey: null,
  title: "",
  contentEl: null,

  openSection: (sectionKey, title) => set({ sectionKey, title }),

  toggleSection: (sectionKey, title) => {
    const current = get().sectionKey;
    if (current === sectionKey) {
      set({ sectionKey: null, title: "", contentEl: null });
      return;
    }
    set({ sectionKey, title });
  },

  setContentEl: (el) => set({ contentEl: el }),

  close: () => set({ sectionKey: null, title: "", contentEl: null }),
}));
