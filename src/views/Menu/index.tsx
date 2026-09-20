import { useMenuActiveStore } from "@/store";
import { useDebounceFn } from "ahooks";
import { OverlayScrollbarsComponent } from "overlayscrollbars-react";
import "overlayscrollbars/overlayscrollbars.css";
import { useEffect, useRef, useState, type FC } from "react";
import Panel from "./components";
import styles from "./index.module.less";
import "./overlay-scrollbar.css";

const SIDE_PADDING = 16;

export const Menu: FC = () => {
  // 使用 Zustand hook 订阅状态变化，确保组件能够响应状态更新
  const menuActive = useMenuActiveStore((state) => state.menuActive);
  const activePanelKey = menuActive as keyof typeof Panel;
  const ActivePanelComponent = Panel[activePanelKey] ?? Panel.start;

  const wrapperRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [needsScroll, setNeedsScroll] = useState(false);
  const [barWidth, setBarWidth] = useState<number | "100%">("100%");
  const [widthTransition, setWidthTransition] = useState(false);
  // 用 React state 驱动进入动画，避免 re-render 冲掉 classList 添加的 class
  const [entering, setEntering] = useState(true);
  const measuringRef = useRef(false);

  // 内容未超出可用宽度时按实际宽度展示，超出则占满并滚动
  const checkSizes = (options?: { allowTransition?: boolean }) => {
    if (!wrapperRef.current || !contentRef.current) return;

    const availableWidth = wrapperRef.current.clientWidth;
    const contentWidth = contentRef.current.scrollWidth + SIDE_PADDING * 2;

    // 切换瞬间内容尚未完成布局时跳过，避免宽度先缩后弹
    if (contentWidth <= SIDE_PADDING * 2) return;

    const overflow = contentWidth > availableWidth;
    const nextWidth: number | "100%" = overflow ? "100%" : contentWidth;

    setNeedsScroll(overflow);
    setBarWidth((prev) => {
      if (prev === nextWidth) return prev;
      if (options?.allowTransition) {
        setWidthTransition(true);
      }
      return nextWidth;
    });
  };

  // 防抖处理的 resize 事件
  const { run: debouncedCheckSizes } = useDebounceFn(
    () => checkSizes({ allowTransition: true }),
    { wait: 300 }
  );

  // 切换面板：先卸下动画 class，下一帧再挂上以重播，并在布局稳定后量宽
  useEffect(() => {
    setEntering(false);
    setWidthTransition(false);
    measuringRef.current = true;

    let cancelled = false;
    let raf2 = 0;
    const raf1 = requestAnimationFrame(() => {
      if (cancelled) return;
      setEntering(true);

      raf2 = requestAnimationFrame(() => {
        if (cancelled) return;
        checkSizes({ allowTransition: true });
        measuringRef.current = false;
      });
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      measuringRef.current = false;
    };
  }, [menuActive]);

  useEffect(() => {
    checkSizes();

    window.addEventListener("resize", debouncedCheckSizes);

    // 只监听结构变化，避免属性抖动反复触发量宽
    const observer = new MutationObserver(() => {
      if (measuringRef.current) return;
      checkSizes({ allowTransition: true });
    });
    if (contentRef.current) {
      observer.observe(contentRef.current, {
        childList: true,
        subtree: true,
      });
    }

    const resizeObserver =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            if (measuringRef.current) return;
            checkSizes({ allowTransition: true });
          })
        : null;
    if (resizeObserver && wrapperRef.current) {
      resizeObserver.observe(wrapperRef.current);
    }

    return () => {
      window.removeEventListener("resize", debouncedCheckSizes);
      observer.disconnect();
      resizeObserver?.disconnect();
    };
  }, [ActivePanelComponent, debouncedCheckSizes]);

  return (
    <div ref={wrapperRef} className="w-full shrink-0 flex justify-center">
      <div
        className={[
          styles.menuBar,
          entering ? styles.menuBarEnter : "",
          widthTransition ? styles.menuBarWidthTransition : "",
          "overflow-hidden rounded-[10px] h-[70px] max-h-[70px] min-h-[70px] z-[3] relative max-w-full",
        ]
          .filter(Boolean)
          .join(" ")}
        style={{ width: barWidth }}
      >
        <OverlayScrollbarsComponent
          className="custom-scrollbar"
          options={{
            scrollbars: {
              autoHide: "scroll",
              autoHideDelay: 1000,
            },
            overflow: {
              x: needsScroll ? "scroll" : "hidden",
              y: "hidden",
            },
          }}
          style={{
            width: "100%",
            height: "100%",
            position: "relative",
          }}
        >
          <div
            className={`h-full flex items-center ${needsScroll ? "justify-start" : "justify-center"}`}
          >
            <span
              className="inline-block h-full min-w-[16px]"
              style={{ width: SIDE_PADDING }}
            ></span>
            <div
              key={menuActive ?? "menu"}
              ref={contentRef}
              style={{ flexShrink: 0 }}
              className={`${styles.contentEnter} flex items-center gap-[2px]`}
            >
              {ActivePanelComponent ? <ActivePanelComponent /> : null}
            </div>
            <span
              className="inline-block h-full min-w-[16px]"
              style={{ width: SIDE_PADDING }}
            ></span>
          </div>
        </OverlayScrollbarsComponent>
      </div>
    </div>
  );
};
