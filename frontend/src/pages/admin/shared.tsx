import { useState, useEffect, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button, type ButtonProps } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import type { GenerateJob, TemplateStatus } from "./types";
import { PREVIEW_SCALE, STATUS_LABEL } from "./types";

export function formatTokenCount(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (n >= 10000) return `${(n / 1000).toFixed(1)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(2)}k`.replace(/\.?0+k$/, "k");
  return String(n);
}

export function formatCny(amount: number | null | undefined): string {
  if (amount == null || Number.isNaN(amount)) return "";
  if (amount <= 0) return "¥0";
  if (amount < 0.01) return `¥${amount.toFixed(3)}`;
  if (amount < 1) return `¥${amount.toFixed(2)}`;
  return `¥${amount.toFixed(2)}`;
}

export function TokenWithCost(props: {
  tokens: number | null | undefined;
  cost: number | null | undefined;
  titleExtra?: string;
}) {
  const { tokens, cost, titleExtra } = props;
  const hasTokens = tokens != null && !Number.isNaN(tokens);
  const costLabel = formatCny(cost);
  if (!hasTokens && !costLabel) {
    return <span className="text-muted-foreground">—</span>;
  }
  const title = [
    hasTokens ? `${tokens} tokens` : null,
    costLabel ? `约 ${costLabel}（公开价估算，非账单）` : null,
    titleExtra,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <span title={title} className="whitespace-nowrap">
      {hasTokens ? formatTokenCount(tokens) : "—"}
      {costLabel ? (
        <span className="text-xs text-muted-foreground"> · {costLabel}</span>
      ) : null}
    </span>
  );
}

export function providerSelectLabel(p: {
  label: string;
  tier?: "heavy" | "light";
  configured: boolean;
}): string {
  const tierHint =
    p.tier === "heavy" ? "大模型" : p.tier === "light" ? "轻量" : "";
  const base = tierHint ? `${p.label}（${tierHint}）` : p.label;
  return p.configured ? base : `${base}（未配置）`;
}

export function imageProviderSelectLabel(p: {
  label: string;
  configured: boolean;
}): string {
  return p.configured ? p.label : `${p.label}（未配置）`;
}

export function isActiveJob(status: string) {
  return (
    status === "running" ||
    status === "queued" ||
    status === "awaiting_html"
  );
}

export function needsBrowserHtmlConvert(job: {
  status?: string;
  needsBrowserConvert?: boolean;
}): boolean {
  return (
    job.status === "awaiting_html" ||
    (Boolean(job.needsBrowserConvert) && job.status !== "succeeded")
  );
}

