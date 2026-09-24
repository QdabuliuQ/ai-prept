import { create } from "zustand";
import { usePPTStore } from "./pptStore";

interface PageActiveState {
  pageActive: string | null;
  
  setPageActive: (pageActive: string | null) => void;
  getPageActive: () => string | null;
  isPageActive: (pageActive: string) => boolean;
  resetPageActive: () => void;
  getPageIndex: (pages: any[]) => number;
  goToPrevPage: () => string | null;
  goToNextPage: () => string | null;
}

export const usePageActiveStore = create<PageActiveState>((set, get) => ({
  pageActive: null,

  setPageActive: (pageActive) => set({ pageActive }),
  
  getPageActive: () => get().pageActive,
  
  isPageActive: (pageActive) => get().pageActive === pageActive,
  
  resetPageActive: () => set({ pageActive: null }),
  
  getPageIndex: (pages) => {
    return pages.findIndex((page: any) => page.id === get().pageActive);
  },

  goToPrevPage: () => {
    const pages = usePPTStore.getState().getPages();
    if (pages.length === 0) return null;

    const currentIndex = get().getPageIndex(pages);
    if (currentIndex === -1) {
      const firstPageId = pages[0].id;
      set({ pageActive: firstPageId });
      return firstPageId;
    }

    if (currentIndex > 0) {
      const prevPageId = pages[currentIndex - 1].id;
      set({ pageActive: prevPageId });
      return prevPageId;
    }

    return get().pageActive;
  },

  goToNextPage: () => {
    const pages = usePPTStore.getState().getPages();
    if (pages.length === 0) return null;

    const currentIndex = get().getPageIndex(pages);
    if (currentIndex === -1) {
      const firstPageId = pages[0].id;
      set({ pageActive: firstPageId });
      return firstPageId;
    }

    if (currentIndex < pages.length - 1) {
      const nextPageId = pages[currentIndex + 1].id;
      set({ pageActive: nextPageId });
      return nextPageId;
    }

    return get().pageActive;
  },
}));

