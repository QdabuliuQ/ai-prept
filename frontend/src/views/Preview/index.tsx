import {
  CANVAS_ASPECT_RATIO,
  CANVAS_ASPECT_RATIO_CSS,
} from "@/constants/canvas";
import {
  useContextMenuStore,
  useFullscreenStore,
  useMenuActiveStore,
  usePageActiveStore,
  usePPTStore,
} from "@/store";
import { useFilePreviewStore } from "@/store/zustand/filePreviewStore";
import type { Page } from "@/store/ppt";
import { initPPTStore } from "@/utils/initStore";
import {
  addPageAndActivate,
  deletePageAndFallback,
  duplicatePageAndActivate,
  resetPageElements,
} from "@/utils/operate";
import { showPageContextMenu } from "@/utils/pageContextMenu";
import {
  getCachedThumbnail,
  scheduleVisibleThumbnails,
  usePageThumbnail,
  usePagesThumbnailSync,
} from "@/utils/pageThumbnail";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Add,
  Down,
  PlayOne,
  Plus,
  PreviewCloseOne,
  Up,
} from "@icon-park/react";
import { useKeyPress, useMemoizedFn, useMount } from "ahooks";
import { OverlayScrollbarsComponent } from "overlayscrollbars-react";
import { SlideThumbSkeleton } from "@/components/SlideThumbSkeleton";
import { TemplateFileTree } from "./TemplateFileTree";
import { FolderTree, Images } from "lucide-react";
import {
  memo,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FC,
} from "react";
import styles from "./index.module.less";

/**
 * 侧栏默认宽约 230，扣除页码与间距后缩略图宽约 180。
 * 高度按画布 16:9 推算，再加底部 gap。
 * 注意：虚拟列表不要用 measureElement —— 切到「文件」页签时容器
 * display:none，ResizeObserver 会把高度量成 0，切回后缩略图就会叠在一起。
 */
const PREVIEW_THUMB_WIDTH_EST = 180;
const ITEM_GAP = 14;
/** pageItem 左右 padding + 页码列 + gap */
const ITEM_CHROME_X = 8 + 12 + 20 + 8;
const ESTIMATED_ITEM_SIZE =
  Math.round(PREVIEW_THUMB_WIDTH_EST / CANVAS_ASPECT_RATIO) + ITEM_GAP;

function thumbItemSizeForWidth(containerWidth: number): number {
  const thumbWidth = Math.max(containerWidth - ITEM_CHROME_X, 120);
  return Math.round(thumbWidth / CANVAS_ASPECT_RATIO) + ITEM_GAP;
}

const PageItem: FC<{
  page: Page;
  index: number;
  totalPages: number;
  pageActive: string | null;
  onPageClick: (pageId: string) => void;
  onContextMenu: (e: React.MouseEvent, pageId: string) => void;
  onPlayPage: (pageId: string, e: React.MouseEvent) => void;
  onMovePageUp: (pageId: string, e: React.MouseEvent) => void;
  onMovePageDown: (pageId: string, e: React.MouseEvent) => void;
  onAddPageAfter: (pageId: string, e: React.MouseEvent) => void;
}> = memo(
  ({
    page,
    index,
    totalPages,
    pageActive,
    onPageClick,
    onContextMenu,
    onPlayPage,
    onMovePageUp,
    onMovePageDown,
    onAddPageAfter,
  }) => {
    const isActive = pageActive === page.id;
    const thumbnailUrl = usePageThumbnail(page);

    return (
      <div
        className={`${styles.pageItem} relative flex cursor-pointer gap-[8px]`}
      >
        <span
          className={`${styles.pageIndex} ${isActive ? styles.pageIndexActive : ""}`}
        >
          {index + 1}
        </span>
        <div
          className={`${styles.thumbWrap} ${isActive ? styles.thumbActive : styles.thumbInactive}`}
          onClick={() => onPageClick(page.id)}
          onContextMenu={(e) => onContextMenu(e, page.id)}
        >
          <div
            className={styles.thumbCanvas}
            style={{ aspectRatio: CANVAS_ASPECT_RATIO_CSS }}
          >
            {thumbnailUrl ? (
              <img
                src={thumbnailUrl}
                alt={`slide-${index + 1}`}
                className="absolute inset-0 h-full w-full object-fill"
                draggable={false}
              />
            ) : (
              <SlideThumbSkeleton />
            )}
            {page.visible === false && (
              <div
                className="pointer-events-auto absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center rounded-[10px] bg-black/15"
                onClick={() => onPageClick(page.id)}
                onContextMenu={(e) => onContextMenu(e, page.id)}
              >
                <PreviewCloseOne
                  theme="outline"
                  size="22"
                  fill="var(--icon-color)"
                />
              </div>
            )}
          </div>
        </div>
        <div className="floatButton absolute bottom-[-10px] right-[24px] z-10 flex w-[78%] items-center justify-between opacity-0 transition-opacity duration-150">
          <div>
            {page.visible && (
              <div
                className={`${styles.floatAction} bg-chrome-panel-solid`}
                onClick={(e) => onPlayPage(page.id, e)}
              >
                <PlayOne theme="filled" size="15" fill="#f25f00" />
              </div>
            )}
          </div>
          <div className="flex items-center gap-[7px]">
            {index > 0 && (
              <div
                className={`${styles.floatAction} bg-primary`}
                onClick={(e) => onMovePageUp(page.id, e)}
              >
                <Up theme="outline" size="15" fill="#fff" />
              </div>
            )}
            {index < totalPages - 1 && (
              <div
                className={`${styles.floatAction} bg-primary`}
                onClick={(e) => onMovePageDown(page.id, e)}
              >
                <Down theme="outline" size="15" fill="#fff" />
              </div>
            )}
            <div
              className={`${styles.floatAction} bg-primary`}
              onClick={(e) => onAddPageAfter(page.id, e)}
            >
              <Plus theme="outline" size="15" fill="#fff" />
            </div>
          </div>
        </div>
      </div>
    );
  }
);

