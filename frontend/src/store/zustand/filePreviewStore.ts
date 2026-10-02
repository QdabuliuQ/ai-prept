import { create } from "zustand";

export type FilePreviewKind = "image";

export type FilePreview = {
  kind: FilePreviewKind;
  path: string;
  name: string;
  url: string;
  size?: number;
};

interface FilePreviewState {
  preview: FilePreview | null;
  open: (preview: FilePreview) => void;
  close: () => void;
}

export const useFilePreviewStore = create<FilePreviewState>((set) => ({
  preview: null,
  open: (preview) => set({ preview }),
  close: () => set({ preview: null }),
}));
