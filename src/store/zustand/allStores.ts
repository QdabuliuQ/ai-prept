import { create } from "zustand";

// Display Status Store
interface DisplayStatusState {
  displayStatus: "default" | "grid";
  setDisplayStatus: (status: "default" | "grid") => void;
  getDisplayStatus: () => "default" | "grid";
}

export const useDisplayStatusStore = create<DisplayStatusState>((set, get) => ({
  displayStatus: "default",
  setDisplayStatus: (status) => set({ displayStatus: status }),
  getDisplayStatus: () => get().displayStatus,
}));

class DisplayStatusStoreCompat {
  setDisplayStatus = (status: "default" | "grid") => {
    useDisplayStatusStore.getState().setDisplayStatus(status);
  };
  getDisplayStatus = () => {
    return useDisplayStatusStore.getState().getDisplayStatus();
  };
}

export const displayStatusStore = new DisplayStatusStoreCompat();

// Menu Active Store
interface MenuActiveState {
  menuActive: string | null;
  setMenuActive: (menuActive: string | null) => void;
  getMenuActive: () => string | null;
  resetMenu: () => void;
  setActiveMenu: (menuActive: string | null) => void;
  isActive: (menuActive: string) => boolean;
}

export const useMenuActiveStore = create<MenuActiveState>((set, get) => ({
  menuActive: "start",
  setMenuActive: (menuActive) => set({ menuActive }),
  getMenuActive: () => get().menuActive,
  resetMenu: () => set({ menuActive: "start" }),
  setActiveMenu: (menuActive) => set({ menuActive }),
  isActive: (menuActive) => get().menuActive === menuActive,
}));

class MenuActiveStoreCompat {
  get menuActive() {
    return useMenuActiveStore.getState().menuActive;
  }

  setMenuActive = (menuActive: string | null) => {
    useMenuActiveStore.getState().setMenuActive(menuActive);
  };
  getMenuActive = () => {
    return useMenuActiveStore.getState().getMenuActive();
  };
  resetMenu = () => {
    useMenuActiveStore.getState().resetMenu();
  };
  setActiveMenu = (menuActive: string | null) => {
    useMenuActiveStore.getState().setActiveMenu(menuActive);
  };
  isActive = (menuActive: string) => {
    return useMenuActiveStore.getState().isActive(menuActive);
  };
}

export const menuActiveStore = new MenuActiveStoreCompat();

// Remark Edit Active Store
interface RemarkEditActiveState {
  remarkEditActive: boolean;
  setRemarkEditActive: (remarkEditActive: boolean) => void;
  getRemarkEditActive: () => boolean;
  toggleRemarkEditActive: () => void;
}

export const useRemarkEditActiveStore = create<RemarkEditActiveState>(
  (set, get) => ({
    remarkEditActive: false,
    setRemarkEditActive: (remarkEditActive) => set({ remarkEditActive }),
    getRemarkEditActive: () => get().remarkEditActive,
    toggleRemarkEditActive: () =>
      set({ remarkEditActive: !get().remarkEditActive }),
  }),
);

class RemarkEditActiveStoreCompat {
  setRemarkEditActive = (remarkEditActive: boolean) => {
    useRemarkEditActiveStore.getState().setRemarkEditActive(remarkEditActive);
  };
  getRemarkEditActive = () => {
    return useRemarkEditActiveStore.getState().getRemarkEditActive();
  };
  toggleRemarkEditActive = () => {
    useRemarkEditActiveStore.getState().toggleRemarkEditActive();
  };
}

export const remarkEditActiveStore = new RemarkEditActiveStoreCompat();
