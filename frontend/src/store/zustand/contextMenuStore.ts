import type { MenuItem } from "@/hooks/useContextMenu";
import { create } from "zustand";

interface ContextMenuState {
  menuVisible: boolean;
  menuPosition: { x: number; y: number };
  menuItems: MenuItem[];

  showMenu: (x: number, y: number, items?: MenuItem[]) => void;
  hideMenu: () => void;
  setMenuItems: (items: MenuItem[]) => void;
  getMenuItems: () => MenuItem[];
  isVisible: () => boolean;
  getPosition: () => { x: number; y: number };
}

export const useContextMenuStore = create<ContextMenuState>((set, get) => ({
  menuVisible: false,
  menuPosition: { x: 0, y: 0 },
  menuItems: [],

  showMenu: (x, y, items = []) =>
    set({ menuVisible: true, menuPosition: { x, y }, menuItems: items }),
  hideMenu: () => set({ menuVisible: false }),
  setMenuItems: (items) => set({ menuItems: items }),
  getMenuItems: () => get().menuItems,
  isVisible: () => get().menuVisible,
  getPosition: () => get().menuPosition,
}));

// Compatibility class
class ContextMenuStoreCompat {
  showMenu = (x: number, y: number, items?: MenuItem[]) => {
    console.log("contextMenuStore.showMenu called", {
      x,
      y,
      itemsCount: items?.length || 0,
      items,
    });
    useContextMenuStore.getState().showMenu(x, y, items);
  };

  hideMenu = () => {
    useContextMenuStore.getState().hideMenu();
  };

  setMenuItems = (items: MenuItem[]) => {
    useContextMenuStore.getState().setMenuItems(items);
  };

  getMenuItems = () => {
    return useContextMenuStore.getState().getMenuItems();
  };

  isVisible = () => {
    return useContextMenuStore.getState().isVisible();
  };

  getPosition = () => {
    return useContextMenuStore.getState().getPosition();
  };
}

export const contextMenuStore = new ContextMenuStoreCompat();
