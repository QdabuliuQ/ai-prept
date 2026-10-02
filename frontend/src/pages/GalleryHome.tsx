import { useEffect, useMemo, useState } from "react";
import { Loader2, Search, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import logo from "@/assets/images/ai-prept-logo.png";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Toaster } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";
import { useRouter } from "@/navigation";
import {
  coerceTemplateCategory,
  fetchTemplateCategories,
  galleryCategoryFilters,
  type TemplateCategory,
} from "@/constants/templateCategories";

type GalleryTemplate = {
  id: string;
  title: string;
  description: string;
  slideCount: number;
  cover: string;
  pages: string[];
  featured?: boolean;
  category?: string;
  updatedAt: number;
};

type GalleryModelOption = { id: string; label: string };
type GalleryProviderOption = {
  id: string;
  label: string;
  models: GalleryModelOption[];
  configured: boolean;
};

type ModelPrefs = {
  llmProvider: string;
  llmModel: string;
  imageProvider: string;
  imageModel: string;
};

const PREFS_KEY = "webppt:gallery-model-prefs";
const dockSelectTriggerClass =
  "h-8 w-auto max-w-[10.5rem] shrink-0 gap-1 rounded-full border-0 bg-white/10 px-3 text-[11px] font-medium text-white/85 shadow-none ring-1 ring-white/12 hover:bg-white/14 hover:text-white focus:ring-2 focus:ring-[#f97316]/75 disabled:opacity-50 [&>span]:line-clamp-1 [&>svg]:size-3 [&>svg]:opacity-60";
const dockSelectContentClass =
  "z-[80] max-h-72 border-[#f97316]/30 bg-[#1a1917] text-white shadow-[0_16px_48px_rgba(0,0,0,0.55)]";
const dockSelectItemClass =
  "cursor-pointer text-xs text-white/85 focus:bg-[#f97316]/20 focus:text-[#fed7aa] data-[state=checked]:text-[#fb923c] data-[disabled]:opacity-40";

function readPrefs(): Partial<ModelPrefs> {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    return raw ? (JSON.parse(raw) as Partial<ModelPrefs>) : {};
  } catch {
    return {};
  }
}

function writePrefs(value: ModelPrefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(value));
  } catch {
    // Ignore unavailable storage.
  }
}

