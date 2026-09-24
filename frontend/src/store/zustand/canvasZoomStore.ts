import { create } from "zustand";

interface CanvasZoomState {
  /** 容器等比适配的最大缩放（四周留白后） */
  fitScale: number;
  /** 相对 fitScale 的缩放百分比，100 = 适配最大，默认 100 */
  zoomPercent: number;
  setFitScale: (fitScale: number) => void;
  setZoomPercent: (zoomPercent: number) => void;
  getScale: () => number;
}

const clampPercent = (value: number) =>
  Math.min(200, Math.max(10, Math.round(value)));

export const useCanvasZoomStore = create<CanvasZoomState>((set, get) => ({
  fitScale: 1,
  zoomPercent: 100,
  setFitScale: (fitScale) => {
    const next = Math.max(fitScale, 0.1);
    const prev = get().fitScale;
    if (Math.abs(next - prev) <= 0.005) return;
    set({ fitScale: next });
  },
  setZoomPercent: (zoomPercent) => set({ zoomPercent: clampPercent(zoomPercent) }),
  getScale: () => {
    const { fitScale, zoomPercent } = get();
    return Math.max(fitScale * (zoomPercent / 100), 0.1);
  },
}));
