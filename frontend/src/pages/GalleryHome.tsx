import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import { useEventListener, useMemoizedFn, useSize } from "ahooks";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Eye,
  Loader2,
  Minus,
  MousePointerClick,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { toast } from "sonner";
import logo from "@/assets/images/ai-prept-logo.png";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

type SizeKey = "sm" | "lg";

type PlacedCard = GalleryTemplate & {
  mockKey: string;
  size: SizeKey;
  featured: boolean;
  x: number;
  y: number;
  w: number;
  h: number;
};

const GAP = 14;
const PAD = 48;
const TARGET_COUNT = 48;
const MIN_ZOOM = 0.45;
const MAX_ZOOM = 1.35;
const DRAG_THRESHOLD = 5;

/** 16:9；小卡面积 ×4 = 大卡面积（线性 2×）。含间隙时大卡正好盖住 2×2 小卡占位。 */
const ASPECT = 16 / 9;
const SM_W = 280;
const SM_H = Math.round(SM_W / ASPECT);
const LG_W = SM_W * 2 + GAP;
const LG_H = SM_H * 2 + GAP;

function sizeBox(key: SizeKey): { w: number; h: number } {
  return key === "lg" ? { w: LG_W, h: LG_H } : { w: SM_W, h: SM_H };
}

function realTemplateId(id: string): string {
  return id.replace(/__mock_\d+$/, "");
}

function GalleryCardCover({
  src,
  alt,
  rootRef,
}: {
  src: string;
  alt: string;
  /** 模板墙视口：用于 transform 画布下的可视检测 */
  rootRef?: RefObject<HTMLElement | null>;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const markLoaded = useCallback(() => setLoaded(true), []);

  useEffect(() => {
    setInView(false);
    setLoaded(false);
  }, [src]);

  useEffect(() => {
    if (!src || inView) return;
    const el = hostRef.current;
    if (!el) return;

    // transform 画布下原生 loading=lazy 不可靠，按视口交叉再请求图片
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setInView(true);
          observer.disconnect();
        }
      },
      {
        root: rootRef?.current ?? null,
        rootMargin: "240px",
        threshold: 0.01,
      },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [src, inView, rootRef]);

  return (
    <div ref={hostRef} className="absolute inset-0 overflow-hidden">
      {!loaded ? (
        <div className="absolute inset-0 z-[1] flex items-center justify-center bg-[#1a1917]">
          <Loader2 className="size-6 animate-spin text-white/45 sm:size-7" />
        </div>
      ) : null}
      {inView && src ? (
        <img
          src={src}
          alt={alt}
          loading="lazy"
          decoding="async"
          fetchPriority="low"
          draggable={false}
          className={cn(
            "pointer-events-none h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]",
            loaded ? "opacity-100" : "opacity-0",
          )}
          ref={(el) => {
            if (el?.complete && el.naturalWidth > 0) markLoaded();
          }}
          onLoad={markLoaded}
          onError={markLoaded}
        />
      ) : null}
    </div>
  );
}

const PREVIEW_FADE_MS = 320;

function isImageCached(url: string): boolean {
  if (!url || typeof window === "undefined") return false;
  const probe = new Image();
  probe.src = url;
  return probe.complete && probe.naturalWidth > 0;
}

/**
 * 预览主图切页：
 * - 下一页未完成：深灰 Loading 遮罩盖满，不透出上一页
 * - 已缓存：跳过 Loading，直接淡入
 * - 新图叠在上层淡入，避免卸旧图时闪黑
 */
function PreviewCrossfade({
  src,
  alt,
}: {
  src: string;
  alt: string;
}) {
  const genRef = useRef(0);
  const displayedRef = useRef("");
  const topSrcRef = useRef<string | null>(null);
  const settlingRef = useRef<string | null>(null);

  const [bottomSrc, setBottomSrc] = useState("");
  const [topSrc, setTopSrc] = useState<string | null>(null);
  const [topShow, setTopShow] = useState(false);
  const [waiting, setWaiting] = useState(false);

  useEffect(() => {
    if (!src) {
      genRef.current += 1;
      displayedRef.current = "";
      topSrcRef.current = null;
      settlingRef.current = null;
      setBottomSrc("");
      setTopSrc(null);
      setTopShow(false);
      setWaiting(false);
      return;
    }

    if (src === displayedRef.current && !topSrcRef.current) return;
    if (src === topSrcRef.current) return;

    ++genRef.current;
    settlingRef.current = null;
    topSrcRef.current = src;
    setTopSrc(src);
    setTopShow(false);
    // 未缓存时立刻盖 Loading，避免透出上一页
    setWaiting(!isImageCached(src));
  }, [src]);

  const commitTop = useCallback((loadedSrc: string) => {
    if (topSrcRef.current !== loadedSrc) return;
    if (settlingRef.current === loadedSrc) return;
    settlingRef.current = loadedSrc;

    const gen = genRef.current;
    setWaiting(false);

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (genRef.current !== gen) return;
        setTopShow(true);

        window.setTimeout(() => {
          if (genRef.current !== gen) return;
          setBottomSrc(loadedSrc);
          displayedRef.current = loadedSrc;

          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              if (genRef.current !== gen) return;
              if (topSrcRef.current !== loadedSrc) return;
              topSrcRef.current = null;
              settlingRef.current = null;
              setTopSrc(null);
              setTopShow(false);
            });
          });
        }, PREVIEW_FADE_MS);
      });
    });
  }, []);

  const onTopEl = useCallback(
    (el: HTMLImageElement | null, loadedSrc: string) => {
      if (!el || topSrcRef.current !== loadedSrc) return;
      if (el.complete && el.naturalWidth > 0) {
        commitTop(loadedSrc);
        return;
      }
      setWaiting(true);
    },
    [commitTop],
  );

  const showLoader = waiting || (!bottomSrc && !topSrc);

  return (
    <div className="relative h-full w-full bg-[#1c1917]">
      {bottomSrc && !waiting ? (
        <img
          src={bottomSrc}
          alt={alt}
          draggable={false}
          className="absolute inset-0 h-full w-full object-contain opacity-100 transition-opacity ease-out"
          style={{ transitionDuration: "150ms" }}
        />
      ) : null}
      {topSrc ? (
        <img
          key={topSrc}
          src={topSrc}
          alt={alt}
          draggable={false}
          className={cn(
            "absolute inset-0 z-[1] h-full w-full object-contain transition-opacity ease-out",
            topShow && !waiting ? "opacity-100" : "opacity-0",
          )}
          style={{ transitionDuration: `${PREVIEW_FADE_MS}ms` }}
          ref={(el) => onTopEl(el, topSrc)}
          onLoad={() => commitTop(topSrc)}
          onError={() => commitTop(topSrc)}
        />
      ) : null}
      {showLoader ? (
        <div
          className="absolute inset-0 z-[2] flex flex-col items-center justify-center gap-2.5 bg-[#1c1917]"
          aria-live="polite"
          aria-busy="true"
        >
          <Loader2 className="size-8 animate-spin text-white/90" />
          <span className="text-sm tracking-wide text-white/75">加载中...</span>
        </div>
      ) : null}
    </div>
  );
}

