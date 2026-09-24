/** 模板类型 = 视觉风格 id；展示名以 `/api/gallery/categories` 为准。 */

export type TemplateCategory = {
  id: string;
  labelZh: string;
};

export const DEFAULT_TEMPLATE_CATEGORY = "other";

export function categoryLabelZh(
  categories: readonly TemplateCategory[],
  id: string,
): string {
  return categories.find((c) => c.id === id)?.labelZh || id;
}

/** 首页筛选 chips：按当前模板实际出现的类型去重（不含 other） */
export function galleryCategoryFilters(
  templates: ReadonlyArray<{ category?: string }>,
  catalog: readonly TemplateCategory[] = [],
): Array<{ id: string; label: string }> {
  const labelOf = (id: string) =>
    catalog.find((c) => c.id === id)?.labelZh || id;
  const seen = new Set<string>();
  const out: Array<{ id: string; label: string }> = [];
  for (const tpl of templates) {
    const id = typeof tpl.category === "string" ? tpl.category.trim() : "";
    if (!id || id === DEFAULT_TEMPLATE_CATEGORY || seen.has(id)) continue;
    seen.add(id);
    out.push({ id, label: labelOf(id) });
  }
  out.sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
  return out;
}

export function coerceTemplateCategory(
  value: unknown,
  allowed: readonly TemplateCategory[],
): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw) return DEFAULT_TEMPLATE_CATEGORY;
  if (!allowed.length) return raw;
  return allowed.some((c) => c.id === raw) ? raw : DEFAULT_TEMPLATE_CATEGORY;
}

export async function fetchTemplateCategories(
  signal?: AbortSignal,
): Promise<TemplateCategory[]> {
  const res = await fetch("/api/gallery/categories", { signal });
  if (!res.ok) throw new Error("CATEGORIES_FAILED");
  const data = (await res.json()) as { categories?: TemplateCategory[] };
  return (data.categories || []).filter(
    (c): c is TemplateCategory =>
      !!c && typeof c.id === "string" && typeof c.labelZh === "string",
  );
}
