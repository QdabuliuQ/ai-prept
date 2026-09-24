import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { pptxBrowserConvert } from "@/utils/pptxBrowserConvert";
import { adminFetch, adminFetchBinary } from "./api";
import {
  isActiveJob,
  JobProgressBar,
  jobStatusBadge,
  LoadingButton,
  needsBrowserHtmlConvert,
  useConfirmDialog,
} from "./shared";
import type { GenerateJob } from "./types";

const PAGE_SIZE = 10;

export function JobsPanel() {
  const { confirm, dialog } = useConfirmDialog();
  const [jobs, setJobs] = useState<GenerateJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [logJob, setLogJob] = useState<GenerateJob | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [clearingTerminal, setClearingTerminal] = useState(false);
  const [page, setPage] = useState(1);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const logPreRef = useRef<HTMLPreElement | null>(null);
  const logStickBottomRef = useRef(true);
  const convertingRef = useRef<Set<string>>(new Set());
  const convertFailedRef = useRef<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminFetch("/api/admin/generate");
      setJobs(data.jobs || []);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runBrowserConvert = useCallback(
    async (job: GenerateJob) => {
      const tid =
        job.convertTemplateId ||
        job.templateId ||
        job.templateIds?.[0] ||
        "";
      if (
        !tid ||
        convertingRef.current.has(job.id) ||
        convertFailedRef.current.has(job.id)
      ) {
        return;
      }
      convertingRef.current.add(job.id);
      try {
        toast.message(`浏览器转换中… ${tid}`);
        const buffer = await adminFetchBinary(
          `/api/admin/templates/${encodeURIComponent(tid)}/source.pptx`,
        );
        let labelZh = "";
        try {
          const detail = await adminFetch(
            `/api/admin/templates/${encodeURIComponent(tid)}`,
          );
          const label = detail?.label;
          if (label && typeof label === "object") {
            labelZh = String(label.zh_CN || label.en_US || "").trim();
          }
        } catch {
          /* optional: backend will preserve prior label */
        }
        if (!labelZh || labelZh === tid) {
          labelZh = "";
        }
        const result = await pptxBrowserConvert(buffer, {
          labelZh: labelZh || tid,
        });
        await adminFetch(
          `/api/admin/templates/${encodeURIComponent(tid)}/import-html-package`,
          {
            method: "POST",
            body: JSON.stringify({
              // 空字符串让后端保留 template.json 里已有的中文名
              labelZh: labelZh || undefined,
              slides: result.slides,
              images: result.images,
              warnings: result.warnings,
              theme: result.theme,
            }),
          },
        );
        try {
          await adminFetch(
            `/api/admin/generate/${encodeURIComponent(job.id)}/mark-converted`,
            { method: "POST", body: "{}" },
          );
        } catch {
          /* mark-converted optional if already succeeded */
        }
        convertFailedRef.current.delete(job.id);
        toast.success(`HTML 转换完成：${tid}（${result.slides.length} 页）`);
        await load();
      } catch (e) {
        convertFailedRef.current.add(job.id);
        toast.error(
          e instanceof Error
            ? `浏览器转换失败：${e.message}`
            : `浏览器转换失败：${String(e)}`,
        );
      } finally {
        convertingRef.current.delete(job.id);
      }
    },
    [load],
  );

  useEffect(() => {
    for (const job of jobs) {
      if (needsBrowserHtmlConvert(job)) {
        void runBrowserConvert(job);
      }
    }
  }, [jobs, runBrowserConvert]);

  const hasActive = jobs.some((j) => isActiveJob(j.status));
  const hasAwaitingHtml = jobs.some((j) => needsBrowserHtmlConvert(j));
  const hasTerminal = jobs.some(
    (j) => !isActiveJob(j.status) && j.status !== "awaiting_html",
  );
  const logModalOpen = Boolean(logJob?.id);
  useEffect(() => {
    if ((!hasActive && !hasAwaitingHtml) || logModalOpen) return;
    const t = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(t);
  }, [hasActive, hasAwaitingHtml, logModalOpen, load]);

  useEffect(() => {
    if (!logJob?.id) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await adminFetch(
          `/api/admin/generate/${encodeURIComponent(logJob.id)}`,
        );
        if (!cancelled && data.job) {
          setLogJob(data.job);
          setJobs((prev) => {
            const i = prev.findIndex((j) => j.id === data.job.id);
            if (i < 0) return prev;
            const next = [...prev];
            next[i] = data.job;
            return next;
          });
        }
      } catch {
        /* ignore transient */
      }
    };
    void tick();
    if (!isActiveJob(logJob.status) && !needsBrowserHtmlConvert(logJob)) {
      return () => {
        cancelled = true;
      };
    }
    const t = window.setInterval(() => void tick(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [logJob?.id, logJob?.status, logJob?.needsBrowserConvert]);

  useEffect(() => {
    const el = logPreRef.current;
    if (!el || !logStickBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [logJob?.log]);

  const cancelJob = async (id: string) => {
    setCancellingId(id);
    try {
      await adminFetch(`/api/admin/generate/${encodeURIComponent(id)}`, {
        method: "POST",
        body: JSON.stringify({ action: "cancel" }),
      });
      toast.success("已取消生成");
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setCancellingId(null);
    }
  };

  const deleteJob = async (id: string) => {
    setDeletingId(id);
    try {
      await adminFetch(`/api/admin/generate/${encodeURIComponent(id)}`, {
        method: "POST",
        body: JSON.stringify({ action: "delete" }),
      });
      toast.success("已删除日志");
      setLogJob((prev) => (prev?.id === id ? null : prev));
      setJobs((prev) => prev.filter((j) => j.id !== id));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setDeletingId(null);
    }
  };

  const clearTerminalJobs = async () => {
    setClearingTerminal(true);
    try {
      const data = await adminFetch("/api/admin/generate", {
        method: "POST",
        body: JSON.stringify({ action: "clear-terminal" }),
      });
      const deleted = (data.deleted as string[] | undefined)?.length ?? 0;
      toast.success(
        deleted > 0 ? `已清空 ${deleted} 条已结束任务日志` : "没有可清空的日志",
      );
      setLogJob((prev) => (prev && !isActiveJob(prev.status) ? null : prev));
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setClearingTerminal(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(jobs.length / PAGE_SIZE));
  const pageJobs = jobs.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const countLabel = (row: GenerateJob) => {
    if (row.pipeline === "rewrite-page") {
      const file = row.slideFile || (row.pageIndex != null ? `页${row.pageIndex + 1}` : "本页");
      return `重写页 · ${file}`;
    }
    const n = row.count ?? 1;
    const p = row.pages;
    const refine =
      typeof row.planRefine === "boolean"
        ? row.planRefine
          ? " · 精修开"
          : " · 精修关"
        : "";
    const repair =
      typeof row.repairOnFail === "boolean"
        ? row.repairOnFail
          ? " · 修复开"
          : " · 修复关"
        : "";
    const gate = row.qualityGate ? ` · gate=${row.qualityGate}` : "";
    const strip =
      typeof row.stripUnsupported === "boolean"
        ? row.stripUnsupported
          ? " · 剥离开"
          : " · 剥离关"
        : "";
    const palette =
      typeof row.paletteRefine === "boolean"
        ? row.paletteRefine
          ? " · 色板开"
          : " · 色板关"
        : "";
    const thinking =
      typeof row.llmThinking === "boolean"
        ? row.llmThinking
          ? " · 思考开"
          : " · 思考关"
        : "";
    return p
      ? `${n}×${p}页${refine}${repair}${gate}${strip}${palette}${thinking}`
      : `${n}${refine}${repair}${gate}${strip}${palette}${thinking}`;
  };

  return (
    <>
      {dialog}
      <div className="mb-3 flex flex-wrap gap-2">
        <LoadingButton
          variant="outline"
          onClick={() => void load()}
          loading={loading}
        >
          刷新
        </LoadingButton>
        <LoadingButton
          variant="destructive"
          disabled={!hasTerminal}
          loading={clearingTerminal}
          onClick={() =>
            confirm({
              title: "清空全部已结束任务日志？",
              description:
                "将删除 succeeded / failed / cancelled 的任务记录；运行中任务不受影响。",
              okText: "清空",
              destructive: true,
              onConfirm: () => clearTerminalJobs(),
            })
          }
        >
          清空已结束
        </LoadingButton>
      </div>

      <div className="rounded-lg border bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead className="w-[168px]">ID</TableHead>
              <TableHead className="w-[110px]">线路</TableHead>
              <TableHead className="w-[100px]">状态</TableHead>
              <TableHead className="w-[200px]">进度</TableHead>
              <TableHead className="w-[100px]">数量</TableHead>
              <TableHead className="w-[170px]">LLM</TableHead>
              <TableHead className="w-[150px]">文生图</TableHead>
              <TableHead className="w-[180px]">模板</TableHead>
              <TableHead className="w-[168px]">创建时间</TableHead>
              <TableHead className="w-[180px]">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageJobs.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={11}
                  className="py-10 text-center text-muted-foreground"
                >
                  {loading ? "加载中…" : "暂无任务"}
                </TableCell>
              </TableRow>
            ) : (
              pageJobs.map((row) => {
                const expandable = Boolean(row.prompt);
                const expanded = expandedIds.has(row.id);
                return (
                  <Fragment key={row.id}>
                    <TableRow>
                      <TableCell>
                        {expandable ? (
                          <button
                            type="button"
                            className="text-muted-foreground hover:text-foreground"
                            onClick={() =>
                              setExpandedIds((prev) => {
                                const next = new Set(prev);
                                if (next.has(row.id)) next.delete(row.id);
                                else next.add(row.id);
                                return next;
                              })
                            }
                          >
                            {expanded ? (
                              <ChevronDown className="h-4 w-4" />
                            ) : (
                              <ChevronRight className="h-4 w-4" />
                            )}
                          </button>
                        ) : null}
                      </TableCell>
                      <TableCell className="max-w-[168px] truncate font-mono text-xs">
                        {row.id}
                      </TableCell>
                      <TableCell>
                        {row.pipeline === "html-slide" ? (
                          <Badge variant="secondary">HTML</Badge>
                        ) : (
                          <Badge className="border-transparent bg-cyan-100 text-cyan-800 hover:bg-cyan-100">
                            PPT Master
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>{jobStatusBadge(row.status)}</TableCell>
                      <TableCell>
                        <JobProgressBar job={row} />
                      </TableCell>
                      <TableCell className="text-xs">{countLabel(row)}</TableCell>
                      <TableCell className="max-w-[170px] truncate text-xs">
                        {row.llmLabel || row.llmModel
                          ? `${row.llmLabel || row.llmModel}${
                              row.llmLightLabel ? ` / ${row.llmLightLabel}` : ""
                            }`
                          : "—"}
                      </TableCell>
                      <TableCell className="max-w-[150px] truncate text-xs">
                        {row.skipImage
                          ? "跳过"
                          : row.imageLabel || row.imageModel || "—"}
                      </TableCell>
                      <TableCell className="max-w-[180px] truncate text-xs">
                        {(row.templateIds && row.templateIds.length > 0
                          ? row.templateIds.join(", ")
                          : row.templateId) ||
                          row.progress?.lastId ||
                          "—"}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs">
                        {row.createdAt
                          ? new Date(row.createdAt).toLocaleString()
                          : "—"}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <Button
                            variant="link"
                            size="sm"
                            className="h-auto px-1"
                            onClick={() => setLogJob(row)}
                          >
                            日志
                          </Button>
                          {isActiveJob(row.status) ? (
                            <LoadingButton
                              variant="link"
                              size="sm"
                              className="h-auto px-1 text-destructive"
                              loading={cancellingId === row.id}
                              onClick={() =>
                                confirm({
                                  title: "确认取消生成？",
                                  description:
                                    "将终止 agent 进程；已完成的模板仍会保留。",
                                  okText: "取消生成",
                                  cancelText: "继续",
                                  destructive: true,
                                  onConfirm: () => cancelJob(row.id),
                                })
                              }
                            >
                              取消
                            </LoadingButton>
                          ) : (
                            <LoadingButton
                              variant="link"
                              size="sm"
                              className="h-auto px-1 text-destructive"
                              loading={deletingId === row.id}
                              onClick={() =>
                                confirm({
                                  title: "确认删除此任务日志？",
                                  description:
                                    "仅删除任务记录与日志文件，已生成的模板不会删除。",
                                  okText: "删除",
                                  destructive: true,
                                  onConfirm: () => deleteJob(row.id),
                                })
                              }
                            >
                              删除
                            </LoadingButton>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                    {expanded && expandable ? (
                      <TableRow>
                        <TableCell colSpan={11} className="bg-muted/30">
                          <p className="text-xs text-muted-foreground">
                            Prompt：{row.prompt || "—"}
                          </p>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </Fragment>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {jobs.length > PAGE_SIZE ? (
        <div className="mt-3 flex items-center justify-end gap-2 text-sm">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </Button>
          <span className="text-muted-foreground">
            {page} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            下一页
          </Button>
        </div>
      ) : null}

      <Dialog
        open={Boolean(logJob)}
        onOpenChange={(open) => {
          if (!open) setLogJob(null);
        }}
      >
        <DialogContent className="max-w-[860px]">
          <DialogHeader>
            <DialogTitle className="flex flex-wrap items-center gap-2">
              {logJob ? (
                <>
                  <span>{`日志 · ${logJob.id}`}</span>
                  {jobStatusBadge(logJob.status)}
                  {isActiveJob(logJob.status) && (
                    <span className="text-xs font-normal text-muted-foreground">
                      每 1.5s 自动刷新
                    </span>
                  )}
                  {needsBrowserHtmlConvert(logJob) && (
                    <span className="text-xs font-normal text-muted-foreground">
                      浏览器转换中…
                    </span>
                  )}
                </>
              ) : (
                "日志"
              )}
            </DialogTitle>
          </DialogHeader>
          <pre
            ref={logPreRef}
            onScroll={(e) => {
              const el = e.currentTarget;
              logStickBottomRef.current =
                el.scrollHeight - el.scrollTop - el.clientHeight < 48;
            }}
            className={cn(
              "m-0 max-h-[min(60vh,480px)] overflow-auto rounded-lg p-3.5 text-xs leading-relaxed",
              "whitespace-pre-wrap break-words font-mono",
              "bg-[#0f1115] text-[#c8f0c8]",
            )}
          >
            {logJob?.log || ""}
          </pre>
          {logJob?.error ? (
            <Alert variant="destructive">
              <AlertDescription>{logJob.error}</AlertDescription>
            </Alert>
          ) : null}
          {logJob &&
          !isActiveJob(logJob.status) &&
          !needsBrowserHtmlConvert(logJob) ? (
            <DialogFooter>
              <Button variant="outline" onClick={() => setLogJob(null)}>
                关闭
              </Button>
              <LoadingButton
                variant="destructive"
                loading={deletingId === logJob.id}
                onClick={() =>
                  confirm({
                    title: "确认删除此任务日志？",
                    description:
                      "仅删除任务记录与日志文件，已生成的模板不会删除。",
                    okText: "删除",
                    destructive: true,
                    onConfirm: () => deleteJob(logJob.id),
                  })
                }
              >
                删除日志
              </LoadingButton>
            </DialogFooter>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