export function AdminSlideFrame({
  src,
  title,
  scale = PREVIEW_SCALE,
}: {
  src: string;
  title: string;
  scale?: number;
}) {
  const [loading, setLoading] = useState(true);
  const w = 1920 * scale;
  const h = 1080 * scale;

  useEffect(() => {
    setLoading(true);
  }, [src]);

  return (
    <div
      className="relative overflow-hidden rounded bg-[#e8e6e1] shadow-sm"
      style={{ width: w, height: h }}
    >
      {loading ? (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-[#e8e6e1]/90">
          <Loader2 className="h-7 w-7 animate-spin text-muted-foreground" />
          <span className="text-xs text-muted-foreground">加载中…</span>
        </div>
      ) : null}
      <div
        className="absolute left-0 top-0 pointer-events-none origin-top-left"
        style={{ transform: `scale(${scale})` }}
      >
        <iframe
          key={src}
          title={title}
          src={src}
          sandbox="allow-scripts allow-same-origin"
          onLoad={() => setLoading(false)}
          style={{ width: 1920, height: 1080, border: 0, display: "block" }}
        />
      </div>
    </div>
  );
}

export function JobProgressBar({ job }: { job: GenerateJob }) {
  const total = Math.max(1, job.progress?.total || job.count || 1);
  let done = job.progress?.done ?? 0;
  let ok = job.progress?.ok ?? 0;
  let fail = job.progress?.fail ?? 0;
  const skip = job.progress?.skip ?? 0;
  const templateHits = job.templateIds?.length || (job.templateId ? 1 : 0);

  if (job.status === "succeeded") {
    if (ok === 0 && templateHits > 0) ok = templateHits;
    if (ok === 0 && done > 0) ok = done;
    if (done < ok + fail + skip) done = ok + fail + skip;
    if (done === 0) done = Math.max(ok, total);
  } else if (job.status === "failed") {
    if (done === 0 && fail === 0 && ok === 0) {
      fail = Math.max(1, total - skip);
      done = fail;
    } else if (done < ok + fail + skip) {
      done = ok + fail + skip;
    }
  }

  const finished =
    job.status === "succeeded" ||
    job.status === "failed" ||
    job.status === "cancelled";
  const percent =
    job.status === "succeeded" || job.status === "failed"
      ? 100
      : job.status === "cancelled"
        ? total > 0
          ? Math.min(100, Math.round((done / total) * 100))
          : 0
        : (job.progress?.percent ??
          (total > 0 ? Math.round((done / total) * 100) : 0));

  const barClass =
    job.status === "failed"
      ? "[&>div]:bg-destructive"
      : job.status === "succeeded"
        ? "[&>div]:bg-emerald-500"
        : job.status === "cancelled"
          ? "[&>div]:bg-amber-500"
          : undefined;

  return (
    <div className="min-w-[150px] max-w-[220px]">
      <div className="mb-1 flex items-center justify-between gap-2 text-xs">
        <Progress value={percent} className={cn("h-2 flex-1", barClass)} />
        <span className="shrink-0 tabular-nums text-muted-foreground">
          {done}/{total}
        </span>
      </div>
      <div
        className="truncate text-[11px] leading-snug text-muted-foreground"
        title={[
          `成功 ${ok}`,
          fail > 0 ? `失败 ${fail}` : null,
          skip > 0 ? `跳过 ${skip}` : null,
          job.concurrency ? `并行 ${job.concurrency}` : null,
          job.progress?.lastId || null,
          finished && job.status === "cancelled" ? "已取消" : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      >
        成功 {ok}
        {fail > 0 ? ` · 失败 ${fail}` : ""}
        {skip > 0 ? ` · 跳过 ${skip}` : ""}
        {job.concurrency ? ` · 并行 ${job.concurrency}` : ""}
      </div>
    </div>
  );
}

export function jobStatusBadge(status: string) {
  if (status === "succeeded") {
    return (
      <Badge className="border-transparent bg-emerald-100 text-emerald-800 hover:bg-emerald-100">
        {status}
      </Badge>
    );
  }
  if (status === "failed") {
    return <Badge variant="destructive">{status}</Badge>;
  }
  if (status === "cancelled") {
    return (
      <Badge className="border-transparent bg-amber-100 text-amber-800 hover:bg-amber-100">
        {status}
      </Badge>
    );
  }
  if (status === "running") {
    return (
      <Badge className="border-transparent bg-sky-100 text-sky-800 hover:bg-sky-100">
        {status}
      </Badge>
    );
  }
  if (status === "awaiting_html") {
    return (
      <Badge className="border-transparent bg-violet-100 text-violet-800 hover:bg-violet-100">
        浏览器转换中…
      </Badge>
    );
  }
  return <Badge variant="secondary">{status}</Badge>;
}

export function templateStatusBadge(status: TemplateStatus) {
  if (status === "approved") {
    return (
      <Badge className="border-transparent bg-emerald-100 text-emerald-800 hover:bg-emerald-100">
        {STATUS_LABEL[status]}
      </Badge>
    );
  }
  if (status === "rejected") {
    return <Badge variant="destructive">{STATUS_LABEL[status]}</Badge>;
  }
  if (status === "pending") {
    return (
      <Badge className="border-transparent bg-amber-100 text-amber-900 hover:bg-amber-100">
        {STATUS_LABEL[status]}
      </Badge>
    );
  }
  return <Badge variant="secondary">{STATUS_LABEL[status]}</Badge>;
}

/** 未能转成标准 html-slide 的 SVG 兜底包 */
export function templateRenderBadge(
  render: string | null | undefined,
  htmlConvertFailed?: boolean,
) {
  const failed =
    htmlConvertFailed === true ||
    String(render || "").toLowerCase() === "svg-fallback";
  if (failed) {
    return (
      <Badge
        variant="destructive"
        className="border-transparent bg-rose-100 text-rose-900 hover:bg-rose-100"
        title="svg_to_pptx / 转 HTML 失败，仅为整页 SVG 预览包，不可当标准可编辑 html-slide"
      >
        未转 HTML
      </Badge>
    );
  }
  const r = String(render || "").toLowerCase();
  if (r === "html-slide" || r === "html") {
    return (
      <Badge
        className="border-transparent bg-emerald-50 text-emerald-800 hover:bg-emerald-50"
        title="标准 html-slide 可编辑包"
      >
        HTML
      </Badge>
    );
  }
  if (r === "svg") {
    return (
      <Badge
        className="border-transparent bg-cyan-100 text-cyan-800 hover:bg-cyan-100"
        title="PPT Master SVG 线路（已成功导出 PPTX 并转包）"
      >
        SVG→HTML
      </Badge>
    );
  }
  return null;
}

export function LoadingButton({
  loading,
  children,
  disabled,
  ...props
}: ButtonProps & { loading?: boolean }) {
  return (
    <Button disabled={disabled || loading} {...props}>
      {loading ? <Loader2 className="animate-spin" /> : null}
      {children}
    </Button>
  );
}

export type ConfirmOptions = {
  title: string;
  description?: ReactNode;
  okText?: string;
  cancelText?: string;
  destructive?: boolean;
  onConfirm: () => void | Promise<void>;
};

export function useConfirmDialog() {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);
  const [pending, setPending] = useState(false);

  const confirm = (next: ConfirmOptions) => setOpts(next);

  const dialog = (
    <AlertDialog
      open={Boolean(opts)}
      onOpenChange={(open) => {
        if (!open && !pending) setOpts(null);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{opts?.title}</AlertDialogTitle>
          {opts?.description ? (
            <AlertDialogDescription asChild>
              <div>{opts.description}</div>
            </AlertDialogDescription>
          ) : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>
            {opts?.cancelText || "取消"}
          </AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            className={
              opts?.destructive
                ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
                : undefined
            }
            onClick={(e) => {
              e.preventDefault();
              if (!opts) return;
              void (async () => {
                setPending(true);
                try {
                  await opts.onConfirm();
                  setOpts(null);
                } finally {
                  setPending(false);
                }
              })();
            }}
          >
            {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {opts?.okText || "确认"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );

  return { confirm, dialog };
}

export function SectionDivider({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 py-2">
      <span className="shrink-0 text-xs font-medium text-muted-foreground">
        {children}
      </span>
      <div className="h-px flex-1 bg-border" />
    </div>
  );
}

export function Field({
  label,
  extra,
  children,
  className,
}: {
  label: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="text-sm font-medium leading-none">{label}</div>
      {children}
      {extra ? (
        <p className="text-xs text-muted-foreground">{extra}</p>
      ) : null}
    </div>
  );
}

export function DescRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}
