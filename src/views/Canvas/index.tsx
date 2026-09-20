import SearchSvg from "@/assets/images/search.svg";
import { GlobalContextMenu } from "@/components";
import { CANVAS_HEIGHT, CANVAS_WIDTH } from "@/constants/canvas";
import type { MenuItem } from "@/hooks/useContextMenu";
import { textureItems } from "@/views/Menu/components/Start/texture";
import { HtmlSlideFrame } from "./HtmlSlideFrame";
import {
  contextMenuStore,
  fullscreenStore,
  menuActiveStore,
  pageActiveStore,
  pptStore,
  useCanvasZoomStore,
  useFullscreenStore,
  usePageActiveStore,
  usePPTStore,
  useRemarkEditActiveStore,
  useThemeStore,
} from "@/store";
import type { Page } from "@/store/ppt";
import { initPPTStore } from "@/utils/initStore";
import { buildBlankSlideHtml } from "@/utils/slideHtml";
import { downloadImage, exportPageAsImage } from "@/utils/tool";
import {
  Clear,
  CloseOne,
  DividingLineOne,
  Export,
  GoEnd,
  GoStart,
  GridTwo,
  Left,
  Play,
  PreviewCloseOne,
  PreviewOpen,
  Right,
  Ruler,
} from "@icon-park/react";
import Guides from "@scena/react-guides";
import { useDebounceFn, useMemoizedFn } from "ahooks";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FC,
} from "react";
import { useTranslation } from "react-i18next";
import { PreviewCanvas } from "./PreviewCanvas";
import { RemarkEdit } from "./RemarkEdit";

interface CanvasProps {
  mode?: "preview" | "play" | "edit";
  page?: Page;
  previewZoom?: number; // preview 模式下的缩放比例
}

