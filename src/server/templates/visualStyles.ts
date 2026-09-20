/**
 * Read ppt-master visual-styles/_catalog.json for Admin / APIs.
 */

import fs from "fs";
import path from "path";

export type VisualStyleStatus = "curated" | "variant" | "experimental";

export type VisualStyleCatalogEntry = {
  id: string;
  family: string;
  group_zh: string;
  label_zh: string;
  status: VisualStyleStatus | string;
  base?: string | null;
  path: string;
  rendering?: string | null;
  illus?: string | null;
  character?: string;
};

export type VisualStyleCatalog = {
  schema_version: string;
  generated_at?: string;
  count: number;
  styles: VisualStyleCatalogEntry[];
};

const FALLBACK: VisualStyleCatalogEntry[] = [
  { id: "dark-tech", family: "corporate-product", group_zh: "企业 / 产品", label_zh: "暗色科技", status: "curated", path: "dark-tech.md" },
  { id: "swiss-minimal", family: "corporate-product", group_zh: "企业 / 产品", label_zh: "瑞士极简", status: "curated", path: "swiss-minimal.md" },
  { id: "zine", family: "expressive-print", group_zh: "表现 / 印刷", label_zh: "小誌印刷", status: "curated", path: "zine.md" },
];

export function visualStylesDir(): string {
  const env = (process.env.PPT_MASTER_ROOT || "").trim();
  const root = env
    ? path.resolve(env)
    : path.resolve(process.cwd(), "ppt-master");
  return path.join(
    root,
    "skills",
    "ppt-master",
    "references",
    "visual-styles",
  );
}

export function loadVisualStyleCatalog(): VisualStyleCatalog {
  const file = path.join(visualStylesDir(), "_catalog.json");
  try {
    const raw = fs.readFileSync(file, "utf8");
    const data = JSON.parse(raw) as VisualStyleCatalog;
    if (data && Array.isArray(data.styles) && data.styles.length > 0) {
      return data;
    }
  } catch {
    /* fall through */
  }
  return {
    schema_version: "1.0",
    count: FALLBACK.length,
    styles: FALLBACK,
  };
}

/** Ant Design Select `options` with optgroups */
export function visualStyleSelectOptions(opts?: {
  includeVariants?: boolean;
}): { label: string; options: { value: string; label: string }[] }[] {
  const includeVariants = opts?.includeVariants !== false;
  const catalog = loadVisualStyleCatalog();
  const groups = new Map<string, { value: string; label: string }[]>();

  for (const s of catalog.styles) {
    const status = s.status || "curated";
    if (!includeVariants && status !== "curated") continue;
    const group = s.group_zh || "其他";
    let label =
      s.label_zh && s.label_zh !== s.id
        ? `${s.id} ${s.label_zh}`
        : s.id;
    if (status === "variant") {
      label = s.base ? `${label} · 变体←${s.base}` : `${label} · 变体`;
    }
    const list = groups.get(group) || [];
    list.push({ value: s.id, label });
    groups.set(group, list);
  }

  return Array.from(groups.entries()).map(([label, options]) => ({
    label,
    options,
  }));
}

/** Flat curated (or all) style ids for random pick. */
export function listVisualStyleIds(opts?: {
  includeVariants?: boolean;
}): string[] {
  const includeVariants = opts?.includeVariants === true;
  const catalog = loadVisualStyleCatalog();
  const ids: string[] = [];
  for (const s of catalog.styles) {
    const status = s.status || "curated";
    if (!includeVariants && status !== "curated") continue;
    if (s.id) ids.push(s.id);
  }
  return ids.length > 0 ? ids : FALLBACK.map((s) => s.id);
}

export function pickRandomVisualStyle(opts?: {
  includeVariants?: boolean;
  exclude?: string[];
}): VisualStyleCatalogEntry {
  const exclude = new Set((opts?.exclude || []).map((x) => x.trim()).filter(Boolean));
  const catalog = loadVisualStyleCatalog();
  const includeVariants = opts?.includeVariants === true;
  let pool = catalog.styles.filter((s) => {
    const status = s.status || "curated";
    if (!includeVariants && status !== "curated") return false;
    if (!s.id || exclude.has(s.id)) return false;
    return true;
  });
  if (pool.length === 0) pool = FALLBACK.filter((s) => !exclude.has(s.id));
  if (pool.length === 0) pool = FALLBACK;
  return pool[Math.floor(Math.random() * pool.length)]!;
}