/** 约 1/4 为大卡，其余小卡 */
const SIZE_PATTERN: SizeKey[] = [
  "sm",
  "sm",
  "lg",
  "sm",
  "sm",
  "sm",
  "lg",
  "sm",
  "sm",
  "sm",
  "sm",
  "lg",
];

const STATIC_FILTERS = [
  { id: "all", label: "全部" },
  { id: "mine", label: "我的模板" },
  { id: "featured", label: "精选" },
] as const;

function expandTemplates(source: GalleryTemplate[]): GalleryTemplate[] {
  if (source.length === 0) return [];
  const out: GalleryTemplate[] = [];
  for (let i = 0; i < TARGET_COUNT; i += 1) {
    const base = source[i % source.length];
    out.push({
      ...base,
      id: `${base.id}__mock_${i}`,
      title: i < source.length ? base.title : `${base.title} · ${i + 1}`,
    });
  }
  return out;
}

/** 按小卡网格打包：大卡占 2×2 格，小卡占 1 格 */
function packCards(items: GalleryTemplate[]): {
  cards: PlacedCard[];
  width: number;
  height: number;
} {
  const cellW = SM_W + GAP;
  const cellH = SM_H + GAP;
  const cols = 10;
  const rowsEstimate = Math.ceil(items.length * 1.5) + 8;
  const occupied: boolean[][] = Array.from({ length: rowsEstimate }, () =>
    Array.from({ length: cols }, () => false),
  );

  const canPlace = (c: number, r: number, cw: number, rh: number) => {
    if (c + cw > cols || r + rh > occupied.length) return false;
    for (let y = r; y < r + rh; y += 1) {
      for (let x = c; x < c + cw; x += 1) {
        if (occupied[y][x]) return false;
      }
    }
    return true;
  };

  const mark = (c: number, r: number, cw: number, rh: number) => {
    for (let y = r; y < r + rh; y += 1) {
      for (let x = c; x < c + cw; x += 1) {
        occupied[y][x] = true;
      }
    }
  };

  const findSpot = (cw: number, rh: number): { c: number; r: number } | null => {
    for (let r = 0; r < occupied.length; r += 1) {
      for (let c = 0; c <= cols - cw; c += 1) {
        if (canPlace(c, r, cw, rh)) return { c, r };
      }
    }
    return null;
  };

  const cards: PlacedCard[] = [];
  let maxRow = 0;

  items.forEach((tpl, index) => {
    const size = SIZE_PATTERN[index % SIZE_PATTERN.length];
    const span = size === "lg" ? 2 : 1;
    let spot = findSpot(span, span);
    if (!spot && size === "lg") {
      // 放不下大卡时降级为小卡，避免留空洞
      spot = findSpot(1, 1);
      if (spot) {
        const { w, h } = sizeBox("sm");
        mark(spot.c, spot.r, 1, 1);
        maxRow = Math.max(maxRow, spot.r);
        cards.push({
          ...tpl,
          mockKey: tpl.id,
          size: "sm",
          featured: Boolean(tpl.featured),
          x: PAD + spot.c * cellW,
          y: PAD + spot.r * cellH,
          w,
          h,
        });
        return;
      }
    }
    if (!spot) return;
    const { w, h } = sizeBox(size === "lg" && span === 2 ? "lg" : "sm");
    const key: SizeKey = span === 2 ? "lg" : "sm";
    mark(spot.c, spot.r, span, span);
    maxRow = Math.max(maxRow, spot.r + span - 1);
    cards.push({
      ...tpl,
      mockKey: tpl.id,
      size: key,
      featured: Boolean(tpl.featured),
      x: PAD + spot.c * cellW,
      y: PAD + spot.r * cellH,
      w,
      h,
    });
  });

  return {
    cards,
    width: PAD * 2 + cols * cellW - GAP,
    height: PAD * 2 + (maxRow + 1) * cellH - GAP,
  };
}

function matchesFilter(
  tpl: GalleryTemplate,
  filterId: string,
  categories: readonly TemplateCategory[],
) {
  if (filterId === "all" || filterId === "mine") return true;
  if (filterId === "featured") return Boolean(tpl.featured);
  return coerceTemplateCategory(tpl.category, categories) === filterId;
}