export default function GalleryHome() {
  const router = useRouter();
  const [templates, setTemplates] = useState<GalleryTemplate[]>([]);
  const [categories, setCategories] = useState<TemplateCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState<GalleryTemplate | null>(null);
  const [prompt, setPrompt] = useState("");
  const [promptFocused, setPromptFocused] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [inspiring, setInspiring] = useState(false);
  const [llmProviders, setLlmProviders] = useState<GalleryProviderOption[]>([]);
  const [imageProviders, setImageProviders] = useState<GalleryProviderOption[]>([]);
  const [llmProvider, setLlmProvider] = useState("gemini");
  const [llmModel, setLlmModel] = useState("gemini-3.8-flash");
  const [imageProvider, setImageProvider] = useState("siliconflow");
  const [imageModel, setImageModel] = useState("Kwai-Kolors/Kolors");

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetch("/api/gallery"), fetchTemplateCategories()])
      .then(async ([response, cats]) => {
        if (!response.ok) throw new Error("LIST_FAILED");
        const data = (await response.json()) as { templates?: GalleryTemplate[] };
        if (!cancelled) {
          setTemplates(data.templates || []);
          setCategories(cats);
        }
      })
      .catch(() => {
        if (!cancelled) setError("无法读取已上传的模板");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/gallery/models")
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        const llms = (data.llmProviders || []) as GalleryProviderOption[];
        const images = (data.imageProviders || []) as GalleryProviderOption[];
        const saved = readPrefs();
        setLlmProviders(llms);
        setImageProviders(images);
        const lp = llms.find((item) => item.id === saved.llmProvider) || llms[0];
        const ip = images.find((item) => item.id === saved.imageProvider) || images[0];
        if (lp) {
          setLlmProvider(lp.id);
          setLlmModel(saved.llmModel || lp.models[0]?.id || "");
        }
        if (ip) {
          setImageProvider(ip.id);
          setImageModel(saved.imageModel || ip.models[0]?.id || "");
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    writePrefs({ llmProvider, llmModel, imageProvider, imageModel });
  }, [llmProvider, llmModel, imageProvider, imageModel]);

  const filters = useMemo(
    () => [
      { id: "all", label: "全部" },
      { id: "featured", label: "精选" },
      ...galleryCategoryFilters(templates, categories),
    ],
    [templates, categories],
  );
  const visibleTemplates = useMemo(
    () =>
      templates.filter((template) => {
        if (filter === "all") return true;
        if (filter === "featured") return Boolean(template.featured);
        return coerceTemplateCategory(template.category, categories) === filter;
      }),
    [templates, filter, categories],
  );
  const llmModelOptions = llmProviders.find((p) => p.id === llmProvider)?.models || [];
  const imageModelOptions = imageProviders.find((p) => p.id === imageProvider)?.models || [];

  const inspire = async () => {
    setInspiring(true);
    try {
      const response = await fetch("/api/gallery/inspire", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = (await response.json()) as { prompt?: string; error?: string };
      if (!response.ok) throw new Error(data.error || "灵感生成失败");
      setPrompt(data.prompt || "");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "灵感生成失败");
    } finally {
      setInspiring(false);
    }
  };

  const generate = async () => {
    if (!selected || !prompt.trim()) {
      toast.warning(selected ? "请填写内容要求" : "请先选择一个模板");
      return;
    }
    setGenerating(true);
    try {
      const response = await fetch("/api/gallery/remix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ templateId: selected.id, prompt: prompt.trim(), skipImage: false, llmProvider, llmModel, imageProvider, imageModel }),
      });
      const data = (await response.json()) as { job?: { id?: string }; error?: string; message?: string };
      if (!response.ok || !data.job?.id) throw new Error(data.message || data.error || "启动失败");
      sessionStorage.setItem("webppt:pending-remix-job", JSON.stringify({ jobId: data.job.id, sourceTemplateId: selected.id, prompt: prompt.trim() }));
      router.push("/edit");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#121110] text-white">
      <Toaster theme="dark" position="top-center" />
      <header className="absolute left-0 right-0 top-0 z-10 flex items-center gap-2.5 px-5 py-4 sm:px-7">
        <img src={logo} alt="Ai Prept" className="size-9 rounded-lg object-cover" />
        <span className="text-lg font-semibold tracking-tight">Ai Prept</span>
      </header>

      <main className="mx-auto flex min-h-screen max-w-7xl flex-col px-4 pb-56 pt-24 sm:px-7">
        {loading ? (
          <div className="flex flex-1 items-center justify-center"><Loader2 className="size-8 animate-spin text-white/50" /></div>
        ) : error ? (
          <div className="flex flex-1 items-center justify-center text-sm text-white/50">{error}</div>
        ) : (
          <>
            <div className="mb-5 flex gap-2 overflow-x-auto pb-1">
              {filters.map((item) => (
                <Button key={item.id} size="sm" onClick={() => setFilter(item.id)} className={cn("shrink-0 rounded-full px-3 py-1.5 text-xs", filter === item.id ? "bg-[#f97316] text-white hover:bg-[#ea580c]" : "bg-white/10 text-white/70 hover:bg-white/15 hover:text-white")}>
                  {item.label}
                </Button>
              ))}
            </div>
            {visibleTemplates.length === 0 ? (
              <div className="flex flex-1 items-center justify-center text-sm text-white/45">还没有上传成功的模板</div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {visibleTemplates.map((template) => {
                  const active = selected?.id === template.id;
                  return (
                    <button key={template.id} type="button" onClick={() => setSelected(active ? null : template)} className={cn("group overflow-hidden rounded-xl bg-[#1a1917] text-left shadow-[0_8px_28px_rgba(0,0,0,0.35)] transition hover:-translate-y-0.5", active && "ring-2 ring-[#f97316] ring-offset-2 ring-offset-[#121110]")}>
                      <div className="aspect-video overflow-hidden bg-black/20"><img src={template.cover} alt={template.title} className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]" /></div>
                      <div className="p-3"><div className="truncate text-sm font-medium">{template.title}</div><div className="mt-1 line-clamp-2 text-xs text-white/45">{template.description}</div></div>
                    </button>
                  );
                })}
              </div>
            )}
          </>
        )}
      </main>

      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-20 flex justify-center bg-gradient-to-t from-[#0c0b0a] via-[#0c0b0a]/85 to-transparent px-3 pb-6 pt-20 sm:pb-8">
        <div className="pointer-events-auto flex w-full max-w-[760px] flex-col gap-3">
          {selected ? <div className="flex items-center gap-3 rounded-2xl bg-[#252320]/95 px-3 py-2.5"><img src={selected.cover} alt="" className="h-11 w-[78px] rounded-md object-cover" /><p className="min-w-0 flex-1 truncate text-[13px]">已选择「{selected.title}」模板</p><Button size="icon" variant="ghost" onClick={() => setSelected(null)} className="rounded-full text-white/70 hover:bg-white/10 hover:text-white"><X className="size-4" /></Button></div> : null}
          <div className={cn("flex gap-2 rounded-2xl border border-white/10 bg-[#1a1917]/95 p-2 backdrop-blur-md", promptFocused ? "items-start" : "items-center")}>
            <div className="flex min-w-0 flex-1 items-start gap-3 rounded-xl px-3 py-2.5"><Search className="mt-1 size-[18px] shrink-0 text-white/35" /><Textarea value={prompt} rows={1} onChange={(event) => setPrompt(event.target.value)} onFocus={() => setPromptFocused(true)} onBlur={() => setPromptFocused(false)} placeholder={selected ? `基于「${selected.title}」开始创作…` : "先选择模板，再描述你想做的 PPT"} className={cn("min-h-0 min-w-0 flex-1 resize-none border-0 bg-transparent p-0 text-[15px] text-white/90 shadow-none placeholder:text-white/35 focus-visible:ring-0", promptFocused ? "h-32 overflow-y-auto" : "h-6 overflow-hidden")} /></div>
            <div className="flex shrink-0 items-center gap-1.5"><Button type="button" disabled={inspiring || generating} onClick={() => void inspire()} className="rounded-full bg-white/10 text-sm text-white/80 hover:bg-white/15">{inspiring ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}发现灵感</Button><Button type="button" disabled={generating} onClick={() => void generate()} className="rounded-full bg-[#f97316] text-white hover:bg-[#ea580c]">{generating ? <Loader2 className="size-3.5 animate-spin" /> : null}开始生成</Button></div>
          </div>
          {(llmProviders.length > 0 || imageProviders.length > 0) && <div className="flex flex-nowrap items-center gap-2 overflow-x-auto rounded-2xl border border-white/10 bg-[#1a1917]/90 px-3 py-2 backdrop-blur-md"><span className="shrink-0 text-[11px] text-white/40">文本</span><Select value={llmProvider} onValueChange={(value) => { setLlmProvider(value); setLlmModel(llmProviders.find((p) => p.id === value)?.models[0]?.id || ""); }}><SelectTrigger aria-label="文本模型服务商" className={dockSelectTriggerClass}><SelectValue placeholder="服务商" /></SelectTrigger><SelectContent className={dockSelectContentClass}>{llmProviders.map((provider) => <SelectItem key={provider.id} value={provider.id} disabled={!provider.configured} className={dockSelectItemClass}>{provider.label}</SelectItem>)}</SelectContent></Select><Select value={llmModel} onValueChange={setLlmModel}><SelectTrigger aria-label="文本模型" className={cn(dockSelectTriggerClass, "max-w-[13rem]")}><SelectValue placeholder="模型" /></SelectTrigger><SelectContent className={dockSelectContentClass}>{llmModelOptions.map((model) => <SelectItem key={model.id} value={model.id} className={dockSelectItemClass}>{model.label}</SelectItem>)}</SelectContent></Select><span className="mx-0.5 h-3 w-px bg-white/15" /><span className="shrink-0 text-[11px] text-white/40">图片</span><Select value={imageProvider} onValueChange={(value) => { setImageProvider(value); setImageModel(imageProviders.find((p) => p.id === value)?.models[0]?.id || ""); }}><SelectTrigger aria-label="图片模型服务商" className={dockSelectTriggerClass}><SelectValue placeholder="服务商" /></SelectTrigger><SelectContent className={dockSelectContentClass}>{imageProviders.map((provider) => <SelectItem key={provider.id} value={provider.id} disabled={!provider.configured} className={dockSelectItemClass}>{provider.label}</SelectItem>)}</SelectContent></Select><Select value={imageModel} onValueChange={setImageModel}><SelectTrigger aria-label="图片模型" className={cn(dockSelectTriggerClass, "max-w-[13rem]")}><SelectValue placeholder="模型" /></SelectTrigger><SelectContent className={dockSelectContentClass}>{imageModelOptions.map((model) => <SelectItem key={model.id} value={model.id} className={dockSelectItemClass}>{model.label}</SelectItem>)}</SelectContent></Select></div>}
        </div>
      </div>
    </div>
  );
}