const Component: FC<CanvasProps> = ({ mode = "edit", page, previewZoom }) => {
  const { t } = useTranslation();
  // 使用 Zustand hooks 订阅状态变化
  const pages = usePPTStore((state) => state.pages);
  const pageActive = usePageActiveStore((state) => state.pageActive);
  const horizontalLineFromStore = usePPTStore((state) => state.horizontalLine);
  const verticalLineFromStore = usePPTStore((state) => state.verticalLine);

  const containerRef = useRef<HTMLDivElement>(null);
  const fitScale = useCanvasZoomStore((state) => state.fitScale);
  const zoomPercent = useCanvasZoomStore((state) => state.zoomPercent);
  const setFitScale = useCanvasZoomStore((state) => state.setFitScale);
  // edit 模式：适配缩放 × 用户百分比；其他模式本地占位
  const scale =
    mode === "edit"
      ? Math.max(fitScale * (zoomPercent / 100), 0.1)
      : 1;
  const [, forceUpdate] = useState(0); // 用于 play 模式强制重新渲染
  const lastContainerSizeRef = useRef({ width: 0, height: 0 });
  const [showEndMessage, setShowEndMessage] = useState(false); // 是否显示结束提示
  /** 放大后拖拽平移（屏幕像素） */
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [spacePressed, setSpacePressed] = useState(false);
  const panStartRef = useRef<{
    x: number;
    y: number;
    panX: number;
    panY: number;
    pointerId: number;
  } | null>(null);
  const didPanRef = useRef(false);
  const canPanCanvas = mode === "edit" && zoomPercent > 100;

  // 计算容器适配缩放：由外部容器决定最大等比例尺寸，四周至少保留 20px
  const calculateScale = useMemoizedFn(() => {
    if (!containerRef.current || mode !== "edit") return;

    const containerRect = containerRef.current.getBoundingClientRect();
    const currentSize = {
      width: Math.round(containerRect.width),
      height: Math.round(containerRect.height),
    };

    // 检查容器尺寸是否真正变化，避免不必要的计算
    const lastSize = lastContainerSizeRef.current;
    if (
      currentSize.width === lastSize.width &&
      currentSize.height === lastSize.height
    ) {
      return;
    }

    lastContainerSizeRef.current = currentSize;

    // 上下左右各至少 20px
    const PADDING = 20;
    const availableWidth = Math.max(currentSize.width - PADDING * 2, 1);
    const availableHeight = Math.max(currentSize.height - PADDING * 2, 1);

    // 宽高分别计算，取较小值以保持 16:9 等比例，并默认放到最大
    const scaleX = availableWidth / CANVAS_WIDTH;
    const scaleY = availableHeight / CANVAS_HEIGHT;
    const newFitScale = Math.max(Math.min(scaleX, scaleY), 0.1);

    setFitScale(newFitScale);
  });

  // 初始化数据 - 只执行一次（作为备用，主要初始化在 App.tsx 中）
  useEffect(() => {
    initPPTStore();
  }, []);

  // 初始化缩放
  useEffect(() => {
    setTimeout(calculateScale, 0);
  }, [calculateScale]);

  // 缩放回到适配及以下时重置平移
  useEffect(() => {
    if (zoomPercent <= 100) {
      setPanOffset({ x: 0, y: 0 });
    }
  }, [zoomPercent]);

  // Space 进入平移模式（放大时）
  useEffect(() => {
    if (mode !== "edit") return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat) return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        (e.target as HTMLElement)?.isContentEditable
      ) {
        return;
      }
      e.preventDefault();
      setSpacePressed(true);
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === "Space") {
        setSpacePressed(false);
        setIsPanning(false);
        panStartRef.current = null;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [mode]);

  // 画布区域滚轮：向上上一页，向下下一页（固定冷却，不因持续滚动延长锁定）
  useEffect(() => {
    if (mode !== "edit") return;
    const el = containerRef.current;
    if (!el) return;

    /** 翻页后的冷却：冷却期内同向滚动忽略，到期后即使鼠标未动也可继续翻页 */
    const PAGE_COOLDOWN_MS = 320;
    let locked = false;
    let lastDirection: 1 | -1 | 0 = 0;
    let cooldownTimer: ReturnType<typeof setTimeout> | null = null;

    const armCooldown = () => {
      if (cooldownTimer) clearTimeout(cooldownTimer);
      locked = true;
      cooldownTimer = setTimeout(() => {
        locked = false;
        cooldownTimer = null;
      }, PAGE_COOLDOWN_MS);
    };

    const onWheel = (e: WheelEvent) => {
      // 保留 Ctrl/Meta + 滚轮给浏览器缩放
      if (e.ctrlKey || e.metaKey) return;
      if (Math.abs(e.deltaY) < Math.abs(e.deltaX)) return;

      e.preventDefault();

      const direction: 1 | -1 | 0 =
        e.deltaY > 0 ? 1 : e.deltaY < 0 ? -1 : 0;
      if (!direction) return;

      // 冷却期内同向滚动（含惯性）忽略；换向视为新手势，立即允许翻页
      if (locked && direction === lastDirection) return;

      lastDirection = direction;
      armCooldown();

      if (direction > 0) {
        pageActiveStore.goToNextPage();
      } else {
        pageActiveStore.goToPrevPage();
      }
      contextMenuStore.hideMenu();
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      el.removeEventListener("wheel", onWheel);
      if (cooldownTimer) clearTimeout(cooldownTimer);
    };
  }, [mode]);

  // 监听全局点击事件，关闭右键菜单
  // 注意：react-contexify 已经内置了点击外部关闭菜单的功能
  // 这里只需要同步 contextMenuStore 的状态
  useEffect(() => {
    if (mode === "preview") {
      return;
    }

    const handleDocumentClick = (e: MouseEvent) => {
      const target = e.target as Node;

      // 检查点击是否在菜单内部
      const menuElement = document.querySelector(
        '[data-contexify-root="true"]'
      );
      if (menuElement && menuElement.contains(target)) {
        // 如果点击在菜单内部，不处理
        // react-contexify 会自己处理菜单项的点击和关闭
        return;
      }

      // 如果菜单显示且点击在菜单外部，同步关闭 contextMenuStore
      // react-contexify 的 hideAll 会关闭菜单，但不会更新我们的 store
      if (contextMenuStore.isVisible()) {
        // 延迟执行，确保菜单项的 onClick 先执行
        setTimeout(() => {
          if (contextMenuStore.isVisible()) {
            contextMenuStore.hideMenu();
          }
        }, 100);
      }
    };

    // 使用较长的延迟，确保菜单项的 onClick 先执行
    document.addEventListener("click", handleDocumentClick, false);

    return () => {
      document.removeEventListener("click", handleDocumentClick, false);
    };
  }, [mode]);


  // 自动切换定时器
  const autoToggleTimerRef = useRef<NodeJS.Timeout | null>(null);

  // 切换到下一页的函数（供自动切换和点击切换共用）
  const goToNextPage = useMemoizedFn(() => {
    const pages = pptStore.getPages();
    const currentPageId = page?.id || pageActiveStore.getPageActive();
    const currentPage = page || pptStore.getActivePage(currentPageId as string);

    if (!currentPage) return;

    const currentPageIndex = pages.findIndex((p) => p.id === currentPageId);
    const isLastPage = currentPageIndex === pages.length - 1;

    // 先同步 pageActiveStore 到当前页面
    if (currentPageId) {
      pageActiveStore.setPageActive(currentPageId);
    }
    const lastPageId = pageActiveStore.getPageActive();
    const newPageId = pageActiveStore.goToNextPage();

    // 如果无法切换到下一页（已经是最后一页），显示结束提示
    if (isLastPage && lastPageId === newPageId) {
      setShowEndMessage(true);
      return;
    }

    // 如果可以切换，切换到下一页
    if (lastPageId !== newPageId && newPageId) {
      fullscreenStore.enterFullscreen(newPageId);
      setShowEndMessage(false);
    }
  });

  // 监听页面变化，重置结束提示状态和动画结束标志，设置自动切换定时器
  useEffect(() => {
    if (mode === "play") {
      setShowEndMessage(false);
      animationEndHandledRef.current = false;

      // 清除之前的自动切换定时器
      if (autoToggleTimerRef.current) {
        clearTimeout(autoToggleTimerRef.current);
        autoToggleTimerRef.current = null;
      }

      // 检查是否开启自动切换
      const currentPageId = page?.id || pageActiveStore.getPageActive();
      const currentPage =
        page || (currentPageId ? pptStore.getActivePage(currentPageId) : null);

      if (currentPage) {
        const { autoToggle = false, autoToggleTime = 5 } = currentPage as any;

        if (autoToggle && autoToggleTime > 0) {
          // 设置自动切换定时器（时间单位：秒）
          autoToggleTimerRef.current = setTimeout(() => {
            goToNextPage();
          }, autoToggleTime * 1000);
        }
      }
    }

    // 清理函数：组件卸载或页面切换时清除定时器
    return () => {
      if (autoToggleTimerRef.current) {
        clearTimeout(autoToggleTimerRef.current);
        autoToggleTimerRef.current = null;
      }
    };
  }, [page, mode, goToNextPage]);

  // 监听窗口大小变化 - 性能优化版本
  useEffect(() => {
    // preview 模式下不需要监听（已经有固定的 zoom）
    if (mode === "preview") return;

    let timeoutId: NodeJS.Timeout;
    let rafId: number;

    const handleResize = () => {
      clearTimeout(timeoutId);
      cancelAnimationFrame(rafId);

      // 使用 requestAnimationFrame + setTimeout 组合，优化性能
      rafId = requestAnimationFrame(() => {
        timeoutId = setTimeout(() => {
          if (mode === "play") {
            // play 模式下强制重新渲染以更新缩放
            forceUpdate((prev) => prev + 1);
          } else {
            // edit 模式使用原来的计算逻辑
            calculateScale();
          }
        }, 100); // play 模式响应更快
      });
    };

    // 节流优化：只在需要时添加事件监听
    const options = { passive: true };
    window.addEventListener("resize", handleResize, options);

    // play 模式下，ResizeObserver 监听容器变化
    let resizeObserver: ResizeObserver | null = null;
    if (containerRef.current && "ResizeObserver" in window && mode !== "play") {
      resizeObserver = new ResizeObserver(handleResize);
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      clearTimeout(timeoutId);
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", handleResize);
      resizeObserver?.disconnect();
    };
  }, [calculateScale, mode]);

  // 处理画布点击事件 - 优化版本
  const handleCanvasClick = useMemoizedFn((e: React.MouseEvent) => {
    if (mode === "preview" || mode === "play") {
      return;
    }

    // 平移操作后不触发取消选中
    if (didPanRef.current) {
      didPanRef.current = false;
      return;
    }

    // 检查点击的是否是画布本身（而不是其中的元素）
    if (e.target === e.currentTarget) {
      // 取消选择时切换回开始页面
      menuActiveStore.setActiveMenu("start");
      // 关闭右键菜单（如果菜单显示的话）
      contextMenuStore.hideMenu();
    }
  });



  // 关闭右键菜单
  const closeMenu = useMemoizedFn(() => {
    contextMenuStore.hideMenu();
  });

  // 根据 pageActive 获取当前页面，使用 hook 订阅状态变化确保响应式更新
  const currentPage = useMemo(() => {
    if (mode === "edit") {
      // edit 模式：使用 pageActive 从 pages 中查找
      return pageActive ? pages.find((p) => p.id === pageActive) : undefined;
    } else if (mode === "preview" && page) {
      // preview 模式：优先使用传入的 page prop，如果没有则从 pages 中查找
      return pages.find((p) => p.id === page.id) || page;
    } else {
      // play 模式或其他：使用传入的 page prop
      return page;
    }
  }, [mode, pageActive, pages, page]);

  // 获取页面背景属性
  const backgroundType = (currentPage as any)?.backgroundType || "solidColor";
  const background = (currentPage as any)?.background || "#fff";
  const bgColor = (currentPage as any)?.bgColor || "#9C92AC";
  const fgColor = (currentPage as any)?.fgColor || "#9C92AC";
  const bgOpacity = (currentPage as any)?.bgOpacity ?? 0.4;
  const selectedTexture = (currentPage as any)?.selectedTexture || "";
  const backgroundImage = (currentPage as any)?.backgroundImage || "";

  // 生成背景样式
  const getBackgroundStyle = useMemoizedFn(() => {
    if (backgroundType === "solidColor") {
      return {
        backgroundColor: background,
        backgroundImage: "none",
      };
    }
    if (backgroundType === "image" && backgroundImage) {
      return {
        backgroundColor: "#ffffff",
        backgroundImage: `url(${backgroundImage})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
        backgroundRepeat: "no-repeat",
      };
    }
    if (backgroundType === "texture" && selectedTexture) {
      // 从 textureItems 中查找对应的纹理项
      const textureItem = textureItems.find(
        (item) => item.type === selectedTexture
      );
      let textureBackgroundImage = textureItem?.style.backgroundImage || "";

      // 替换 SVG 中的 fill 和 fill-opacity
      if (textureBackgroundImage) {
        // 将 fgColor 转换为 URL 编码格式（去掉 #，添加 %23）
        const encodedFgColor = fgColor.replace("#", "%23");

        // 替换 fill='%23------' 为 fill='%23' + fgColor（去掉#）
        textureBackgroundImage = textureBackgroundImage.replace(
          /fill='%23[0-9A-Fa-f]{6}'/g,
          `fill='${encodedFgColor}'`
        );

        // 替换 fill-opacity='----' 为 fill-opacity='' + bgOpacity
        textureBackgroundImage = textureBackgroundImage.replace(
          /fill-opacity='[^']*'/g,
          `fill-opacity='${bgOpacity}'`
        );
      }

      // 对于纹理背景，使用 bgColor 作为背景色，backgroundImage 从 textureItems 获取并替换颜色
      return {
        backgroundColor: bgColor,
        backgroundImage: textureBackgroundImage,
      };
    }
    return {
      backgroundColor: "#fff",
      backgroundImage: "none",
    };
  });

  const backgroundStyle = getBackgroundStyle();

  // 使用 Zustand hooks 订阅状态变化，确保组件能够响应状态更新
  const isFullscreen = useFullscreenStore((state) => state.isFullscreen);
  const gridType = usePPTStore((state) => state.gridType);
  const gridSize = usePPTStore((state) => state.gridSize);
  const guideLineShow = usePPTStore((state) => state.guideLineShow);

  const showLine = mode === "edit" && gridType === "line" && guideLineShow;
  // 标尺缩放跟随画布缩放（编辑模式使用 scale，播放/预览为 1）
  const rulerZoom = mode === "edit" ? scale : 1;
  const guideSnapStep = gridSize;
  const guideSnapThreshold = Math.max(1, Math.floor(guideSnapStep / 2));

  // Canvas 样式对象
  const getCanvasStyle = () => {
    let computedScale = 1;

    // play 模式下的全屏缩放（确保宽度或高度撑满）
    if (mode === "play") {
      const screenWidth = window.innerWidth;
      const screenHeight = window.innerHeight;

      // 计算缩放比例（保持宽高比）
      const scaleX = screenWidth / CANVAS_WIDTH;
      const scaleY = screenHeight / CANVAS_HEIGHT;

      // 使用 Math.min 确保整个 Canvas 都在屏幕内，同时至少一边撑满
      computedScale = Math.min(scaleX, scaleY);
    } else if (isFullscreen) {
      // 其他模式的全屏（如果有的话）
      const screenWidth = window.innerWidth;
      const screenHeight = window.innerHeight;

      const scaleX = screenWidth / CANVAS_WIDTH;
      const scaleY = screenHeight / CANVAS_HEIGHT;
      computedScale = Math.min(scaleX, scaleY) * 0.95; // 留5%边距
    } else if (mode === "preview") {
      // preview 模式使用固定缩放
      computedScale = 1;
    } else {
      // edit 模式使用动态缩放
      computedScale = scale;
    }

    const baseStyle = {
      width: `${CANVAS_WIDTH}px`,
      height: `${CANVAS_HEIGHT}px`,
      left: "50%",
      top: "50%",
      marginLeft: `-${CANVAS_WIDTH / 2}px`,
      marginTop: `-${CANVAS_HEIGHT / 2}px`,
    };

    if (mode === "play") {
      // play 模式使用 zoom 进行缩放
      return {
        ...baseStyle,
        zoom: computedScale,
      };
    }

    const panX = mode === "edit" ? panOffset.x : 0;
    const panY = mode === "edit" ? panOffset.y : 0;

    // translate 在 scale 之后应用（CSS 从右到左），平移使用屏幕像素
    return {
      ...baseStyle,
      transform: `translate(${panX}px, ${panY}px) scale(${computedScale})`,
      transformOrigin: "center center",
      transition: isPanning ? "none" : undefined,
    };
  };

  const canvasStyle = getCanvasStyle();

  const clampPan = useMemoizedFn((x: number, y: number) => {
    const parent = containerRef.current;
    if (!parent) return { x, y };
    const { width, height } = parent.getBoundingClientRect();
    const scaledW = CANVAS_WIDTH * scale;
    const scaledH = CANVAS_HEIGHT * scale;
    const maxX = Math.max(40, (scaledW - width) / 2 + 80);
    const maxY = Math.max(40, (scaledH - height) / 2 + 80);
    return {
      x: Math.min(maxX, Math.max(-maxX, x)),
      y: Math.min(maxY, Math.max(-maxY, y)),
    };
  });

  const startPan = useMemoizedFn((e: React.PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    didPanRef.current = false;
    panStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      panX: panOffset.x,
      panY: panOffset.y,
      pointerId: e.pointerId,
    };
    setIsPanning(true);
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  });

  const handlePanPointerDown = useMemoizedFn((e: React.PointerEvent) => {
    if (!canPanCanvas) return;

    const isMiddle = e.button === 1;
    const isSpaceLeft = e.button === 0 && spacePressed;
    const isEmptyParent =
      e.button === 0 && e.target === e.currentTarget && !spacePressed;

    // 空白父容器 / 中键 / Space+左键 可拖动画布
    if (!isMiddle && !isSpaceLeft && !isEmptyParent) return;

    startPan(e);
  });

  const handleCanvasPanPointerDown = useMemoizedFn((e: React.PointerEvent) => {
    if (!canPanCanvas) return;
    const isMiddle = e.button === 1;
    const isSpaceLeft = e.button === 0 && spacePressed;
    const isEmptyCanvas = e.button === 0 && e.target === e.currentTarget;
    if (!isMiddle && !isSpaceLeft && !isEmptyCanvas) return;
    startPan(e);
  });

  const handlePanPointerMove = useMemoizedFn((e: React.PointerEvent) => {
    const start = panStartRef.current;
    if (!start || start.pointerId !== e.pointerId) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
      didPanRef.current = true;
    }
    const next = clampPan(start.panX + dx, start.panY + dy);
    setPanOffset(next);
  });

  const handlePanPointerUp = useMemoizedFn((e: React.PointerEvent) => {
    const start = panStartRef.current;
    if (!start || start.pointerId !== e.pointerId) return;
    panStartRef.current = null;
    setIsPanning(false);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      // ignore
    }
  });

  const renderSlideHtml = useMemoizedFn(() => {
    if (!currentPage) return null;
    const isEditCanvas = mode === "edit";
    return (
      <HtmlSlideFrame
        page={currentPage as Page}
        pointerEventsNone={!isEditCanvas}
        editable={isEditCanvas}
        title={`slide-${currentPage.id}`}
      />
    );
  });

  // 播放模式右键菜单处理
  const handlePlayContextMenu = useMemoizedFn((e: React.MouseEvent) => {
    if (mode !== "play") return;

    e.preventDefault();
    e.stopPropagation();

    const pages = pptStore.getPages();
    // 在 play 模式下，优先使用 page?.id，如果没有则使用 fullscreenStore 的 currentSlidePageId
    const currentPageId =
      page?.id ||
      fullscreenStore.getCurrentSlidePageId() ||
      pageActiveStore.getPageActive();
    const currentPageIndex = pages.findIndex((p) => p.id === currentPageId);

    // 使用 MenuItem 类型定义菜单项
    const menuItems: MenuItem[] = [
      {
        type: "item",
        label: "上一页",
        onClick: () => {
          if (currentPageIndex > 0) {
            const prevPageId =
              pages[showEndMessage ? currentPageIndex : currentPageIndex - 1]
                .id;
            pageActiveStore.setPageActive(prevPageId);
            fullscreenStore.enterFullscreen(prevPageId);
            setShowEndMessage(false);
          }
        },
        icon: <Left theme="outline" size="13" fill="var(--icon-color)" />,
        disabled: currentPageIndex === 0,
      },
      {
        type: "item",
        label: "下一页",
        onClick: () => {
          if (currentPageIndex < pages.length - 1) {
            // 直接计算下一页的ID，不依赖 pageActiveStore
            const nextPageId = pages[currentPageIndex + 1].id;
            pageActiveStore.setPageActive(nextPageId);
            fullscreenStore.enterFullscreen(nextPageId);
            setShowEndMessage(false);
          } else {
            // 如果无法切换，显示结束提示
            setShowEndMessage(true);
          }
        },
        icon: <Right theme="outline" size="13" fill="var(--icon-color)" />,
        disabled: currentPageIndex === pages.length - 1,
      },
      {
        type: "item",
        label: "第一页",
        onClick: () => {
          if (pages.length > 0) {
            const firstPageId = pages[0].id;
            pageActiveStore.setPageActive(firstPageId);
            fullscreenStore.enterFullscreen(firstPageId);
            setShowEndMessage(false);
          }
        },
        icon: <GoStart theme="outline" size="13" fill="var(--icon-color)" />,
        disabled: currentPageIndex === 0,
      },
      {
        type: "item",
        label: "最后一页",
        onClick: () => {
          if (pages.length > 0) {
            const lastPageId = pages[pages.length - 1].id;
            pageActiveStore.setPageActive(lastPageId);
            fullscreenStore.enterFullscreen(lastPageId);
            setShowEndMessage(false);
          }
        },
        icon: <GoEnd theme="outline" size="13" fill="var(--icon-color)" />,
        disabled: currentPageIndex === pages.length - 1,
      },
      {
        type: "separator",
      },
      {
        type: "item",
        label: "结束放映",
        onClick: () => {
          // 关闭菜单
          contextMenuStore.hideMenu();

          // 退出全屏模式
          fullscreenStore.exitFullscreen();
          // 同步更新编辑模式的当前页
          if (currentPageId) {
            pageActiveStore.setPageActive(currentPageId);
          }
          setShowEndMessage(false);
        },
        icon: (
          <CloseOne
            theme="multi-color"
            size="13"
            fill={["#ff8501", "#ff8501", "#FFF", "#43CCF8"]}
          />
        ),
      },
    ];

    contextMenuStore.showMenu(e.clientX, e.clientY, menuItems);
  });

  // 放映：单击前进到下一页
  const handlePlayNext = useMemoizedFn(() => {
    if (mode !== "play") return;
    if (contextMenuStore.isVisible()) return;

    if (showEndMessage) {
      fullscreenStore.exitFullscreen();
      setShowEndMessage(false);
      return;
    }

    const pagesList = pptStore.getPages();
    const currentPageId = page?.id || pageActiveStore.getPageActive();
    const currentPage = page || pptStore.getActivePage(currentPageId as string);
    if (!currentPage) return;

    const currentPageIndex = pagesList.findIndex((p) => p.id === currentPageId);
    const isLastPage = currentPageIndex === pagesList.length - 1;
    const { clickToNext = true } = currentPage as Page & { clickToNext?: boolean };
    if (!clickToNext) return;

    if (currentPageId) {
      pageActiveStore.setPageActive(currentPageId);
    }
    const lastPageId = pageActiveStore.getPageActive();
    const newPageId = pageActiveStore.goToNextPage();

    if (isLastPage && lastPageId === newPageId) {
      setShowEndMessage(true);
      return;
    }

    if (lastPageId !== newPageId && newPageId) {
      fullscreenStore.enterFullscreen(newPageId);
      setShowEndMessage(false);
    }
  });

  const playCanvasClickHandle = useMemoizedFn(() => {
    handlePlayNext();
  });

  // 用于防止重复执行的标志
  const animationEndHandledRef = useRef(false);

  // 处理页面切换动画结束事件
  const handleAnimationEnd = useMemoizedFn(
    (e: React.AnimationEvent<HTMLDivElement>) => {
      if (mode !== "play") return;

      // 只处理页面容器本身的动画结束事件，忽略子元素的动画事件
      const target = e.target as HTMLElement;
      const containerId =
        mode === "play"
          ? "play-canvas-container"
          : "preview-canvas-container-" + page?.id;

      if (target.id !== containerId) return;

      // 防止重复执行
      if (animationEndHandledRef.current) return;
      animationEndHandledRef.current = true;

      // 获取当前页面
      const currentPage =
        page ||
        pptStore.getActivePage(pageActiveStore.getPageActive() as string);

      if (!currentPage) {
        animationEndHandledRef.current = false;
        return;
      }

      // 延迟重置标志，确保只执行一次
      setTimeout(() => {
        animationEndHandledRef.current = false;
      }, 100);
    }
  );

  const CanvasContainer = useMemoizedFn(() => {
    // 编辑模式：支持交互、右键菜单等
    if (mode === "edit") {
      return (
        <div
          id="canvas-container"
          className="absolute overflow-hidden transition-transform duration-200 ease-in-out rounded-[10px]"
          style={{
            ...canvasStyle,
            ...backgroundStyle,
            boxShadow:
              "0 1px 3px rgba(0, 0, 0, 0.06), 0 8px 24px rgba(0, 0, 0, 0.08)",
            cursor: isPanning
              ? "grabbing"
              : canPanCanvas && spacePressed
                ? "grab"
                : undefined,
          }}
          onTransitionEnd={updateCanvasOffset}
          onClick={handleCanvasClick}
          onPointerDown={handleCanvasPanPointerDown}
          onPointerMove={handlePanPointerMove}
          onPointerUp={handlePanPointerUp}
          onPointerCancel={handlePanPointerUp}
          onContextMenu={(e) => {
            e.preventDefault();
            e.stopPropagation();
            const menuItems: MenuItem[] = [];
            if ((e as any).customData) {
              const { menuItems: customMenuItems } = (e as any).customData;
              // 为每个自定义菜单项包装 onClick 处理函数
              const wrappedCustomMenuItems = customMenuItems.map(
                (item: any) => ({
                  ...item,
                  onClick: item.onClick
                    ? () => {
                        item.onClick();
                        closeMenu();
                      }
                    : undefined,
                })
              );
              menuItems.push(...wrappedCustomMenuItems);
            } else {
              // 获取当前页面信息
              const currentPageId = pageActiveStore.getPageActive();
              const currentPage = currentPageId
                ? pptStore.getActivePage(currentPageId)
                : undefined;
              const isPageVisible = currentPage?.visible !== false;

              // 构建右键菜单项
              menuItems.push(
                // 网格线设置
                {
                  type: "submenu",
                  label: t("contextMenu.gridLines"),
                  icon: <GridTwo theme="outline" size="13" fill="var(--icon-color)" />,
                  children: [
                    {
                      type: "item",
                      label: "10×10",
                      onClick: () => {
                        pptStore.setGridType("grid");
                        pptStore.setGridSize(10);
                        closeMenu();
                      },
                      disabled: gridType === "grid" && gridSize === 10,
                    },
                    {
                      type: "item",
                      label: "20×20",
                      onClick: () => {
                        pptStore.setGridType("grid");
                        pptStore.setGridSize(20);
                        closeMenu();
                      },
                      disabled: gridType === "grid" && gridSize === 20,
                    },
                    {
                      type: "item",
                      label: "30×30",
                      onClick: () => {
                        pptStore.setGridType("grid");
                        pptStore.setGridSize(30);
                        closeMenu();
                      },
                      disabled: gridType === "grid" && gridSize === 30,
                    },
                    {
                      type: "item",
                      label: "40×40",
                      onClick: () => {
                        pptStore.setGridType("grid");
                        pptStore.setGridSize(40);
                        closeMenu();
                      },
                      disabled: gridType === "grid" && gridSize === 40,
                    },
                  ],
                },
                // 标尺
                {
                  type: "item",
                  label:
                    gridType === "line"
                      ? t("contextMenu.hideRuler")
                      : t("contextMenu.showRuler"),
                  onClick: () => {
                    if (gridType === "line") {
                      pptStore.setGridType("none");
                    } else {
                      pptStore.setGridType("line");
                    }
                    closeMenu();
                  },
                  icon: <Ruler theme="outline" size="13" fill="var(--icon-color)" />,
                },
                // 参考线
                {
                  type: "item",
                  label: guideLineShow
                    ? t("contextMenu.hideGuides")
                    : t("contextMenu.showGuides"),
                  onClick: () => {
                    pptStore.setGuideLineShow(!guideLineShow);
                    closeMenu();
                  },
                  icon: (
                    <DividingLineOne theme="outline" size="13" fill="var(--icon-color)" />
                  ),
                  disabled: gridType !== "line",
                },
                // 清除参考线
                {
                  type: "item",
                  label: t("contextMenu.clearGuides"),
                  onClick: () => {
                    pptStore.setHorizontalLine([]);
                    pptStore.setVerticalLine([]);
                    closeMenu();
                  },
                  icon: <Clear theme="outline" size="13" fill="var(--icon-color)" />,
                  disabled: gridType !== "line",
                },
                // 分隔线
                {
                  type: "separator",
                },
                // 重置幻灯片
                {
                  type: "item",
                  label: t("contextMenu.resetSlide"),
                  onClick: () => {
                    if (currentPageId) {
                      const pg = pptStore.getActivePage(currentPageId);
                      if (pg) {
                        pptStore.setPageHtml(
                          currentPageId,
                          buildBlankSlideHtml(pg),
                        );
                        menuActiveStore.resetMenu();
                      }
                    }
                    closeMenu();
                  },
                  icon: <Clear theme="outline" size="13" fill="var(--icon-color)" />,
                },
                // 隐藏/显示幻灯片
                {
                  type: "item",
                  label: isPageVisible
                    ? t("contextMenu.hideSlide")
                    : t("contextMenu.showSlide"),
                  onClick: () => {
                    if (currentPageId) {
                      pptStore.togglePageVisible(currentPageId);
                    }
                    closeMenu();
                  },
                  icon: isPageVisible ? (
                    <PreviewCloseOne theme="outline" size="13" fill="var(--icon-color)" />
                  ) : (
                    <PreviewOpen theme="outline" size="13" fill="var(--icon-color)" />
                  ),
                },
                // 播放幻灯片
                {
                  type: "item",
                  label: t("contextMenu.playSlide"),
                  onClick: () => {
                    if (currentPageId) {
                      fullscreenStore.enterFullscreen(currentPageId);
                    }
                    closeMenu();
                  },
                  icon: <Play theme="outline" size="13" fill="var(--icon-color)" />,
                  disabled: !isPageVisible,
                },
                // 导出图片
                {
                  type: "item",
                  label: t("contextMenu.exportImage"),
                  onClick: async () => {
                    if (currentPageId) {
                      const dataUrl = await exportPageAsImage(currentPageId);
                      if (dataUrl) {
                        const name = pptStore.getName();
                        downloadImage(
                          dataUrl,
                          `${name || t("contextMenu.untitled")}_${currentPageId}.png`
                        );
                      }
                    }
                    closeMenu();
                  },
                  icon: <Export theme="outline" size="13" fill="var(--icon-color)" />,
                }
              );

              menuActiveStore.resetMenu();

              // 显示全局右键菜单
              contextMenuStore.showMenu(e.clientX, e.clientY, menuItems);
              return;
            }

            // 显示全局右键菜单
            contextMenuStore.showMenu(e.clientX, e.clientY, menuItems);
          }}
        >
          {gridType === "grid" && (
            <div
              className="absolute inset-0 pointer-events-none"
              style={{
                backgroundImage: `repeating-linear-gradient(0deg, transparent, transparent ${gridSize - 1}px, var(--grid-line) ${gridSize}px), repeating-linear-gradient(90deg, transparent, transparent ${gridSize - 1}px, var(--grid-line) ${gridSize}px)`,
                backgroundSize: `${gridSize}px ${gridSize}px`,
              }}
            />
          )}
          {renderSlideHtml()}
        </div>
      );
    }

    // 在 play 模式下优先使用传入的 page prop，否则从 pages 中查找
    // preview 模式下也从 pages 中查找，确保能响应页面内容变化
    const currentPage =
      mode === "play" && page
        ? page
        : mode === "preview" && page
          ? pages.find((p) => p.id === page.id) || page
          : pageActive
            ? pages.find((p) => p.id === pageActive)
            : undefined;
    const {
      toggleInAnimation = "",
      toggleInDelay = "0",
      toggleInDuration = "default",
    } = (currentPage as any) || {};

    let animationClassName = "";

    if (mode === "play" && toggleInAnimation !== "") {
      animationClassName = `animate__animated animate__${toggleInAnimation}`;
      if (toggleInDelay) {
        animationClassName +=
          toggleInDelay == "0s" ? "" : ` animate__delay-${toggleInDelay}`;
      }
      if (toggleInDuration) {
        animationClassName +=
          toggleInDuration == "default" ? "" : ` animate__${toggleInDuration}`;
      }
    }

    // 预览模式或播放模式：只读，不支持交互
    return (
      <div
        id={
          mode === "play"
            ? "play-canvas-container"
            : "preview-canvas-container-" + page?.id
        }
        className={`${animationClassName} absolute overflow-hidden transition-transform duration-200 ease-in-out`}
        style={{
          ...canvasStyle,
          ...(showEndMessage ? { backgroundColor: "#000" } : backgroundStyle),
        }}
        onClick={mode === "play" ? playCanvasClickHandle : undefined}
        onContextMenu={mode === "play" ? handlePlayContextMenu : undefined}
        onAnimationEnd={mode === "play" ? handleAnimationEnd : undefined}
      >
        {mode === "play" ? (
          <div
            className="absolute inset-0 pointer-events-none"
            aria-hidden
          >
            {renderSlideHtml()}
          </div>
        ) : (
          renderSlideHtml()
        )}
        {mode === "play" && showEndMessage && (
          <div className="absolute inset-0 flex items-center justify-center cursor-pointer text-[15px] bg-[#000] text-[#fff] z-[9999]">
            放映结束，单击鼠标退出
          </div>
        )}
      </div>
    );
  });

  // 获取页面ID用于生成唯一的容器ID
  const pageId =
    mode === "edit" ? pageActive || "default" : page?.id || "default";

  const remarkEditActive = useRemarkEditActiveStore(
    (state) => state.remarkEditActive
  );

  // 获取当前页面的 remark 属性，使用 hook 订阅状态变化
  const currentPageRemark = useMemo(() => {
    if (mode === "edit") {
      if (!pageActive) return "";
      const activePage = pages.find((p) => p.id === pageActive);
      return (activePage as any)?.remark || "";
    }
    return (page as any)?.remark || "";
  }, [mode, pageActive, pages, page]);

  // 本地 state 存储 remark 值，用于即时更新 UI
  const [localRemark, setLocalRemark] = useState(currentPageRemark);

  // 当页面切换或 store 中的 remark 变化时，同步更新本地 state
  useEffect(() => {
    setLocalRemark(currentPageRemark);
  }, [currentPageRemark]);

  // 更新页面 remark 属性的函数
  const updatePageRemark = useMemoizedFn((remark: string) => {
    if (mode !== "edit") return;

    const pageActive = pageActiveStore.getPageActive();
    if (!pageActive) return;

    const page = pptStore.getActivePage(pageActive);
    if (!page) return;

    const pageIndex = pptStore.getPages().findIndex((p) => p.id === pageActive);
    if (pageIndex === -1) return;

    const newPages = [...pptStore.getPages()];
    newPages[pageIndex] = {
      ...newPages[pageIndex],
      remark,
    } as any;
    pptStore.setPages(newPages);
  });

  // 防抖定时器引用
  const remarkDebounceTimerRef = useRef<NodeJS.Timeout | null>(null);

  // 防抖处理备注变更：先更新本地 state，再通过防抖更新 Zustand store
  const handleRemarkChange = useCallback(
    (value: string) => {
      // 先更新本地 state，立即反映到 UI
      setLocalRemark(value);

      // 清除之前的定时器
      if (remarkDebounceTimerRef.current) {
        clearTimeout(remarkDebounceTimerRef.current);
      }

      // 防抖更新 Zustand store
      remarkDebounceTimerRef.current = setTimeout(() => {
        updatePageRemark(value);
      }, 300);
    },
    [updatePageRemark]
  );

  // 清理防抖定时器
  useEffect(() => {
    return () => {
      if (remarkDebounceTimerRef.current) {
        clearTimeout(remarkDebounceTimerRef.current);
      }
    };
  }, []);

  // 动态生成 className（全屏优先）
  const getContainerClassName = () => {
    // 如果全屏，优先使用全屏样式
    if (isFullscreen) {
      return "flex items-center justify-center w-full h-full relative";
    }

    // 非全屏时根据 mode 使用不同样式
    if (mode === "edit") {
      if (gridType === "line") {
        return `relative overflow-hidden bg-transparent ${remarkEditActive ? "h-[calc(100%-32px)]" : "h-full"}`;
      }
      return (
        "w-full relative overflow-hidden bg-transparent" +
        (remarkEditActive ? " h-[calc(100%-32px)]" : " h-full")
      );
    }

    // preview 和 play 模式
    return "w-full h-full relative";
  };

  const containerClassName = getContainerClassName();

  // 动态生成 style（用于 preview/play 模式的 zoom）
  // 获取容器样式
  const getContainerStyle = () => {
    // 优先判断全屏状态（play 模式全屏）
    if (isFullscreen && mode === "play") {
      // play 模式全屏时，不使用 zoom，而是通过 Canvas 内部的 scale 来控制
      // 这里返回 undefined，让 Canvas 使用默认样式
      return undefined;
    }

    // 非全屏时，如果是 preview 模式且有 previewZoom，使用 previewZoom
    if (mode === "preview" && previewZoom !== undefined) {
      return { zoom: previewZoom };
    }

    if (mode === "edit" && gridType === "line") {
      return {
        width: `calc(100% - 23px)`,
        height: `calc(100% - 23px - ${remarkEditActive ? 32 : 0}px)`,
        marginLeft: "23px",
        marginTop: "23px",
      };
    }

    return undefined;
  };

  const containerStyle = getContainerStyle();

  // 标尺容器尺寸，需扣除 23px
  const [rulerSize, setRulerSize] = useState({ width: 0, height: 0 });
  // canvas-container 相对于 parent-canvas-container 的偏移
  const [canvasOffset, setCanvasOffset] = useState({ left: 0, top: 0 });
  // 是否正在调整大小（用于显示蒙层）
  const [showResizeOverlay, setShowResizeOverlay] = useState(false);
  // Guides 组件的 ref
  const horizontalGuidesRef = useRef<any>(null);
  const verticalGuidesRef = useRef<any>(null);

  const updateRulerSize = useMemoizedFn(() => {
    const container = document.getElementById(
      `parent-canvas-container-${pageId}`
    );
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const width = Math.max(0, rect.width - 23);
    const height = Math.max(0, rect.height - 23);

    setRulerSize((prev) => {
      if (prev.width !== width || prev.height !== height) {
        return { width, height };
      }
      return prev;
    });
    // updateCanvasOffset();
  });

  // 计算 canvas-container 的偏移
  const updateCanvasOffset = useMemoizedFn((e?: React.TransitionEvent) => {
    // 如果是 transitionend 事件，只处理 transform 属性的过渡
    if (e && e.propertyName !== "transform") {
      return;
    }

    const parentContainer = document.getElementById(
      `parent-canvas-container-${pageId}`
    );
    if (!parentContainer) return;

    const parentRect = parentContainer.getBoundingClientRect();

    // 使用当前的缩放比例
    const canvasScale = scale;

    // 计算画布在父容器中的逻辑位置（未缩放前的坐标）
    // 画布使用 left: 50%, marginLeft: -CANVAS_WIDTH/2 来居中
    const parentWidth = parentRect.width;
    const parentHeight = parentRect.height;

    // 画布逻辑位置（相对于父容器的左上角）+ 平移（屏幕像素 / scale）
    const logicalLeft =
      parentWidth / 2 / canvasScale - CANVAS_WIDTH / 2 + panOffset.x / canvasScale;
    const logicalTop =
      parentHeight / 2 / canvasScale - CANVAS_HEIGHT / 2 + panOffset.y / canvasScale;

    setCanvasOffset((prev) => {
      if (prev.left !== logicalLeft || prev.top !== logicalTop) {
        return { left: logicalLeft, top: logicalTop };
      }
      return prev;
    });
  });

  const { run: debouncedHandleResizeEnd } = useDebounceFn(
    () => {
      updateRulerSize();
      // 等待画布过渡动画结束后再计算偏移
      setTimeout(() => {
        updateCanvasOffset();
      }, 250); // 等待 200ms 动画 + 50ms 缓冲
      setTimeout(() => {
        setShowResizeOverlay(false);
      }, 300);
    },
    {
      wait: 150,
    }
  );

  useEffect(() => {
    // 只在 edit 模式下监听 resize
    if (mode !== "edit" || gridType !== "line") {
      return;
    }

    updateRulerSize();

    // 等待画布过渡动画结束后再计算偏移
    // 画布有 transition-transform duration-200 的过渡动画
    const timer = setTimeout(() => {
      updateCanvasOffset();
    }, 250); // 等待 200ms 动画 + 50ms 缓冲

    const resizeHandle = () => {
      setShowResizeOverlay(true);
      debouncedHandleResizeEnd();
    };

    window.addEventListener("resize", resizeHandle);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", resizeHandle);
    };
  }, [
    pageId,
    mode,
    gridType,
    scale,
    updateRulerSize,
    debouncedHandleResizeEnd,
    updateCanvasOffset,
    remarkEditActive,
  ]);

  // 当 rulerZoom 或 canvasOffset 变化时，更新 Guides 的 scrollPos
  // 如果组件不支持 scrollPos 属性的响应式更新，通过 ref 调用 scrollGuides
  useEffect(() => {
    if (
      gridType === "line" &&
      (horizontalGuidesRef.current || verticalGuidesRef.current)
    ) {
      if (horizontalGuidesRef.current) {
        horizontalGuidesRef.current.scrollGuides(-canvasOffset.top, rulerZoom);
      }
      if (verticalGuidesRef.current) {
        verticalGuidesRef.current.scrollGuides(-canvasOffset.left, rulerZoom);
      }
    }
  }, [rulerZoom, canvasOffset.top, canvasOffset.left, gridType]);

  // 平移变化时同步标尺偏移
  useEffect(() => {
    if (mode !== "edit" || isPanning) return;
    updateCanvasOffset();
  }, [panOffset.x, panOffset.y, mode, isPanning, updateCanvasOffset]);

  // 使用从 store 订阅的参考线数据并转换为数字数组
  const horizontalLine = useMemo(
    () => horizontalLineFromStore.map(Number),
    [horizontalLineFromStore]
  );
  const verticalLine = useMemo(
    () => verticalLineFromStore.map(Number),
    [verticalLineFromStore]
  );

  // 监听参考线变化，通过 ref 调用 loadGuides 或 setState 更新 Guides 组件
  useEffect(() => {
    if (gridType !== "line" || mode !== "edit") {
      return;
    }

    // 更新水平参考线
    if (horizontalGuidesRef.current) {
      // 尝试调用 loadGuides 方法
      if (typeof horizontalGuidesRef.current.loadGuides === "function") {
        horizontalGuidesRef.current.loadGuides(horizontalLine);
      }
      // 如果 loadGuides 不存在，尝试使用 setState
      else if (typeof horizontalGuidesRef.current.setState === "function") {
        horizontalGuidesRef.current.setState({ guides: horizontalLine });
      }
    }

    // 更新垂直参考线
    if (verticalGuidesRef.current) {
      // 尝试调用 loadGuides 方法
      if (typeof verticalGuidesRef.current.loadGuides === "function") {
        verticalGuidesRef.current.loadGuides(verticalLine);
      }
      // 如果 loadGuides 不存在，尝试使用 setState
      else if (typeof verticalGuidesRef.current.setState === "function") {
        verticalGuidesRef.current.setState({ guides: verticalLine });
      }
    }
  }, [horizontalLine, verticalLine, gridType, mode]);

  const computedUnit = useMemo(() => {
    if (scale > 1.5) return 25;
    else if (scale > 0.75 && scale <= 1.5) return 50;
    else if (scale > 0.4 && scale <= 0.75) return 100;
    else if (scale > 0.2 && scale <= 0.4) return 200;
    else return 400;
  }, [scale]);

  const themeMode = useThemeStore((state) => state.theme);
  const guideColors = useMemo(
    () =>
      themeMode === "dark"
        ? {
            backgroundColor: "#1e1d1b",
            lineColor: "#3a3835",
            textColor: "#7a7670",
            cornerText: "#6a6560",
          }
        : {
            backgroundColor: "#fafafa",
            lineColor: "#d9d9d9",
            textColor: "#999",
            cornerText: "#ccc",
          },
    [themeMode]
  );

  return (
    <div
      className={`h-full flex-1 relative m-0 p-0 ${mode === "edit" ? "bg-transparent" : "bg-chrome-guide"}`}
      id={mode === "edit" ? "ruler-container" : undefined}
    >
      {/* resize 时的蒙层 */}
      {mode === "edit" && (
        <div
          className="absolute inset-0 w-full h-full flex items-center justify-center"
          style={{
            pointerEvents: "none",
            opacity: showResizeOverlay ? 1 : 0,
            background: showResizeOverlay
              ? themeMode === "dark"
                ? "rgba(20, 19, 18, 0.55)"
                : "rgba(255, 255, 255, 0.5)"
              : "transparent",
            zIndex: showResizeOverlay ? 9999 : -1,
            backdropFilter: showResizeOverlay ? "blur(20px)" : "none",
            WebkitBackdropFilter: showResizeOverlay ? "blur(20px)" : "none",
            transition: "opacity 0.2s ease-in-out",
          }}
        >
          <img src={SearchSvg} alt="search" className="w-[100px] h-[100px]" />
        </div>
      )}
      {gridType === "line" && mode === "edit" && (
        <>
          <Guides
            ref={horizontalGuidesRef}
            showGuides={showLine}
            useResizeObserver={true}
            type="horizontal"
            width={rulerSize.width}
            height={23}
            unit={computedUnit}
            zoom={rulerZoom}
            displayDragPos={false}
            direction="end"
            backgroundColor={guideColors.backgroundColor}
            lineColor={guideColors.lineColor}
            textColor={guideColors.textColor}
            font="12px"
            textOffset={[0, 9]}
            snapThreshold={guideSnapThreshold}
            scrollPos={-canvasOffset.left}
            rulerStyle={{
              display: "block",
              width: "100%",
              height: "100%",
              margin: 0,
              padding: 0,
            }}
            style={{
              position: "absolute",
              top: 0,
              left: 23,
              margin: 0,
              padding: 0,
              zIndex: 2,
              height: 23,
              width: "calc(100% - 23px)",
              backgroundColor: guideColors.backgroundColor,
              pointerEvents: "auto",
            }}
            guides={horizontalLine}
            onChangeGuides={(v) => {
              pptStore.setHorizontalLine([...v.guides]);
            }}
          />
          <Guides
            ref={verticalGuidesRef}
            showGuides={showLine}
            useResizeObserver={true}
            type="vertical"
            width={23}
            height={rulerSize.height}
            unit={computedUnit}
            zoom={rulerZoom}
            displayDragPos={false}
            direction="end"
            backgroundColor={guideColors.backgroundColor}
            lineColor={guideColors.lineColor}
            textColor={guideColors.textColor}
            font="12px"
            textOffset={[9, 0]}
            snapThreshold={guideSnapThreshold}
            scrollPos={-canvasOffset.top}
            rulerStyle={{
              display: "block",
              width: "100%",
              height: "100%",
              margin: 0,
              padding: 0,
            }}
            style={{
              position: "absolute",
              top: 23,
              left: 0,
              margin: 0,
              padding: 0,
              zIndex: 2,
              width: 23,
              height: `calc(100% - 23px - ${remarkEditActive ? 32 : 0}px)`,
              backgroundColor: guideColors.backgroundColor,
              pointerEvents: "auto",
            }}
            guides={verticalLine}
            onChangeGuides={(v) => pptStore.setVerticalLine(v.guides)}
          />
          <div
            className="w-[23px] text-[11px] leading-[12px] h-[23px] absolute top-0 left-0 flex items-center justify-center m-0 p-0"
            style={{
              color: guideColors.cornerText,
              backgroundColor: guideColors.backgroundColor,
            }}
          >
            px
          </div>
        </>
      )}
      <div
        ref={containerRef}
        id={
          mode !== "preview" ? `parent-canvas-container-${pageId}` : undefined
        }
        className={containerClassName}
        style={{
          ...containerStyle,
          cursor: isPanning ? "grabbing" : canPanCanvas ? "grab" : undefined,
          userSelect: isPanning || spacePressed ? "none" : undefined,
        }}
        onPointerDown={mode === "edit" ? handlePanPointerDown : undefined}
        onPointerMove={mode === "edit" ? handlePanPointerMove : undefined}
        onPointerUp={mode === "edit" ? handlePanPointerUp : undefined}
        onPointerCancel={mode === "edit" ? handlePanPointerUp : undefined}
        onAuxClick={
          mode === "edit"
            ? (e) => {
                // 阻止中键默认自动滚动
                if (e.button === 1) e.preventDefault();
              }
            : undefined
        }
      >
        {mode === "play" && (
          <GlobalContextMenu
            parentSelector={`#parent-canvas-container-${pageId}`}
          />
        )}
        <CanvasContainer />
      </div>
      {mode === "edit" && remarkEditActive && (
        <RemarkEdit value={localRemark} onChange={handleRemarkChange} />
      )}
    </div>
  );
};

/** preview 走轻量 PreviewCanvas，避免挂载完整编辑/播放态逻辑 */
export const Canvas: FC<CanvasProps> = (props) => {
  if (props.mode === "preview") {
    if (!props.page) return null;
    return (
      <PreviewCanvas
        page={props.page as Page}
        previewZoom={props.previewZoom}
      />
    );
  }
  return <Component {...props} />;
};
