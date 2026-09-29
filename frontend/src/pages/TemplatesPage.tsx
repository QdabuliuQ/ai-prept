import ThemeSwitcher from "@/components/ThemeSwitcher";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useRouter } from "@/navigation";
import { useThemeStore } from "@/store";
import type { PPTDocumentJSON } from "@/utils/loadDocument";
import { buildTemplateSlideEmbedSrc } from "@/utils/templateEmbed";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

type TemplateCard = {
  id: string;
  templateId: string;
  label: { zh_CN?: string; en_US?: string };
  description: { zh_CN?: string; en_US?: string };
  slideCount: number;
  previewFile: string | null;
};

type SlidePage = {
  id: string;
  html?: string;
  sourceFile?: string;
  remark?: string;
};

type TemplateDoc = PPTDocumentJSON & {
  pages: SlidePage[];
  templateId?: string;
  templateDir?: string;
};

const MODAL_SCALE = 0.5; // 960/1920

function SlideFrame({
  src,
  title,
  scale,
}: {
  src: string;
  title: string;
  scale: number;
}) {
  const w = 1920 * scale;
  const h = 1080 * scale;
  return (
    <div
      className="relative overflow-hidden rounded-md border border-border bg-muted"
      style={{ width: w, height: h }}
    >
      <div
        className="pointer-events-none absolute left-0 top-0 origin-top-left"
        style={{ transform: `scale(${scale})` }}
      >
        <iframe
          title={title}
          src={src}
          sandbox="allow-scripts allow-same-origin"
          className="border-0"
          style={{ width: 1920, height: 1080 }}
        />
      </div>
    </div>
  );
}

