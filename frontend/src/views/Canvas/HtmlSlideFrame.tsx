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
import { usePPTStore } from "@/store";
import type { Page } from "@/store/ppt";
import {
  type CSSProperties,
  type FC,
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

/**
 * 用项目内路由 /embed/slide 嵌入幻灯片页（不用 srcdoc）。
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
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const bridgeRef = useRef<SlideEditorParentBridge | null>(null);
  const skipNextHtmlReloadRef = useRef(false);
  const [src, setSrc] = useState("");
  const [editorReady, setEditorReady] = useState(false);
  const [hoverRect, setHoverRect] = useState<SlideRect | null>(null);
  const [selected, setSelected] = useState<SelectedElementInfo | null>(null);
  const [multiSelected, setMultiSelected] = useState<SelectedElementInfo[]>(
    [],
  );
  const setPageHtml = usePPTStore((s) => s.setPageHtml);
  const useDesign = fit === "design";
  const scale = useDesign ? 1 : SLIDE_HTML_SCALE;
  const transformingRef = useRef(false);

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

  // 切换 / 挂载页面：申请租约并立即加载（layout 阶段，赶在 iframe 请求前）
  useLayoutEffect(() => {
    const token = acquireSlideEmbedAccess(page.id, page.html);
    tokenRef.current = token;
    const next = buildSlideEmbedSrc(page.id, page.html, token, {
      edit: editable,
    });
    lastSrcRef.current = next;
    setSrc(next);
    setHoverRect(null);
    setSelected(null);
    setMultiSelected([]);
    setEditorReady(false);
    transformingRef.current = false;

    return () => {
      releaseSlideEmbedAccess(page.id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page.id, editable]);

  // 同页 HTML 变更：防抖刷新（本帧写回 store 时跳过，避免打断编辑）
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
      lastSrcRef.current = next;
      setSrc(next);
      setHoverRect(null);
      setSelected(null);
      setMultiSelected([]);
      setEditorReady(false);
    }, reloadDebounceMs);

    return () => window.clearTimeout(timer);
  }, [page.html, page.id, reloadDebounceMs, editable]);

  // Parent bridge for editable mode
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
        if (info) setMultiSelected([]);
      },
      onMultiSelect: (els) => {
        if (transformingRef.current) return;
        setMultiSelected(els);
      },
      onContentChanged: (html) => {
        void persistHtml(html);
      },
    });
    bridgeRef.current = bridge;
    setEditorReady(false);

    return () => {
      bridge.destroy();
      if (bridgeRef.current === bridge) bridgeRef.current = null;
      setEditorReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editable, page.id]);

  useEffect(() => {
    if (!editable || !bridgeRef.current) return;
    bridgeRef.current.setIframe(iframeRef.current);
  }, [editable, src, editorReady]);

  const handleIframeLoad = () => {
    if (!editable || !bridgeRef.current) return;
    bridgeRef.current.setIframe(iframeRef.current);
    void bridgeRef.current.enterSelectionMode().catch(() => {
      /* runtime not ready yet — EDITOR_READY will retry */
    });
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
    // Click-without-drag (text edit): just reopen selection events
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

  return (
    <div
      className={className}
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        ...style,
      }}
    >
      {src ? (
        <iframe
          ref={iframeRef}
          title={title || `slide-${page.id}`}
          src={src}
          sandbox="allow-scripts allow-same-origin"
          className={pointerEventsNone ? "pointer-events-none" : undefined}
          onLoad={editable ? handleIframeLoad : undefined}
          style={{
            border: 0,
            display: "block",
            width: SLIDE_HTML_WIDTH,
            height: SLIDE_HTML_HEIGHT,
            transform: useDesign ? undefined : `scale(${SLIDE_HTML_SCALE})`,
            transformOrigin: "top left",
            background: "transparent",
          }}
        />
      ) : null}
      {editable && !useDesign && (
        <div
          className="absolute top-0 left-0 overflow-visible"
          style={{
            width: SLIDE_HTML_WIDTH * scale,
            height: SLIDE_HTML_HEIGHT * scale,
            pointerEvents: "none",
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
