import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  MoreHorizontal,
  Search,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  categoryLabelZh,
  coerceTemplateCategory,
  fetchTemplateCategories,
  type TemplateCategory,
} from "@/constants/templateCategories";
import { cn } from "@/lib/utils";
import { useRouter } from "@/navigation";
import { buildTemplateSlideEmbedSrc } from "@/utils/templateEmbed";
import {
  captureTemplatePreviewBlobs,
  previewBlobsToPayload,
} from "@/utils/templatePreviewCapture";
import type { TemplateFormat } from "@/types/templateFormat";
import { adminFetch } from "./api";
import {
  AdminSlideFrame,
  formatCny,
  formatTokenCount,
  LoadingButton,
  templateStatusBadge,
  templateRenderBadge,
  TokenWithCost,
  toneBadge,
  useConfirmDialog,
} from "./shared";
import type { TemplateStatus, TemplateSummary } from "./types";

const PAGE_SIZE = 10;

export function TemplatesPanel({
  onRemixQueued,
  onRemixDone,
  focusTemplateId,
}: {
  onRemixQueued?: () => void;
  onRemixDone?: (templateId: string) => void;
  focusTemplateId?: string | null;
}) {
  const router = useRouter();
  const { confirm, dialog } = useConfirmDialog();
  const [rows, setRows] = useState<TemplateSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  /** review=待审批 → ready=已通过待上传 → live=已上传公开 */
  const [catalogTab, setCatalogTab] = useState<"review" | "ready" | "live">(
    "review",
  );
  const [search, setSearch] = useState("");
  const [tablePage, setTablePage] = useState(1);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [categories, setCategories] = useState<TemplateCategory[]>([]);
  const [busy, setBusy] = useState<{
    id: string;
    action:
      | "preview"
      | "approve"
      | "reject"
      | "pending"
      | "delete"
      | "batch-delete"
      | "batch-approve"
      | "batch-reject"
      | "batch-upload"
      | "use-template"
      | "open-editor"
      | "export-pptx"
      | "visual-spec"
      | "upload-qiniu"
      | "featured"
      | "category"
      | "rewrite-page";
  } | null>(null);
  const [preview, setPreview] = useState<{
    id: string;
    format?: TemplateFormat;
    render?: string;
    htmlConvertFailed?: boolean;
    reviewNote?: string | null;
    pages: Array<{
      id: string;
      title: string;
      file: string;
    }>;
  } | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [previewFrameKey, setPreviewFrameKey] = useState(0);
  const [rewriteIssue, setRewriteIssue] = useState("");
  const [rewriting, setRewriting] = useState(false);
  const [useTemplate, setUseTemplate] = useState<TemplateSummary | null>(null);
  const [usePrompt, setUsePrompt] = useState("");
  const [useRegenImages, setUseRegenImages] = useState(false);
  const [randomizingUsePrompt, setRandomizingUsePrompt] = useState(false);

  const isBusy = (id: string, action: NonNullable<typeof busy>["action"]) =>
    busy?.id === id && busy.action === action;
  const rowBusy = (id: string) => busy?.id === id;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [data, cats] = await Promise.all([
        adminFetch("/api/admin/templates"),
        fetchTemplateCategories(),
      ]);
      setRows(data.templates || []);
      setCategories(cats);
      setSelectedIds([]);
      setTablePage(1);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const id = (focusTemplateId || "").trim();
    if (!id) return;
    setHighlightId(id);
    setSearch(id);
    setCatalogTab("review");
    setTablePage(1);
  }, [focusTemplateId]);

  const setStatus = async (
    id: string,
    status: TemplateStatus,
    action: "approve" | "reject" | "pending",
  ) => {
    setBusy({ id, action });
    try {
      await adminFetch(`/api/admin/templates/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      const row = rows.find((r) => r.id === id);
      const svgFallback =
        row?.htmlConvertFailed || row?.render === "svg-fallback";
      if (status === "approved" && svgFallback) {
        toast.warning(
          "已通过，但该包「未转 HTML」（SVG 兜底），不是标准可编辑 html-slide",
          { duration: 8000 },
        );
      } else {
        toast.success(
          status === "approved"
            ? "已通过，请生成规范后上传七牛"
            : status === "rejected"
              ? "已驳回"
              : "已更新",
        );
      }
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const toggleFeatured = async (id: string, featured: boolean) => {
    setBusy({ id, action: "featured" });
    try {
      await adminFetch(`/api/admin/templates/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify({ featured }),
      });
      toast.success(featured ? "已标为精选" : "已取消精选");
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const setCategory = async (id: string, category: string) => {
    setBusy({ id, action: "category" });
    try {
      await adminFetch(`/api/admin/templates/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify({ category }),
      });
      toast.success(`已设为「${categoryLabelZh(categories, category)}」`);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const remove = (id: string) => {
    const row = rows.find((r) => r.id === id);
    const onQiniu = row?.storageBackend === "qiniu";
    confirm({
      title: `删除模板 ${id}？`,
      description: onQiniu
        ? "将同时删除七牛云上的压缩包与预览图，以及本地 agent-output 目录，不可恢复。"
        : "将从本地 agent-output 目录永久删除，不可恢复。",
      okText: "删除",
      destructive: true,
      onConfirm: async () => {
        setBusy({ id, action: "delete" });
        try {
          await adminFetch(`/api/admin/templates/${encodeURIComponent(id)}`, {
            method: "DELETE",
          });
          toast.success(onQiniu ? "已删除（含七牛）" : "已删除");
          setRows((prev) => prev.filter((r) => r.id !== id));
          setSelectedIds((prev) => prev.filter((x) => x !== id));
          await load();
        } catch (e) {
          toast.error(e instanceof Error ? e.message : String(e));
          throw e;
        } finally {
          setBusy(null);
        }
      },
    });
  };

  const removeSelected = () => {
    const ids = [...selectedIds];
    if (ids.length === 0) {
      toast.warning("请先勾选要删除的模板");
      return;
    }
    const idSet = new Set(ids);
    const qiniuCount = rows.filter(
      (r) => idSet.has(r.id) && r.storageBackend === "qiniu",
    ).length;
    confirm({
      title: `批量删除 ${ids.length} 个模板？`,
      description: (
        <div>
          <p className="mb-2">
            将从本地{" "}
            <code className="rounded bg-muted px-1 text-xs">agent-output/</code>{" "}
            永久删除
            {qiniuCount > 0
              ? `；其中 ${qiniuCount} 个已上传七牛，压缩包与预览图也会一并删除`
              : ""}
            ，不可恢复。
          </p>
          <p className="text-xs text-muted-foreground">
            {ids.slice(0, 12).join(", ")}
            {ids.length > 12 ? ` 等 ${ids.length} 个` : ""}
          </p>
        </div>
      ),
      okText: qiniuCount > 0 ? "删除（含七牛）" : "删除本地文件",
      destructive: true,
      onConfirm: async () => {
        setBusy({ id: "__batch__", action: "batch-delete" });
        try {
          const data = await adminFetch("/api/admin/templates", {
            method: "POST",
            body: JSON.stringify({ action: "delete", ids }),
          });
          const deletedIds =
            (data.deleted as string[] | undefined)?.filter(Boolean) ?? [];
          const failed =
            (data.failed as Array<{ id: string }> | undefined) || [];
          const deleted = deletedIds.length;
          if (failed.length === 0) {
            toast.success(
              qiniuCount > 0
                ? `已删除 ${deleted} 个模板（含七牛）`
                : `已删除 ${deleted} 个本地模板`,
            );
          } else {
            toast.warning(
              `删除 ${deleted} 个，失败 ${failed.length} 个：${failed
                .map((f) => f.id)
                .join(", ")}`,
            );
          }
          if (deletedIds.length > 0) {
            const gone = new Set(deletedIds);
            setRows((prev) => prev.filter((r) => !gone.has(r.id)));
            setSelectedIds((prev) => prev.filter((sid) => !gone.has(sid)));
          }
          await load();
        } catch (e) {
          toast.error(e instanceof Error ? e.message : String(e));
          throw e;
        } finally {
          setBusy(null);
        }
      },
    });
  };

  const openPreview = async (id: string) => {
    setBusy({ id, action: "preview" });
    try {
      const data = await adminFetch(
        `/api/admin/templates/${encodeURIComponent(id)}`,
      );
      setPreview({
        id,
        format: data.format || data.meta?.format || "html-slide",
        render: data.render || data.meta?.render,
        htmlConvertFailed: Boolean(
          data.htmlConvertFailed ?? data.render === "svg-fallback",
        ),
        reviewNote: data.reviewNote || data.meta?.review?.note || null,
        pages: data.pages || [],
      });
      setPageIndex(0);
      setRewriteIssue("");
      setPreviewFrameKey(0);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const submitRewritePage = async () => {
    const current = preview?.pages[pageIndex];
    if (!preview || !current?.file) {
      toast.warning("没有可重写的页面");
      return;
    }
    const issue = rewriteIssue.trim();
    if (issue.length < 4) {
      toast.warning("请描述本页问题（至少 4 字）");
      return;
    }
    if (preview.pages.length === 0) {
      toast.warning("模板尚无 HTML 页面，请先完成转换");
      return;
    }
    setRewriting(true);
    setBusy({ id: preview.id, action: "rewrite-page" });
    const toastId = `rewrite-${preview.id}-${pageIndex}`;
    toast.loading("正在按问题重写本页…", { id: toastId });
    try {
      const data = await adminFetch(
        `/api/admin/templates/${encodeURIComponent(preview.id)}/rewrite-page`,
        {
          method: "POST",
          body: JSON.stringify({
            issue,
            file: current.file,
            pageIndex,
          }),
        },
      );
      const jobId = String(data.job?.id || "");
      if (!jobId) {
        throw new Error("未返回任务 id");
      }
      onRemixQueued?.();
      let succeeded = false;
      for (let i = 0; i < 90; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        try {
          const j = await adminFetch(
            `/api/admin/generate/${encodeURIComponent(jobId)}`,
          );
          const job = j.job || j;
          const st = String(job?.status || "");
          if (st === "succeeded") {
            succeeded = true;
            break;
          }
          if (st === "failed" || st === "cancelled") {
            throw new Error(job?.error || `重写任务${st}`);
          }
        } catch (err) {
          if (
            err instanceof Error &&
            (err.message.startsWith("重写任务") ||
              err.message.includes("FAIL") ||
              err.message.includes("失败") ||
              err.message.includes("超时"))
          ) {
            throw err;
          }
          /* keep polling on transient fetch errors */
        }
      }
      if (!succeeded) {
        throw new Error("重写超时，请到任务日志查看进度");
      }
      try {
        const detail = await adminFetch(
          `/api/admin/templates/${encodeURIComponent(preview.id)}`,
        );
        setPreview({
          id: preview.id,
          format: detail.format || detail.meta?.format || preview.format,
          render: detail.render || detail.meta?.render || preview.render,
          htmlConvertFailed: Boolean(
            detail.htmlConvertFailed ??
              (detail.render === "svg-fallback" || preview.htmlConvertFailed),
          ),
          reviewNote:
            detail.reviewNote ||
            detail.meta?.review?.note ||
            preview.reviewNote ||
            null,
          pages: detail.pages || preview.pages,
        });
      } catch {
        /* keep local preview meta */
      }
      setPreviewFrameKey((k) => k + 1);
      setRewriteIssue("");
      toast.success(
        "本页已重写。若已 prepare 上传，请重新截图后再传。",
        { id: toastId, duration: 6000 },
      );
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e), { id: toastId });
    } finally {
      setRewriting(false);
      setBusy(null);
    }
  };

  const fetchEditorDoc = async (id: string) => {
    return adminFetch(`/api/admin/templates/${encodeURIComponent(id)}?doc=1`);
  };

  const openInEditor = async (id: string) => {
    setBusy({ id, action: "open-editor" });
    try {
      const data = await fetchEditorDoc(id);
      if (!data.pages?.length) {
        throw new Error("模板没有可加载的页面");
      }
      sessionStorage.setItem(
        "webppt:pending-template-doc",
        JSON.stringify(data),
      );
      toast.success("模板已加载，正在打开编辑器");
      router.push("/edit");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const openUseTemplate = (row: TemplateSummary) => {
    if (!row.hasVisualSpec) {
      toast.warning(
        "该模板还没有 visual-spec.md。请先点击「visual-spec」生成设计规范，再使用模板。",
      );
      return;
    }
    setUsePrompt("");
    setUseRegenImages(false);
    setUseTemplate(row);
  };

  const randomizeUsePrompt = async () => {
    setRandomizingUsePrompt(true);
    try {
      const data = await adminFetch("/api/admin/prompt-random", {
        method: "POST",
        body: JSON.stringify({}),
      });
      const next = String(data.prompt || "").trim();
      if (!next) throw new Error("AI 未返回可用内容");
      setUsePrompt(next);
      toast.success("已生成一条随机主题，可以直接修改后使用");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRandomizingUsePrompt(false);
    }
  };

  const submitUseTemplate = async () => {
    const row = useTemplate;
    const prompt = usePrompt.trim();
    if (!row || !prompt) {
      toast.warning("请先输入这份新模板的内容要求");
      return;
    }
    if (!row.hasVisualSpec) {
      toast.warning(
        "源模板缺少 visual-spec.md，请先生成设计规范后再使用模板",
      );
      return;
    }
    setBusy({ id: row.id, action: "use-template" });
    try {
      const data = await adminFetch(
        `/api/admin/templates/${encodeURIComponent(row.id)}/use`,
        {
          method: "POST",
          body: JSON.stringify({
            prompt,
            skipImage: !useRegenImages,
          }),
        },
      );
      setUseTemplate(null);
      setUsePrompt("");
      setUseRegenImages(false);
      const jobId = String(data.job?.id || "");
      toast.success(
        jobId
          ? `已启动套用任务：${jobId}（保版式改文案）。完成后列表会自动刷新，也可在「任务日志」查看。`
          : "已启动套用任务（保版式改文案）",
      );
      onRemixQueued?.();
      if (jobId) {
        void (async () => {
          for (let i = 0; i < 90; i++) {
            await new Promise((r) => setTimeout(r, 2000));
            try {
              const j = await adminFetch(
                `/api/admin/generate/${encodeURIComponent(jobId)}`,
              );
              const job = j.job || j;
              const st = String(job?.status || "");
              if (st === "succeeded") {
                const tid =
                  (job.templateIds && job.templateIds[0]) ||
                  job.templateId ||
                  "";
                await load();
                if (tid) {
                  setHighlightId(tid);
                  setSearch(tid);
                  setCatalogTab("fresh");
                  setTablePage(1);
                  onRemixDone?.(tid);
                }
                toast.success(
                  tid
                    ? `套用完成：${tid}（已回到模板列表并定位）`
                    : "套用完成，模板列表已刷新",
                );
                return;
              }
              if (st === "failed" || st === "cancelled") {
                await load();
                toast.error(job?.error || `套用任务${st}`);
                return;
              }
            } catch {
              /* keep polling */
            }
          }
          await load();
        })();
      } else {
        await load();
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const exportPptx = async (id: string, label?: string) => {
    setBusy({ id, action: "export-pptx" });
    const key = `export-${id}`;
    toast.loading("正在导出 PPTX…", { id: key });
    try {
      const data = await fetchEditorDoc(id);
      const pages = (data.pages || []).filter(
        (p: { html?: string }) => p.html && String(p.html).trim(),
      );
      if (!pages.length) {
        throw new Error("没有可导出的 HTML 页面");
      }
      let downloadHtmlToPptx: typeof import("@/services/exportHtmlToPptx").downloadHtmlToPptx;
      try {
        ({ downloadHtmlToPptx } = await import("@/services/exportHtmlToPptx"));
      } catch (loadErr) {
        console.warn("exportHtmlToPptx chunk load retry", loadErr);
        ({ downloadHtmlToPptx } = await import("@/services/exportHtmlToPptx"));
      }
      await downloadHtmlToPptx({
        name: label || data.name || id,
        pages,
        assetBaseUrl: `/api/html-templates/${id}/assets`,
        onProgress: ({ current, total }) => {
          const percent =
            total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;
          toast.loading(`正在导出 PPTX ${percent}%`, { id: key });
        },
      });
      toast.success("PPTX 已下载（html-to-pptx）", { id: key });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      const isChunk =
        /Loading chunk|ChunkLoadError|Failed to fetch dynamically imported/i.test(
          msg,
        );
      toast.error(
        isChunk
          ? "导出模块加载失败（开发态分包未就绪）。请硬刷新后重试。"
          : msg,
        { id: key },
      );
    } finally {
      setBusy(null);
    }
  };

  const ensureVisualSpec = async (
    id: string,
    opts?: {
      messageKey?: string;
      onProgress?: (text: string) => void;
      force?: boolean;
      /** 仅磁盘缺失时生成（准备/上传用，不信任列表缓存） */
      ifMissing?: boolean;
    },
  ) => {
    const row = rows.find((r) => r.id === id);
    // force：覆盖生成；ifMissing：始终打 API，由服务端判断是否已有文件
    // 默认：列表已有 hasVisualSpec 时跳过（手动点 visual-spec 仍可 force）
    if (!opts?.force && !opts?.ifMissing && row?.hasVisualSpec) return;
    const key = opts?.messageKey || `visual-spec-${id}`;
    const text = opts?.ifMissing
      ? "检查 / 补全 visual-spec.md…"
      : "生成 visual-spec.md…";
    opts?.onProgress?.(text);
    toast.loading(text, { id: key });
    await adminFetch(
      `/api/admin/templates/${encodeURIComponent(id)}/visual-spec`,
      {
        method: "POST",
        body: JSON.stringify({
          ...(opts?.ifMissing ? { ifMissing: true } : {}),
        }),
      },
    );
  };

  const generateVisualSpec = async (id: string) => {
    setBusy({ id, action: "visual-spec" });
    const key = `visual-spec-${id}`;
    toast.loading("正在生成 visual-spec.md…", { id: key });
    try {
      await ensureVisualSpec(id, { messageKey: key, force: true });
      toast.success("visual-spec.md 已生成", { id: key });
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e), { id: key });
    } finally {
      setBusy(null);
    }
  };

  const prepareOne = async (
    id: string,
    opts?: {
      messageKey?: string;
      onProgress?: (text: string) => void;
    },
  ) => {
    const key = opts?.messageKey || `prepare-${id}`;
    const progress = (text: string) => {
      opts?.onProgress?.(text);
      toast.loading(text, { id: key });
    };
    const row = rows.find((r) => r.id === id);
    if (row && row.status !== "approved") {
      throw new Error("仅「已通过」模板可上传");
    }
    await ensureVisualSpec(id, {
      messageKey: key,
      onProgress: opts?.onProgress,
      ifMissing: true,
    });

    progress("读取页面列表…");
    const detail = await adminFetch(
      `/api/admin/templates/${encodeURIComponent(id)}`,
    );
    const slideFiles = ((detail.pages || []) as Array<{ file?: string }>)
      .map((p) => String(p.file || "").replace(/^\/+/, ""))
      .filter((f) => f.toLowerCase().endsWith(".html"));
    if (slideFiles.length === 0) {
      throw new Error("模板无 slides/*.html");
    }

    const shots = await captureTemplatePreviewBlobs(
      id,
      slideFiles,
      (done, total) => {
        progress(`离屏截取预览图 ${done}/${total}…`);
      },
    );
    if (shots.length !== slideFiles.length) {
      throw new Error(
        `预览图数量不符：需要 ${slideFiles.length}，得到 ${shots.length}`,
      );
    }

    progress("写入预览图并打包…");
    const payload = await previewBlobsToPayload(shots);
    if (!payload.previews.length) {
      throw new Error("预览图编码失败");
    }
    return adminFetch(
      `/api/admin/templates/${encodeURIComponent(id)}/prepare`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  };

  const uploadOneToQiniu = async (
    id: string,
    opts?: {
      messageKey?: string;
      onProgress?: (text: string) => void;
    },
  ) => {
    const key = opts?.messageKey || `upload-qiniu-${id}`;
    const row = rows.find((r) => r.id === id);
    if (row && row.status !== "approved") {
      throw new Error("仅「已通过」模板可上传");
    }
    await prepareOne(id, { ...opts, messageKey: key });
    const uploading = "上传压缩包和预览图…";
    opts?.onProgress?.(uploading);
    toast.loading(uploading, { id: key });
    return adminFetch(
      `/api/admin/templates/${encodeURIComponent(id)}/upload`,
      { method: "POST", body: JSON.stringify({}) },
    );
  };

  const uploadToQiniu = async (id: string) => {
    setBusy({ id, action: "upload-qiniu" });
    const key = `upload-qiniu-${id}`;
    try {
      const data = await uploadOneToQiniu(id, { messageKey: key });
      const zipMb =
        typeof data.zipBytes === "number"
          ? `${(data.zipBytes / (1024 * 1024)).toFixed(2)} MB`
          : null;
      toast.success(
        [
          "已上传七牛",
          zipMb,
          typeof data.previewPages === "number"
            ? `预览 ${data.previewPages} 页`
            : null,
          data.url ? data.url : null,
        ]
          .filter(Boolean)
          .join(" · "),
        { id: key, duration: 8000 },
      );
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e), { id: key });
    } finally {
      setBusy(null);
    }
  };

  const batchSetStatus = (action: "approve" | "reject") => {
    const ids = [...selectedIds];
    if (ids.length === 0) {
      toast.warning(
        action === "approve" ? "请先勾选要通过的模板" : "请先勾选要驳回的模板",
      );
      return;
    }
    const label = action === "approve" ? "通过" : "驳回";
    confirm({
      title: `批量${label} ${ids.length} 个模板？`,
      description: (
        <div>
          <p className="mb-2">
            {action === "approve"
              ? "通过后可上传七牛，并在公开库可见。"
              : "驳回后公开库不可见。"}
          </p>
          <p className="text-xs text-muted-foreground">
            {ids.slice(0, 12).join(", ")}
            {ids.length > 12 ? ` 等 ${ids.length} 个` : ""}
          </p>
        </div>
      ),
      okText: label,
      destructive: action === "reject",
      onConfirm: async () => {
        setBusy({ id: ids[0], action: `batch-${action}` });
        try {
          const data = await adminFetch("/api/admin/templates", {
            method: "POST",
            body: JSON.stringify({ action, ids }),
          });
          const ok = (data.updated || []).length;
          const fail = (data.failed || []).length;
          if (fail > 0) {
            toast.warning(`批量${label}完成：成功 ${ok}，失败 ${fail}`);
          } else {
            toast.success(`已批量${label} ${ok} 个`);
          }
          setSelectedIds([]);
          await load();
        } catch (e) {
          toast.error(e instanceof Error ? e.message : String(e));
          throw e;
        } finally {
          setBusy(null);
        }
      },
    });
  };

  const uploadSelected = () => {
    const ids = [...selectedIds];
    if (ids.length === 0) {
      toast.warning("请先勾选要上传的模板");
      return;
    }
    const selected = rows.filter((r) => ids.includes(r.id));
    const eligible = selected.filter((r) => r.status === "approved");
    const skipped = selected.filter((r) => r.status !== "approved");
    const needSpec = eligible.filter((r) => !r.hasVisualSpec);
    if (eligible.length === 0) {
      toast.warning("没有可上传项。需状态为「已通过」");
      return;
    }
    confirm({
      title: `批量上传 ${eligible.length} 个模板到七牛？`,
      description: (
        <div>
          <p className="mb-2">
            每个模板会先离屏截图、打本地压缩包，再上传七牛。缺 visual-spec
            的会自动生成后再上传。
          </p>
          {needSpec.length > 0 ? (
            <p className="mb-2 text-amber-700 dark:text-amber-300">
              其中 {needSpec.length} 个将先自动生成 visual-spec.md
            </p>
          ) : null}
          {skipped.length > 0 ? (
            <p className="mb-2 text-amber-700 dark:text-amber-300">
              将跳过 {skipped.length} 个（未通过）
            </p>
          ) : null}
          <p className="text-xs text-muted-foreground">
            {eligible
              .slice(0, 8)
              .map((r) => r.label?.zh_CN || r.id)
              .join("、")}
            {eligible.length > 8 ? ` 等 ${eligible.length} 个` : ""}
          </p>
        </div>
      ),
      okText: "开始上传",
      onConfirm: async () => {
        setBusy({ id: eligible[0].id, action: "batch-upload" });
        const key = "batch-upload-qiniu";
        let ok = 0;
        const failed: Array<{ id: string; error: string }> = [];
        try {
          for (let i = 0; i < eligible.length; i += 1) {
            const row = eligible[i];
            try {
              await uploadOneToQiniu(row.id, {
                messageKey: key,
                onProgress: (text) => {
                  toast.loading(
                    `[${i + 1}/${eligible.length}] ${row.label?.zh_CN || row.id} · ${text}`,
                    { id: key },
                  );
                },
              });
              ok += 1;
            } catch (e) {
              failed.push({
                id: row.id,
                error: e instanceof Error ? e.message : String(e),
              });
            }
          }
          if (failed.length === 0) {
            toast.success(`批量上传完成：${ok} 个`, {
              id: key,
              duration: 6000,
            });
          } else {
            toast.warning(
              `批量上传结束：成功 ${ok}，失败 ${failed.length}（${failed
                .slice(0, 3)
                .map((f) => `${f.id}: ${f.error}`)
                .join("；")}${failed.length > 3 ? "…" : ""}）`,
              { id: key, duration: 10000 },
            );
          }
          setSelectedIds([]);
          await load();
        } finally {
          setBusy(null);
        }
      },
    });
  };

  const page = preview?.pages[pageIndex];
  const embedSrc =
    preview && page?.file
      ? buildTemplateSlideEmbedSrc(preview.id, page.file)
      : null;

  useEffect(() => {
    if (!preview || rewriting) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") {
        setPageIndex((i) => Math.max(0, i - 1));
      } else if (e.key === "ArrowRight") {
        setPageIndex((i) => Math.min((preview.pages.length || 1) - 1, i + 1));
      } else if (e.key === "Escape") {
        setPreview(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [preview, rewriting]);

  const isUploaded = (row: TemplateSummary) => row.storageBackend === "qiniu";
  const isReview = (row: TemplateSummary) =>
    row.status === "pending" ||
    row.status === "rejected" ||
    row.status === "draft";
  const isReady = (row: TemplateSummary) =>
    row.status === "approved" && !isUploaded(row);

  const filteredRows = useMemo(
    () =>
      rows.filter((row) => {
        const inTab =
          catalogTab === "review"
            ? isReview(row)
            : catalogTab === "ready"
              ? isReady(row)
              : isUploaded(row);
        if (!inTab) return false;
        const q = search.trim().toLowerCase();
        if (!q) return true;
        const hay = [
          row.id,
          row.publicId,
          row.label?.zh_CN,
          row.label?.en_US,
          row.sourceTemplateId,
        ]
          .filter(Boolean)
          .join("\n")
          .toLowerCase();
        return hay.includes(q);
      }),
    [rows, catalogTab, search],
  );

  const reviewCount = rows.filter(isReview).length;
  const readyCount = rows.filter(isReady).length;
  const liveCount = rows.filter(isUploaded).length;

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const pageRows = filteredRows.slice(
    (tablePage - 1) * PAGE_SIZE,
    tablePage * PAGE_SIZE,
  );

  const pageIds = pageRows.map((r) => r.id);
  const allPageSelected =
    pageIds.length > 0 && pageIds.every((id) => selectedIds.includes(id));
  const somePageSelected =
    pageIds.some((id) => selectedIds.includes(id)) && !allPageSelected;

  const toggleSelectAllPage = (checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) => Array.from(new Set([...prev, ...pageIds])));
    } else {
      const drop = new Set(pageIds);
      setSelectedIds((prev) => prev.filter((id) => !drop.has(id)));
    }
  };

  const toggleSelect = (id: string, checked: boolean) => {
    setSelectedIds((prev) =>
      checked ? Array.from(new Set([...prev, id])) : prev.filter((x) => x !== id),
    );
  };

  return (
    <>
      {dialog}
      <Tabs
        value={catalogTab}
        onValueChange={(key) => {
          if (key === "ready" || key === "live" || key === "review") {
            setCatalogTab(key);
          }
          setSelectedIds([]);
          setTablePage(1);
        }}
        className="mb-3"
      >
        <TabsList>
          <TabsTrigger value="review">待审批 ({reviewCount})</TabsTrigger>
          <TabsTrigger value="ready">已通过·待上传 ({readyCount})</TabsTrigger>
          <TabsTrigger value="live">已上传 ({liveCount})</TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative w-[260px]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-8"
            placeholder="搜索名称 / id / 套用来源"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setTablePage(1);
            }}
          />
        </div>
        <LoadingButton
          variant="outline"
          onClick={() => void load()}
          loading={loading}
        >
          刷新
        </LoadingButton>
        {catalogTab === "review" ? (
          <>
            <LoadingButton
              variant="outline"
              loading={busy?.action === "batch-approve"}
              disabled={selectedIds.length === 0 || Boolean(busy)}
              onClick={() => batchSetStatus("approve")}
            >
              批量通过{selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}
            </LoadingButton>
            <LoadingButton
              variant="outline"
              loading={busy?.action === "batch-reject"}
              disabled={selectedIds.length === 0 || Boolean(busy)}
              onClick={() => batchSetStatus("reject")}
            >
              批量不通过
              {selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}
            </LoadingButton>
          </>
        ) : null}
        {catalogTab === "ready" || catalogTab === "live" ? (
          <LoadingButton
            variant={catalogTab === "live" ? "outline" : "default"}
            loading={busy?.action === "batch-upload"}
            disabled={selectedIds.length === 0 || Boolean(busy)}
            onClick={uploadSelected}
            title="需已通过；缺 visual-spec 会自动生成后再上传"
          >
            {catalogTab === "live" ? "批量重传" : "批量上传"}
            {selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}
          </LoadingButton>
        ) : null}
        <LoadingButton
          variant="destructive"
          loading={busy?.action === "batch-delete"}
          disabled={selectedIds.length === 0 || Boolean(busy)}
          onClick={removeSelected}
        >
          批量删除{selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}
        </LoadingButton>
        <span className="text-sm text-muted-foreground">
          共 {filteredRows.length} 条
          {search.trim() ? `（已筛选，全库 ${rows.length}）` : ""}
          {" · "}
          {catalogTab === "review"
            ? "通过后进入「已通过·待上传」"
            : catalogTab === "ready"
              ? "生成规范并上传后，首页才可见"
              : "已上七牛；可标记精选"}
        </span>
      </div>

      <div className="rounded-lg border border-border bg-card">
        <div className="overflow-x-auto">
          <Table className="min-w-[1480px] table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox
                    checked={
                      allPageSelected
                        ? true
                        : somePageSelected
                          ? "indeterminate"
                          : false
                    }
                    onCheckedChange={(v) => toggleSelectAllPage(v === true)}
                    aria-label="全选本页"
                  />
                </TableHead>
                <TableHead className="w-[240px]">名称</TableHead>
                <TableHead className="w-[96px]">状态</TableHead>
                <TableHead className="w-[64px] text-center">页数</TableHead>
                <TableHead className="w-[118px] text-right">页面 Token</TableHead>
                <TableHead className="w-[136px] text-right">图片 Token</TableHead>
                <TableHead className="w-[88px]">存储</TableHead>
                <TableHead className="w-[160px]">更新</TableHead>
                <TableHead className="w-[460px]">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pageRows.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={9}
                    className="py-10 text-center text-muted-foreground"
                  >
                    {loading ? "加载中…" : "暂无模板"}
                  </TableCell>
                </TableRow>
              ) : (
                pageRows.map((row) => {
                  const uploaded = isUploaded(row);
                  const approved = row.status === "approved";
                  const canUpload = approved;
                  const showVisualSpec = approved;
                  const showUpload = approved;
                  const showFeatured = uploaded;
                  const moreItems = [
                    catalogTab === "review" && row.status !== "approved"
                      ? {
                          key: "approve",
                          label: "通过",
                          disabled:
                            rowBusy(row.id) && !isBusy(row.id, "approve"),
                          onClick: () =>
                            void setStatus(row.id, "approved", "approve"),
                        }
                      : null,
                    catalogTab === "review" && row.status !== "rejected"
                      ? {
                          key: "reject",
                          label: "驳回",
                          disabled:
                            rowBusy(row.id) && !isBusy(row.id, "reject"),
                          onClick: () =>
                            void setStatus(row.id, "rejected", "reject"),
                        }
                      : null,
                    approved
                      ? {
                          key: "pending",
                          label: "撤回待审",
                          disabled:
                            rowBusy(row.id) && !isBusy(row.id, "pending"),
                          onClick: () =>
                            void setStatus(row.id, "pending", "pending"),
                        }
                      : null,
                    {
                      key: "delete",
                      label: "删除",
                      danger: true,
                      disabled: rowBusy(row.id) && !isBusy(row.id, "delete"),
                      onClick: () => remove(row.id),
                    },
                  ].filter(Boolean) as Array<{
                    key: string;
                    label: string;
                    danger?: boolean;
                    disabled?: boolean;
                    onClick: () => void;
                  }>;

                  const displayId = row.publicId || row.id;
                  const tokens = row.imageTokens;
                  const imgs = row.imageCount ?? row.imageCalls;
                  const hasTokens = tokens != null && tokens > 0;
                  const costLabel = formatCny(row.imageCostCny);
                  const imgLabel = imgs != null && imgs > 0 ? `${imgs}张` : null;

                  return (
                    <TableRow
                      key={row.id}
                      className={cn(
                        highlightId === row.id &&
                          "bg-orange-50/80 dark:bg-orange-950/50",
                      )}
                    >
                      <TableCell>
                        <Checkbox
                          checked={selectedIds.includes(row.id)}
                          onCheckedChange={(v) =>
                            toggleSelect(row.id, v === true)
                          }
                          aria-label={`选择 ${row.id}`}
                        />
                      </TableCell>
                      <TableCell>
                        <div className="min-w-0 max-w-[220px]">
                          <div
                            title={row.label?.zh_CN || row.id}
                            className={cn(
                              "truncate font-medium",
                              highlightId === row.id &&
                                "rounded bg-orange-100/80 px-1 dark:bg-orange-900/50",
                            )}
                          >
                            {row.label?.zh_CN || row.id}
                          </div>
                          <div
                            title={
                              row.sourceTemplateId
                                ? `${displayId} ← ${row.sourceTemplateId}`
                                : displayId
                            }
                            className="truncate font-mono text-xs text-muted-foreground"
                          >
                            {displayId}
                          </div>
                          <Select
                            value={coerceTemplateCategory(
                              row.category,
                              categories,
                            )}
                            disabled={
                              rowBusy(row.id) && !isBusy(row.id, "category")
                            }
                            onValueChange={(v) => void setCategory(row.id, v)}
                          >
                            <SelectTrigger
                              className="mt-1.5 h-7 w-[132px] text-xs"
                              aria-label="视觉风格类型"
                            >
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent className="max-h-72">
                              {categories.map((item) => (
                                <SelectItem key={item.id} value={item.id}>
                                  {item.labelZh}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1">
                          {templateStatusBadge(row.status)}
                          {templateRenderBadge(
                            row.render,
                            row.htmlConvertFailed,
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-center">
                        {row.slideCount}
                      </TableCell>
                      <TableCell className="text-right">
                        <TokenWithCost
                          tokens={row.pageTokens}
                          cost={row.pageCostCny}
                        />
                      </TableCell>
                      <TableCell className="text-right">
                        {!hasTokens && !imgLabel && !costLabel ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <span
                            title={
                              [
                                hasTokens
                                  ? `${tokens} tokens`
                                  : "接口未回传 token",
                                costLabel
                                  ? `约 ${costLabel}（公开价估算）`
                                  : null,
                                imgs != null ? `${imgs} 次/张` : null,
                              ]
                                .filter(Boolean)
                                .join(" · ") || undefined
                            }
                            className="whitespace-nowrap"
                          >
                            {hasTokens ? formatTokenCount(tokens) : "—"}
                            {costLabel ? (
                              <span className="text-xs text-muted-foreground">
                                {" "}
                                · {costLabel}
                              </span>
                            ) : null}
                            {imgLabel ? (
                              <span className="text-xs text-muted-foreground">
                                {" "}
                                / {imgLabel}
                              </span>
                            ) : null}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            row.storageBackend === "qiniu"
                              ? "default"
                              : "secondary"
                          }
                          className={
                            row.storageBackend === "qiniu"
                              ? toneBadge.sky
                              : undefined
                          }
                        >
                          {row.storageBackend || "local"}
                        </Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs">
                        {row.mtimeMs
                          ? new Date(row.mtimeMs).toLocaleString()
                          : "—"}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-nowrap items-center gap-1 whitespace-nowrap">
                          <LoadingButton
                            size="sm"
                            variant="outline"
                            loading={isBusy(row.id, "preview")}
                            disabled={
                              rowBusy(row.id) && !isBusy(row.id, "preview")
                            }
                            onClick={() => void openPreview(row.id)}
                          >
                            预览
                          </LoadingButton>
                          <LoadingButton
                            size="sm"
                            variant="outline"
                            className="border-primary text-primary hover:bg-primary/5"
                            loading={isBusy(row.id, "use-template")}
                            disabled={
                              rowBusy(row.id) && !isBusy(row.id, "use-template")
                            }
                            title="保留版式与配色，按新主题改写文案/配图"
                            onClick={() => openUseTemplate(row)}
                          >
                            使用模板
                          </LoadingButton>
                          <LoadingButton
                            size="sm"
                            variant="outline"
                            loading={isBusy(row.id, "open-editor")}
                            disabled={
                              rowBusy(row.id) && !isBusy(row.id, "open-editor")
                            }
                            onClick={() => void openInEditor(row.id)}
                          >
                            编辑器
                          </LoadingButton>
                          <LoadingButton
                            size="sm"
                            variant="outline"
                            loading={isBusy(row.id, "export-pptx")}
                            disabled={
                              rowBusy(row.id) && !isBusy(row.id, "export-pptx")
                            }
                            onClick={() =>
                              void exportPptx(
                                row.id,
                                row.label?.zh_CN || row.id,
                              )
                            }
                          >
                            PPTX
                          </LoadingButton>
                          {showVisualSpec ? (
                            <LoadingButton
                              size="sm"
                              variant="outline"
                              loading={isBusy(row.id, "visual-spec")}
                              disabled={
                                rowBusy(row.id) &&
                                !isBusy(row.id, "visual-spec")
                              }
                              title="调用 LLM 生成 / 覆盖 visual-spec.md"
                              onClick={() => void generateVisualSpec(row.id)}
                            >
                              生成规范
                            </LoadingButton>
                          ) : null}
                          {showUpload ? (
                            <LoadingButton
                              size="sm"
                              variant={uploaded ? "outline" : "default"}
                              loading={isBusy(row.id, "upload-qiniu")}
                              disabled={
                                !canUpload ||
                                (rowBusy(row.id) &&
                                  !isBusy(row.id, "upload-qiniu"))
                              }
                              title={
                                canUpload
                                  ? "缺 visual-spec 会先自动生成，再截图打包上传七牛"
                                  : "仅「已通过」可上传"
                              }
                              onClick={() => void uploadToQiniu(row.id)}
                            >
                              {uploaded ? "重传" : "上传"}
                            </LoadingButton>
                          ) : null}
                          {showFeatured ? (
                            <LoadingButton
                              size="sm"
                              variant={row.featured ? "default" : "outline"}
                              loading={isBusy(row.id, "featured")}
                              disabled={
                                rowBusy(row.id) && !isBusy(row.id, "featured")
                              }
                              title={
                                row.featured
                                  ? "取消公开墙精选标记"
                                  : "在公开墙标记为精选"
                              }
                              onClick={() =>
                                void toggleFeatured(row.id, !row.featured)
                              }
                            >
                              {row.featured ? "取消精选" : "精选"}
                            </LoadingButton>
                          ) : null}
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <LoadingButton
                                size="sm"
                                variant="outline"
                                loading={
                                  isBusy(row.id, "approve") ||
                                  isBusy(row.id, "reject") ||
                                  isBusy(row.id, "pending") ||
                                  isBusy(row.id, "delete")
                                }
                              >
                                <MoreHorizontal className="h-4 w-4" />
                              </LoadingButton>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              {moreItems.map((it) => (
                                <DropdownMenuItem
                                  key={it.key}
                                  disabled={it.disabled}
                                  className={
                                    it.danger
                                      ? "text-destructive focus:text-destructive"
                                      : undefined
                                  }
                                  onClick={it.onClick}
                                >
                                  {it.label}
                                </DropdownMenuItem>
                              ))}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {filteredRows.length > PAGE_SIZE ? (
        <div className="mt-3 flex items-center justify-end gap-2 text-sm">
          <Button
            variant="outline"
            size="sm"
            disabled={tablePage <= 1}
            onClick={() => setTablePage((p) => Math.max(1, p - 1))}
          >
            上一页
          </Button>
          <span className="text-muted-foreground">
            {tablePage} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={tablePage >= totalPages}
            onClick={() => setTablePage((p) => Math.min(totalPages, p + 1))}
          >
            下一页
          </Button>
        </div>
      ) : null}

      <Dialog
        open={Boolean(preview)}
        onOpenChange={(open) => {
          if (!open && !rewriting) setPreview(null);
        }}
      >
        <DialogContent className="max-w-[1040px] gap-0 overflow-hidden p-0">
          <DialogHeader className="border-b px-6 py-4">
            <DialogTitle className="pr-8 text-base">
              {preview ? `预览 · ${preview.id}` : "预览"}
            </DialogTitle>
            {preview ? (
              <div className="space-y-1">
                {preview.htmlConvertFailed ||
                preview.render === "svg-fallback" ? (
                  <p className="rounded-md border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-xs text-rose-900 dark:border-rose-800 dark:bg-rose-950/50 dark:text-rose-200">
                    未转成标准 HTML：当前为 SVG
                    兜底预览包（svg_to_pptx/转包失败），仅供人工查看，不是可编辑
                    html-slide。
                    {preview.reviewNote ? ` ${preview.reviewNote}` : ""}
                  </p>
                ) : null}
                <p className="text-xs font-normal text-muted-foreground">
                  {page?.title || "—"}
                  {page?.file ? ` · ${page.file}` : ""}
                  {preview.pages.length > 0
                    ? ` · ${pageIndex + 1} / ${preview.pages.length}`
                    : ""}
                  {" · 左右方向键翻页"}
                </p>
              </div>
            ) : null}
          </DialogHeader>
          <div className="bg-muted px-6 py-5">
            {embedSrc && page ? (
              <div className="flex flex-col items-center gap-4">
                <AdminSlideFrame
                  key={`${preview!.id}-html-${page.file}-${pageIndex}-${previewFrameKey}`}
                  src={`${embedSrc}${embedSrc.includes("?") ? "&" : "?"}v=${previewFrameKey}`}
                  title={page.title || page.file}
                />
                <div className="flex max-w-full flex-wrap justify-center gap-2">
                  {preview!.pages.map((p, i) => (
                    <button
                      key={p.id || p.file || String(i)}
                      type="button"
                      disabled={rewriting}
                      onClick={() => setPageIndex(i)}
                      className={cn(
                        "h-8 min-w-8 rounded px-2 text-xs",
                        i === pageIndex
                          ? "bg-primary text-primary-foreground"
                          : "bg-foreground/5 text-foreground/70 hover:bg-foreground/10",
                        rewriting && "opacity-50",
                      )}
                    >
                      {i + 1}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">无页面</p>
            )}
          </div>
          {preview && preview.pages.length > 0 ? (
            <div className="space-y-3 border-t px-6 py-3">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">本页问题（可重写）</span>
                  <span className="text-xs text-muted-foreground">
                    可改文案与版式，保留主题色与本地配图
                  </span>
                </div>
                <Textarea
                  value={rewriteIssue}
                  onChange={(e) => setRewriteIssue(e.target.value)}
                  disabled={rewriting}
                  placeholder="例如：标题与副题重叠；右侧留白太大；正文太挤请改成两栏…"
                  rows={2}
                  maxLength={2000}
                />
                <div className="text-right text-xs text-muted-foreground">
                  {rewriteIssue.length} / 2000
                </div>
              </div>
              <DialogFooter className="flex-row flex-wrap items-center justify-between gap-2 border-0 p-0 sm:justify-between">
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    disabled={rewriting || pageIndex <= 0}
                    onClick={() => setPageIndex((i) => Math.max(0, i - 1))}
                  >
                    <ChevronLeft className="h-4 w-4" />
                    上一页
                  </Button>
                  <Button
                    variant="outline"
                    disabled={
                      rewriting || pageIndex >= preview.pages.length - 1
                    }
                    onClick={() =>
                      setPageIndex((i) =>
                        Math.min((preview?.pages.length || 1) - 1, i + 1),
                      )
                    }
                  >
                    下一页
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
                <div className="flex gap-2">
                  <LoadingButton
                    loading={rewriting}
                    disabled={rewriteIssue.trim().length < 4}
                    onClick={() => void submitRewritePage()}
                  >
                    按问题重写本页
                  </LoadingButton>
                  <Button
                    variant="outline"
                    disabled={rewriting}
                    onClick={() => setPreview(null)}
                  >
                    关闭
                  </Button>
                </div>
              </DialogFooter>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(useTemplate)}
        onOpenChange={(open) => {
          if (!open && busy?.action !== "use-template") {
            setUseTemplate(null);
            setUsePrompt("");
            setUseRegenImages(false);
          }
        }}
      >
        <DialogContent className="max-w-[680px]">
          <DialogHeader>
            <DialogTitle>
              {useTemplate
                ? `使用模板 · ${useTemplate.label?.zh_CN || useTemplate.id}`
                : "使用模板"}
            </DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            输入新主题与内容要求。系统会<strong>原样保留</strong>
            当前模板的配色、版式与装饰，只替换文案槽位（以及可选配图），生成一份新的待审模板。套用前须已有
            visual-spec.md。
          </p>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">内容要求</span>
            <span className="text-xs text-muted-foreground">
              可先用 AI 生成，再按需修改
            </span>
          </div>
          <Textarea
            autoFocus
            value={usePrompt}
            onChange={(e) => setUsePrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submitUseTemplate();
              }
            }}
            placeholder="例如：为制造业客户制作一份 AI 质检方案介绍，突出痛点、流程、收益和落地计划"
            rows={5}
            maxLength={6000}
          />
          <div className="text-right text-xs text-muted-foreground">
            {usePrompt.length} / 6000
          </div>
          <div className="mt-2 flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium">重生配图</div>
              <p className="text-xs text-muted-foreground">
                关=保留模板原图（更稳）；开=按新主题重跑文生图（仅 image 槽）
              </p>
            </div>
            <Switch
              checked={useRegenImages}
              onCheckedChange={setUseRegenImages}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            按 Enter 立即生成；需要换行时按 Shift + Enter。
          </p>
          <DialogFooter className="flex-row items-center justify-between sm:justify-between">
            <LoadingButton
              variant="outline"
              loading={randomizingUsePrompt}
              disabled={busy?.action === "use-template"}
              onClick={() => void randomizeUsePrompt()}
            >
              <Zap className="h-4 w-4" />
              AI 随机生成
            </LoadingButton>
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  if (busy?.action !== "use-template") {
                    setUseTemplate(null);
                    setUsePrompt("");
                    setUseRegenImages(false);
                  }
                }}
              >
                取消
              </Button>
              <LoadingButton
                loading={busy?.action === "use-template"}
                disabled={!usePrompt.trim()}
                onClick={() => void submitUseTemplate()}
              >
                开始生成
              </LoadingButton>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
