"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  App,
  Button,
  Card,
  ConfigProvider,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Layout,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  Tabs,
  Alert,
  Descriptions,
  Divider,
} from "antd";
import {
  LeftOutlined,
  RightOutlined,
  MoreOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import zhCN from "antd/locale/zh_CN";
import { useRouter } from "next/navigation";
import { buildTemplateSlideEmbedSrc } from "@/utils/templateEmbed";
import type { TemplateFormat } from "@/types/templateFormat";
import {
  PPT_MASTER_VISUAL_STYLES,
  pptMasterVisualStyleSelectOptions,
  type PptMasterStyleSelectGroup,
} from "@/constants/pptMasterStyles";

const { Header, Content } = Layout;
const { Text, Paragraph, Title } = Typography;
const { TextArea } = Input;

const PREVIEW_SCALE = 0.5; // 960×540

function AdminSlideFrame({
  src,
  title,
  scale = PREVIEW_SCALE,
}: {
  src: string;
  title: string;
  scale?: number;
}) {
  const w = 1920 * scale;
  const h = 1080 * scale;
  return (
    <div
      style={{
        position: "relative",
        width: w,
        height: h,
        overflow: "hidden",
        background: "#e8e6e1",
        borderRadius: 4,
        boxShadow: "0 1px 4px rgba(0,0,0,0.12)",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          transform: `scale(${scale})`,
          transformOrigin: "top left",
          pointerEvents: "none",
        }}
      >
        <iframe
          title={title}
          src={src}
          sandbox="allow-scripts allow-same-origin"
          style={{ width: 1920, height: 1080, border: 0, display: "block" }}
        />
      </div>
    </div>
  );
}

const TOKEN_KEY = "webppt_admin_token";
const TOKEN_HEADER = "x-admin-token";

type TemplateStatus = "draft" | "pending" | "approved" | "rejected";

type TemplateSummary = {
  id: string;
  templateId: string;
  label: { zh_CN?: string; en_US?: string };
  description: { zh_CN?: string; en_US?: string };
  slideCount: number;
  previewFile: string | null;
  previewPages?: string[];
  format?: TemplateFormat;
  status: TemplateStatus;
  storageBackend: string;
  mtimeMs: number;
  sourceTemplateId?: string | null;
  pageTokens?: number | null;
  imageTokens?: number | null;
  imageCalls?: number | null;
  imageCount?: number | null;
  pageCostCny?: number | null;
  imageCostCny?: number | null;
  totalCostCny?: number | null;
};

function formatTokenCount(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (n >= 10000) return `${(n / 1000).toFixed(1)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(2)}k`.replace(/\.?0+k$/, "k");
  return String(n);
}

function formatCny(amount: number | null | undefined): string {
  if (amount == null || Number.isNaN(amount)) return "";
  if (amount <= 0) return "¥0";
  if (amount < 0.01) return `¥${amount.toFixed(3)}`;
  if (amount < 1) return `¥${amount.toFixed(2)}`;
  return `¥${amount.toFixed(2)}`;
}

function TokenWithCost(props: {
  tokens: number | null | undefined;
  cost: number | null | undefined;
  titleExtra?: string;
}) {
  const { tokens, cost, titleExtra } = props;
  const hasTokens = tokens != null && !Number.isNaN(tokens);
  const costLabel = formatCny(cost);
  if (!hasTokens && !costLabel) {
    return <Text type="secondary">—</Text>;
  }
  const title = [
    hasTokens ? `${tokens} tokens` : null,
    costLabel ? `约 ${costLabel}（公开价估算，非账单）` : null,
    titleExtra,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Text title={title} style={{ whiteSpace: "nowrap" }}>
      {hasTokens ? formatTokenCount(tokens) : "—"}
      {costLabel ? (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {" "}
          · {costLabel}
        </Text>
      ) : null}
    </Text>
  );
}

type GenerateJobProgress = {
  total: number;
  done: number;
  ok: number;
  fail: number;
  skip: number;
  lastId?: string;
  percent: number;
};

type GeneratePipeline = "html-slide" | "ppt-master";

type GenerateJob = {
  id: string;
  prompt: string;
  mock: boolean;
  skipImage: boolean;
  paletteRefine?: boolean;
  packageFormat?: TemplateFormat;
  pipeline?: GeneratePipeline;
  visualStyle?: string;
  styleIntent?: string;
  ensureStyle?: boolean;
  randomTheme?: boolean;
  randomStyle?: boolean;
  randomStyleMode?: "catalog" | "invent";
  sourceTemplateId?: string;
  /** 历史任务可能带 html；新任务一律 svg */
  pptMasterRender?: "svg" | "html";
  templateId?: string;
  count?: number;
  concurrency?: number;
  pages?: number;
  planRefine?: boolean;
  repairOnFail?: boolean;
  qualityGate?: "soft" | "strict" | "skip";
  stripUnsupported?: boolean;
  templateIds?: string[];
  llmProvider?: string;
  llmModel?: string;
  llmLabel?: string;
  llmLightProvider?: string;
  llmLightModel?: string;
  llmLightLabel?: string;
  imageProvider?: string;
  imageModel?: string;
  imageLabel?: string;
  status: string;
  createdAt: string;
  finishedAt?: string;
  error?: string;
  log: string;
  outputDir?: string;
  progress?: GenerateJobProgress;
};

type LlmProviderPublic = {
  id: string;
  label: string;
  tier?: "heavy" | "light";
  baseUrl: string;
  models: { id: string; label: string }[];
  configured: boolean;
  keyCount?: number;
  keyHint?: string;
};

type ImageProviderPublic = {
  id: string;
  label: string;
  baseUrl: string;
  models: { id: string; label: string }[];
  configured: boolean;
  keyCount?: number;
  keyHint?: string;
  transport?: string;
};

function providerSelectLabel(p: LlmProviderPublic): string {
  const tierHint =
    p.tier === "heavy" ? "大模型" : p.tier === "light" ? "轻量" : "";
  const base = tierHint ? `${p.label}（${tierHint}）` : p.label;
  return p.configured ? base : `${base}（未配置）`;
}

function imageProviderSelectLabel(p: ImageProviderPublic): string {
  return p.configured ? p.label : `${p.label}（未配置）`;
}

function JobProgressBar({ job }: { job: GenerateJob }) {
  const total = Math.max(1, job.progress?.total || job.count || 1);
  let done = job.progress?.done ?? 0;
  let ok = job.progress?.ok ?? 0;
  let fail = job.progress?.fail ?? 0;
  const skip = job.progress?.skip ?? 0;
  const templateHits = job.templateIds?.length || (job.templateId ? 1 : 0);

  // 结束态兜底：旧任务 / 单包路径可能没写全 progress，避免「succeeded 却 0/1」
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
  const status =
    job.status === "failed"
      ? "exception"
      : job.status === "succeeded"
        ? "success"
        : job.status === "cancelled"
          ? "normal"
          : "active";

  return (
    <div style={{ minWidth: 150, maxWidth: 220 }}>
      <Progress
        percent={percent}
        size="small"
        status={status}
        format={() => `${done}/${total}`}
      />
      <div
        style={{
          fontSize: 11,
          color: "rgba(0,0,0,0.45)",
          marginTop: 2,
          lineHeight: 1.35,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
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

function jobStatusTag(status: string) {
  const color =
    status === "succeeded"
      ? "green"
      : status === "failed"
        ? "red"
        : status === "cancelled"
          ? "orange"
          : status === "running"
            ? "blue"
            : "default";
  return <Tag color={color}>{status}</Tag>;
}

function isActiveJob(status: string) {
  return status === "running" || status === "queued";
}

function readToken(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(TOKEN_KEY) || "";
}

function writeToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
  document.cookie = `webppt_admin_token=${encodeURIComponent(token)}; path=/; SameSite=Lax`;
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  document.cookie = "webppt_admin_token=; path=/; Max-Age=0; SameSite=Lax";
}

async function adminFetch(url: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers || {});
  const token = readToken();
  if (token) headers.set(TOKEN_HEADER, token);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(url, { ...init, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || data.message || `HTTP ${res.status}`);
  }
  return data;
}

const STATUS_COLOR: Record<TemplateStatus, string> = {
  draft: "default",
  pending: "gold",
  approved: "green",
  rejected: "red",
};

const STATUS_LABEL: Record<TemplateStatus, string> = {
  draft: "草稿",
  pending: "待审批",
  approved: "已通过",
  rejected: "已驳回",
};

function LoginGate({ onOk }: { onOk: () => void }) {
  const { message } = App.useApp();
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!token.trim()) {
      message.warning("请输入 ADMIN_TOKEN");
      return;
    }
    setLoading(true);
    try {
      writeToken(token.trim());
      await adminFetch("/api/admin/templates");
      message.success("已登录");
      onOk();
    } catch (e) {
      clearToken();
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f5f5f5] p-6">
      <Card title="WebPPT 模板后台" style={{ width: 420 }}>
        <Paragraph type="secondary">
          使用环境变量 <Text code>ADMIN_TOKEN</Text> 登录。请在{" "}
          <Text code>.env.local</Text> 配置后重启 <Text code>npm run dev</Text>
          。
        </Paragraph>
        <Form layout="vertical" onFinish={submit}>
          <Form.Item label="Admin Token" required>
            <Input.Password
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="与 ADMIN_TOKEN 一致"
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            进入后台
          </Button>
        </Form>
      </Card>
    </div>
  );
}

function GeneratePanel({ onCreated }: { onCreated: () => void }) {
  const { message } = App.useApp();
  const [prompt, setPrompt] = useState("");
  const [count, setCount] = useState(1);
  const [pages, setPages] = useState(7);
  const [mock, setMock] = useState(false);
  const [skipImage, setSkipImage] = useState(false);
  const [paletteRefine, setPaletteRefine] = useState(false);
  const [svgRepair, setSvgRepair] = useState(true);
  const [qualityGate, setQualityGate] = useState<"soft" | "strict" | "skip">(
    "soft"
  );
  const [stripUnsupported, setStripUnsupported] = useState(true);
  const [visualStyle, setVisualStyle] = useState("dark-tech");
  const [styleIntent, setStyleIntent] = useState("");
  const [ensureStyle, setEnsureStyle] = useState(true);
  const [randomTheme, setRandomTheme] = useState(false);
  const [randomStyle, setRandomStyle] = useState(false);
  const [randomStyleMode, setRandomStyleMode] = useState<"catalog" | "invent">(
    "catalog"
  );
  const [styleSelectOptions, setStyleSelectOptions] = useState<
    PptMasterStyleSelectGroup[]
  >(() => pptMasterVisualStyleSelectOptions());
  const [styleCatalogMeta, setStyleCatalogMeta] = useState<string | null>(null);
  const [llmProviders, setLlmProviders] = useState<LlmProviderPublic[]>([]);
  const [llmProvider, setLlmProvider] = useState("deepseek");
  const [llmModel, setLlmModel] = useState("deepseek-v4-flash");
  const [imageProviders, setImageProviders] = useState<ImageProviderPublic[]>(
    []
  );
  const [imageProvider, setImageProvider] = useState("openai");
  const [imageModel, setImageModel] = useState("nano-banana-fast");
  const [loading, setLoading] = useState(false);
  const [randomizingPrompt, setRandomizingPrompt] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [lastJob, setLastJob] = useState<GenerateJob | null>(null);

  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      try {
        const [llmData, stylesSettled] = await Promise.all([
          adminFetch("/api/admin/llm"),
          adminFetch("/api/admin/styles").then(
            (data) => ({ ok: true as const, data }),
            (err: unknown) => ({ ok: false as const, err })
          ),
        ]);
        if (cancelled) return;
        const providers = (llmData.providers as LlmProviderPublic[]) || [];
        setLlmProviders(providers);
        const preferred =
          providers.find((p) => p.id === "deepseek" && p.configured) ||
          providers.find((p) => p.tier === "heavy" && p.configured) ||
          providers.find((p) => p.configured) ||
          providers[0];
        if (preferred) {
          setLlmProvider(preferred.id);
          setLlmModel(preferred.models[0]?.id || "");
        }
        const imgProviders =
          (llmData.imageProviders as ImageProviderPublic[]) || [];
        setImageProviders(imgProviders);
        const preferredImg =
          imgProviders.find((p) => p.id === "openai" && p.configured) ||
          imgProviders.find((p) => p.configured) ||
          imgProviders[0];
        if (preferredImg) {
          setImageProvider(preferredImg.id);
          setImageModel(preferredImg.models[0]?.id || "");
        }
        if (stylesSettled.ok && stylesSettled.data?.selectOptions?.length) {
          const stylesData = stylesSettled.data;
          setStyleSelectOptions(
            stylesData.selectOptions as PptMasterStyleSelectGroup[]
          );
          const n = Number(stylesData.count) || 0;
          const at = stylesData.generated_at
            ? String(stylesData.generated_at)
            : "";
          const variantN = Array.isArray(stylesData.styles)
            ? stylesData.styles.filter(
                (s: { status?: string }) => s?.status === "variant"
              ).length
            : 0;
          setStyleCatalogMeta(
            at
              ? `目录 ${n} 种（含变体 ${variantN}）· ${at}`
              : `目录 ${n} 种（含变体 ${variantN} · _catalog.json）`
          );
        } else if (!stylesSettled.ok) {
          const msg =
            stylesSettled.err instanceof Error
              ? stylesSettled.err.message
              : String(stylesSettled.err || "加载失败");
          setStyleCatalogMeta(
            `风格目录未更新（回退本地 ${PPT_MASTER_VISUAL_STYLES.length} 种）：${msg}`
          );
          message.warning(`视觉风格目录加载失败，仍显示旧列表：${msg}`);
        }
      } catch (e) {
        if (!cancelled) {
          message.error(e instanceof Error ? e.message : "加载 LLM 配置失败");
        }
      }
    };
    void boot();
    return () => {
      cancelled = true;
    };
  }, [message]);

  const selectedProvider = llmProviders.find((p) => p.id === llmProvider);
  const modelOptions = selectedProvider?.models || [];
  const selectedImageProvider = imageProviders.find(
    (p) => p.id === imageProvider
  );
  const imageModelOptions = selectedImageProvider?.models || [];

  const onProviderChange = (id: string) => {
    setLlmProvider(id);
    const p = llmProviders.find((x) => x.id === id);
    setLlmModel(p?.models[0]?.id || "");
  };

  const onImageProviderChange = (id: string) => {
    setImageProvider(id);
    const p = imageProviders.find((x) => x.id === id);
    setImageModel(p?.models[0]?.id || "");
  };

  // 轮询最近任务进度
  useEffect(() => {
    if (!lastJob?.id) return;
    if (!isActiveJob(lastJob.status)) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await adminFetch(
          `/api/admin/generate/${encodeURIComponent(lastJob.id)}`
        );
        if (!cancelled && data.job) setLastJob(data.job);
      } catch {
        /* ignore transient */
      }
    };
    const t = window.setInterval(() => void tick(), 1500);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [lastJob?.id, lastJob?.status]);

  const cancelLastJob = async () => {
    if (!lastJob?.id || !isActiveJob(lastJob.status)) return;
    setCancelling(true);
    try {
      const data = await adminFetch(
        `/api/admin/generate/${encodeURIComponent(lastJob.id)}`,
        {
          method: "POST",
          body: JSON.stringify({ action: "cancel" }),
        }
      );
      if (data.job) setLastJob(data.job);
      message.success("已取消生成");
      onCreated();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setCancelling(false);
    }
  };

  const randomizePrompt = async () => {
    setRandomizingPrompt(true);
    try {
      const data = await adminFetch("/api/admin/prompt-random", {
        method: "POST",
        body: JSON.stringify({ visualStyle }),
      });
      const next = String(data.prompt || "").trim();
      if (!next) throw new Error("未返回主题描述");
      setPrompt(next);
      message.success(
        data.model ? `已用 ${data.model} 生成主题` : "已随机生成主题"
      );
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRandomizingPrompt(false);
    }
  };

  const submit = async () => {
    const n = Math.floor(Number(count) || 0);
    if (n < 1 || n > 20) {
      message.warning("生成数量请填写 1–20");
      return;
    }
    const pageCount = Math.min(12, Math.max(3, Math.floor(Number(pages) || 7)));
    if (!mock && selectedProvider && !selectedProvider.configured) {
      message.warning(
        `${selectedProvider.label} 未配置 API Key，请先在 .env.local 填写`
      );
      return;
    }
    if (!mock && !llmModel) {
      message.warning("请选择主力 LLM 模型");
      return;
    }
    if (
      !mock &&
      !skipImage &&
      selectedImageProvider &&
      !selectedImageProvider.configured
    ) {
      message.warning(
        `${selectedImageProvider.label} 未配置 API Key，请先在 .env.local 填写 POLLINATIONS_* / IMAGE_*`
      );
      return;
    }
    if (!mock && !skipImage && !imageModel) {
      message.warning("请选择文生图模型");
      return;
    }
    setLoading(true);
    try {
      let nextPrompt = prompt.trim();
      let nextStyle = visualStyle;
      let nextIntent = styleIntent.trim();
      let nextEnsure = Boolean(nextIntent) && ensureStyle;

      if (randomStyle) {
        const styleData = await adminFetch("/api/admin/styles/random", {
          method: "POST",
          body: JSON.stringify({
            mode: randomStyleMode,
            exclude: [visualStyle],
          }),
        });
        if (randomStyleMode === "invent") {
          nextIntent = String(styleData.styleIntent || "").trim();
          if (!nextIntent) throw new Error("随机风格意图为空");
          nextEnsure = styleData.ensureStyle !== false;
          setStyleIntent(nextIntent);
          setEnsureStyle(nextEnsure);
          message.info(`随机风格意图：${nextIntent}`);
        } else {
          nextStyle = String(styleData.styleId || "").trim();
          if (!nextStyle) throw new Error("随机风格为空");
          nextIntent = "";
          nextEnsure = false;
          setVisualStyle(nextStyle);
          setStyleIntent("");
          message.info(
            `随机风格：${nextStyle}${
              styleData.labelZh ? `（${styleData.labelZh}）` : ""
            }`
          );
        }
      }

      if (randomTheme) {
        const themeData = await adminFetch("/api/admin/prompt-random", {
          method: "POST",
          body: JSON.stringify({
            visualStyle: nextIntent ? undefined : nextStyle,
          }),
        });
        nextPrompt = String(themeData.prompt || "").trim();
        if (!nextPrompt) throw new Error("随机主题为空");
        setPrompt(nextPrompt);
        message.info(
          themeData.model
            ? `随机主题（${themeData.model}）已填入`
            : "随机主题已填入"
        );
      }

      if (!nextPrompt && !randomTheme) {
        // allow empty → server default hint
      }

      const data = await adminFetch("/api/admin/generate", {
        method: "POST",
        body: JSON.stringify({
          prompt: nextPrompt || undefined,
          count: n,
          pages: pageCount,
          mock,
          skipImage,
          paletteRefine,
          packageFormat: "ppt-master",
          pipeline: "ppt-master",
          visualStyle: nextStyle,
          styleIntent: nextIntent || undefined,
          ensureStyle: nextEnsure,
          randomTheme,
          randomStyle,
          randomStyleMode: randomStyle ? randomStyleMode : undefined,
          repairOnFail: svgRepair,
          qualityGate,
          stripUnsupported,
          llmProvider,
          llmModel,
          imageProvider,
          imageModel,
        }),
      });
      setLastJob(data.job);
      const styleLabel = nextIntent || nextStyle;
      message.success(
        `已启动 PPT Master ×${n}（${pageCount} 页/包 · ${styleLabel} · SVG）`
      );
      onCreated();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message="PPT Master 生成线路"
        description={
          <span>
            使用仓库内 <Text code>ppt-master</Text> Skill：LLM 写规范 SVG → 质检
            → 原生 PPTX → <Text code>pptx-to-template-package</Text>{" "}
            转为模板包（
            <Text code>format=ppt-master</Text>）。关闭「跳过生图」时会用{" "}
            <Text code>IMAGE_*</Text> 先落盘再嵌入。写入{" "}
            <Text code>agent-output/</Text>，状态 <Tag color="gold">待审批</Tag>
            。需本机已解压 <Text code>ppt-master/</Text> 并装好其{" "}
            <Text code>.venv</Text>。
          </span>
        }
      />
      <Card title="新建生成任务">
        <Form layout="vertical" onFinish={submit}>
          <Form.Item
            label="产物格式"
            style={{ marginBottom: 8 }}
            extra="入库 format=ppt-master；经 PPTX 转换的 html-slide 形包。"
          >
            <Tag color="geekblue">ppt-master</Tag>
            <Tag color="default" style={{ marginLeft: 4 }}>
              SVG 线路
            </Tag>
            <Text type="secondary" style={{ marginLeft: 8 }}>
              规范 SVG → 质检 → 原生 PPTX → 转 HTML 包
            </Text>
          </Form.Item>

          <Divider orientation="left" plain style={{ margin: "8px 0 16px" }}>
            1. 规模
          </Divider>
          <Space size="large" wrap style={{ width: "100%" }}>
            <Form.Item
              label="生成数量"
              required
              extra="每包独立跑 PPT Master（1–20）"
              style={{ marginBottom: 8 }}
            >
              <InputNumber
                min={1}
                max={20}
                value={count}
                onChange={(v) => setCount(typeof v === "number" ? v : 1)}
                style={{ width: 160 }}
              />
            </Form.Item>
            <Form.Item
              label="母版页数"
              extra="每包页数（3–12）"
              style={{ marginBottom: 8 }}
            >
              <InputNumber
                min={3}
                max={12}
                value={pages}
                onChange={(v) => setPages(typeof v === "number" ? v : 7)}
                style={{ width: 160 }}
              />
            </Form.Item>
          </Space>

          <Divider orientation="left" plain style={{ margin: "8px 0 16px" }}>
            2. 主题
          </Divider>
          <Form.Item
            label={
              <Space size={12} wrap>
                <span>主题描述</span>
                <Space size={6}>
                  <Text type="secondary">提交时随机</Text>
                  <Switch
                    size="small"
                    checked={randomTheme}
                    onChange={setRandomTheme}
                  />
                </Space>
                <Button
                  type="link"
                  size="small"
                  icon={<ThunderboltOutlined />}
                  loading={randomizingPrompt}
                  disabled={randomTheme}
                  onClick={(e) => {
                    e.preventDefault();
                    void randomizePrompt();
                  }}
                  style={{ paddingInline: 0 }}
                >
                  现在生成一版
                </Button>
              </Space>
            }
            extra={
              randomTheme
                ? "已开启：提交时用 SCORE_VL 覆盖下方文案"
                : "写内容主题（产品/活动/议题），不要写视觉风格名。包名按主题命名。"
            }
          >
            <TextArea
              rows={3}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="例如：AI 产品发布会 / 话剧首演手册——写内容主题即可；勿把风格名写进主题"
              disabled={randomTheme}
            />
          </Form.Item>

          <Divider orientation="left" plain style={{ margin: "8px 0 16px" }}>
            3. 视觉风格
          </Divider>
          <Form.Item label="来源" style={{ marginBottom: 12 }}>
            <Select
              value={randomStyle ? randomStyleMode : "pick"}
              style={{ width: 280 }}
              onChange={(v) => {
                if (v === "pick") {
                  setRandomStyle(false);
                } else {
                  setRandomStyle(true);
                  setRandomStyleMode(v as "catalog" | "invent");
                  setStyleIntent("");
                }
              }}
              options={[
                { value: "pick", label: "指定已有风格" },
                { value: "catalog", label: "随机 · 从已有目录抽一张" },
                { value: "invent", label: "随机 · 发明新风格并建卡" },
              ]}
            />
          </Form.Item>
          {randomStyle ? (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={
                randomStyleMode === "invent"
                  ? "提交时发明一句风格意图；近义复用已有卡，没有则自动建卡。"
                  : "提交时从目录随机抽一张已有风格卡，不会新建。"
              }
            />
          ) : (
            <>
              <Form.Item
                label="视觉风格"
                style={{ marginBottom: 12 }}
                extra={
                  styleCatalogMeta ||
                  "来自 ppt-master visual-styles/_catalog.json"
                }
              >
                <Select
                  value={visualStyle}
                  onChange={(id) => {
                    setVisualStyle(id);
                    setStyleIntent("");
                  }}
                  style={{ width: 360 }}
                  showSearch
                  optionFilterProp="label"
                  options={styleSelectOptions}
                  disabled={Boolean(styleIntent.trim())}
                />
              </Form.Item>
              <Form.Item
                label="或写风格意图"
                style={{ marginBottom: 8 }}
                extra="填写后优先于上方下拉。近义会复用已有卡；没有则按 style-skill 写新卡。留空则只用下拉。"
              >
                <TextArea
                  rows={2}
                  value={styleIntent}
                  onChange={(e) => setStyleIntent(e.target.value)}
                  placeholder="例如：夜间水族馆导视、蜡笔儿童绘本、法院卷宗封面"
                />
              </Form.Item>
              <Form.Item
                label="缺卡时自动生成"
                style={{ marginBottom: 8 }}
                extra="仅在填写了风格意图时生效。关闭则必须能匹配已有卡，否则任务失败。"
              >
                <Switch
                  checked={ensureStyle}
                  onChange={setEnsureStyle}
                  disabled={!styleIntent.trim()}
                />
              </Form.Item>
            </>
          )}

          <Divider orientation="left" plain style={{ margin: "8px 0 16px" }}>
            4. 模型
          </Divider>
          <Space size="large" wrap align="start">
            <Form.Item
              label="主力模型（规划 / SVG）"
              style={{ marginBottom: 8, minWidth: 160 }}
              extra={
                selectedProvider
                  ? selectedProvider.configured
                    ? `Keys ×${selectedProvider.keyCount || 1}${
                        selectedProvider.keyHint
                          ? ` · ${selectedProvider.keyHint}`
                          : ""
                      }`
                    : "未配置 Key"
                  : undefined
              }
            >
              <Space direction="vertical" size={4}>
                <Select
                  value={llmProvider}
                  onChange={onProviderChange}
                  style={{ width: 200 }}
                  options={llmProviders.map((p) => ({
                    value: p.id,
                    label: providerSelectLabel(p),
                  }))}
                />
                <Select
                  value={llmModel}
                  onChange={setLlmModel}
                  style={{ minWidth: 260 }}
                  options={modelOptions.map((m) => ({
                    value: m.id,
                    label: m.label,
                  }))}
                />
              </Space>
            </Form.Item>
            <Form.Item
              label="文生图模型"
              style={{ marginBottom: 8, minWidth: 160 }}
              extra={
                skipImage || mock
                  ? "已跳过 / Mock"
                  : selectedImageProvider
                    ? selectedImageProvider.configured
                      ? `Keys ×${selectedImageProvider.keyCount || 1}${
                          selectedImageProvider.keyHint
                            ? ` · ${selectedImageProvider.keyHint}`
                            : ""
                        }`
                      : "未配置 Key"
                    : undefined
              }
            >
              <Space direction="vertical" size={4}>
                <Select
                  value={imageProvider}
                  onChange={onImageProviderChange}
                  style={{ width: 200 }}
                  disabled={skipImage || mock}
                  options={imageProviders.map((p) => ({
                    value: p.id,
                    label: imageProviderSelectLabel(p),
                  }))}
                />
                <Select
                  value={imageModel}
                  onChange={setImageModel}
                  style={{ minWidth: 260 }}
                  disabled={skipImage || mock}
                  options={imageModelOptions.map((m) => ({
                    value: m.id,
                    label: m.label,
                  }))}
                />
              </Space>
            </Form.Item>
            <Form.Item label="Mock（示意 SVG）" style={{ marginBottom: 8 }}>
              <Switch checked={mock} onChange={setMock} />
            </Form.Item>
            <Form.Item
              label="跳过生图"
              style={{ marginBottom: 8 }}
              extra="关=Plan 配图后走 IMAGE_* 文生图，嵌入 SVG"
            >
              <Switch
                checked={skipImage}
                onChange={setSkipImage}
                disabled={mock}
              />
            </Form.Item>
            <Form.Item
              label="色板精修"
              style={{ marginBottom: 8 }}
              extra="开=Plan 后按 WCAG 抬升 text/muted 对比度（默认关）"
            >
              <Switch checked={paletteRefine} onChange={setPaletteRefine} />
            </Form.Item>
          </Space>

          <Divider orientation="left" plain style={{ margin: "8px 0 16px" }}>
            5. 导出
          </Divider>
          <Space size="large" wrap align="start">
            <Form.Item
              label="质检门禁"
              style={{ marginBottom: 0 }}
              extra="soft=失败仍导出；strict=失败即停；skip=跳过质检"
            >
              <Select
                value={qualityGate}
                onChange={(v) =>
                  setQualityGate(v as "soft" | "strict" | "skip")
                }
                style={{ width: 160 }}
                options={[
                  { value: "soft", label: "soft（默认）" },
                  { value: "strict", label: "strict" },
                  { value: "skip", label: "skip" },
                ]}
              />
            </Form.Item>
            <Form.Item
              label="SVG 质量修复"
              style={{ marginBottom: 0 }}
              extra={
                qualityGate === "skip"
                  ? "skip 门禁时修复不生效"
                  : "开=门禁失败后 bounds/LLM 重修；关=只检不修"
              }
            >
              <Switch
                checked={svgRepair}
                onChange={setSvgRepair}
                disabled={qualityGate === "skip"}
              />
            </Form.Item>
            <Form.Item
              label="剥离非法节点"
              style={{ marginBottom: 0 }}
              extra="开=去掉 animate / br / 悬空 marker / text@dx / 非法 clip-path（推荐）"
            >
              <Switch
                checked={stripUnsupported}
                onChange={setStripUnsupported}
              />
            </Form.Item>
          </Space>
          <div style={{ marginTop: 16 }}>
            <Button type="primary" htmlType="submit" loading={loading}>
              {`执行 PPT Master ×${count}（${pages} 页/包 · SVG）`}
            </Button>
          </div>
        </Form>
      </Card>
      {lastJob && (
        <Card title={`最近任务 ${lastJob.id}`}>
          <JobProgressBar job={lastJob} />
          <Descriptions size="small" column={1} style={{ marginTop: 12 }}>
            <Descriptions.Item label="状态">
              {jobStatusTag(lastJob.status)}
            </Descriptions.Item>
            <Descriptions.Item label="线路">
              {lastJob.pipeline === "html-slide" ? (
                <Tag>HTML Slide</Tag>
              ) : (
                <Tag color="cyan">PPT Master</Tag>
              )}
              {(lastJob.pipeline === "ppt-master" ||
                lastJob.pipeline == null) && (
                <Tag
                  color={
                    lastJob.pptMasterRender === "html" ? "default" : "cyan"
                  }
                  style={{ marginLeft: 4 }}
                >
                  {lastJob.pptMasterRender === "html"
                    ? "HTML 直出（历史）"
                    : "SVG"}
                </Tag>
              )}
              {lastJob.visualStyle ? (
                <Text type="secondary" style={{ marginLeft: 8 }}>
                  {lastJob.visualStyle}
                  {lastJob.styleIntent
                    ? ` · 意图「${lastJob.styleIntent}」`
                    : ""}
                  {lastJob.ensureStyle ? " · 自动建卡" : ""}
                  {lastJob.randomTheme ? " · 随机主题" : ""}
                  {lastJob.randomStyle
                    ? ` · 随机风格(${lastJob.randomStyleMode || "catalog"})`
                    : ""}
                </Text>
              ) : null}
            </Descriptions.Item>
            <Descriptions.Item label="LLM">
              {lastJob.llmLabel ||
                (lastJob.llmModel
                  ? `${lastJob.llmProvider || ""} · ${lastJob.llmModel}`
                  : "—")}
            </Descriptions.Item>
            <Descriptions.Item label="文生图">
              {lastJob.skipImage
                ? "跳过"
                : lastJob.imageLabel ||
                  (lastJob.imageModel
                    ? `${lastJob.imageProvider || ""} · ${lastJob.imageModel}`
                    : "—")}
            </Descriptions.Item>
            <Descriptions.Item label="色板精修">
              {lastJob.paletteRefine ? "开" : "关"}
            </Descriptions.Item>
            <Descriptions.Item label="数量">
              {lastJob.count ?? 1}
              {lastJob.pages ? ` · ${lastJob.pages} 页/包` : ""}
            </Descriptions.Item>
            <Descriptions.Item label="生成方式">
              {lastJob.pipeline === "html-slide"
                ? "html-slide（历史）"
                : "ppt-master"}
            </Descriptions.Item>
            <Descriptions.Item label="模板 ID">
              {(lastJob.templateIds && lastJob.templateIds.length > 0
                ? lastJob.templateIds.join(", ")
                : lastJob.templateId) || "生成中…"}
            </Descriptions.Item>
            <Descriptions.Item label="输出">
              {lastJob.outputDir}
            </Descriptions.Item>
          </Descriptions>
          <Space style={{ marginTop: 12 }} wrap>
            {isActiveJob(lastJob.status) && (
              <Popconfirm
                title="确认取消生成？"
                description="将终止 agent 进程；已完成的模板仍会保留。"
                okText="取消生成"
                cancelText="继续"
                okButtonProps={{ danger: true }}
                onConfirm={() => void cancelLastJob()}
              >
                <Button danger loading={cancelling}>
                  取消生成
                </Button>
              </Popconfirm>
            )}
            <Paragraph type="secondary" style={{ margin: 0 }}>
              进度约每 1.5s 刷新；也可在「任务日志」查看详情。
            </Paragraph>
          </Space>
        </Card>
      )}
    </Space>
  );
}