PageItem.displayName = "PageItem";

const PreviewComponent: FC = () => {
  const pages = usePPTStore((state) => state.pages);
  const pageActive = usePageActiveStore((state) => state.pageActive);
  const setPageActive = usePageActiveStore((state) => state.setPageActive);
  const setActiveMenu = useMenuActiveStore((state) => state.setActiveMenu);
  const hideMenu = useContextMenuStore((state) => state.hideMenu);
  const enterFullscreen = useFullscreenStore((state) => state.enterFullscreen);
  const movePage = usePPTStore((state) => state.movePage);
  const togglePageVisible = usePPTStore((state) => state.togglePageVisible);

  usePagesThumbnailSync(pages);

  useMount(() => {
    if (pages.length === 0) {
      initPPTStore();
    }
  });

  const containerRef = useRef<HTMLDivElement>(null);
  const thumbsPaneRef = useRef<HTMLDivElement>(null);
  const addButtonRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<any>(null);
  const [scrollHeight, setScrollHeight] = useState(0);
  const [scrollElement, setScrollElement] = useState<HTMLElement | null>(null);
  const [sideTab, setSideTab] = useState<"preview" | "files">("preview");
  const [itemSize, setItemSize] = useState(ESTIMATED_ITEM_SIZE);

  const virtualizer = useVirtualizer({
    count: pages.length,
    getScrollElement: () => scrollElement,
    estimateSize: () => itemSize,
    overscan: 4,
    getItemKey: (index) => pages[index]?.id ?? index,
  });
  const measureThumbList = useMemoizedFn(() => virtualizer.measure());

  const virtualItems = virtualizer.getVirtualItems();
  const visibleRangeKey = virtualItems
    .map((item) => item.index)
    .join(",");

  // OverlayScrollbars 就绪后绑定虚拟列表滚动容器
  useLayoutEffect(() => {
    if (sideTab !== "preview") return;

    const bindViewport = () => {
      const osInstance = scrollContainerRef.current?.osInstance?.();
      if (!osInstance) return false;
      const { viewport } = osInstance.elements();
      setScrollElement(viewport);
      requestAnimationFrame(() => measureThumbList());
      return true;
    };

    if (bindViewport()) return;

    const timer = window.setInterval(() => {
      if (bindViewport()) {
        window.clearInterval(timer);
      }
    }, 50);

    return () => window.clearInterval(timer);
  }, [scrollHeight, sideTab, measureThumbList]);

  // 可视区优先生成缩略图
  useEffect(() => {
    if (!visibleRangeKey || pages.length === 0) return;
    const visiblePages = visibleRangeKey
      .split(",")
      .map((index) => pages[Number(index)])
      .filter(Boolean) as Page[];
    scheduleVisibleThumbnails(visiblePages, { immediate: true });
  }, [visibleRangeKey, pages]);

  const scrollToBottom = useMemoizedFn(() => {
    setTimeout(() => {
      if (!scrollContainerRef.current) return;
      const osInstance = scrollContainerRef.current.osInstance();
      if (!osInstance) return;
      const { viewport } = osInstance.elements();
      viewport.scrollTo({
        top: viewport.scrollHeight,
        behavior: "smooth",
      });
    }, 300);
  });

  const handleContextMenu = useMemoizedFn(
    (e: React.MouseEvent, pageId: string) => {
      showPageContextMenu({
        pageId,
        event: e,
        onScrollToBottom: scrollToBottom,
      });
    }
  );

  const handlePageClick = useMemoizedFn((pageId: string) => {
    useFilePreviewStore.getState().close();
    setPageActive(pageId);
    setActiveMenu("start");
    hideMenu();
  });

  const handleAddPage = useMemoizedFn(() => {
    const lastPage = pages[pages.length - 1];
    addPageAndActivate(lastPage?.id, () => {
      scrollToBottom();
    });
  });

  const handlePlayPage = useMemoizedFn(
    (pageId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      enterFullscreen(pageId);
    }
  );

  const handleAddPageAfter = useMemoizedFn(
    (pageId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      addPageAndActivate(pageId, () => {
        scrollToBottom();
      });
    }
  );

  const handleMovePageUp = useMemoizedFn(
    (pageId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      movePage(pageId, "up");
    }
  );

  const handleMovePageDown = useMemoizedFn(
    (pageId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      movePage(pageId, "down");
    }
  );

  const handleDuplicatePage = useMemoizedFn(() => {
    duplicatePageAndActivate(pageActive, () => {
      scrollToBottom();
    });
  });

  const handleDeletePage = useMemoizedFn(() => {
    deletePageAndFallback(pageActive);
  });

  const handleTogglePageVisible = useMemoizedFn(() => {
    if (!pageActive) return;
    togglePageVisible(pageActive);
  });

  const handlePlayActivePage = useMemoizedFn(() => {
    if (!pageActive) return;
    enterFullscreen(pageActive);
  });

  const handleResetPage = useMemoizedFn(() => {
    resetPageElements(pageActive);
  });

  const isInputElement = (target: HTMLElement) => {
    return (
      target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.isContentEditable
    );
  };

  useKeyPress(["ctrl.c"], (e) => {
    const target = e.target as HTMLElement;
    if (!isInputElement(target)) {
      e.preventDefault();
      handleDuplicatePage();
    }
  });

  useKeyPress(["ctrl.d"], (e) => {
    const target = e.target as HTMLElement;
    if (!isInputElement(target)) {
      e.preventDefault();
      handleDeletePage();
    }
  });

  useKeyPress(["ctrl.h"], (e) => {
    const target = e.target as HTMLElement;
    if (!isInputElement(target)) {
      e.preventDefault();
      handleTogglePageVisible();
    }
  });

  useKeyPress(["ctrl.p"], (e) => {
    const target = e.target as HTMLElement;
    if (!isInputElement(target)) {
      e.preventDefault();
      handlePlayActivePage();
    }
  });

  useKeyPress(["ctrl.r"], (e) => {
    const target = e.target as HTMLElement;
    if (!isInputElement(target)) {
      e.preventDefault();
      handleResetPage();
    }
  });

  useEffect(() => {
    if (sideTab !== "preview") return;

    const calculateHeight = () => {
      if (!thumbsPaneRef.current || !addButtonRef.current) return;

      const pane = thumbsPaneRef.current;
      // display:none 时宽高为 0，勿写入，否则会污染虚拟列表间距
      if (pane.clientWidth <= 0 || pane.clientHeight <= 0) return;

      const buttonHeight = addButtonRef.current.offsetHeight;
      const availableHeight = Math.max(pane.clientHeight - buttonHeight, 80);
      setScrollHeight(availableHeight);
      setItemSize(thumbItemSizeForWidth(pane.clientWidth));
    };

    // 等 tab 内容挂载后再量
    const raf = requestAnimationFrame(calculateHeight);
    window.addEventListener("resize", calculateHeight);

    const resizeObserver = new ResizeObserver(calculateHeight);
    if (thumbsPaneRef.current) {
      resizeObserver.observe(thumbsPaneRef.current);
    }
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", calculateHeight);
      resizeObserver.disconnect();
    };
  }, [sideTab]);

  // 宽度变化后强制按新 itemSize 重算偏移，避免叠层
  useEffect(() => {
    if (sideTab !== "preview") return;
    measureThumbList();
  }, [itemSize, pages.length, sideTab, measureThumbList]);

  // 预热：若缓存为空，立刻为前几页生成，减少首次白屏
  useEffect(() => {
    if (pages.length === 0) return;
    const cold = pages
      .slice(0, 8)
      .filter((page) => !getCachedThumbnail(page.id));
    if (cold.length > 0) {
      scheduleVisibleThumbnails(cold, { immediate: true });
    }
  }, [pages]);

  return (
    <div
      ref={containerRef}
      className={`${styles.shell} box-border flex h-full w-full flex-col`}
      style={{ minWidth: 0 }}
    >
      <div
        className={styles.sideTabs}
        role="tablist"
        aria-label="左侧栏视图"
      >
        <button
          type="button"
          role="tab"
          aria-selected={sideTab === "preview"}
          className={`${styles.sideTab} ${sideTab === "preview" ? styles.sideTabActive : ""}`}
          onClick={() => setSideTab("preview")}
        >
          <span className={styles.sideTabIcon} aria-hidden>
            <Images />
          </span>
          <span className={styles.sideTabLabel}>预览</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={sideTab === "files"}
          className={`${styles.sideTab} ${sideTab === "files" ? styles.sideTabActive : ""}`}
          onClick={() => setSideTab("files")}
        >
          <span className={styles.sideTabIcon} aria-hidden>
            <FolderTree />
          </span>
          <span className={styles.sideTabLabel}>文件</span>
        </button>
      </div>

      <div className={styles.panel}>
          <div
            ref={thumbsPaneRef}
            className={`${styles.sidebar} flex min-h-0 flex-1 flex-col pb-2`}
            role="tabpanel"
            aria-hidden={sideTab !== "preview"}
            style={{ display: sideTab === "preview" ? "flex" : "none" }}
          >
            <OverlayScrollbarsComponent
              ref={scrollContainerRef}
              className="min-h-0 flex-1"
              style={{
                height: scrollHeight > 0 ? `${scrollHeight}px` : "100%",
                maxHeight: scrollHeight > 0 ? `${scrollHeight}px` : "100%",
                padding: "8px 0 8px",
                boxSizing: "border-box",
              }}
              options={{
                scrollbars: {
                  theme: "os-theme-light",
                  autoHide: "leave",
                  autoHideDelay: 300,
                },
                overflow: {
                  x: "hidden",
                  y: "scroll",
                },
              }}
            >
              {pages.length > 0 ? (
                <div
                  style={{
                    height: virtualizer.getTotalSize(),
                    width: "100%",
                    position: "relative",
                  }}
                >
                  {virtualItems.map((virtualRow) => {
                    const page = pages[virtualRow.index];
                    if (!page) return null;
                    return (
                      <div
                        key={virtualRow.key}
                        data-index={virtualRow.index}
                        style={{
                          position: "absolute",
                          top: 0,
                          left: 0,
                          width: "100%",
                          height: `${itemSize}px`,
                          transform: `translateY(${virtualRow.start}px)`,
                          paddingBottom: ITEM_GAP,
                          boxSizing: "border-box",
                        }}
                      >
                        <PageItem
                          page={page}
                          index={virtualRow.index}
                          totalPages={pages.length}
                          pageActive={pageActive}
                          onPageClick={handlePageClick}
                          onContextMenu={handleContextMenu}
                          onPlayPage={handlePlayPage}
                          onMovePageUp={handleMovePageUp}
                          onMovePageDown={handleMovePageDown}
                          onAddPageAfter={handleAddPageAfter}
                        />
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="flex h-full items-center justify-center px-[15px] text-sm text-chrome-muted">
                  暂无页面数据
                </div>
              )}
            </OverlayScrollbarsComponent>
            <div ref={addButtonRef} className={styles.addPageWrap}>
              <div
                className={styles.addPageBtn}
                onClick={handleAddPage}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    handleAddPage();
                  }
                }}
              >
                <Add theme="outline" size="15" fill="currentColor" />
                <span>新建幻灯片</span>
              </div>
            </div>
          </div>
          <div
            className={`${styles.sidebar} min-h-0 min-w-0 flex-1 overflow-hidden pt-2 pb-2`}
            role="tabpanel"
            aria-hidden={sideTab !== "files"}
            style={{ display: sideTab === "files" ? "flex" : "none" }}
          >
            <TemplateFileTree />
          </div>
      </div>
    </div>
  );
};

export const Preview: FC = PreviewComponent;
