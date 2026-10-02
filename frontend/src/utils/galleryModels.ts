/** Shared gallery / editor model catalog + localStorage prefs. */

export type GalleryModelOption = {
  id: string;
  label: string;
};

export type GalleryProviderOption = {
  id: string;
  label: string;
  tier?: string;
  models: GalleryModelOption[];
  configured: boolean;
};

export type GalleryModelPrefs = {
  llmProvider: string;
  llmModel: string;
  imageProvider: string;
  imageModel: string;
};

export type GalleryModelsCatalog = {
  llmProviders: GalleryProviderOption[];
  imageProviders: GalleryProviderOption[];
  defaults: Partial<GalleryModelPrefs>;
};

export const GALLERY_MODEL_PREFS_KEY = "webppt:gallery-model-prefs";

export function readModelPrefs(): Partial<GalleryModelPrefs> {
  try {
    const raw = localStorage.getItem(GALLERY_MODEL_PREFS_KEY);
    if (!raw) return {};
    const data = JSON.parse(raw) as Partial<GalleryModelPrefs>;
    return data && typeof data === "object" ? data : {};
  } catch {
    return {};
  }
}

export function writeModelPrefs(prefs: GalleryModelPrefs) {
  try {
    localStorage.setItem(GALLERY_MODEL_PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* ignore */
  }
}

export function pickProvider(
  list: GalleryProviderOption[],
  prefer?: string,
  fallback?: string,
): GalleryProviderOption | undefined {
  const configured = list.filter((p) => p.configured && p.models?.length);
  const pool = configured.length ? configured : list;
  return (
    pool.find((p) => p.id === prefer) ||
    pool.find((p) => p.id === fallback) ||
    pool[0]
  );
}

export function pickModel(
  provider: GalleryProviderOption | undefined,
  prefer?: string,
): string {
  const models = provider?.models || [];
  if (!models.length) return "";
  return models.find((m) => m.id === prefer)?.id || models[0].id;
}

export async function fetchGalleryModels(): Promise<GalleryModelsCatalog | null> {
  const res = await fetch("/api/gallery/models");
  if (!res.ok) return null;
  const data = (await res.json()) as {
    llmProviders?: GalleryProviderOption[];
    imageProviders?: GalleryProviderOption[];
    defaults?: Partial<GalleryModelPrefs>;
  };
  return {
    llmProviders: data.llmProviders || [],
    imageProviders: data.imageProviders || [],
    defaults: data.defaults || {},
  };
}
