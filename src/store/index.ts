// Export all Zustand stores (new)
export {
  usePPTStore,
  usePageActiveStore,
  useContextMenuStore,
  useFullscreenStore,
  useDisplayStatusStore,
  useMenuActiveStore,
  useRemarkEditActiveStore,
  useCanvasZoomStore,
  useThemeStore,
  useChartInspectorStore,
} from "./zustand";

export type { Page, ThemeMode } from "./zustand";

// Export compatibility layers (for gradual migration)
export {
  pageActiveStore,
  pptStore,
  contextMenuStore,
  fullscreenStore,
  displayStatusStore,
  menuActiveStore,
  remarkEditActiveStore,
} from "./zustand";
