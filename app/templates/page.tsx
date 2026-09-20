"use client";

import type { PPTDocumentJSON } from "@/utils/loadDocument";
import { buildTemplateSlideEmbedSrc } from "@/utils/templateEmbed";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Empty, Modal, Spin, message } from "antd";
import { LeftOutlined, RightOutlined } from "@ant-design/icons";

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
      className="relative overflow-hidden bg-[#e8e6e1]"
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
  const [loading, setLoading] = useState(true);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [templates, setTemplates] = useState<TemplateCard[]>([]);

  const [viewerOpen, setViewerOpen] = useState(false);
  const [viewerLoading, setViewerLoading] = useState(false);
  const [viewerDoc, setViewerDoc] = useState<TemplateDoc | null>(null);
  const [viewerTplId, setViewerTplId] = useState<string | null>(null);
  const [pageIndex, setPageIndex] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/html-templates");
        if (!res.ok) throw new Error("LIST_FAILED");
        const data = (await res.json()) as { templates: TemplateCard[] };
        if (!cancelled) setTemplates(data.templates || []);
      } catch {
        if (!cancelled) message.error("无法读取模板列表");
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
        message.success("模板已加载，正在打开编辑器");
        router.push("/");
      } catch {
        message.error("加载模板失败");
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
        message.error("无法打开预览");
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
    <div className="min-h-screen bg-[#f4f2ef] text-[#1a1a1a]">
      <header className="sticky top-0 z-10 border-b border-black/5 bg-[#f4f2ef]/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">PPT 模板</h1>
            <p className="mt-0.5 text-sm text-black/50">
              来自 agent-output，可逐页预览后加载到编辑器
            </p>
          </div>
          <Button type="default" onClick={() => router.push("/")}>
            返回编辑器
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        {loading ? (
          <div className="flex justify-center py-24">
            <Spin size="large" />
          </div>
        ) : templates.length === 0 ? (
          <Empty
            description={
              <span className="text-black/45">
                暂无模板。用 agent 生成后放入 agent-output/
              </span>
            }
          />
        ) : (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {templates.map((tpl) => (
              <article
                key={tpl.id}
                className="flex flex-col overflow-hidden rounded-xl border border-black/8 bg-white shadow-sm"
              >
                <button
                  type="button"
                  className="relative aspect-video w-full overflow-hidden bg-[#e8e6e1] text-left"
                  onClick={() => openViewer(tpl)}
                >
                  {tpl.previewFile ? (
                    <div className="pointer-events-none absolute left-0 top-0 origin-top-left scale-[0.3125]">
                      <iframe
                        title={`preview-${tpl.id}`}
                        src={buildTemplateSlideEmbedSrc(tpl.id, tpl.previewFile)}
                        sandbox="allow-scripts allow-same-origin"
                        className="border-0"
                        style={{ width: 1920, height: 1080 }}
                      />
                    </div>
                  ) : (
                    <div className="flex h-full items-center justify-center text-sm text-black/35">
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
                    <span className="shrink-0 rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/55">
                      {tpl.slideCount} 页
                    </span>
                  </div>
                  <p className="line-clamp-2 flex-1 text-sm text-black/55">
                    {tpl.description.zh_CN || tpl.id}
                  </p>
                  <div className="flex gap-2">
                    <Button block onClick={() => openViewer(tpl)}>
                      逐页查看
                    </Button>
                    <Button
                      type="primary"
                      block
                      loading={loadingId === tpl.id}
                      onClick={() => handleLoad(tpl.id)}
                    >
                      加载到编辑器
                    </Button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </main>

      <Modal
        open={viewerOpen}
        onCancel={() => setViewerOpen(false)}
        width={1040}
        centered
        destroyOnClose
        rootClassName="admin-flat-modal"
        title={
          <div className="pr-8">
            <div className="text-base font-semibold text-black/88">
              {viewerDoc?.name || "模板预览"}
            </div>
            <div className="mt-0.5 text-xs font-normal text-black/45">
              {pageTitle}
              {pages.length > 0
                ? ` · ${pageIndex + 1} / ${pages.length}`
                : ""}
              {" · 左右方向键翻页"}
            </div>
          </div>
        }
        footer={
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Button
                icon={<LeftOutlined />}
                disabled={pageIndex <= 0}
                onClick={() => setPageIndex((i) => Math.max(0, i - 1))}
              >
                上一页
              </Button>
              <Button
                icon={<RightOutlined />}
                disabled={pageIndex >= pages.length - 1}
                onClick={() =>
                  setPageIndex((i) => Math.min(pages.length - 1, i + 1))
                }
              >
                下一页
              </Button>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => setViewerOpen(false)}>关闭</Button>
              <Button
                type="primary"
                loading={!!viewerTplId && loadingId === viewerTplId}
                disabled={!viewerDoc || !viewerTplId}
                onClick={() => {
                  if (viewerTplId && viewerDoc) {
                    void handleLoad(viewerTplId, viewerDoc);
                  }
                }}
              >
                加载到编辑器
              </Button>
            </div>
          </div>
        }
      >
        {viewerLoading || !currentEmbedSrc ? (
          <div className="flex justify-center py-16">
            <Spin size="large" />
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
                  className={`h-8 min-w-8 rounded px-2 text-xs ${
                    i === pageIndex
                      ? "bg-[#f25f00] text-white"
                      : "bg-black/5 text-black/65 hover:bg-black/10"
                  }`}
                >
                  {i + 1}
                </button>
              ))}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
