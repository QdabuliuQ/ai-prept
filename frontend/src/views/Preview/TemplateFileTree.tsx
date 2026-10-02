import { cn } from "@/lib/utils";
import { pageActiveStore, usePageActiveStore, usePPTStore } from "@/store";
import { useFilePreviewStore } from "@/store/zustand/filePreviewStore";
import { buildTemplateSlideEmbedSrc } from "@/utils/templateEmbed";
import {
  buildTreeFromSourceFiles,
  extractAssetPathsFromHtml,
  isImageAssetPath,
  mergeTrees,
  normalizePath,
  sanitizeTree,
  templateAssetUrl,
  treeHasNamedDir,
  type TemplateTreeNode,
} from "@/utils/templateTree";
import {
  ChevronDown,
  ChevronRight,
  FileCode2,
  FileImage,
  FileJson,
  FileText,
  Folder,
  FolderOpen,
  FolderTree,
  LoaderCircle,
} from "lucide-react";
import { useEffect, useMemo, useState, type FC } from "react";
import styles from "./index.module.less";

export type { TemplateTreeNode };

function fileIcon(name: string) {
  const lower = name.toLowerCase();
  if (
    lower.endsWith(".html") ||
    lower.endsWith(".htm") ||
    lower.endsWith(".css")
  ) {
    return FileCode2;
  }
  if (
    lower.endsWith(".png") ||
    lower.endsWith(".jpg") ||
    lower.endsWith(".jpeg") ||
    lower.endsWith(".webp") ||
    lower.endsWith(".gif") ||
    lower.endsWith(".svg")
  ) {
    return FileImage;
  }
  if (lower.endsWith(".json")) return FileJson;
  return FileText;
}

function defaultExpanded(nodes: TemplateTreeNode[]): Set<string> {
  const open = new Set<string>();
  for (const n of nodes) {
    if (n.type === "dir" && (n.name === "slides" || n.name === "images")) {
      open.add(n.path);
    }
  }
  return open;
}

const TreeNodeRow: FC<{
  node: TemplateTreeNode;
  depth: number;
  expanded: Set<string>;
  activePath: string | null;
  onToggle: (path: string) => void;
  onSelectFile: (node: TemplateTreeNode) => void;
}> = ({ node, depth, expanded, activePath, onToggle, onSelectFile }) => {
  const isDir = node.type === "dir";
  const isOpen = isDir && expanded.has(node.path);
  const isActive =
    !isDir &&
    activePath != null &&
    normalizePath(activePath) === normalizePath(node.path);
  const Icon = isDir ? (isOpen ? FolderOpen : Folder) : fileIcon(node.name);

  return (
    <div className="min-w-0 max-w-full">
      <button
        type="button"
        className={cn(styles.treeRow, isActive && styles.treeRowActive)}
        style={{ paddingLeft: 8 + depth * 12 }}
        onClick={() => {
          if (isDir) onToggle(node.path);
          else onSelectFile(node);
        }}
        title={node.path}
      >
        <span className={styles.treeChevron}>
          {isDir ? (
            isOpen ? (
              <ChevronDown className="size-3" />
            ) : (
              <ChevronRight className="size-3" />
            )
          ) : null}
        </span>
        <Icon className="size-3.5 shrink-0 opacity-80" />
        <span className={styles.treeRowName}>{node.name}</span>
      </button>
      {isDir && isOpen && node.children?.length
        ? node.children.map((child) => (
            <TreeNodeRow
              key={child.path}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              activePath={activePath}
              onToggle={onToggle}
              onSelectFile={onSelectFile}
            />
          ))
        : null}
    </div>
  );
};

const TreeEmpty: FC<{ title: string; desc: string }> = ({ title, desc }) => (
  <div className={styles.treeEmpty}>
    <span className={styles.treeEmptyIcon} aria-hidden>
      <FolderTree className="size-5" />
    </span>
    <p className={styles.treeEmptyTitle}>{title}</p>
    <p className={styles.treeEmptyDesc}>{desc}</p>
  </div>
);

