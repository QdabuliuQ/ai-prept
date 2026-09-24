import { create } from "zustand";

export type ThemeMode = "light" | "dark";

const STORAGE_KEY = "webppt-theme";

function readStoredTheme(): ThemeMode {
  if (typeof window === "undefined") return "light";
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "dark" ? "dark" : "light";
}

function applyThemeToDocument(theme: ThemeMode) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.dataset.theme = theme;
}

interface ThemeState {
  theme: ThemeMode;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  hydrateTheme: () => void;
}

const initialTheme =
  typeof window !== "undefined" ? readStoredTheme() : ("light" as ThemeMode);

if (typeof window !== "undefined") {
  applyThemeToDocument(initialTheme);
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: initialTheme,
  setTheme: (theme) => {
    localStorage.setItem(STORAGE_KEY, theme);
    applyThemeToDocument(theme);
    set({ theme });
  },
  toggleTheme: () => {
    const next = get().theme === "dark" ? "light" : "dark";
    get().setTheme(next);
  },
  hydrateTheme: () => {
    const theme = readStoredTheme();
    applyThemeToDocument(theme);
    set({ theme });
  },
}));
