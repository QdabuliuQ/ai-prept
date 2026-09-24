import { create } from "zustand";

interface FullscreenState {
  isFullscreen: boolean;
  currentSlidePageId: string | null;
  
  setFullscreen: (status: boolean) => void;
  enterFullscreen: (startPageId?: string) => void;
  exitFullscreen: () => void;
  toggleFullscreen: (startPageId?: string) => void;
  getFullscreen: () => boolean;
  setCurrentSlidePageId: (pageId: string) => void;
  getCurrentSlidePageId: () => string | null;
}

export const useFullscreenStore = create<FullscreenState>((set, get) => ({
  isFullscreen: false,
  currentSlidePageId: null,
  
  setFullscreen: (status) => set({ isFullscreen: status }),
  
  enterFullscreen: (startPageId?) => {
    set({ isFullscreen: true });
    if (startPageId) {
      set({ currentSlidePageId: startPageId });
    }
  },
  
  exitFullscreen: () => set({ isFullscreen: false }),
  
  toggleFullscreen: (startPageId?) => {
    const { isFullscreen } = get();
    if (isFullscreen) {
      get().exitFullscreen();
    } else {
      get().enterFullscreen(startPageId);
    }
  },
  
  getFullscreen: () => get().isFullscreen,
  
  setCurrentSlidePageId: (pageId) => set({ currentSlidePageId: pageId }),
  
  getCurrentSlidePageId: () => get().currentSlidePageId,
}));

// Compatibility class
class FullscreenStoreCompat {
  get isFullscreen() {
    return useFullscreenStore.getState().isFullscreen;
  }

  get currentSlidePageId() {
    return useFullscreenStore.getState().currentSlidePageId;
  }
  
  setFullscreen = (status: boolean) => {
    useFullscreenStore.getState().setFullscreen(status);
  };
  
  enterFullscreen = (startPageId?: string) => {
    useFullscreenStore.getState().enterFullscreen(startPageId);
  };
  
  exitFullscreen = () => {
    useFullscreenStore.getState().exitFullscreen();
  };
  
  toggleFullscreen = (startPageId?: string) => {
    useFullscreenStore.getState().toggleFullscreen(startPageId);
  };
  
  getFullscreen = () => {
    return useFullscreenStore.getState().getFullscreen();
  };
  
  setCurrentSlidePageId = (pageId: string) => {
    useFullscreenStore.getState().setCurrentSlidePageId(pageId);
  };
  
  getCurrentSlidePageId = () => {
    return useFullscreenStore.getState().getCurrentSlidePageId();
  };
}

export const fullscreenStore = new FullscreenStoreCompat();

