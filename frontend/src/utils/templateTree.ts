/** 模板包文件树节点（编辑器侧栏 / API /tree 共用） */
export type TemplateTreeNode = {
  name: string;
  type: "dir" | "file";
  path: string;
  size?: number;
  children?: TemplateTreeNode[];
};

export function normalizePath(path: string): string {
  return path
    .replace(/^\.\//, "")
    .replace(/^\/+/, "")
    .replace(/\\/g, "/")
    .replace(/[?#].*$/, "");
}

/** 编辑器侧栏不展示的目录 / 压缩包 */
const TREE_HIDDEN_DIRS = new Set(["previews", "source"]);

function shouldHideTreeNode(node: TemplateTreeNode): boolean {
  const name = normalizePath(node.name).toLowerCase();
  if (!name) return true;
  if (node.type === "dir" && TREE_HIDDEN_DIRS.has(name)) return true;
  if (node.type === "file") {
    if (name === "source.pptx" || name.endsWith(".zip") || name.endsWith(".pptx")) {
      return true;
    }
  }
  return false;
}

export function sanitizeTree(nodes: TemplateTreeNode[]): TemplateTreeNode[] {
  const out: TemplateTreeNode[] = [];
  for (const node of nodes) {
    if (shouldHideTreeNode(node)) continue;
    const path = normalizePath(node.path);
    const name =
      normalizePath(node.name).split("/").filter(Boolean).pop() ||
      normalizePath(node.name);
    out.push({
      ...node,
      path,
      name,
      children: node.children ? sanitizeTree(node.children) : undefined,
    });
  }
  return out;
}

const IMAGE_EXT = /\.(png|jpe?g|webp|gif|svg|avif|bmp)(?:\?|#|$)/i;

export function isImageAssetPath(path: string): boolean {
  return IMAGE_EXT.test(normalizePath(path));
}

export function templateAssetUrl(templateId: string, relPath: string): string {
  const path = normalizePath(relPath);
  return `/api/html-templates/${encodeURIComponent(templateId)}/assets/${path
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 预览用：优先幻灯片 HTML 里已能显示的 src，再回退 API / embed。 */
export function candidateImageUrls(
  templateId: string,
  relPath: string,
  pages?: Array<{ html?: string }>,
): string[] {
  const path = normalizePath(relPath);
  const fileName = path.split("/").pop() || path;
  const urls: string[] = [];
  const seen = new Set<string>();
  const add = (raw?: string | null) => {
    const u = (raw || "").trim();
    if (!u || seen.has(u)) return;
    seen.add(u);
    urls.push(u);
  };

  if (pages?.length && fileName) {
    const re = new RegExp(
      `(?:src|href)\\s*=\\s*["']([^"']*${escapeRegExp(fileName)}[^"']*)["']`,
      "gi",
    );
    for (const page of pages) {
      const html = page.html || "";
      for (const m of html.matchAll(re)) add(m[1]);
    }
  }

  add(templateAssetUrl(templateId, path));
  const embedPath = path
    .split("/")
    .map(encodeURIComponent)
    .join("/");
  add(`/embed/template/${encodeURIComponent(templateId)}/${embedPath}`);
  return urls;
}

/** 把 ../images/a.png、/api/.../assets/images/a.png 收成包内相对路径 */
export function toPackageRelativePath(raw: string): string | null {
  let path = (raw || "").trim();
  if (!path || path.startsWith("data:") || path.startsWith("blob:")) return null;
  try {
    if (/^https?:\/\//i.test(path)) {
      path = new URL(path).pathname;
    }
  } catch {
    return null;
  }
  const asset = path.match(/\/assets\/(.+)$/i);
  if (asset?.[1]) path = asset[1];
  path = normalizePath(path.replace(/^(\.\.\/)+/, ""));
  if (!path || path.includes("..")) return null;
  return path;
}

/** 从幻灯片 HTML 里抽出 images/ 等静态资源路径 */
export function extractAssetPathsFromHtml(html: string | undefined | null): string[] {
  if (!html) return [];
  const found = new Set<string>();
  const consider = (raw: string) => {
    const rel = toPackageRelativePath(raw);
    if (!rel || !IMAGE_EXT.test(rel)) return;
    found.add(rel);
  };
  for (const m of html.matchAll(
    /(?:src|href)\s*=\s*["']([^"']+)["']/gi,
  )) {
    consider(m[1] || "");
  }
  for (const m of html.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/gi)) {
    consider(m[1] || "");
  }
  return [...found];
}

function treeHasNamedDir(nodes: TemplateTreeNode[], name: string): boolean {
  return nodes.some((n) => n.type === "dir" && n.name === name);
}

function mergeTrees(
  primary: TemplateTreeNode[],
  extra: TemplateTreeNode[],
): TemplateTreeNode[] {
  if (extra.length === 0) return primary;
  if (primary.length === 0) return extra;
  const byPath = new Map<string, TemplateTreeNode>();
  const ingest = (nodes: TemplateTreeNode[]) => {
    for (const node of nodes) {
      const existing = byPath.get(node.path);
      if (!existing) {
        byPath.set(node.path, {
          ...node,
          children: node.children ? [...node.children] : undefined,
        });
        continue;
      }
      if (node.type === "dir" || existing.type === "dir") {
        existing.type = "dir";
        existing.children = mergeTrees(
          existing.children || [],
          node.children || [],
        );
      }
    }
  };
  ingest(primary);
  ingest(extra);
  const dirs: TemplateTreeNode[] = [];
  const files: TemplateTreeNode[] = [];
  for (const node of byPath.values()) {
    if (node.type === "dir") dirs.push(node);
    else files.push(node);
  }
  const byName = (a: TemplateTreeNode, b: TemplateTreeNode) =>
    a.name.localeCompare(b.name);
  return [...dirs.sort(byName), ...files.sort(byName)];
}

/** 从页面 sourceFile + HTML 资源引用拼一份目录树（API 失败时的回退） */
export function buildTreeFromSourceFiles(
  sourceFiles: Array<string | undefined | null>,
): TemplateTreeNode[] {
  type DirAcc = {
    name: string;
    path: string;
    dirs: Map<string, DirAcc>;
    files: Map<string, TemplateTreeNode>;
  };

  const root: DirAcc = {
    name: "",
    path: "",
    dirs: new Map(),
    files: new Map(),
  };

  for (const raw of sourceFiles) {
    if (!raw || typeof raw !== "string") continue;
    const path = normalizePath(raw);
    if (!path) continue;
    const parts = path.split("/").filter(Boolean);
    if (parts.length === 0) continue;

    let cursor = root;
    for (let i = 0; i < parts.length - 1; i += 1) {
      const seg = parts[i]!;
      const childPath = cursor.path ? `${cursor.path}/${seg}` : seg;
      let next = cursor.dirs.get(seg);
      if (!next) {
        next = { name: seg, path: childPath, dirs: new Map(), files: new Map() };
        cursor.dirs.set(seg, next);
      }
      cursor = next;
    }

    const fileName = parts[parts.length - 1]!;
    cursor.files.set(fileName, {
      name: fileName,
      type: "file",
      path,
    });
  }

  const toNodes = (dir: DirAcc): TemplateTreeNode[] => {
    const nodes: TemplateTreeNode[] = [];
    for (const child of [...dir.dirs.values()].sort((a, b) =>
      a.name.localeCompare(b.name),
    )) {
      nodes.push({
        name: child.name,
        type: "dir",
        path: child.path,
        children: toNodes(child),
      });
    }
    for (const file of [...dir.files.values()].sort((a, b) =>
      a.name.localeCompare(b.name),
    )) {
      nodes.push(file);
    }
    return nodes;
  };

  return toNodes(root);
}

export { mergeTrees, treeHasNamedDir };