/** 当前模板包文件目录（需 pptStore.templateId） */
export const TemplateFileTree: FC = () => {
  const templateId = usePPTStore((s) => s.templateId);
  const pages = usePPTStore((s) => s.pages);
  const pageActive = usePageActiveStore((s) => s.pageActive);
  const previewPath = useFilePreviewStore((s) => s.preview?.path ?? null);

  const [tree, setTree] = useState<TemplateTreeNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const activePath = useMemo(() => {
    if (previewPath) return normalizePath(previewPath);
    if (!pageActive) return null;
    const page = pages.find((p) => p.id === pageActive);
    return page?.sourceFile ? normalizePath(page.sourceFile) : null;
  }, [pageActive, pages, previewPath]);

  useEffect(() => {
    if (!templateId) {
      setTree([]);
      setError(null);
      setLoading(false);
      return;
    }

    const seedFromStore = usePPTStore.getState().templateTree;
    const currentPages = usePPTStore.getState().pages;
    const seedFromPages = buildTreeFromSourceFiles([
      ...currentPages.map((p) => p.sourceFile),
      ...currentPages.flatMap((p) => extractAssetPathsFromHtml(p.html)),
    ]);
    let seed =
      seedFromStore.length > 0
        ? seedFromStore
        : seedFromPages.length > 0
          ? seedFromPages
          : [];
    if (
      seed.length > 0 &&
      !treeHasNamedDir(seed, "images") &&
      treeHasNamedDir(seedFromPages, "images")
    ) {
      seed = mergeTrees(seed, seedFromPages);
    }
    if (seed.length > 0) {
      const cleaned = sanitizeTree(seed);
      setTree(cleaned);
      setExpanded(defaultExpanded(cleaned));
      setError(null);
    }

    let cancelled = false;
    setLoading(seed.length === 0);

    void (async () => {
      try {
        const res = await fetch(
          `/api/html-templates/${encodeURIComponent(templateId)}/tree`,
        );
        const data = (await res.json().catch(() => ({}))) as {
          tree?: TemplateTreeNode[];
          error?: string;
          message?: string;
        };
        if (cancelled) return;
        if (!res.ok) {
          if (seed.length === 0 && seedFromPages.length > 0) {
            const cleaned = sanitizeTree(seedFromPages);
            setTree(cleaned);
            setExpanded(defaultExpanded(cleaned));
            setError(null);
          } else if (seed.length === 0) {
            setError(
              data.message ||
                data.error ||
                `模板包未找到（${res.status}）。请确认后端已启动，且存在 agent-output/${templateId}/template.json`,
            );
          }
          return;
        }
        const next = sanitizeTree(Array.isArray(data.tree) ? data.tree : []);
        setTree(next);
        setExpanded(defaultExpanded(next));
        usePPTStore.getState().setTemplateTree(next);
        setError(null);
      } catch {
        if (cancelled) return;
        if (seed.length === 0 && seedFromPages.length > 0) {
          const cleaned = sanitizeTree(seedFromPages);
          setTree(cleaned);
          setExpanded(defaultExpanded(cleaned));
          setError(null);
        } else if (seed.length === 0) {
          setError("无法连接后端读取模板目录，请确认 API 服务已启动。");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [templateId]);

  const onToggle = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const onSelectFile = (node: TemplateTreeNode) => {
    const path = normalizePath(node.path);
    const lower = path.toLowerCase();
    if (lower.endsWith(".html") || lower.endsWith(".htm")) {
      useFilePreviewStore.getState().close();
      const page = pages.find(
        (p) => p.sourceFile && normalizePath(p.sourceFile) === path,
      );
      if (page) {
        pageActiveStore.setPageActive(page.id);
        return;
      }
    }
    if (isImageAssetPath(path) && templateId) {
      useFilePreviewStore.getState().open({
        kind: "image",
        path,
        name: node.name,
        url: buildTemplateSlideEmbedSrc(templateId, path),
        size: node.size,
      });
      return;
    }
    if (templateId) {
      window.open(
        templateAssetUrl(templateId, path),
        "_blank",
        "noopener,noreferrer",
      );
    }
  };

  if (!templateId) {
    return (
      <TreeEmpty
        title="暂无模板目录"
        desc="从模板库打开文档后，这里会显示模板包的文件结构。"
      />
    );
  }

  if (loading && tree.length === 0) {
    return (
      <div className={styles.treeEmpty}>
        <span className={styles.treeEmptyIcon} aria-hidden>
          <LoaderCircle className="size-5 animate-spin" />
        </span>
        <p className={styles.treeEmptyDesc}>正在加载目录…</p>
      </div>
    );
  }

  if (error && tree.length === 0) {
    return <TreeEmpty title="目录加载失败" desc={error} />;
  }

  if (tree.length === 0) {
    return <TreeEmpty title="目录为空" desc="当前模板包下没有可展示的文件。" />;
  }

  return (
    <div className={styles.treeRoot}>
      <div className={styles.treeList}>
        {tree.map((node) => (
          <TreeNodeRow
            key={node.path}
            node={node}
            depth={0}
            expanded={expanded}
            activePath={activePath}
            onToggle={onToggle}
            onSelectFile={onSelectFile}
          />
        ))}
      </div>
    </div>
  );
};
