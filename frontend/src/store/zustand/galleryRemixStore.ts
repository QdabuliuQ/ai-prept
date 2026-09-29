import { create } from "zustand";

type GalleryRemixState = {
  /** Gallery → 编辑器 remix 任务进行中（queued / running） */
  busy: boolean;
  /** 失败/取消时在编辑器壳层展示，不写入幻灯片 */
  error: string | null;
  errorCancelled: boolean;
  setBusy: (busy: boolean) => void;
  setFailure: (message: string, cancelled?: boolean) => void;
  clearFailure: () => void;
};

export const useGalleryRemixStore = create<GalleryRemixState>((set) => ({
  busy: false,
  error: null,
  errorCancelled: false,
  setBusy: (busy) => set({ busy }),
  setFailure: (message, cancelled = false) =>
    set({
      busy: false,
      error: message,
      errorCancelled: cancelled,
    }),
  clearFailure: () => set({ error: null, errorCancelled: false }),
}));
