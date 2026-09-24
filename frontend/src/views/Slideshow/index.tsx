import {
  fullscreenStore,
  pageActiveStore,
  pptStore,
  useFullscreenStore,
  usePPTStore,
} from "@/store";
import { useMemoizedFn } from "ahooks";
import { useEffect, useRef, useState, type FC } from "react";
import screenfull from "screenfull";
import { Canvas } from "../Canvas";

/**
 * 全屏幻灯片组件
 * 用于演示模式的全屏播放，与 Preview 组件完全独立
 */
const SlideshowComponent: FC = () => {
  // 使用 Zustand hooks 订阅状态变化，确保组件能够响应状态更新
  const pages = usePPTStore((state) => state.pages);
  const currentPageId = useFullscreenStore((state) => state.currentSlidePageId);
  const containerRef = useRef<HTMLDivElement>(null);
  const [isFullscreenReady, setIsFullscreenReady] = useState(false);

  // 获取当前页面索引
  const currentPageIndex = pages.findIndex((page) => page.id === currentPageId);
  const currentPage = pages[currentPageIndex];

  // 上一页
  const handlePrevPage = useMemoizedFn(() => {
    const prevPageId = pageActiveStore.goToPrevPage();
    if (prevPageId) {
      fullscreenStore.setCurrentSlidePageId(prevPageId);
    }
  });

  // 下一页
  const handleNextPage = useMemoizedFn(() => {
    const nextPageId = pageActiveStore.goToNextPage();
    if (nextPageId) {
      fullscreenStore.setCurrentSlidePageId(nextPageId);
    }
  });

  // 退出全屏
  const handleExitFullscreen = useMemoizedFn(() => {
    // 先退出浏览器全屏
    if (screenfull.isEnabled && screenfull.isFullscreen) {
      screenfull.exit();
    }

    // 退出我们的全屏模式
    fullscreenStore.exitFullscreen();

    // 退出时同步更新编辑模式的当前页
    if (currentPageId) {
      pageActiveStore.setPageActive(currentPageId);
    }
  });

  // 同步 pageActiveStore 到当前全屏页面的 id
  useEffect(() => {
    if (currentPageId) {
      pageActiveStore.setPageActive(currentPageId);
    }
  }, [currentPageId]);

  // 进入浏览器全屏
  useEffect(() => {
    if (!screenfull.isEnabled || !containerRef.current) {
      // 如果不支持全屏，直接显示（降级方案）
      setIsFullscreenReady(true);
      return;
    }

    // 请求浏览器全屏
    const requestFullscreen = async () => {
      try {
        await screenfull.request(containerRef.current!);
        // 全屏成功后再显示内容
        setIsFullscreenReady(true);
      } catch (error) {
        console.error("进入全屏失败:", error);
        // 失败也显示内容（降级方案）
        setIsFullscreenReady(true);
      }
    };

    requestFullscreen();

    return () => {
      // 组件卸载时退出浏览器全屏
      if (screenfull.isEnabled && screenfull.isFullscreen) {
        screenfull.exit();
      }
    };
  }, []);

  const keyboardToggle = pptStore.getKeyboardToggle();

  // 键盘导航
  useEffect(() => {
    if (!keyboardToggle) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      switch (e.key) {
        case "ArrowLeft":
          e.preventDefault(); // 防止空格键滚动页面
          handlePrevPage();
          break;
        case "ArrowRight":
          e.preventDefault(); // 防止空格键滚动页面
          handleNextPage();
          break;
        case "Escape":
          handleExitFullscreen();
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    handlePrevPage,
    handleNextPage,
    handleExitFullscreen,
    pages,
    keyboardToggle,
  ]);

  // 监听浏览器全屏状态变化（用户按 F11 或 ESC）
  useEffect(() => {
    if (!screenfull.isEnabled) return;

    const handleFullscreenChange = () => {
      // 如果用户退出了浏览器全屏，也退出我们的全屏模式
      if (!screenfull.isFullscreen) {
        fullscreenStore.exitFullscreen();
        // 同步更新编辑模式的当前页
        if (currentPageId) {
          pageActiveStore.setPageActive(currentPageId);
        }
      }
    };

    screenfull.on("change", handleFullscreenChange);

    return () => {
      screenfull.off("change", handleFullscreenChange);
    };
  }, [currentPageId]);

  if (!currentPage) {
    return null;
  }

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 bg-black z-[9999] flex items-center justify-center"
      style={{
        // 在全屏准备好之前，将元素移到视图外避免闪烁
        transform: isFullscreenReady ? "none" : "translateY(-200vh)",
        opacity: isFullscreenReady ? 1 : 0,
        transition: isFullscreenReady ? "opacity 0.3s ease-in" : "none",
      }}
    >
      {/* Canvas 画布 - 使用 play 模式 */}
      <Canvas mode="play" page={currentPage} />
    </div>
  );
};

export const Slideshow: FC = SlideshowComponent;