function JobsPanel() {
  const { message } = App.useApp();
  const [jobs, setJobs] = useState<GenerateJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [logJob, setLogJob] = useState<GenerateJob | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [clearingTerminal, setClearingTerminal] = useState(false);
  const logPreRef = useRef<HTMLPreElement | null>(null);
  const logStickBottomRef = useRef(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminFetch("/api/admin/generate");
      setJobs(data.jobs || []);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void load();
  }, [load]);

  // 仅当存在排队/运行中任务、且未打开日志弹窗时轮询列表
  //（弹窗打开时改由下方单 job 刷新，避免外面表格 loading 闪烁）
  const hasActive = jobs.some((j) => isActiveJob(j.status));
  const hasTerminal = jobs.some((j) => !isActiveJob(j.status));
  const logModalOpen = Boolean(logJob?.id);
  useEffect(() => {
    if (!hasActive || logModalOpen) return;
    const t = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(t);
  }, [hasActive, logModalOpen, load]);

  // 日志弹窗打开时单独拉最新 job（不闪表格 loading）
  useEffect(() => {
    if (!logJob?.id) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await adminFetch(
          `/api/admin/generate/${encodeURIComponent(logJob.id)}`
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
    // 仅运行中持续刷新；结束后停轮询，关闭弹窗后由列表轮询接手
    if (!isActiveJob(logJob.status)) {
      return () => {
        cancelled = true;
      };
    }
    const t = window.setInterval(() => void tick(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [logJob?.id, logJob?.status]);

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
      message.success("已取消生成");
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
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
      message.success("已删除日志");
      setLogJob((prev) => (prev?.id === id ? null : prev));
      setJobs((prev) => prev.filter((j) => j.id !== id));
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
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
      message.success(
        deleted > 0 ? `已清空 ${deleted} 条已结束任务日志` : "没有可清空的日志"
      );
      setLogJob((prev) => (prev && !isActiveJob(prev.status) ? null : prev));
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setClearingTerminal(false);
    }
  };

  const columns: ColumnsType<GenerateJob> = [
    { title: "ID", dataIndex: "id", width: 168, ellipsis: true },
    {
      title: "线路",
      width: 110,
      render: (_, row) =>
        row.pipeline === "html-slide" ? (
          <Tag>HTML</Tag>
        ) : (
          <Tag color="cyan">PPT Master</Tag>
        ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: string) => jobStatusTag(s),
    },
    {
      title: "进度",
      width: 200,
      render: (_, row) => <JobProgressBar job={row} />,
    },
    {
      title: "数量",
      dataIndex: "count",
      width: 100,
      render: (v: number | undefined, row) => {
        const n = v ?? 1;
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
        return p
          ? `${n}×${p}页${refine}${repair}${gate}${strip}${palette}`
          : `${n}${refine}${repair}${gate}${strip}${palette}`;
      },
    },
    {
      title: "LLM",
      width: 170,
      ellipsis: true,
      render: (_, row) =>
        row.llmLabel || row.llmModel
          ? `${row.llmLabel || row.llmModel}${
              row.llmLightLabel ? ` / ${row.llmLightLabel}` : ""
            }`
          : "—",
    },
    {
      title: "文生图",
      width: 150,
      ellipsis: true,
      render: (_, row) =>
        row.skipImage ? "跳过" : row.imageLabel || row.imageModel || "—",
    },
    {
      title: "模板",
      width: 180,
      ellipsis: true,
      render: (_, row) =>
        (row.templateIds && row.templateIds.length > 0
          ? row.templateIds.join(", ")
          : row.templateId) ||
        row.progress?.lastId ||
        "—",
    },
    {
      title: "创建时间",
      dataIndex: "createdAt",
      width: 168,
      render: (v: string) => (v ? new Date(v).toLocaleString() : "—"),
    },
    {
      title: "操作",
      width: 180,
      fixed: "right",
      render: (_, row) => (
        <Space size={0}>
          <Button type="link" onClick={() => setLogJob(row)}>
            日志
          </Button>
          {isActiveJob(row.status) ? (
            <Popconfirm
              title="确认取消生成？"
              description="将终止 agent 进程；已完成的模板仍会保留。"
              okText="取消生成"
              cancelText="继续"
              okButtonProps={{ danger: true }}
              onConfirm={() => void cancelJob(row.id)}
            >
              <Button type="link" danger loading={cancellingId === row.id}>
                取消
              </Button>
            </Popconfirm>
          ) : (
            <Popconfirm
              title="确认删除此任务日志？"
              description="仅删除任务记录与日志文件，已生成的模板不会删除。"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => void deleteJob(row.id)}
            >
              <Button type="link" danger loading={deletingId === row.id}>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button onClick={() => void load()} loading={loading}>
          刷新
        </Button>
        <Popconfirm
          title="清空全部已结束任务日志？"
          description="将删除 succeeded / failed / cancelled 的任务记录；运行中任务不受影响。"
          okText="清空"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          disabled={!hasTerminal}
          onConfirm={() => void clearTerminalJobs()}
        >
          <Button danger disabled={!hasTerminal} loading={clearingTerminal}>
            清空已结束
          </Button>
        </Popconfirm>
      </Space>
      <Table
        rowKey="id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={jobs}
        pagination={{ pageSize: 10 }}
        scroll={{ x: 1100 }}
        expandable={{
          expandedRowRender: (row) => (
            <Text type="secondary" style={{ fontSize: 12 }}>
              Prompt：{row.prompt || "—"}
            </Text>
          ),
          rowExpandable: (row) => Boolean(row.prompt),
        }}
      />
      <Modal
        title={
          logJob ? (
            <Space size={8}>
              <span>{`日志 · ${logJob.id}`}</span>
              {jobStatusTag(logJob.status)}
              {isActiveJob(logJob.status) && (
                <Text
                  type="secondary"
                  style={{ fontSize: 12, fontWeight: 400 }}
                >
                  每 1.5s 自动刷新
                </Text>
              )}
            </Space>
          ) : (
            "日志"
          )
        }
        open={Boolean(logJob)}
        onCancel={() => setLogJob(null)}
        footer={
          logJob && !isActiveJob(logJob.status) ? (
            <Space>
              <Button onClick={() => setLogJob(null)}>关闭</Button>
              <Popconfirm
                title="确认删除此任务日志？"
                description="仅删除任务记录与日志文件，已生成的模板不会删除。"
                okText="删除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
                onConfirm={() => void deleteJob(logJob.id)}
              >
                <Button danger loading={deletingId === logJob.id}>
                  删除日志
                </Button>
              </Popconfirm>
            </Space>
          ) : null
        }
        width={860}
        centered
        destroyOnClose
        rootClassName="admin-flat-modal"
      >
        <pre
          ref={logPreRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            logStickBottomRef.current =
              el.scrollHeight - el.scrollTop - el.clientHeight < 48;
          }}
          style={{
            margin: 0,
            maxHeight: "min(60vh, 480px)",
            overflow: "auto",
            background: "#0f1115",
            color: "#c8f0c8",
            padding: "14px 16px",
            borderRadius: 8,
            fontSize: 12,
            lineHeight: 1.55,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            fontFamily:
              "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
          }}
        >
          {logJob?.log || ""}
        </pre>
        {logJob?.error && (
          <Alert
            type="error"
            message={logJob.error}
            style={{ marginTop: 12 }}
          />
        )}
      </Modal>
    </>
  );
}

function TemplatesPanel({
  onRemixQueued,
  onRemixDone,
  focusTemplateId,
}: {
  onRemixQueued?: () => void;
  onRemixDone?: (templateId: string) => void;
  focusTemplateId?: string | null;
}) {
  const router = useRouter();
  const { message, modal } = App.useApp();
  const [rows, setRows] = useState<TemplateSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [tablePage, setTablePage] = useState(1);
  const [highlightId, setHighlightId] = useState<string | null>(null);  const [busy, setBusy] = useState<{
    id: string;
    action:
      | "preview"
      | "approve"
      | "reject"
      | "pending"
      | "delete"
      | "batch-delete"
      | "use-template"
      | "open-editor"
      | "export-pptx"
      | "visual-spec"
      | "upload-qiniu";
  } | null>(null);
  const [preview, setPreview] = useState<{
    id: string;
    format?: TemplateFormat;
    pages: Array<{
      id: string;
      title: string;
      file: string;
    }>;
  } | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
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
      const q =
        statusFilter === "all"
          ? ""
          : `?status=${encodeURIComponent(statusFilter)}`;
      const data = await adminFetch(`/api/admin/templates${q}`);
      setRows(data.templates || []);
      setSelectedIds([]);
      setTablePage(1);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [message, statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const id = (focusTemplateId || "").trim();
    if (!id) return;
    setHighlightId(id);
    setSearch(id);
    setStatusFilter("all");
    setTablePage(1);
  }, [focusTemplateId]);

  const setStatus = async (
    id: string,
    status: TemplateStatus,
    action: "approve" | "reject" | "pending"
  ) => {
    setBusy({ id, action });
    try {
      await adminFetch(`/api/admin/templates/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      message.success(
        status === "approved"
          ? "已通过，公开库可见"
          : status === "rejected"
            ? "已驳回"
            : "已更新"
      );
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const remove = (id: string) => {
    modal.confirm({
      title: `删除模板 ${id}？`,
      content: "将从本地 agent-output 目录永久删除，不可恢复。",
      okType: "danger",
      centered: true,
      rootClassName: "admin-flat-modal",
      className: "admin-flat-modal",
      onOk: async () => {
        setBusy({ id, action: "delete" });
        try {
          await adminFetch(`/api/admin/templates/${encodeURIComponent(id)}`, {
            method: "DELETE",
          });
          message.success("已删除");
          setRows((prev) => prev.filter((r) => r.id !== id));
          setSelectedIds((prev) => prev.filter((x) => x !== id));
          await load();
        } catch (e) {
          message.error(e instanceof Error ? e.message : String(e));
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
      message.warning("请先勾选要删除的模板");
      return;
    }
    modal.confirm({
      title: `批量删除 ${ids.length} 个模板？`,
      content: (
        <div>
          <p style={{ marginBottom: 8 }}>
            将从本地 <Text code>agent-output/</Text> 永久删除，不可恢复。
          </p>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {ids.slice(0, 12).join(", ")}
            {ids.length > 12 ? ` 等 ${ids.length} 个` : ""}
          </Text>
        </div>
      ),
      okType: "danger",
      okText: "删除本地文件",
      centered: true,
      rootClassName: "admin-flat-modal",
      className: "admin-flat-modal",
      onOk: async () => {
        setBusy({ id: "__batch__", action: "batch-delete" });
        try {
          // POST：避免部分环境对 DELETE+body 丢弃请求体
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
            message.success(`已删除 ${deleted} 个本地模板`);
          } else {
            message.warning(
              `删除 ${deleted} 个，失败 ${failed.length} 个：${failed
                .map((f) => f.id)
                .join(", ")}`
            );
          }
          // 先本地更新，再拉列表，避免“删了但 UI 没动”
          if (deletedIds.length > 0) {
            const gone = new Set(deletedIds);
            setRows((prev) => prev.filter((r) => !gone.has(r.id)));
            setSelectedIds((prev) => prev.filter((id) => !gone.has(id)));
          }
          await load();
        } catch (e) {
          message.error(e instanceof Error ? e.message : String(e));
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
        `/api/admin/templates/${encodeURIComponent(id)}`
      );
      setPreview({
        id,
        format: data.format || data.meta?.format || "html-slide",
        pages: data.pages || [],
      });
      setPageIndex(0);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
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
        JSON.stringify(data)
      );
      message.success("模板已加载，正在打开编辑器");
      router.push("/");
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const openUseTemplate = (row: TemplateSummary) => {
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
      message.success("已生成一条随机主题，可以直接修改后使用");
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRandomizingUsePrompt(false);
    }
  };

  const submitUseTemplate = async () => {
    const row = useTemplate;
    const prompt = usePrompt.trim();
    if (!row || !prompt) {
      message.warning("请先输入这份新模板的内容要求");
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
            // false = 按新主题重生配图；true/默认 = 保留原图
            skipImage: !useRegenImages,
          }),
        }
      );
      setUseTemplate(null);
      setUsePrompt("");
      setUseRegenImages(false);
      const jobId = String(data.job?.id || "");
      message.success(
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
                  setStatusFilter("all");
                  setTablePage(1);
                  onRemixDone?.(tid);
                }
                message.success(
                  tid
                    ? `套用完成：${tid}（已回到模板列表并定位）`
                    : "套用完成，模板列表已刷新",
                );
                return;
              }
              if (st === "failed" || st === "cancelled") {
                await load();
                message.error(job?.error || `套用任务${st}`);
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
      }    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const exportPptx = async (id: string, label?: string) => {
    setBusy({ id, action: "export-pptx" });
    const key = `export-${id}`;
    message.loading({ content: "正在导出 PPTX…", key, duration: 0 });
    try {
      const data = await fetchEditorDoc(id);
      const pages = (data.pages || []).filter(
        (p: { html?: string }) => p.html && String(p.html).trim()
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
          message.loading({
            content: `导出 PPTX ${current}/${total}…`,
            key,
            duration: 0,
          });
        },
      });
      message.success({ content: "PPTX 已下载（html-to-pptx）", key });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      const isChunk =
        /Loading chunk|ChunkLoadError|Failed to fetch dynamically imported/i.test(
          msg
        );
      message.error({
        content: isChunk
          ? "导出模块加载失败（开发态分包未就绪）。请硬刷新后重试。"
          : msg,
        key,
      });
    } finally {
      setBusy(null);
    }
  };

  const generateVisualSpec = async (id: string) => {
    setBusy({ id, action: "visual-spec" });
    const key = `visual-spec-${id}`;
    message.loading({ content: "正在生成 visual-spec.md…", key, duration: 0 });
    try {
      const data = await adminFetch(
        `/api/admin/templates/${encodeURIComponent(id)}/visual-spec`,
        { method: "POST", body: JSON.stringify({}) }
      );
      message.success({
        content: data.path ? `已生成 ${data.path}` : "visual-spec.md 已生成",
        key,
      });
    } catch (e) {
      message.error({
        content: e instanceof Error ? e.message : String(e),
        key,
      });
    } finally {
      setBusy(null);
    }
  };

  const uploadToQiniu = async (id: string) => {
    setBusy({ id, action: "upload-qiniu" });
    const key = `upload-qiniu-${id}`;
    message.loading({
      content: "1校验 → 2截屏WebP → 3压缩文件 → 4生成规范 → 5打包 → 6上传七牛…",
      key,
      duration: 0,
    });
    try {
      const data = await adminFetch(
        `/api/admin/templates/${encodeURIComponent(id)}/upload`,
        { method: "POST", body: JSON.stringify({}) }
      );
      const zipMb =
        typeof data.zipBytes === "number"
          ? `${(data.zipBytes / (1024 * 1024)).toFixed(2)} MB`
          : null;
      message.success({
        content: [
          "已上传七牛",
          zipMb,
          typeof data.previewPages === "number"
            ? `预览 ${data.previewPages} 页`
            : null,
          data.visualSpecPath ? "含 visual-spec" : null,
          typeof data.imagesCompressed === "number"
            ? `图 ${data.imagesCompressed}`
            : null,
          typeof data.htmlCompressed === "number"
            ? `HTML ${data.htmlCompressed}`
            : null,
          data.url ? data.url : null,
        ]
          .filter(Boolean)
          .join(" · "),
        key,
        duration: 8,
      });
      await load();
    } catch (e) {
      message.error({
        content: e instanceof Error ? e.message : String(e),
        key,
      });
    } finally {
      setBusy(null);
    }
  };

  const columns: ColumnsType<TemplateSummary> = [
    {
      title: "名称",
      dataIndex: "label",
      width: 240,
      ellipsis: true,
      render: (label: TemplateSummary["label"], row) => (
        <div style={{ minWidth: 0, maxWidth: 220 }}>
          <div
            title={label?.zh_CN || row.id}
            style={{
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              fontWeight: 500,
              background:
                highlightId === row.id ? "rgba(22, 119, 255, 0.12)" : undefined,
              borderRadius: 4,
              padding: highlightId === row.id ? "0 4px" : undefined,
            }}
          >
            {label?.zh_CN || row.id}
            {row.sourceTemplateId ? (
              <Tag color="cyan" style={{ marginLeft: 6, marginRight: 0 }}>
                套用
              </Tag>
            ) : null}
          </div>
          <Text
            type="secondary"
            title={
              row.sourceTemplateId
                ? `${row.id} ← ${row.sourceTemplateId}`
                : row.id
            }
            style={{
              fontSize: 12,
              display: "block",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {row.sourceTemplateId
              ? `${row.id} ← ${row.sourceTemplateId}`
              : row.id}
          </Text>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 96,
      render: (s: TemplateStatus) => (
        <Tag color={STATUS_COLOR[s]}>{STATUS_LABEL[s]}</Tag>
      ),
    },
    { title: "页数", dataIndex: "slideCount", width: 64, align: "center" },
    {
      title: "格式",
      dataIndex: "format",
      width: 110,
      render: (f: TemplateFormat | undefined) => (
        <Tag color={f === "ppt-master" ? "geekblue" : "purple"}>
          {f === "ppt-master" ? "ppt-master" : "html-slide"}
        </Tag>
      ),
    },
    {
      title: "页面 Token",
      dataIndex: "pageTokens",
      width: 118,
      align: "right",
      render: (_: number | null | undefined, row: TemplateSummary) => (
        <TokenWithCost tokens={row.pageTokens} cost={row.pageCostCny} />
      ),
    },
    {
      title: "图片 Token",
      key: "imageTokens",
      width: 136,
      align: "right",
      render: (_: unknown, row: TemplateSummary) => {
        const tokens = row.imageTokens;
        const imgs = row.imageCount ?? row.imageCalls;
        const hasTokens = tokens != null && tokens > 0;
        const costLabel = formatCny(row.imageCostCny);
        const imgLabel = imgs != null && imgs > 0 ? `${imgs}张` : null;
        if (!hasTokens && !imgLabel && !costLabel) {
          return <Text type="secondary">—</Text>;
        }
        return (
          <Text
            title={
              [
                hasTokens ? `${tokens} tokens` : "接口未回传 token",
                costLabel ? `约 ${costLabel}（公开价估算）` : null,
                imgs != null ? `${imgs} 次/张` : null,
              ]
                .filter(Boolean)
                .join(" · ") || undefined
            }
            style={{ whiteSpace: "nowrap" }}
          >
            {hasTokens ? formatTokenCount(tokens) : "—"}
            {costLabel ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {" "}
                · {costLabel}
              </Text>
            ) : null}
            {imgLabel ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {" "}
                / {imgLabel}
              </Text>
            ) : null}
          </Text>
        );
      },
    },
    {
      title: "存储",
      dataIndex: "storageBackend",
      width: 88,
      render: (v: string) => (
        <Tag color={v === "qiniu" ? "blue" : undefined} style={{ margin: 0 }}>
          {v || "local"}
        </Tag>
      ),
    },
    {
      title: "更新",
      dataIndex: "mtimeMs",
      width: 160,
      render: (v: number) => (
        <span style={{ whiteSpace: "nowrap" }}>
          {v ? new Date(v).toLocaleString() : "—"}
        </span>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 460,
      fixed: "right",
      render: (_, row) => {
        const moreItems = [
          row.status !== "approved"
            ? {
                key: "approve",
                label: "通过",
                disabled: rowBusy(row.id) && !isBusy(row.id, "approve"),
                onClick: () => void setStatus(row.id, "approved", "approve"),
              }
            : null,
          row.status !== "rejected"
            ? {
                key: "reject",
                label: "驳回",
                disabled: rowBusy(row.id) && !isBusy(row.id, "reject"),
                onClick: () => void setStatus(row.id, "rejected", "reject"),
              }
            : null,
          row.status === "approved"
            ? {
                key: "pending",
                label: "撤回待审",
                disabled: rowBusy(row.id) && !isBusy(row.id, "pending"),
                onClick: () => void setStatus(row.id, "pending", "pending"),
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

        const canUpload = row.status === "approved";

        return (
          <Space size={4} wrap={false} style={{ whiteSpace: "nowrap" }}>
            <Button
              size="small"
              loading={isBusy(row.id, "preview")}
              disabled={rowBusy(row.id) && !isBusy(row.id, "preview")}
              onClick={() => void openPreview(row.id)}
            >
              预览
            </Button>
            <Button
              size="small"
              type="primary"
              ghost
              loading={isBusy(row.id, "use-template")}
              disabled={rowBusy(row.id) && !isBusy(row.id, "use-template")}
              onClick={() => openUseTemplate(row)}
            >
              使用模板
            </Button>
            <Button
              size="small"
              loading={isBusy(row.id, "open-editor")}
              disabled={rowBusy(row.id) && !isBusy(row.id, "open-editor")}
              onClick={() => void openInEditor(row.id)}
            >
              编辑器
            </Button>
            <Button
              size="small"
              loading={isBusy(row.id, "export-pptx")}
              disabled={rowBusy(row.id) && !isBusy(row.id, "export-pptx")}
              onClick={() =>
                void exportPptx(row.id, row.label?.zh_CN || row.id)
              }
            >
              PPTX
            </Button>
            <Button
              size="small"
              loading={isBusy(row.id, "visual-spec")}
              disabled={rowBusy(row.id) && !isBusy(row.id, "visual-spec")}
              title="调用 LLM 生成 / 覆盖 agent-output/<id>/visual-spec.md"
              onClick={() => void generateVisualSpec(row.id)}
            >
              visual-spec
            </Button>
            <Button
              size="small"
              type={row.storageBackend === "qiniu" ? "default" : "primary"}
              loading={isBusy(row.id, "upload-qiniu")}
              disabled={
                !canUpload ||
                (rowBusy(row.id) && !isBusy(row.id, "upload-qiniu"))
              }
              title={
                canUpload
                  ? row.storageBackend === "qiniu"
                    ? "按流程重传：截屏→压缩→生成规范→打包→七牛"
                    : "仅已通过：截屏 WebP → 压缩 → 生成 visual-spec → zip → 七牛"
                  : "仅已通过模板可上传七牛"
              }
              onClick={() => void uploadToQiniu(row.id)}
            >
              {row.storageBackend === "qiniu" ? "重传" : "上传"}
            </Button>
            <Dropdown
              menu={{
                items: moreItems.map((it) => ({
                  key: it.key,
                  label: it.label,
                  danger: it.danger,
                  disabled: it.disabled,
                  onClick: it.onClick,
                })),
              }}
              trigger={["click"]}
            >
              <Button
                size="small"
                icon={<MoreOutlined />}
                loading={
                  isBusy(row.id, "approve") ||
                  isBusy(row.id, "reject") ||
                  isBusy(row.id, "pending") ||
                  isBusy(row.id, "delete")
                }
              />
            </Dropdown>
          </Space>
        );
      },
    },
  ];

  const page = preview?.pages[pageIndex];
  const embedSrc =
    preview && page?.file
      ? buildTemplateSlideEmbedSrc(preview.id, page.file)
      : null;

  useEffect(() => {
    if (!preview) return;
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
  }, [preview]);

  const filteredRows = rows.filter((row) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    const hay = [
      row.id,
      row.label?.zh_CN,
      row.label?.en_US,
      row.sourceTemplateId,
    ]
      .filter(Boolean)
      .join("\n")
      .toLowerCase();
    return hay.includes(q);
  });

  return (
    <>
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          style={{ width: 160 }}
          value={statusFilter}
          onChange={(v) => {
            setStatusFilter(v);
            setTablePage(1);
          }}
          options={[
            { value: "all", label: "全部状态" },
            { value: "pending", label: "待审批" },
            { value: "approved", label: "已通过" },
            { value: "rejected", label: "已驳回" },
            { value: "draft", label: "草稿" },
          ]}
        />
        <Input.Search
          allowClear
          placeholder="搜索名称 / id / 套用来源"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setTablePage(1);
          }}
          style={{ width: 260 }}
        />
        <Button onClick={() => void load()} loading={loading}>
          刷新
        </Button>
        <Button
          danger
          loading={busy?.action === "batch-delete"}
          disabled={selectedIds.length === 0 || busy?.action === "batch-delete"}
          onClick={removeSelected}
        >
          批量删除{selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}
        </Button>
        <Text type="secondary">
          共 {filteredRows.length} 条
          {search.trim() ? `（已筛选，全库 ${rows.length}）` : ""}
          ；最新套用带青色「套用」标签。
        </Text>
      </Space>
      <Table
        rowKey="id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={filteredRows}
        pagination={{
          pageSize: 10,
          current: tablePage,
          onChange: (p) => setTablePage(p),
          showSizeChanger: false,
        }}
        scroll={{ x: 1100 }}
        tableLayout="fixed"
        rowClassName={(row) =>
          highlightId === row.id ? "admin-template-row-focus" : ""
        }
        rowSelection={{
          selectedRowKeys: selectedIds,
          preserveSelectedRowKeys: true,
          onChange: (keys) => setSelectedIds(keys.map(String)),
        }}
      />

      <Modal
        open={Boolean(preview)}
        onCancel={() => setPreview(null)}
        width={1040}
        centered
        destroyOnClose
        rootClassName="admin-flat-modal"
        styles={{
          content: { background: "#fff", padding: 0, overflow: "hidden" },
          header: {
            background: "#fff",
            margin: 0,
            padding: "16px 24px",
            borderBottom: "1px solid #f0f0f0",
          },
          body: { background: "#f4f4f2", padding: "20px 24px" },
          footer: {
            background: "#fff",
            margin: 0,
            padding: "12px 24px",
            borderTop: "1px solid #f0f0f0",
          },
        }}
        title={
          preview ? (
            <div style={{ paddingRight: 28 }}>
              <div
                style={{
                  fontSize: 16,
                  fontWeight: 600,
                  color: "#111",
                }}
              >
                预览 · {preview.id}
              </div>
              <div
                style={{
                  marginTop: 4,
                  fontSize: 12,
                  fontWeight: 400,
                  color: "rgba(0,0,0,0.45)",
                }}
              >
                {page?.title || "—"}
                {page?.file ? ` · ${page.file}` : ""}
                {preview.pages.length > 0
                  ? ` · ${pageIndex + 1} / ${preview.pages.length}`
                  : ""}
                {" · 左右方向键翻页"}
              </div>
            </div>
          ) : (
            "预览"
          )
        }
        footer={
          preview && preview.pages.length > 0 ? (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
              }}
            >
              <Space>
                <Button
                  icon={<LeftOutlined />}
                  disabled={pageIndex <= 0}
                  onClick={() => setPageIndex((i) => Math.max(0, i - 1))}
                >
                  上一页
                </Button>
                <Button
                  icon={<RightOutlined />}
                  disabled={pageIndex >= preview.pages.length - 1}
                  onClick={() =>
                    setPageIndex((i) =>
                      Math.min((preview?.pages.length || 1) - 1, i + 1)
                    )
                  }
                >
                  下一页
                </Button>
              </Space>
              <Button onClick={() => setPreview(null)}>关闭</Button>
            </div>
          ) : null
        }
      >
        {embedSrc && page ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 16,
            }}
          >
            <AdminSlideFrame
              key={`${preview!.id}-html-${page.file}-${pageIndex}`}
              src={embedSrc}
              title={page.title || page.file}
            />
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                justifyContent: "center",
                gap: 8,
                maxWidth: "100%",
              }}
            >
              {preview!.pages.map((p, i) => (
                <button
                  key={p.id || p.file || String(i)}
                  type="button"
                  onClick={() => setPageIndex(i)}
                  style={{
                    height: 32,
                    minWidth: 32,
                    padding: "0 8px",
                    borderRadius: 4,
                    border: "none",
                    cursor: "pointer",
                    fontSize: 12,
                    background:
                      i === pageIndex ? "#1677ff" : "rgba(0,0,0,0.06)",
                    color: i === pageIndex ? "#fff" : "rgba(0,0,0,0.65)",
                  }}
                >
                  {i + 1}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <Text type="secondary">无页面</Text>
        )}
      </Modal>

      <Modal
        open={Boolean(useTemplate)}
        title={
          useTemplate
            ? `使用模板 · ${useTemplate.label?.zh_CN || useTemplate.id}`
            : "使用模板"
        }
        centered
        destroyOnClose
        rootClassName="admin-flat-modal"
        width={680}
        styles={{
          footer: {
            marginTop: 0,
            padding: "12px 24px",
            display: "block",
          },
        }}
        footer={
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              width: "100%",
            }}
          >
            <Button
              icon={<ThunderboltOutlined />}
              loading={randomizingUsePrompt}
              disabled={busy?.action === "use-template"}
              onClick={() => void randomizeUsePrompt()}
            >
              AI 随机生成
            </Button>
            <Space>
              <Button
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
              <Button
                type="primary"
                loading={busy?.action === "use-template"}
                disabled={!usePrompt.trim()}
                onClick={() => void submitUseTemplate()}
              >
                开始生成
              </Button>
            </Space>
          </div>
        }
        onCancel={() => {
          if (busy?.action !== "use-template") {
            setUseTemplate(null);
            setUsePrompt("");
            setUseRegenImages(false);
          }
        }}
      >
        <Paragraph type="secondary" style={{ marginBottom: 12 }}>
          输入新主题与内容要求。系统会<strong>原样保留</strong>当前模板的配色、版式与装饰，只替换文案槽位（以及可选配图），生成一份新的待审模板。
        </Paragraph>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 8,
          }}
        >
          <Text strong style={{ fontSize: 13 }}>
            内容要求
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            可先用 AI 生成，再按需修改
          </Text>
        </div>
        <TextArea
          autoFocus
          value={usePrompt}
          onChange={(e) => setUsePrompt(e.target.value)}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              void submitUseTemplate();
            }
          }}
          placeholder="例如：为制造业客户制作一份 AI 质检方案介绍，突出痛点、流程、收益和落地计划"
          autoSize={{ minRows: 5, maxRows: 10 }}
          maxLength={6000}
          showCount
        />
        <div
          style={{
            marginTop: 16,
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 16,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <Text strong style={{ fontSize: 13, display: "block" }}>
              重生配图
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              关=保留模板原图（更稳）；开=按新主题重跑文生图（仅 image 槽）
            </Text>
          </div>
          <Switch checked={useRegenImages} onChange={setUseRegenImages} />
        </div>
        <Text
          type="secondary"
          style={{ display: "block", marginTop: 8, fontSize: 12 }}
        >
          按 Enter 立即生成；需要换行时按 Shift + Enter。
        </Text>
      </Modal>
    </>
  );
}

function AdminApp() {
  const [authed, setAuthed] = useState(false);
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState("templates");
  const [focusTemplateId, setFocusTemplateId] = useState<string | null>(null);

  useEffect(() => {
    const boot = async () => {
      if (!readToken()) {
        setReady(true);
        return;
      }
      try {
        await adminFetch("/api/admin/templates");
        setAuthed(true);
      } catch {
        clearToken();
      } finally {
        setReady(true);
      }
    };
    void boot();
  }, []);

  const logout = () => {
    clearToken();
    setAuthed(false);
  };

  const items = [
    {
      key: "templates",
      label: "模板管理 / 审批",
      children: (
        <TemplatesPanel
          onRemixQueued={() => setTab("jobs")}
          onRemixDone={(id) => {
            setFocusTemplateId(id);
            setTab("templates");
          }}
          focusTemplateId={focusTemplateId}
        />
      ),
    },
    {
      key: "generate",
      label: "生成模板",
      children: <GeneratePanel onCreated={() => setTab("jobs")} />,
    },
    {
      key: "jobs",
      label: "任务日志",
      children: <JobsPanel />,
    },
  ];

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        加载中…
      </div>
    );
  }

  if (!authed) {
    return <LoginGate onOk={() => setAuthed(true)} />;
  }

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          background: "#111",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          paddingInline: 24,
        }}
      >
        <Title level={4} style={{ color: "#fff", margin: 0 }}>
          WebPPT 模板后台
        </Title>
        <Space>
          <Button type="link" href="/templates" style={{ color: "#ccc" }}>
            公开模板库
          </Button>
          <Button type="link" href="/" style={{ color: "#ccc" }}>
            编辑器
          </Button>
          <Button onClick={logout}>退出</Button>
        </Space>
      </Header>
      <Content
        style={{ padding: 24, maxWidth: 1200, margin: "0 auto", width: "100%" }}
      >
        <Tabs activeKey={tab} onChange={setTab} items={items} />
      </Content>
    </Layout>
  );
}

export default function AdminPage() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorBgElevated: "#ffffff",
          colorBgContainer: "#ffffff",
          colorText: "rgba(0, 0, 0, 0.88)",
          colorTextSecondary: "rgba(0, 0, 0, 0.45)",
        },
      }}
    >
      <App>
        <AdminApp />
      </App>
    </ConfigProvider>
  );
}
