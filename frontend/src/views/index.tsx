import { GlobalContextMenu } from "@/components/GlobalContextMenu";
import { SideInspector } from "@/components/SideInspector";
import { useDisplayStatusStore, useFullscreenStore } from "@/store";
import { useEffect, useRef, type CSSProperties } from "react";
import { Canvas } from "./Canvas";
import { Footer } from "./Footer";
import { Grid } from "./Grid";
import { Header } from "./Header";
import { Menu } from "./Menu";
import { Preview } from "./Preview";
import { Slideshow } from "./Slideshow";

const DEFAULT_PREVIEW_WIDTH = 230;

const meshBaseStyle: CSSProperties = {
  background: "var(--app-mesh-base)",
};

const blobBaseClass =
  "absolute rounded-full blur-[90px] will-change-transform [transform:translateZ(0)]";

const glassVeilStyle: CSSProperties = {
  background: "var(--app-glass-veil)",
};

const glassPanelClass =
  "box-border overflow-hidden border border-chrome-border bg-chrome-panel shadow-[var(--panel-shadow)] backdrop-blur-[22px] backdrop-saturate-[1.25]";

const canvasPaneClass =
  "flex flex-col flex-1 min-h-0 overflow-hidden rounded-xl border border-[var(--canvas-pane-border)] bg-[var(--canvas-pane-bg)] shadow-[var(--canvas-pane-shadow)] backdrop-blur-[12px] backdrop-saturate-[1.1] p-0";

export default function Index() {
  const displayStatus = useDisplayStatusStore((state) => state.displayStatus);
  const isFullscreen = useFullscreenStore((state) => state.isFullscreen);
  const previewPanelRef = useRef<HTMLDivElement>(null);

  // 同步预览面板宽度到 CSS 变量，供 Header 左侧对齐
  useEffect(() => {
    const setWidth = (width: number) => {
      document.documentElement.style.setProperty(
        "--preview-pane-width",
        `${Math.max(0, Math.round(width))}px`
      );
    };

    if (displayStatus !== "default") {
      setWidth(DEFAULT_PREVIEW_WIDTH);
      return;
    }

    const el = previewPanelRef.current;
    if (!el) {
      setWidth(DEFAULT_PREVIEW_WIDTH);
      return;
    }

    setWidth(el.getBoundingClientRect().width);

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setWidth(entry.contentRect.width);
    });
    resizeObserver.observe(el);

    return () => {
      resizeObserver.disconnect();
    };
  }, [displayStatus, isFullscreen]);

  return (
    <div className="relative isolate max-w-[100vw] max-h-[100vh] w-[100vw] h-[100vh] flex flex-col overflow-hidden bg-[var(--app-bg)]">
      {/* Apple 风格 Mesh Gradient 氛围背景（纯装饰，无内容） */}
      <div
        className="absolute inset-0 z-0 overflow-hidden pointer-events-none"
        aria-hidden="true"
      >
        <div className="absolute inset-0" style={meshBaseStyle} />
        <div
          className={`${blobBaseClass} w-[70vw] h-[70vw] max-w-[900px] max-h-[900px] -top-[28%] -right-[22%] opacity-95 dark:opacity-40`}
          style={{
            background:
              "radial-gradient(circle at 40% 45%, rgba(255,186,150,0.7) 0%, rgba(255,210,180,0.45) 28%, rgba(255,230,210,0.18) 55%, transparent 72%)",
          }}
        />
        <div
          className={`${blobBaseClass} w-[65vw] h-[65vw] max-w-[820px] max-h-[820px] -bottom-[30%] -left-[20%] opacity-90 dark:opacity-35`}
          style={{
            background:
              "radial-gradient(circle at 55% 40%, rgba(255,198,160,0.65) 0%, rgba(245,220,195,0.4) 32%, rgba(255,240,220,0.15) 58%, transparent 75%)",
          }}
        />
        <div
          className={`${blobBaseClass} w-[50vw] h-[50vw] max-w-[640px] max-h-[640px] -top-[18%] -left-[12%] opacity-75 mix-blend-soft-light dark:opacity-30 dark:mix-blend-normal`}
          style={{
            background:
              "radial-gradient(circle at 50% 50%, rgba(220,225,230,0.55) 0%, rgba(235,238,240,0.28) 40%, transparent 70%)",
          }}
        />
        <div
          className="absolute w-[55vw] h-[45vw] max-w-[720px] max-h-[560px] top-[28%] left-[22%] rounded-full blur-[100px] opacity-80 will-change-transform dark:opacity-20"
          style={{
            background:
              "radial-gradient(ellipse at 50% 50%, rgba(255,255,255,0.75) 0%, rgba(245,242,238,0.35) 45%, transparent 72%)",
          }}
        />
        <div
          className={`${blobBaseClass} w-[40vw] h-[40vw] max-w-[520px] max-h-[520px] -bottom-[8%] right-[5%] opacity-70 dark:opacity-25`}
          style={{
            background:
              "radial-gradient(circle at 50% 50%, rgba(255,224,170,0.4) 0%, rgba(255,236,210,0.18) 40%, transparent 70%)",
          }}
        />
        <div
          className="absolute inset-0 backdrop-blur-[40px] backdrop-saturate-[1.2]"
          style={glassVeilStyle}
        />
      </div>

      {isFullscreen && <Slideshow />}

      {!isFullscreen && (
        <div className="relative z-[1] flex flex-col flex-1 min-h-0 h-full w-full">
          <GlobalContextMenu />
          <Header />
          {displayStatus === "default" && (
            <div
              id="main-container"
              className="flex flex-1 min-h-0 flex-row items-stretch gap-[15px] mt-[10px] mb-0 bg-transparent w-[calc(100%-40px)] mx-[20px]"
            >
              <div
                ref={previewPanelRef}
                className={`${glassPanelClass} flex-none w-[230px] min-w-[200px] max-w-[300px] h-full min-h-0 rounded-[14px]`}
              >
                <Preview />
              </div>
              <div className="flex flex-1 min-w-0 flex-col h-full min-h-0 gap-[15px] overflow-hidden">
                <Menu />
                <div className="flex flex-1 min-h-0 min-w-0 gap-[15px] overflow-hidden">
                  <div className={`${canvasPaneClass} flex-1`}>
                    <Canvas />
                  </div>
                  <SideInspector />
                </div>
              </div>
            </div>
          )}
          {displayStatus === "grid" && (
            <div className="flex-1 min-h-0 flex flex-col mt-[8px] w-[calc(100%-40px)] mx-[20px] gap-[8px]">
              <Menu />
              <div className="flex-1 min-h-0">
                <Grid />
              </div>
            </div>
          )}
          <Footer />
        </div>
      )}
    </div>
  );
}