export default function TemplatesPage() {
  const router = useRouter();
  const themeMode = useThemeStore((s) => s.theme);
  const hydrateTheme = useThemeStore((s) => s.hydrateTheme);
  const isDark = themeMode === "dark";

  const [loading, setLoading] = useState(true);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [templates, setTemplates] = useState<TemplateCard[]>([]);

  const [viewerOpen, setViewerOpen] = useState(false);
  const [viewerLoading, setViewerLoading] = useState(false);
  const [viewerDoc, setViewerDoc] = useState<TemplateDoc | null>(null);
  const [viewerTplId, setViewerTplId] = useState<string | null>(null);
  const [pageIndex, setPageIndex] = useState(0);

  useEffect(() => {
    hydrateTheme();
  }, [hydrateTheme]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/html-templates");
        if (!res.ok) throw new Error("LIST_FAILED");
        const data = (await res.json()) as { templates: TemplateCard[] };
        if (!cancelled) setTemplates(data.templates || []);
      } catch {
        if (!cancelled) toast.error("无法读取模板列表");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const fetchDoc = useCallback(async (id: string) => {
    const res = await fetch(`/api/html-templates/${encodeURIComponent(id)}`);
    if (!res.ok) throw new Error("LOAD_FAILED");
    return (await res.json()) as TemplateDoc;
  }, []);

  const handleLoad = useCallback(
    async (id: string, doc?: TemplateDoc) => {
      setLoadingId(id);
      try {
        const data = doc || (await fetchDoc(id));
        sessionStorage.setItem(
          "webppt:pending-template-doc",
          JSON.stringify(data),
        );
        toast.success("模板已加载，正在打开编辑器");
        router.push("/edit");
      } catch {
        toast.error("加载模板失败");
      } finally {
        setLoadingId(null);
      }
    },
    [fetchDoc, router],
  );

  const openViewer = useCallback(
    async (tpl: TemplateCard) => {
      setViewerOpen(true);
      setViewerTplId(tpl.id);
      setViewerDoc(null);
      setPageIndex(0);
      setViewerLoading(true);
      try {
        const doc = await fetchDoc(tpl.id);
        setViewerDoc(doc);
      } catch {
        toast.error("无法打开预览");
        setViewerOpen(false);
      } finally {
        setViewerLoading(false);
      }
    },
    [fetchDoc],
  );

  const pages = viewerDoc?.pages || [];
  const current = pages[pageIndex];
  const currentEmbedSrc =
    viewerTplId && current?.sourceFile
      ? buildTemplateSlideEmbedSrc(viewerTplId, current.sourceFile)
      : null;
  const pageTitle = useMemo(() => {
    if (!current) return "";
    return current.remark || `第 ${pageIndex + 1} 页`;
  }, [current, pageIndex]);

  useEffect(() => {
    if (!viewerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") {
        setPageIndex((i) => Math.max(0, i - 1));
      } else if (e.key === "ArrowRight") {
        setPageIndex((i) => Math.min(pages.length - 1, i + 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [viewerOpen, pages.length]);

  return (
    <TooltipProvider delayDuration={200}>
      <div className="min-h-screen bg-background text-foreground">
        <Toaster theme={isDark ? "dark" : "light"} position="top-center" />
        <header className="sticky top-0 z-10 border-b border-border bg-background/90 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-4">
            <div className="min-w-0">
              <h1 className="text-xl font-semibold tracking-tight">PPT 模板</h1>
              <p className="mt-0.5 text-sm text-muted-foreground">
                来自 agent-output，可逐页预览后加载到编辑器
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <ThemeSwitcher />
              <Button variant="outline" onClick={() => router.push("/edit")}>
                返回编辑器
              </Button>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-6xl px-6 py-8">
          {loading ? (
            <div className="flex justify-center py-24">
              <Loader2 className="size-8 animate-spin text-muted-foreground" />
            </div>
          ) : templates.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-24 text-center text-sm text-muted-foreground">
              <p>暂无模板。用 agent 生成后放入 agent-output/</p>
            </div>
          ) : (
            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {templates.map((tpl) => (
                <article
                  key={tpl.id}
                  className="flex flex-col overflow-hidden rounded-xl border border-border bg-card text-card-foreground shadow-sm"
                >
                  <button
                    type="button"
                    className="relative aspect-video w-full overflow-hidden bg-muted text-left"
                    onClick={() => openViewer(tpl)}
                  >
                    {tpl.previewFile ? (
                      <div className="pointer-events-none absolute left-0 top-0 origin-top-left scale-[0.3125]">
                        <iframe
                          title={`preview-${tpl.id}`}
                          src={buildTemplateSlideEmbedSrc(
                            tpl.id,
                            tpl.previewFile,
                          )}
                          sandbox="allow-scripts allow-same-origin"
                          className="border-0"
                          style={{ width: 1920, height: 1080 }}
                        />
                      </div>
                    ) : (
                      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                        无预览
                      </div>
                    )}
                    <span className="absolute bottom-2 right-2 rounded bg-black/55 px-2 py-0.5 text-xs text-white">
                      点击查看全部页
                    </span>
                  </button>
                  <div className="flex flex-1 flex-col gap-2 p-4">
                    <div className="flex items-start justify-between gap-2">
                      <h2 className="text-base font-semibold leading-snug">
                        {tpl.label.zh_CN || tpl.templateId}
                      </h2>
                      <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                        {tpl.slideCount} 页
                      </span>
                    </div>
                    <p className="line-clamp-2 flex-1 text-sm text-muted-foreground">
                      {tpl.description.zh_CN || tpl.id}
                    </p>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        className="flex-1"
                        onClick={() => openViewer(tpl)}
                      >
                        逐页查看
                      </Button>
                      <Button
                        className="flex-1"
                        disabled={loadingId === tpl.id}
                        onClick={() => handleLoad(tpl.id)}
                      >
                        {loadingId === tpl.id ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : null}
                        加载到编辑器
                      </Button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </main>

        <Dialog open={viewerOpen} onOpenChange={setViewerOpen}>
          <DialogContent className="max-w-[1040px] gap-0 overflow-hidden border-border bg-background p-0 text-foreground">
            <DialogHeader className="border-b border-border px-6 py-4 text-left">
              <DialogTitle className="pr-8 text-base font-semibold">
                {viewerDoc?.name || "模板预览"}
              </DialogTitle>
              <p className="text-xs font-normal text-muted-foreground">
                {pageTitle}
                {pages.length > 0
                  ? ` · ${pageIndex + 1} / ${pages.length}`
                  : ""}
                {" · 左右方向键翻页"}
              </p>
            </DialogHeader>

            <div className="px-6 py-5">
              {viewerLoading || !currentEmbedSrc ? (
                <div className="flex justify-center py-16">
                  <Loader2 className="size-8 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <div className="flex flex-col items-center gap-4">
                  <SlideFrame
                    key={current!.id}
                    src={currentEmbedSrc}
                    title={current!.id}
                    scale={MODAL_SCALE}
                  />
                  <div className="flex max-w-full flex-wrap justify-center gap-2">
                    {pages.map((p, i) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => setPageIndex(i)}
                        className={cn(
                          "h-8 min-w-8 rounded px-2 text-xs transition-colors",
                          i === pageIndex
                            ? "bg-primary text-primary-foreground"
                            : "bg-muted text-muted-foreground hover:bg-muted/80 hover:text-foreground",
                        )}
                      >
                        {i + 1}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <DialogFooter className="flex-row flex-wrap items-center justify-between gap-3 border-t border-border px-6 py-4 sm:justify-between">
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pageIndex <= 0}
                  onClick={() => setPageIndex((i) => Math.max(0, i - 1))}
                >
                  <ChevronLeft className="size-4" />
                  上一页
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pageIndex >= pages.length - 1}
                  onClick={() =>
                    setPageIndex((i) => Math.min(pages.length - 1, i + 1))
                  }
                >
                  下一页
                  <ChevronRight className="size-4" />
                </Button>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setViewerOpen(false)}>
                  关闭
                </Button>
                <Button
                  disabled={
                    !viewerDoc ||
                    !viewerTplId ||
                    (!!viewerTplId && loadingId === viewerTplId)
                  }
                  onClick={() => {
                    if (viewerTplId && viewerDoc) {
                      void handleLoad(viewerTplId, viewerDoc);
                    }
                  }}
                >
                  {viewerTplId && loadingId === viewerTplId ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : null}
                  加载到编辑器
                </Button>
              </div>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </TooltipProvider>
  );
}
