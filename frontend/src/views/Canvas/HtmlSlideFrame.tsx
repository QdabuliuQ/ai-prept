import {
  SLIDE_HTML_HEIGHT,
  SLIDE_HTML_SCALE,
  SLIDE_HTML_WIDTH,
} from "@/utils/slideHtml";
import {
  acquireSlideEmbedAccess,
  buildSlideEmbedSrc,
  releaseSlideEmbedAccess,
  touchSlideEmbedHtml,
} from "@/utils/slideEmbedBridge";
import {
  SlideEditorParentBridge,
  type SelectedElementInfo,
  type SlideRect,
} from "@/slide-editor/parent/SlideEditorParentBridge";
import { SelectionOverlay } from "@/views/Canvas/SelectionOverlay";
import {
  useMenuActiveStore,
  usePPTStore,
  useSlideSelectionStore,
} from "@/store";
import type { Page } from "@/store/ppt";
import { getCachedThumbnail } from "@/utils/pageThumbnail";
import {
  type CSSProperties,
  type FC,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

export type HtmlSlideFrameProps = {
  page: Page;
  /** 编辑态建议 true，避免 iframe 抢走画布右键/拖拽；轻量元素编辑时应为 false */
  pointerEventsNone?: boolean;
  className?: string;
  style?: CSSProperties;
  title?: string;
  /**
   * canvas：1920 缩放进编辑器画布（默认，CSS transform）
   * design：按 1920×1080 原尺寸渲染（缩略图/导出捕获用）
   */
  fit?: "canvas" | "design";
  /** 同页 HTML 变更后刷新 iframe 的防抖（ms）；切换 pageId 立即刷新 */
  reloadDebounceMs?: number;
  /** 启用 iframe 内 ElementSelector + 父页 Overlay（仅编辑画布） */
  editable?: boolean;
};

type Slot = 0 | 1;

/**
 * 用项目内路由 /embed/slide 嵌入幻灯片页（不用 srcdoc）。
 * 双缓冲：新页在背后加载完再切前景，并用缩略图垫底，减轻切页闪烁。
 */
export const HtmlSlideFrame: FC<HtmlSlideFrameProps> = ({
  page,
  pointerEventsNone = false,
  className,
  style,
  title,
  fit = "canvas",
  reloadDebounceMs = 300,
  editable = false,
}) => {
  const tokenRef = useRef("");
  const lastSrcRef = useRef("");
  const iframeRefs = useRef<[HTMLIFrameElement | null, HTMLIFrameElement | null]>([
    null,
    null,
  ]);
  const bridgeRef = useRef<SlideEditorParentBridge | null>(null);
  const skipNextHtmlReloadRef = useRef(false);
  const pendingSlotRef = useRef<Slot | null>(null);
  const pendingSrcRef = useRef("");
  const activeSlotRef = useRef<Slot>(0);
  const paintedRef = useRef(false);

  const [slotSrc, setSlotSrc] = useState<[string, string]>(["", ""]);
  const [activeSlot, setActiveSlot] = useState<Slot>(0);
  const [painted, setPainted] = useState(false);
  const [coverUrl, setCoverUrl] = useState<string | null>(null);
  const [editorReady, setEditorReady] = useState(false);
  const [hoverRect, setHoverRect] = useState<SlideRect | null>(null);
  const [selected, setSelected] = useState<SelectedElementInfo | null>(null);
  const [multiSelected, setMultiSelected] = useState<SelectedElementInfo[]>(
    [],
  );

  const setPageHtml = usePPTStore((s) => s.setPageHtml);
  const setSlideSelected = useSlideSelectionStore((s) => s.setSelected);
  const clearSlideSelection = useSlideSelectionStore((s) => s.clearSelection);
  const bindTextApi = useSlideSelectionStore((s) => s.bindTextApi);
  const setActiveMenu = useMenuActiveStore((s) => s.setActiveMenu);
  const useDesign = fit === "design";
  const scale = useDesign ? 1 : SLIDE_HTML_SCALE;
  const transformingRef = useRef(false);

  activeSlotRef.current = activeSlot;
  paintedRef.current = painted;

  const bindActiveIframe = useCallback(() => {
    if (!editable || !bridgeRef.current) return;
    const el = iframeRefs.current[activeSlotRef.current];
    bridgeRef.current.setIframe(el);
    void bridgeRef.current.enterSelectionMode().catch(() => undefined);
  }, [editable]);

  /** 空闲槽加载 next；已有前景时不打断当前画面 */
  const pushSrc = useCallback((next: string) => {
    if (!next || next === lastSrcRef.current) return;
    lastSrcRef.current = next;

    setSlotSrc((prev) => {
      const front = activeSlotRef.current;
      const hasPaintedFront = paintedRef.current && Boolean(prev[front]);

      if (!hasPaintedFront) {
        pendingSlotRef.current = 0;
        pendingSrcRef.current = next;
        return [next, ""];
      }

      const back = (1 - front) as Slot;
      pendingSlotRef.current = back;
      pendingSrcRef.current = next;
      const nextSlots: [string, string] = [prev[0], prev[1]];
      nextSlots[back] = next;
      return nextSlots;
    });
  }, []);

  const promoteSlot = useCallback((slot: Slot) => {
    if (pendingSlotRef.current !== slot || !pendingSrcRef.current) return;
    pendingSlotRef.current = null;
    pendingSrcRef.current = "";
    setActiveSlot(slot);
    setPainted(true);
    setCoverUrl(null);
  }, []);

  const persistHtml = async (htmlFromEvent?: string) => {
    try {
      const html =
        htmlFromEvent ||
        (await bridgeRef.current?.getContent())?.html ||
        undefined;
      if (!html) return;
      skipNextHtmlReloadRef.current = true;
      setPageHtml(page.id, html);
    } catch (err) {
      console.error("[HtmlSlideFrame] persist html failed:", err);
    }
  };

  useLayoutEffect(() => {
    const token = acquireSlideEmbedAccess(page.id, page.html);
    tokenRef.current = token;
    const next = buildSlideEmbedSrc(page.id, page.html, token, {
      edit: editable,
    });

    setCoverUrl(getCachedThumbnail(page.id));
    pushSrc(next);
    setHoverRect(null);
    setSelected(null);
    setMultiSelected([]);
    setEditorReady(false);
    transformingRef.current = false;
    if (editable) clearSlideSelection();

    return () => {
      releaseSlideEmbedAccess(page.id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page.id, editable]);

  useEffect(() => {
    const token = tokenRef.current;
    if (!token) return;
    touchSlideEmbedHtml(page.id, page.html);

    if (skipNextHtmlReloadRef.current) {
      skipNextHtmlReloadRef.current = false;
      lastSrcRef.current = buildSlideEmbedSrc(page.id, page.html, token, {
        edit: editable,
      });
      return;
    }

    const next = buildSlideEmbedSrc(page.id, page.html, token, {
      edit: editable,
    });
    if (next === lastSrcRef.current) return;

    const timer = window.setTimeout(() => {
      pushSrc(next);
      setHoverRect(null);
      setSelected(null);
      setMultiSelected([]);
      setEditorReady(false);
    }, reloadDebounceMs);

    return () => window.clearTimeout(timer);
  }, [page.html, page.id, reloadDebounceMs, editable, pushSrc]);

  useEffect(() => {
    if (!editable) {
      bridgeRef.current?.destroy();
      bridgeRef.current = null;
      setEditorReady(false);
      return;
    }

    const bridge = new SlideEditorParentBridge({
      onReady: () => {
        setEditorReady(true);
        void bridge.enterSelectionMode();
      },
      onHover: setHoverRect,
      onSelect: (info) => {
        if (transformingRef.current) return;
        setSelected(info);
        setSlideSelected(info);
        if (info) {
          setMultiSelected([]);
          setActiveMenu("edit");
        }
      },
      onMultiSelect: (els) => {
        if (transformingRef.current) return;
        setMultiSelected(els);
        setSlideSelected(null);
        if (els.length > 0) setActiveMenu("edit");
      },
      onContentChanged: (html) => {
        void persistHtml(html);
      },
    });
    bridgeRef.current = bridge;
    setEditorReady(false);
    bridge.setIframe(iframeRefs.current[activeSlotRef.current]);

    bindTextApi({
      applyTextStyle: async (patch, target) => {
        const result = await bridge.applyTextStyle(patch, target);
        await bridge.refreshSelection().catch(() => undefined);
        if (result?.html) {
          await persistHtml(result.html);
        } else if (result?.success) {
          await persistHtml();
        }
      },
    });

    return () => {
      bindTextApi(null);
      clearSlideSelection();
      bridge.destroy();
      if (bridgeRef.current === bridge) bridgeRef.current = null;
      setEditorReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editable, page.id]);

  useEffect(() => {
    bindActiveIframe();
  }, [bindActiveIframe, activeSlot, editorReady]);

  const handleSlotLoad = (slot: Slot) => {
    promoteSlot(slot);
    if (!editable || !bridgeRef.current) return;
    // promote 后下一帧 activeSlot 才更新；若正是当前 pending 晋升目标，立刻绑
    if (pendingSlotRef.current === null) {
      bridgeRef.current.setIframe(iframeRefs.current[slot]);
      void bridgeRef.current.enterSelectionMode().catch(() => undefined);
    }
  };

  const handleTransformStart = () => {
    transformingRef.current = true;
    bridgeRef.current?.setSuppressSelectionEvents(true);
    setHoverRect(null);
  };

  const handleTransform = (
    selector: string,
    box: {
      left: number;
      top: number;
      width: number;
      height: number;
      rotation?: number;
      resize?: boolean;
    },
    editorId?: string,
  ) => {
    bridgeRef.current?.setElementTransform(selector, box, editorId);
    setSelected((prev) =>
      prev &&
      (prev.selector === selector ||
        (editorId && prev.editorId === editorId))
        ? {
            ...prev,
            rect: {
              left: box.left,
              top: box.top,
              width: box.width,
              height: box.height,
            },
            rotation: box.rotation ?? 0,
          }
        : prev,
    );
  };

  const handleTransformEnd = async (
    selector: string,
    box: {
      left: number;
      top: number;
      width: number;
      height: number;
      rotation?: number;
      resize?: boolean;
    },
    editorId?: string,
  ) => {
    if (!transformingRef.current) {
      bridgeRef.current?.setSuppressSelectionEvents(false);
      return;
    }
    bridgeRef.current?.setElementTransform(selector, box, editorId);
    try {
      await persistHtml();
      await bridgeRef.current?.refreshSelection();
    } catch (err) {
      console.error("[HtmlSlideFrame] transform end failed:", err);
    } finally {
      transformingRef.current = false;
      bridgeRef.current?.setSuppressSelectionEvents(false);
    }
  };

  const iframeBaseStyle: CSSProperties = {
    border: 0,
    display: "block",
    width: SLIDE_HTML_WIDTH,
    height: SLIDE_HTML_HEIGHT,
    transform: useDesign ? undefined : `scale(${SLIDE_HTML_SCALE})`,
    transformOrigin: "top left",
    background: "#ffffff",
    position: "absolute",
    top: 0,
    left: 0,
  };

  return (
    <div
      className={className}
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        background: "#ffffff",
        ...style,
      }}
    >
      {coverUrl ? (
        <img
          src={coverUrl}
          alt=""
          draggable={false}
          aria-hidden
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            objectFit: "fill",
            zIndex: 0,
            pointerEvents: "none",
          }}
        />
      ) : null}

      {([0, 1] as Slot[]).map((slot) => {
        const src = slotSrc[slot];
        if (!src) return null;
        const isActive = painted && slot === activeSlot;
        return (
          <iframe
            key={slot}
            ref={(el) => {
              iframeRefs.current[slot] = el;
            }}
            title={title || `slide-${page.id}-${slot}`}
            src={src}
            sandbox="allow-scripts allow-same-origin"
            className={
              pointerEventsNone || !isActive ? "pointer-events-none" : undefined
            }
            onLoad={() => handleSlotLoad(slot)}
            style={{
              ...iframeBaseStyle,
              zIndex: isActive ? 2 : 1,
              opacity: isActive ? 1 : 0,
            }}
          />
        );
      })}

      {editable && !useDesign && (
        <div
          className="absolute top-0 left-0 overflow-visible"
          style={{
            width: SLIDE_HTML_WIDTH * scale,
            height: SLIDE_HTML_HEIGHT * scale,
            pointerEvents: "none",
            zIndex: 3,
          }}
        >
          <SelectionOverlay
            scale={scale}
            hoverRect={hoverRect}
            selected={selected}
            multiSelected={multiSelected}
            onTransformStart={handleTransformStart}
            onTransform={handleTransform}
            onTransformEnd={handleTransformEnd}
          />
        </div>
      )}
    </div>
  );
};
