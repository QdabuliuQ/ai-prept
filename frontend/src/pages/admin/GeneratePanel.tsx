import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Zap } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  PPT_MASTER_VISUAL_STYLES,
  pptMasterVisualStyleSelectOptions,
  type PptMasterStyleSelectGroup,
} from "@/constants/pptMasterStyles";
import { adminFetch } from "./api";
import {
  DescRow,
  Field,
  imageProviderSelectLabel,
  isActiveJob,
  JobProgressBar,
  jobStatusBadge,
  LoadingButton,
  providerSelectLabel,
  SectionDivider,
  useConfirmDialog,
} from "./shared";
import type {
  GenerateJob,
  ImageProviderPublic,
  LlmProviderPublic,
} from "./types";

export function GeneratePanel({
  onCreated,
  active = true,
}: {
  onCreated: () => void;
  /** 进入「生成模板」Tab 时重新拉取 LLM 列表（后端新增供应商后无需整页刷新） */
  active?: boolean;
}) {
  const { confirm, dialog } = useConfirmDialog();
  const [prompt, setPrompt] = useState("");
  const [count, setCount] = useState(1);
  const [pages, setPages] = useState(7);
  const [mock, setMock] = useState(false);
  const [skipImage, setSkipImage] = useState(false);
  const [paletteRefine, setPaletteRefine] = useState(false);
  const [llmThinking, setLlmThinking] = useState(false);
  const [svgRepair, setSvgRepair] = useState(true);
  const [qualityGate, setQualityGate] = useState<"soft" | "strict" | "skip">(
    "soft",
  );
  const [stripUnsupported, setStripUnsupported] = useState(true);
  const [visualStyle, setVisualStyle] = useState("dark-tech");
  const [styleIntent, setStyleIntent] = useState("");
  const [ensureStyle, setEnsureStyle] = useState(true);
  const [randomTheme, setRandomTheme] = useState(false);
  const [randomStyle, setRandomStyle] = useState(false);
  const [randomStyleMode, setRandomStyleMode] = useState<"catalog" | "invent">(
    "catalog",
  );
  /** 数量>1 且开启随机时：true=整批共用；false=每包重随（主题/风格各自独立） */
  const [reuseRandomTheme, setReuseRandomTheme] = useState(true);
  const [reuseRandomStyle, setReuseRandomStyle] = useState(true);
  const [styleSelectOptions, setStyleSelectOptions] = useState<
    PptMasterStyleSelectGroup[]
  >(() => pptMasterVisualStyleSelectOptions());
  const [styleCatalogMeta, setStyleCatalogMeta] = useState<string | null>(null);
  const [llmProviders, setLlmProviders] = useState<LlmProviderPublic[]>([]);
  const [llmProvider, setLlmProvider] = useState("deepseek");
  const [llmModel, setLlmModel] = useState("deepseek-v4-flash");
  const [imageProviders, setImageProviders] = useState<ImageProviderPublic[]>(
    [],
  );
  const [imageProvider, setImageProvider] = useState("openai");
  const [imageModel, setImageModel] = useState("nano-banana-fast");
  const [loading, setLoading] = useState(false);
  const [randomizingPrompt, setRandomizingPrompt] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [lastJob, setLastJob] = useState<GenerateJob | null>(null);
  const selectionInitedRef = useRef(false);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const boot = async () => {
      try {
        const [llmData, stylesSettled] = await Promise.all([
          adminFetch("/api/admin/llm"),
          adminFetch("/api/admin/styles").then(
            (data) => ({ ok: true as const, data }),
            (err: unknown) => ({ ok: false as const, err }),
          ),
        ]);
        if (cancelled) return;
        const providers = (llmData.providers as LlmProviderPublic[]) || [];
        setLlmProviders(providers);
        const imgProviders =
          (llmData.imageProviders as ImageProviderPublic[]) || [];
        setImageProviders(imgProviders);

        if (!selectionInitedRef.current) {
          selectionInitedRef.current = true;
          const preferred =
            providers.find((p) => p.id === "deepseek" && p.configured) ||
            providers.find((p) => p.tier === "heavy" && p.configured) ||
            providers.find((p) => p.configured) ||
            providers[0];
          if (preferred) {
            setLlmProvider(preferred.id);
            setLlmModel(preferred.models[0]?.id || "");
          }
          const preferredImg =
            imgProviders.find((p) => p.id === "openai" && p.configured) ||
            imgProviders.find((p) => p.configured) ||
            imgProviders[0];
          if (preferredImg) {
            setImageProvider(preferredImg.id);
            setImageModel(preferredImg.models[0]?.id || "");
          }
        } else {
          // 供应商列表更新后，若当前选择已不存在则回退
          setLlmProvider((cur) =>
            providers.some((p) => p.id === cur) ? cur : providers[0]?.id || cur,
          );
          setImageProvider((cur) =>
            imgProviders.some((p) => p.id === cur)
              ? cur
              : imgProviders[0]?.id || cur,
          );
        }
        if (stylesSettled.ok && stylesSettled.data?.selectOptions?.length) {
          const stylesData = stylesSettled.data;
          setStyleSelectOptions(
            stylesData.selectOptions as PptMasterStyleSelectGroup[],
          );
          const n = Number(stylesData.count) || 0;
          const at = stylesData.generated_at
            ? String(stylesData.generated_at)
            : "";
          const variantN = Array.isArray(stylesData.styles)
            ? stylesData.styles.filter(
                (s: { status?: string }) => s?.status === "variant",
              ).length
            : 0;
          setStyleCatalogMeta(
            at
              ? `目录 ${n} 种（含变体 ${variantN}）· ${at}`
              : `目录 ${n} 种（含变体 ${variantN} · _catalog.json）`,
          );
        } else if (!stylesSettled.ok) {
          const msg =
            stylesSettled.err instanceof Error
              ? stylesSettled.err.message
              : String(stylesSettled.err || "加载失败");
          setStyleCatalogMeta(
            `风格目录未更新（回退本地 ${PPT_MASTER_VISUAL_STYLES.length} 种）：${msg}`,
          );
          toast.warning(`视觉风格目录加载失败，仍显示旧列表：${msg}`);
        }
      } catch (e) {
        if (!cancelled) {
          toast.error(e instanceof Error ? e.message : "加载 LLM 配置失败");
        }
      }
    };
    void boot();
    return () => {
      cancelled = true;
    };
  }, [active]);

  const selectedProvider = llmProviders.find((p) => p.id === llmProvider);
  const modelOptions = selectedProvider?.models || [];
  const selectedImageProvider = imageProviders.find(
    (p) => p.id === imageProvider,
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

  useEffect(() => {
    if (!lastJob?.id) return;
    if (!isActiveJob(lastJob.status)) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await adminFetch(
          `/api/admin/generate/${encodeURIComponent(lastJob.id)}`,
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
        },
      );
      if (data.job) setLastJob(data.job);
      toast.success("已取消生成");
      onCreated();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
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
      toast.success(
        data.model ? `已用 ${data.model} 生成主题` : "已随机生成主题",
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRandomizingPrompt(false);
    }
  };

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const n = Math.floor(Number(count) || 0);
    if (n < 1 || n > 20) {
      toast.warning("生成数量请填写 1–20");
      return;
    }
    const pageCount = Math.min(12, Math.max(3, Math.floor(Number(pages) || 7)));
    if (!mock && selectedProvider && !selectedProvider.configured) {
      toast.warning(
        `${selectedProvider.label} 未配置 API Key，请先在 .env.local 填写`,
      );
      return;
    }
    if (!mock && !llmModel) {
      toast.warning("请选择主力 LLM 模型");
      return;
    }
    if (
      !mock &&
      !skipImage &&
      selectedImageProvider &&
      !selectedImageProvider.configured
    ) {
      toast.warning(
        `${selectedImageProvider.label} 未配置 API Key，请先在 .env 填写 SILICONFLOW_* / IMAGE_* / POLLINATIONS_*`,
      );
      return;
    }
    if (!mock && !skipImage && !imageModel) {
      toast.warning("请选择文生图模型");
      return;
    }
    setLoading(true);
    try {
      let nextPrompt = prompt.trim();
      let nextStyle = visualStyle;
      let nextIntent = styleIntent.trim();
      let nextEnsure = Boolean(nextIntent) && ensureStyle;
      const rerollTheme = n > 1 && randomTheme && !reuseRandomTheme;
      const rerollStyle = n > 1 && randomStyle && !reuseRandomStyle;
      const perPack = rerollTheme || rerollStyle;

      // 需要「整批共用」的项：提交前先抽一次；每包重随的项交给后端
      if (randomStyle && !rerollStyle) {
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
          toast.info(`随机风格意图：${nextIntent}`);
        } else {
          nextStyle = String(styleData.styleId || "").trim();
          if (!nextStyle) throw new Error("随机风格为空");
          nextIntent = "";
          nextEnsure = false;
          setVisualStyle(nextStyle);
          setStyleIntent("");
          toast.info(
            `随机风格：${nextStyle}${
              styleData.labelZh ? `（${styleData.labelZh}）` : ""
            }`,
          );
        }
      }

      if (randomTheme && !rerollTheme) {
        const themeData = await adminFetch("/api/admin/prompt-random", {
          method: "POST",
          body: JSON.stringify({
            visualStyle: nextIntent ? undefined : nextStyle,
          }),
        });
        nextPrompt = String(themeData.prompt || "").trim();
        if (!nextPrompt) throw new Error("随机主题为空");
        setPrompt(nextPrompt);
        toast.info(
          themeData.model
            ? `随机主题（${themeData.model}）已填入`
            : "随机主题已填入",
        );
      }

      if (perPack) {
        toast.info(
          `每包重随：主题${rerollTheme ? "✓" : "共用"} · 风格${
            rerollStyle ? "✓" : "共用"
          }（×${n}）`,
        );
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
          category: nextStyle,
          randomTheme,
          randomStyle,
          randomStyleMode: randomStyle ? randomStyleMode : undefined,
          reuseRandomTheme: randomTheme ? !rerollTheme : undefined,
          reuseRandomStyle: randomStyle ? !rerollStyle : undefined,
          repairOnFail: svgRepair,
          qualityGate,
          stripUnsupported,
          llmThinking,
          llmProvider,
          llmModel,
          imageProvider,
          imageModel,
        }),
      });
      setLastJob(data.job);
      const styleLabel = perPack
        ? [
            rerollTheme ? "主题每包重随" : null,
            rerollStyle ? "风格每包重随" : null,
          ]
            .filter(Boolean)
            .join(" · ") || "每包重随"
        : nextIntent || nextStyle;
      toast.success(
        `已启动 PPT Master ×${n}（${pageCount} 页/包 · ${styleLabel} · SVG）`,
      );
      onCreated();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const styleSourceValue = randomStyle ? randomStyleMode : "pick";

  return (
    <div className="space-y-6">
      {dialog}
      <Alert>
        <AlertTitle>PPT Master 生成线路</AlertTitle>
        <AlertDescription>
          <span>
            使用仓库内{" "}
            <code className="rounded bg-muted px-1 text-xs">ppt-master</code>{" "}
            Skill：LLM 写规范 SVG → 质检 → 原生 PPTX →{" "}
            <strong className="font-medium">Admin 浏览器内</strong>用{" "}
            <code className="rounded bg-muted px-1 text-xs">
              pptx-renderer
            </code>{" "}
            转成模板包（默认不再起 Puppeteer）。写入{" "}
            <code className="rounded bg-muted px-1 text-xs">agent-output/</code>
            ，状态{" "}
            <Badge className="border-transparent bg-amber-100 text-amber-900 hover:bg-amber-100">
              待审批
            </Badge>
            。任务日志里若出现「等待浏览器转换」，请保持本页打开直至转换完成。
          </span>
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>新建生成任务</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={(e) => void submit(e)} className="space-y-4">
            <Field
              label="产物格式"
              extra="入库 format=ppt-master；PPTX 由 Admin 浏览器转成 html-slide 包。"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge className="border-transparent bg-sky-100 text-sky-800 hover:bg-sky-100">
                  ppt-master
                </Badge>
                <Badge variant="secondary">SVG 线路</Badge>
                <span className="text-sm text-muted-foreground">
                  规范 SVG → 质检 → 原生 PPTX → 转 HTML 包
                </span>
              </div>
            </Field>

            <SectionDivider>1. 规模</SectionDivider>
            <div className="flex flex-wrap gap-6">
              <Field label="生成数量" extra="每包独立跑 PPT Master（1–20）">
                <Input
                  type="number"
                  min={1}
                  max={20}
                  value={count}
                  onChange={(e) => setCount(Number(e.target.value) || 1)}
                  className="w-40"
                />
              </Field>
              <Field label="母版页数" extra="每包页数（3–12）">
                <Input
                  type="number"
                  min={3}
                  max={12}
                  value={pages}
                  onChange={(e) => setPages(Number(e.target.value) || 7)}
                  className="w-40"
                />
              </Field>
            </div>

            <SectionDivider>2. 主题</SectionDivider>
            <Field
              label={
                <div className="flex flex-wrap items-center gap-3">
                  <span>主题描述</span>
                  <label className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
                    提交时随机
                    <Switch
                      checked={randomTheme}
                      onCheckedChange={setRandomTheme}
                    />
                  </label>
                  {count > 1 && randomTheme ? (
                    <label className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
                      整批共用
                      <Switch
                        checked={reuseRandomTheme}
                        onCheckedChange={setReuseRandomTheme}
                      />
                    </label>
                  ) : null}
                  <Button
                    type="button"
                    variant="link"
                    size="sm"
                    className="h-auto px-0"
                    disabled={randomTheme || randomizingPrompt}
                    onClick={() => void randomizePrompt()}
                  >
                    <Zap className="h-3.5 w-3.5" />
                    {randomizingPrompt ? "生成中…" : "现在生成一版"}
                  </Button>
                </div>
              }
              extra={
                randomTheme
                  ? count > 1
                    ? reuseRandomTheme
                      ? "已开启随机：整批包共用同一次主题"
                      : "已开启随机：每包重新抽主题（串行）"
                    : "已开启：提交时用 SCORE_VL 覆盖下方文案"
                  : "写内容主题（产品/活动/议题），不要写视觉风格名。包名按主题命名。"
              }
            >
              <Textarea
                rows={3}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="例如：AI 产品发布会 / 话剧首演手册——写内容主题即可；勿把风格名写进主题"
                disabled={randomTheme}
              />
            </Field>

            <SectionDivider>3. 视觉风格（同时作为模板类型）</SectionDivider>
            <Field
              label={
                <div className="flex flex-wrap items-center gap-3">
                  <span>来源</span>
                  {count > 1 && randomStyle ? (
                    <label className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
                      整批共用
                      <Switch
                        checked={reuseRandomStyle}
                        onCheckedChange={setReuseRandomStyle}
                      />
                    </label>
                  ) : null}
                </div>
              }
              extra={
                randomStyle && count > 1
                  ? reuseRandomStyle
                    ? "随机风格：整批包共用同一次抽到的风格"
                    : "随机风格：每包重新抽风格（串行）"
                  : undefined
              }
            >
              <Select
                value={styleSourceValue}
                onValueChange={(v) => {
                  if (v === "pick") {
                    setRandomStyle(false);
                  } else {
                    setRandomStyle(true);
                    setRandomStyleMode(v as "catalog" | "invent");
                    setStyleIntent("");
                  }
                }}
              >
                <SelectTrigger className="w-[280px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pick">指定已有风格</SelectItem>
                  <SelectItem value="catalog">随机 · 从已有目录抽一张</SelectItem>
                  <SelectItem value="invent">随机 · 发明新风格并建卡</SelectItem>
                </SelectContent>
              </Select>
            </Field>

            {randomStyle ? (
              <Alert>
                <AlertDescription>
                  {randomStyleMode === "invent"
                    ? "提交时发明一句风格意图；近义复用已有卡，没有则自动建卡。"
                    : "提交时从目录随机抽一张已有风格卡，不会新建。"}
                </AlertDescription>
              </Alert>
            ) : (
              <>
                <Field
                  label="视觉风格"
                  extra={
                    styleCatalogMeta ||
                    "来自 ppt-master visual-styles/_catalog.json"
                  }
                >
                  <Select
                    value={visualStyle}
                    onValueChange={(id) => {
                      setVisualStyle(id);
                      setStyleIntent("");
                    }}
                    disabled={Boolean(styleIntent.trim())}
                  >
                    <SelectTrigger className="w-[360px] max-w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="max-h-80">
                      {styleSelectOptions.map((group) => (
                        <SelectGroup key={group.label}>
                          <SelectLabel>{group.label}</SelectLabel>
                          {group.options.map((opt) => (
                            <SelectItem key={opt.value} value={opt.value}>
                              {opt.label}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field
                  label="或写风格意图"
                  extra="填写后优先于上方下拉。近义会复用已有卡；没有则按 style-skill 写新卡。留空则只用下拉。"
                >
                  <Textarea
                    rows={2}
                    value={styleIntent}
                    onChange={(e) => setStyleIntent(e.target.value)}
                    placeholder="例如：夜间水族馆导视、蜡笔儿童绘本、法院卷宗封面"
                  />
                </Field>
                <Field
                  label="缺卡时自动生成"
                  extra="仅在填写了风格意图时生效。关闭则必须能匹配已有卡，否则任务失败。"
                >
                  <Switch
                    checked={ensureStyle}
                    onCheckedChange={setEnsureStyle}
                    disabled={!styleIntent.trim()}
                  />
                </Field>
              </>
            )}

            <SectionDivider>4. 模型</SectionDivider>
            <div className="flex flex-wrap items-start gap-6">
              <Field
                label="主力模型（规划 / SVG）"
                className="min-w-[160px]"
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
                <div className="flex flex-col gap-1">
                  <Select value={llmProvider} onValueChange={onProviderChange}>
                    <SelectTrigger className="w-[200px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {llmProviders.map((p) => (
                        <SelectItem key={p.id} value={p.id}>
                          {providerSelectLabel(p)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Select value={llmModel} onValueChange={setLlmModel}>
                    <SelectTrigger className="min-w-[260px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {modelOptions.map((m) => (
                        <SelectItem key={m.id} value={m.id}>
                          {m.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </Field>

              <Field
                label="文生图模型"
                className="min-w-[160px]"
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
                <div className="flex flex-col gap-1">
                  <Select
                    value={imageProvider}
                    onValueChange={onImageProviderChange}
                    disabled={skipImage || mock}
                  >
                    <SelectTrigger className="w-[200px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {imageProviders.map((p) => (
                        <SelectItem key={p.id} value={p.id}>
                          {imageProviderSelectLabel(p)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Select
                    value={imageModel}
                    onValueChange={setImageModel}
                    disabled={skipImage || mock}
                  >
                    <SelectTrigger className="min-w-[260px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {imageModelOptions.map((m) => (
                        <SelectItem key={m.id} value={m.id}>
                          {m.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </Field>

              <Field label="Mock（示意 SVG）">
                <Switch checked={mock} onCheckedChange={setMock} />
              </Field>
              <Field
                label="跳过生图"
                extra="关=Plan 配图后走 IMAGE_* 文生图，嵌入 SVG"
              >
                <Switch
                  checked={skipImage}
                  onCheckedChange={setSkipImage}
                  disabled={mock}
                />
              </Field>
              <Field
                label="色板精修"
                extra="开=Plan 后按 WCAG 抬升 text/muted 对比度（默认关）"
              >
                <Switch
                  checked={paletteRefine}
                  onCheckedChange={setPaletteRefine}
                />
              </Field>
              <Field
                label="LLM 思考模式"
                extra="DeepSeek / Gemini；开=加深推理、更贵更慢（默认关）。Gemini 无法完全关思考，关时压到 minimal/low"
              >
                <Switch
                  checked={llmThinking}
                  onCheckedChange={setLlmThinking}
                  disabled={mock}
                />
              </Field>
            </div>

            <SectionDivider>5. 导出</SectionDivider>
            <div className="flex flex-wrap items-start gap-6">
              <Field
                label="质检门禁"
                extra="soft=失败仍导出；strict=失败即停；skip=跳过质检"
              >
                <Select
                  value={qualityGate}
                  onValueChange={(v) =>
                    setQualityGate(v as "soft" | "strict" | "skip")
                  }
                >
                  <SelectTrigger className="w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="soft">soft（默认）</SelectItem>
                    <SelectItem value="strict">strict</SelectItem>
                    <SelectItem value="skip">skip</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field
                label="SVG 质量修复"
                extra={
                  qualityGate === "skip"
                    ? "skip 门禁时修复不生效"
                    : "开=门禁失败后 bounds/LLM 重修；关=只检不修"
                }
              >
                <Switch
                  checked={svgRepair}
                  onCheckedChange={setSvgRepair}
                  disabled={qualityGate === "skip"}
                />
              </Field>
              <Field
                label="剥离非法节点"
                extra="开=去掉 animate / br / 悬空 marker / text@dx / 非法 clip-path（推荐）"
              >
                <Switch
                  checked={stripUnsupported}
                  onCheckedChange={setStripUnsupported}
                />
              </Field>
            </div>

            <div className="pt-2">
              <LoadingButton type="submit" loading={loading}>
                {`执行 PPT Master ×${count}（${pages} 页/包 · SVG）`}
              </LoadingButton>
            </div>
          </form>
        </CardContent>
      </Card>

      {lastJob && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">最近任务 {lastJob.id}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <JobProgressBar job={lastJob} />
            <dl className="space-y-2">
              <DescRow label="状态">{jobStatusBadge(lastJob.status)}</DescRow>
              <DescRow label="线路">
                <div className="flex flex-wrap items-center gap-2">
                  {lastJob.pipeline === "html-slide" ? (
                    <Badge variant="secondary">HTML Slide</Badge>
                  ) : (
                    <Badge className="border-transparent bg-cyan-100 text-cyan-800 hover:bg-cyan-100">
                      PPT Master
                    </Badge>
                  )}
                  {(lastJob.pipeline === "ppt-master" ||
                    lastJob.pipeline == null) && (
                    <Badge
                      variant={
                        lastJob.pptMasterRender === "html"
                          ? "secondary"
                          : "outline"
                      }
                      className={
                        lastJob.pptMasterRender === "html"
                          ? undefined
                          : "border-transparent bg-cyan-100 text-cyan-800 hover:bg-cyan-100"
                      }
                    >
                      {lastJob.pptMasterRender === "html"
                        ? "HTML 直出（历史）"
                        : "SVG"}
                    </Badge>
                  )}
                  {lastJob.visualStyle ? (
                    <span className="text-sm text-muted-foreground">
                      {lastJob.visualStyle}
                      {lastJob.styleIntent
                        ? ` · 意图「${lastJob.styleIntent}」`
                        : ""}
                      {lastJob.ensureStyle ? " · 自动建卡" : ""}
                      {lastJob.randomTheme ? " · 随机主题" : ""}
                      {lastJob.randomStyle
                        ? ` · 随机风格(${lastJob.randomStyleMode || "catalog"})`
                        : ""}
                      {(lastJob.count || 1) > 1 && lastJob.randomTheme
                        ? lastJob.reuseRandomTheme === false
                          ? " · 主题每包重随"
                          : " · 主题共用"
                        : ""}
                      {(lastJob.count || 1) > 1 && lastJob.randomStyle
                        ? lastJob.reuseRandomStyle === false
                          ? " · 风格每包重随"
                          : " · 风格共用"
                        : ""}
                    </span>
                  ) : null}
                </div>
              </DescRow>
              <DescRow label="LLM">
                {lastJob.llmLabel ||
                  (lastJob.llmModel
                    ? `${lastJob.llmProvider || ""} · ${lastJob.llmModel}`
                    : "—")}
              </DescRow>
              <DescRow label="文生图">
                {lastJob.skipImage
                  ? "跳过"
                  : lastJob.imageLabel ||
                    (lastJob.imageModel
                      ? `${lastJob.imageProvider || ""} · ${lastJob.imageModel}`
                      : "—")}
              </DescRow>
              <DescRow label="色板精修">
                {lastJob.paletteRefine ? "开" : "关"}
              </DescRow>
              <DescRow label="LLM 思考">
                {lastJob.llmThinking ? "开" : "关"}
              </DescRow>
              <DescRow label="数量">
                {lastJob.count ?? 1}
                {lastJob.pages ? ` · ${lastJob.pages} 页/包` : ""}
              </DescRow>
              <DescRow label="生成方式">
                {lastJob.pipeline === "html-slide"
                  ? "html-slide（历史）"
                  : "ppt-master"}
              </DescRow>
              <DescRow label="模板 ID">
                {(lastJob.templateIds && lastJob.templateIds.length > 0
                  ? lastJob.templateIds.join(", ")
                  : lastJob.templateId) || "生成中…"}
              </DescRow>
              <DescRow label="输出">{lastJob.outputDir}</DescRow>
            </dl>
            <div className="flex flex-wrap items-center gap-3 pt-1">
              {isActiveJob(lastJob.status) && (
                <LoadingButton
                  variant="destructive"
                  loading={cancelling}
                  onClick={() =>
                    confirm({
                      title: "确认取消生成？",
                      description: "将终止 agent 进程；已完成的模板仍会保留。",
                      okText: "取消生成",
                      cancelText: "继续",
                      destructive: true,
                      onConfirm: () => cancelLastJob(),
                    })
                  }
                >
                  取消生成
                </LoadingButton>
              )}
              <p className="m-0 text-sm text-muted-foreground">
                进度约每 1.5s 刷新；也可在「任务日志」查看详情。
              </p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