function GenerateCta(props: {
  generating: boolean;
  inspiring: boolean;
  hasTemplate: boolean;
  hasPrompt: boolean;
  onClick: () => void;
}) {
  const { generating, inspiring, hasTemplate, hasPrompt, onClick } = props;
  const disabled = generating || inspiring || !hasTemplate || !hasPrompt;
  const tip = generating
    ? "正在生成中…"
    : inspiring
      ? "请稍候"
      : !hasTemplate
        ? "请先选择模板"
        : !hasPrompt
          ? "请先填写内容要求"
          : "基于所选模板生成新内容";

  return (
    <span className="group/cta relative inline-flex">
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        aria-label={tip}
        className={cn(
          "group relative isolate h-auto overflow-hidden rounded-full p-[1.5px] outline-none transition-[filter] duration-300 hover:brightness-110 focus-visible:ring-2 focus-visible:ring-white/35",
          disabled && "cursor-not-allowed opacity-50",
        )}
      >
        <span
          aria-hidden
          className="inspire-border-spin pointer-events-none absolute inset-[-120%] bg-[conic-gradient(from_0deg,#67e8f9,#a78bfa,#f472b6,#fb923c,#f87171,#67e8f9)] opacity-95"
        />
        <span className="relative z-10 flex items-center gap-1.5 rounded-full bg-[#1c1b19] px-4 py-2.5 text-sm font-medium text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
          {generating ? (
            <Loader2
              className="size-3.5 shrink-0 animate-spin text-white/90"
              aria-hidden
            />
          ) : (
            <Sparkles
              className="size-3.5 shrink-0 text-white/90"
              aria-hidden
            />
          )}
          {generating ? "生成中…" : "开始生成"}
        </span>
      </button>
      {disabled ? (
        <span
          role="tooltip"
          className="pointer-events-none absolute bottom-[calc(100%+8px)] left-1/2 z-40 -translate-x-1/2 whitespace-nowrap rounded-md bg-[#0c0b0a] px-2.5 py-1.5 text-xs font-medium text-white opacity-0 shadow-lg ring-1 ring-white/10 transition-opacity duration-150 group-hover/cta:opacity-100"
        >
          {tip}
          <span
            aria-hidden
            className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-[#0c0b0a]"
          />
        </span>
      ) : null}
    </span>
  );
}

export default function GalleryHome() {
  const viewportRef = useRef<HTMLDivElement>(null);
  const thumbStripRef = useRef<HTMLDivElement>(null);
  const viewportSize = useSize(viewportRef);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [source, setSource] = useState<GalleryTemplate[]>([]);
  const [categories, setCategories] = useState<TemplateCategory[]>([]);
  const [prompt, setPrompt] = useState("");
  const [promptFocused, setPromptFocused] = useState(false);
  const [inspiring, setInspiring] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [filter, setFilter] = useState<string>("all");
  const router = useRouter();

  const filters = useMemo(
    () => [...STATIC_FILTERS, ...galleryCategoryFilters(source, categories)],
    [source, categories],
  );

  useEffect(() => {
    // 当前筛选类型已不在模板集合里时，退回「全部」
    if (STATIC_FILTERS.some((f) => f.id === filter)) return;
    if (filters.some((f) => f.id === filter)) return;
    setFilter("all");
  }, [filter, filters]);

  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(0.8);
  const [dragging, setDragging] = useState(false);
  const centeredRef = useRef(false);

  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    moved: boolean;
    /** 从模板卡片按下时记下，短按松手则打开预览 */
    card: PlacedCard | null;
  } | null>(null);
  const suppressClickRef = useRef(false);

  const [active, setActive] = useState<GalleryTemplate | null>(null);
  const [viewerClosing, setViewerClosing] = useState(false);
  const [pageIndex, setPageIndex] = useState(0);
  const [thumbLoaded, setThumbLoaded] = useState<Record<string, boolean>>({});
  const [selected, setSelected] = useState<GalleryTemplate | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [listRes, cats] = await Promise.all([
          fetch("/api/gallery"),
          fetchTemplateCategories(),
        ]);
        if (!listRes.ok) throw new Error("LIST_FAILED");
        const data = (await listRes.json()) as {
          templates?: GalleryTemplate[];
        };
        if (!cancelled) {
          setSource(data.templates || []);
          setCategories(cats);
        }
      } catch {
        if (!cancelled) setError("无法读取已上传的模板");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const expanded = useMemo(() => expandTemplates(source), [source]);

  const layout = useMemo(() => {
    const filtered = expanded.filter((tpl) =>
      matchesFilter(tpl, filter, categories),
    );
    return packCards(filtered);
  }, [expanded, filter, categories]);

  useEffect(() => {
    centeredRef.current = false;
  }, [layout.width, layout.height]);

  useEffect(() => {
    if (centeredRef.current) return;
    if (!viewportSize?.width || !layout.width) return;
    centeredRef.current = true;
    const z = 0.8;
    setZoom(z);
    setOffset({
      x: (viewportSize.width - layout.width * z) / 2,
      y: (viewportSize.height - layout.height * z) / 2 + 20,
    });
  }, [layout.width, layout.height, viewportSize?.width, viewportSize?.height]);

  const closeViewer = useCallback(() => {
    if (!active || viewerClosing) return;
    setViewerClosing(true);
  }, [active, viewerClosing]);

  const finishCloseViewer = useCallback(() => {
    setActive(null);
    setViewerClosing(false);
    setPageIndex(0);
  }, []);

  const openViewer = useCallback(
    (tpl: GalleryTemplate) => {
      const realId = realTemplateId(tpl.id);
      const real =
        source.find((t) => t.id === realId) ||
        source.find((t) => tpl.cover === t.cover) ||
        tpl;
      setViewerClosing(false);
      setActive({
        ...real,
        title: tpl.title,
      });
      setPageIndex(0);
    },
    [source],
  );

  const selectTemplate = useMemoizedFn((tpl: GalleryTemplate) => {
    const realId = realTemplateId(tpl.id);
    const real =
      source.find((t) => t.id === realId) ||
      source.find((t) => tpl.cover === t.cover) ||
      tpl;
    const next = { ...real, title: real.title || tpl.title, id: realId };
    setSelected(next);
  });

  const clearSelected = useCallback(() => {
    setSelected(null);
  }, []);

  const discoverInspire = useMemoizedFn(async () => {
    if (inspiring || generating) return;
    setInspiring(true);
    try {
      const res = await fetch("/api/gallery/inspire", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const data = (await res.json().catch(() => ({}))) as {
        prompt?: string;
        error?: string;
        detail?: string;
        model?: string;
      };
      if (!res.ok) {
        throw new Error(
          data.error ||
            (typeof data.detail === "string" ? data.detail : "") ||
            `灵感生成失败（${res.status}）`,
        );
      }
      const next = String(data.prompt || "").trim();
      if (!next) throw new Error("未返回创作要求");
      setPrompt(next);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "灵感生成失败");
    } finally {
      setInspiring(false);
    }
  });

  const startGenerate = useMemoizedFn(async () => {
    if (generating || inspiring) return;
    const tid = selected ? realTemplateId(selected.id) : "";
    const brief = prompt.trim();
    if (!tid) {
      toast.warning("请先选择一个模板");
      return;
    }
    if (!brief) {
      toast.warning("请先填写内容要求，或点「发现灵感」");
      return;
    }
    setGenerating(true);
    const toastId = "gallery-remix";
    toast.loading("正在按模板生成内容…", { id: toastId });
    try {
      const res = await fetch("/api/gallery/remix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          templateId: tid,
          prompt: brief,
          skipImage: true,
        }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        job?: { id?: string; status?: string };
        error?: string;
        message?: string;
      };
      if (!res.ok) {
        throw new Error(
          data.message || data.error || `启动失败（${res.status}）`,
        );
      }
      const jobId = String(data.job?.id || "").trim();
      if (!jobId) throw new Error("未返回任务 id");

      let newId = "";
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const jr = await fetch(
          `/api/gallery/jobs/${encodeURIComponent(jobId)}`,
        );
        const jd = (await jr.json().catch(() => ({}))) as {
          job?: {
            status?: string;
            templateId?: string;
            error?: string;
          };
          error?: string;
          message?: string;
        };
        if (!jr.ok) {
          throw new Error(jd.message || jd.error || `查询失败（${jr.status}）`);
        }
        const st = String(jd.job?.status || "");
        if (st === "succeeded") {
          newId = String(jd.job?.templateId || "").trim();
          break;
        }
        if (st === "failed" || st === "cancelled") {
          throw new Error(jd.job?.error || `生成${st === "cancelled" ? "已取消" : "失败"}`);
        }
        toast.loading(`正在生成…（${i + 1}）`, { id: toastId });
      }
      if (!newId) throw new Error("生成超时，请稍后在编辑器重试");

      const docRes = await fetch(
        `/api/html-templates/${encodeURIComponent(newId)}`,
      );
      const doc = await docRes.json().catch(() => ({}));
      if (!docRes.ok) {
        throw new Error(
          (doc as { message?: string; error?: string }).message ||
            (doc as { error?: string }).error ||
            `加载结果失败（${docRes.status}）`,
        );
      }
      sessionStorage.setItem(
        "webppt:pending-template-doc",
        JSON.stringify(doc),
      );
      toast.success("生成完成，正在打开编辑器", { id: toastId });
      router.push("/editor");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "生成失败", {
        id: toastId,
      });
    } finally {
      setGenerating(false);
    }
  });

  const pages = active?.pages || [];
  const pageCount = pages.length;
  const currentPageSrc = pages[pageIndex] || "";

  useEffect(() => {
    setThumbLoaded({});
  }, [active?.id]);

  const step = useCallback(
    (delta: number) => {
      setPageIndex((current) => {
        if (pageCount <= 0) return 0;
        return Math.min(pageCount - 1, Math.max(0, current + delta));
      });
    },
    [pageCount],
  );

  const scrollThumbs = useMemoizedFn((dir: -1 | 1) => {
    const el = thumbStripRef.current;
    if (!el) return;
    el.scrollBy({ left: dir * 420, behavior: "smooth" });
  });

  useEffect(() => {
    if (!active) return;
    const strip = thumbStripRef.current;
    if (!strip) return;
    const selected = strip.children[pageIndex] as HTMLElement | undefined;
    if (!selected) return;
    const stripRect = strip.getBoundingClientRect();
    const selRect = selected.getBoundingClientRect();
    const delta =
      selRect.left +
      selRect.width / 2 -
      (stripRect.left + stripRect.width / 2);
    strip.scrollBy({ left: delta, behavior: "smooth" });
  }, [active, pageIndex]);

  useEffect(() => {
    if (!active) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeViewer();
      else if (event.key === "ArrowLeft") step(-1);
      else if (event.key === "ArrowRight") step(1);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [active, closeViewer, step]);

  const onPointerDown = useMemoizedFn((e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const target = e.target as HTMLElement;
    // 底部栏交互不拖画布；模板卡片上也可以拖，短按打开预览
    if (target.closest("[data-dock]")) return;
    suppressClickRef.current = false;
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      originX: offset.x,
      originY: offset.y,
      moved: false,
      card: null,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
  });

  const onPointerMove = useMemoizedFn((e: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const dx = e.clientX - drag.startX;
    const dy = e.clientY - drag.startY;
    if (!drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    drag.moved = true;
    suppressClickRef.current = true;
    setOffset({ x: drag.originX + dx, y: drag.originY + dy });
  });

  const endDrag = useMemoizedFn((e: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const shouldPreview = !drag.moved && drag.card;
    if (drag.moved) suppressClickRef.current = true;
    dragRef.current = null;
    setDragging(false);
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
    if (shouldPreview && drag.card) {
      openViewer(drag.card);
    }
  });

  const bumpZoom = useMemoizedFn((delta: number) => {
    setZoom((z) =>
      Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round((z + delta) * 100) / 100)),
    );
  });

  const resetView = useMemoizedFn(() => {
    setZoom(0.8);
    if (!viewportSize?.width) return;
    setOffset({
      x: (viewportSize.width - layout.width * 0.8) / 2,
      y: (viewportSize.height - layout.height * 0.8) / 2 + 20,
    });
  });

  useEventListener(
    "wheel",
    (e: WheelEvent) => {
      if (active) return;
      if (!viewportRef.current?.contains(e.target as Node)) return;
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) {
        setZoom((z) =>
          Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z - e.deltaY * 0.0015)),
        );
      } else {
        setOffset((o) => ({ x: o.x - e.deltaX, y: o.y - e.deltaY }));
      }
    },
    { target: viewportRef, passive: false },
  );

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#121110] text-white">
      <Toaster theme="dark" position="top-center" />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(80% 60% at 50% 40%, #1c1a18 0%, #121110 55%, #0c0b0a 100%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            "radial-gradient(rgba(255,255,255,0.045) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 40%, rgba(0,0,0,0.55) 100%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-40"
        style={{
          boxShadow:
            "inset 0 0 72px 28px rgba(0,0,0,0.72), inset 0 0 0 1px rgba(255,255,255,0.04)",
        }}
      />

      <header className="pointer-events-none absolute left-0 right-0 top-0 z-[45] flex items-start px-5 py-4 sm:px-7">
        <div className="pointer-events-auto flex items-center gap-2.5">
          <img
            src={logo}
            alt="Ai Prept"
            width={36}
            height={36}
            className="size-9 shrink-0 rounded-lg object-cover"
          />
          <span className="text-lg font-semibold tracking-tight text-white/95 sm:text-xl">
            Ai Prept
          </span>
        </div>
      </header>

      <div
        ref={viewportRef}
        className={cn(
          "absolute inset-0 z-10 touch-none select-none",
          dragging ? "cursor-grabbing" : "cursor-grab",
        )}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        {loading ? (
          <div className="flex h-full items-center justify-center text-sm text-white/45">
            正在加载模板…
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center text-sm text-white/45">
            {error}
          </div>
        ) : source.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-white/45">
            <p>还没有上传成功的模板</p>
            <a href="/admin" className="text-[#f25f00] hover:underline">
              去 Admin 上传
            </a>
          </div>
        ) : (
          <div
            className="absolute left-0 top-0 origin-top-left will-change-transform"
            style={{
              width: layout.width,
              height: layout.height,
              transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`,
            }}
          >
            {layout.cards.map((card) => {
              const isSelected =
                selected != null &&
                realTemplateId(card.id) === realTemplateId(selected.id);
              return (
              <div
                key={card.mockKey}
                data-card
                role="button"
                tabIndex={0}
                aria-label={`预览 ${card.title}`}
                aria-pressed={isSelected}
                className={cn(
                  "group absolute cursor-pointer overflow-hidden rounded-xl bg-[#1a1917] text-left shadow-[0_8px_28px_rgba(0,0,0,0.45)] transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_16px_40px_rgba(0,0,0,0.55)]",
                  isSelected &&
                    "ring-2 ring-[#e8b84a] ring-offset-2 ring-offset-[#0c0b0a]",
                )}
                style={{
                  left: card.x,
                  top: card.y,
                  width: card.w,
                  height: card.h,
                  touchAction: "none",
                }}
                onPointerDown={(e) => {
                  e.stopPropagation();
                  if (e.button !== 0) return;
                  if (
                    (e.target as HTMLElement).closest(
                      "[data-preview-btn],[data-select-btn]",
                    )
                  ) {
                    return;
                  }
                  const viewport = viewportRef.current;
                  if (!viewport) return;
                  suppressClickRef.current = false;
                  dragRef.current = {
                    pointerId: e.pointerId,
                    startX: e.clientX,
                    startY: e.clientY,
                    originX: offset.x,
                    originY: offset.y,
                    moved: false,
                    card,
                  };
                  viewport.setPointerCapture(e.pointerId);
                  setDragging(true);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    openViewer(card);
                  }
                }}
              >
                <GalleryCardCover
                  src={card.cover}
                  alt={card.title}
                  rootRef={viewportRef}
                />
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
                {card.featured ? (
                  <Badge
                    className="absolute left-2.5 top-2.5 border-transparent bg-[#e8b84a] px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-[#2a2108] hover:bg-[#e8b84a]"
                  >
                    精选
                  </Badge>
                ) : null}
                <div
                  className={cn(
                    "pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 p-2.5 transition-opacity duration-200 sm:p-3",
                    isSelected
                      ? "pointer-events-auto opacity-100"
                      : "opacity-0 group-hover:pointer-events-auto group-hover:opacity-100",
                  )}
                >
                  <p className="min-w-0 flex-1 truncate text-[12px] font-medium leading-snug text-white drop-shadow sm:text-[13px]">
                    {card.title}
                  </p>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Button
                      type="button"
                      size="icon"
                      data-select-btn
                      aria-label={
                        isSelected
                          ? `取消选择 ${card.title}`
                          : `选择 ${card.title}`
                      }
                      title={isSelected ? "取消选择" : "选择模板"}
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (isSelected) clearSelected();
                        else selectTemplate(card);
                      }}
                      className={cn(
                        "h-8 w-8 rounded-full shadow-md hover:scale-105",
                        isSelected
                          ? "bg-[#e8b84a] text-white hover:bg-[#e8b84a]"
                          : "bg-white text-[#1c1917] hover:bg-white",
                      )}
                    >
                      <Check className="size-[15px]" strokeWidth={2.5} />
                    </Button>
                    <Button
                      type="button"
                      size="icon"
                      data-preview-btn
                      aria-label={`预览 ${card.title}`}
                      title="预览"
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation();
                        openViewer(card);
                      }}
                      className="h-8 w-8 rounded-full bg-white text-[#1c1917] shadow-md hover:scale-105 hover:bg-white"
                    >
                      <Eye className="size-[15px]" />
                    </Button>
                  </div>
                </div>
              </div>
              );
            })}
          </div>
        )}
      </div>

      <div
        data-dock
        className="pointer-events-none absolute inset-x-0 bottom-0 z-30 flex flex-col items-center px-3 pb-4 pt-16 sm:pb-5"
        style={{
          background:
            "linear-gradient(to top, rgba(12,11,10,0.92) 0%, rgba(12,11,10,0.55) 45%, transparent 100%)",
        }}
      >
        <div className="pointer-events-auto flex w-full max-w-[720px] flex-col gap-3">
          {selected ? (
            <div className="flex items-center gap-3 rounded-2xl bg-[#252320]/95 px-3 py-2.5 shadow-[0_12px_40px_rgba(0,0,0,0.45)] backdrop-blur-md ring-1 ring-black/40">
              <img
                src={selected.cover}
                alt=""
                className="h-11 w-[78px] shrink-0 rounded-md object-cover"
              />
              <p className="min-w-0 flex-1 truncate text-[13px] font-medium leading-snug text-white">
                已选择「{selected.title}」模板
              </p>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                aria-label="取消选择"
                onClick={clearSelected}
                className="h-8 w-8 shrink-0 rounded-full text-white/70 hover:bg-white/10 hover:text-white"
              >
                <X className="size-4" />
              </Button>
            </div>
          ) : null}

          <div
            className={cn(
              "flex gap-2 rounded-2xl border border-white/10 bg-[#1a1917]/92 p-2 shadow-[0_12px_40px_rgba(0,0,0,0.45)] backdrop-blur-md transition-[align-items] duration-300",
              promptFocused ? "items-start" : "items-center",
            )}
          >
            <div
              className={cn(
                "flex min-w-0 flex-1 gap-2.5 rounded-xl px-3.5 py-2.5 transition-[align-items] duration-300",
                promptFocused ? "items-start" : "items-center",
              )}
            >
              <Search
                className={cn(
                  "size-[18px] shrink-0 text-white/35 transition-[margin] duration-300",
                  promptFocused && "mt-1",
                )}
                aria-hidden
              />
              <Textarea
                value={prompt}
                rows={1}
                onChange={(e) => setPrompt(e.target.value)}
                onFocus={() => setPromptFocused(true)}
                onBlur={() => setPromptFocused(false)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void startGenerate();
                  }
                }}
                placeholder={
                  selected
                    ? `基于「${selected.title}」开始创作…`
                    : "先选择模板，再描述你想做的 PPT"
                }
                className={cn(
                  "min-h-0 min-w-0 flex-1 resize-none border-0 bg-transparent p-0 text-[15px] leading-6 text-white/90 shadow-none placeholder:text-white/35 focus-visible:ring-0",
                  "transition-[height,max-height] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
                  promptFocused
                    ? "h-[9rem] max-h-[9rem] overflow-y-auto"
                    : "h-6 max-h-6 overflow-hidden",
                )}
              />
            </div>
            <div
              className={cn(
                "flex shrink-0 items-center gap-1.5",
                promptFocused && "mt-1.5",
              )}
            >
              <button
                type="button"
                disabled={inspiring || generating}
                onClick={() => void discoverInspire()}
                title="用 AI 写一段创作要求"
                className="flex h-auto items-center gap-1.5 rounded-full bg-white/8 px-3 py-2.5 text-sm font-medium text-white/80 outline-none ring-1 ring-white/10 transition hover:bg-white/12 hover:text-white focus-visible:ring-2 focus-visible:ring-white/35 disabled:opacity-60"
              >
                {inspiring ? (
                  <Loader2 className="size-3.5 shrink-0 animate-spin" />
                ) : (
                  <MousePointerClick className="size-3.5 shrink-0" />
                )}
                {inspiring ? "…" : "发现灵感"}
              </button>
              <GenerateCta
                generating={generating}
                inspiring={inspiring}
                hasTemplate={Boolean(selected)}
                hasPrompt={Boolean(prompt.trim())}
                onClick={() => void startGenerate()}
              />
            </div>
          </div>

          <div className="flex gap-2 overflow-x-auto pb-0.5 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {filters.map((item) => {
              const activeChip = filter === item.id;
              return (
                <Button
                  key={item.id}
                  type="button"
                  size="sm"
                  onClick={() => setFilter(item.id)}
                  className={cn(
                    "h-auto shrink-0 rounded-full px-3 py-1.5 text-xs shadow-none",
                    activeChip
                      ? "bg-white text-[#121110] hover:bg-white/90"
                      : "bg-white/8 text-white/70 ring-1 ring-white/10 hover:bg-white/12 hover:text-white",
                  )}
                >
                  {item.label}
                </Button>
              );
            })}
          </div>
        </div>
      </div>

      <div
        data-dock
        className="absolute bottom-5 right-4 z-30 flex items-center gap-1 rounded-full border border-white/10 bg-[#1a1917]/9 px-1.5 py-1 text-xs text-white/75 shadow-lg backdrop-blur sm:bottom-6 sm:right-6"
      >
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label="缩小"
          onClick={() => bumpZoom(-0.1)}
          className="h-7 w-7 rounded-full text-white/75 hover:bg-white/10 hover:text-white"
        >
          <Minus className="size-3.5" />
        </Button>
        <span className="min-w-[3rem] text-center tabular-nums">
          {Math.round(zoom * 100)}%
        </span>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label="放大"
          onClick={() => bumpZoom(0.1)}
          className="h-7 w-7 rounded-full text-white/75 hover:bg-white/10 hover:text-white"
        >
          <Plus className="size-3.5" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label="重置视图"
          onClick={resetView}
          className="ml-0.5 h-7 w-7 rounded-full text-white/75 hover:bg-white/10 hover:text-white"
          title="重置"
        >
          <RotateCcw className="size-3.5" />
        </Button>
      </div>

      {active ? (
        <div
          className="fixed inset-0 z-50 flex flex-col bg-[#0e0d0c]/88 text-white backdrop-blur-md"
          role="dialog"
          aria-modal="true"
          aria-label={active.title}
          style={{
            animation: viewerClosing
              ? "galleryPreviewFadeOut 200ms ease-in both"
              : "galleryPreviewFade 220ms ease-out both",
          }}
          onAnimationEnd={(e) => {
            if (e.target !== e.currentTarget) return;
            if (viewerClosing) finishCloseViewer();
          }}
        >
          <style>{`
            @keyframes galleryPreviewFade {
              from { opacity: 0; }
              to { opacity: 1; }
            }
            @keyframes galleryPreviewFadeOut {
              from { opacity: 1; }
              to { opacity: 0; }
            }
            @keyframes galleryPreviewRise {
              from { opacity: 0; transform: translateY(18px) scale(0.985); }
              to { opacity: 1; transform: none; }
            }
            @keyframes galleryPreviewSink {
              from { opacity: 1; transform: none; }
              to { opacity: 0; transform: translateY(14px) scale(0.985); }
            }
          `}</style>

          {/* Header — 缩略图 / 标题副标题 / 按钮顶部对齐 */}
          <div
            className="flex shrink-0 items-start justify-between gap-4 px-4 py-3 sm:px-6 sm:py-4"
            style={{
              animation: viewerClosing
                ? "galleryPreviewSink 180ms ease-in both"
                : "galleryPreviewRise 280ms cubic-bezier(0.22,1,0.36,1) both",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex min-w-0 flex-1 items-start gap-3">
              <img
                src={active.cover}
                alt=""
                className="h-12 w-[85px] shrink-0 rounded-md object-cover ring-1 ring-white/15 sm:h-14 sm:w-[100px]"
              />
              <div className="min-w-0 flex-1 pt-0">
                <h2 className="truncate text-[15px] font-semibold leading-snug tracking-tight text-white sm:text-base">
                  {active.title}
                </h2>
                {active.description ? (
                  <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-white/50">
                    {active.description}
                  </p>
                ) : (
                  <p className="mt-1 text-xs text-white/40">
                    点击下方缩略图或方向键翻页
                  </p>
                )}
              </div>
            </div>

            <div className="flex shrink-0 items-start gap-2">
              <Button
                type="button"
                aria-label={
                  selected?.id === active.id
                    ? `取消选择 ${active.title}`
                    : `选择 ${active.title}`
                }
                title={
                  selected?.id === active.id ? "取消选择" : "选择模板"
                }
                onClick={() => {
                  if (selected?.id === active.id) {
                    clearSelected();
                    return;
                  }
                  selectTemplate(active);
                  closeViewer();
                }}
                className={cn(
                  "h-9 gap-1.5 rounded-full px-4 text-xs font-medium shadow-md transition-[transform,background-color,color] hover:scale-[1.03] focus-visible:ring-0 sm:text-sm",
                  selected?.id === active.id
                    ? "bg-[#e8b84a] text-white hover:bg-[#e8b84a]"
                    : "bg-white text-[#1c1917] hover:bg-white",
                )}
              >
                <Check className="size-3.5" strokeWidth={2.5} />
                {selected?.id === active.id ? "已选择" : "使用该模板"}
              </Button>
              <Button
                type="button"
                size="icon"
                aria-label="关闭"
                onClick={closeViewer}
                className="h-9 w-9 rounded-full bg-white/8 text-white/80 hover:bg-white/14 hover:text-white focus-visible:ring-0"
              >
                <X className="size-4" />
              </Button>
            </div>
          </div>

          {/* Main stage — 点空白关闭 */}
          <div
            className="relative flex min-h-0 flex-1 items-center justify-center px-4 sm:px-20"
            style={{
              animation: viewerClosing
                ? "galleryPreviewSink 200ms ease-in both"
                : "galleryPreviewRise 320ms cubic-bezier(0.22,1,0.36,1) 40ms both",
            }}
            onClick={(e) => {
              if (e.target === e.currentTarget) closeViewer();
            }}
          >
            <div
              className="absolute left-3 top-1/2 z-10 -translate-y-1/2 sm:left-6"
              onClick={(e) => e.stopPropagation()}
              onPointerDown={(e) => e.stopPropagation()}
            >
              <Button
                type="button"
                size="icon"
                aria-label="上一页"
                disabled={pageIndex <= 0}
                onClick={() => step(-1)}
                className="h-11 w-11 rounded-full bg-black/45 text-white/90 backdrop-blur hover:bg-black/55 hover:text-white focus-visible:ring-0 disabled:pointer-events-none disabled:opacity-25"
              >
                <ChevronLeft className="size-6" strokeWidth={2.5} />
              </Button>
            </div>

            <div
              className="relative max-h-full w-full max-w-[1100px]"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="relative aspect-video overflow-hidden rounded-xl bg-[#1a1917] shadow-[0_24px_80px_rgba(0,0,0,0.55)] ring-1 ring-white/10">
                {currentPageSrc ? (
                  <PreviewCrossfade
                    key={active?.id || "preview"}
                    src={currentPageSrc}
                    alt={`${active.title} 第 ${pageIndex + 1} 页`}
                  />
                ) : (
                  <div className="flex h-full items-center justify-center">
                    <Loader2 className="size-8 animate-spin text-white/80" />
                  </div>
                )}
              </div>
              <div className="pointer-events-none absolute bottom-3 right-3 rounded-md bg-black/55 px-2 py-0.5 text-[11px] tabular-nums text-white/85 backdrop-blur">
                {pageIndex + 1} / {pageCount}
              </div>
            </div>

            <div
              className="absolute right-3 top-1/2 z-10 -translate-y-1/2 sm:right-6"
              onClick={(e) => e.stopPropagation()}
              onPointerDown={(e) => e.stopPropagation()}
            >
              <Button
                type="button"
                size="icon"
                aria-label="下一页"
                disabled={pageIndex >= pageCount - 1}
                onClick={() => step(1)}
                className="h-11 w-11 rounded-full bg-black/45 text-white/90 backdrop-blur hover:bg-black/55 hover:text-white focus-visible:ring-0 disabled:pointer-events-none disabled:opacity-25"
              >
                <ChevronRight className="size-6" strokeWidth={2.5} />
              </Button>
            </div>
          </div>

          {/* Thumbnail strip */}
          <div
            className="relative shrink-0 px-4 pb-6 pt-4 sm:px-6 sm:pb-7"
            style={{
              animation: viewerClosing
                ? "galleryPreviewSink 200ms ease-in both"
                : "galleryPreviewRise 340ms cubic-bezier(0.22,1,0.36,1) 70ms both",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex w-full items-center gap-2">
              <Button
                type="button"
                size="icon"
                aria-label="向左滚动缩略图"
                onClick={() => scrollThumbs(-1)}
                className="hidden h-10 w-10 shrink-0 rounded-full bg-white/8 text-white/70 ring-1 ring-white/10 hover:bg-white/12 hover:text-white focus-visible:ring-0 sm:flex"
              >
                <ChevronLeft className="size-5" strokeWidth={2.5} />
              </Button>
              <div
                ref={thumbStripRef}
                className="flex min-w-0 flex-1 gap-3 overflow-x-auto scroll-smooth px-1 py-2.5 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
              >
                {pages.map((src, index) => {
                  const selected = index === pageIndex;
                  const loaded = Boolean(thumbLoaded[src]);
                  const markThumbLoaded = () =>
                    setThumbLoaded((prev) =>
                      prev[src] ? prev : { ...prev, [src]: true },
                    );
                  return (
                    <Button
                      key={`${src}-${index}`}
                      type="button"
                      onClick={() => setPageIndex(index)}
                      className={cn(
                        "relative h-auto shrink-0 overflow-hidden rounded-lg bg-[#1a1917] p-0 shadow-none transition-[opacity,filter] duration-200 hover:bg-[#1a1917] focus-visible:ring-0 focus-visible:outline-none",
                        selected
                          ? "opacity-100 ring-2 ring-white ring-offset-2 ring-offset-[#0c0b0a]"
                          : "opacity-40 ring-1 ring-white/10 hover:opacity-65",
                      )}
                    >
                      {!loaded ? (
                        <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#1a1917]">
                          <Loader2 className="size-5 animate-spin text-white/70 sm:size-6" />
                        </div>
                      ) : null}
                      <img
                        src={src}
                        alt={`第 ${index + 1} 页`}
                        className={cn(
                          "h-[96px] w-[170px] object-cover transition-opacity duration-200 sm:h-[112px] sm:w-[200px]",
                          loaded ? "opacity-100" : "opacity-0",
                        )}
                        ref={(el) => {
                          if (el?.complete && el.naturalWidth > 0) markThumbLoaded();
                        }}
                        onLoad={markThumbLoaded}
                        onError={markThumbLoaded}
                      />
                      <span className="absolute bottom-1 left-1 z-20 rounded bg-black/55 px-1.5 py-px text-[10px] tabular-nums text-white/90">
                        {index + 1}
                      </span>
                    </Button>
                  );
                })}
              </div>
              <Button
                type="button"
                size="icon"
                aria-label="向右滚动缩略图"
                onClick={() => scrollThumbs(1)}
                className="hidden h-10 w-10 shrink-0 rounded-full bg-white/8 text-white/70 ring-1 ring-white/10 hover:bg-white/12 hover:text-white focus-visible:ring-0 sm:flex"
              >
                <ChevronRight className="size-5" strokeWidth={2.5} />
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
