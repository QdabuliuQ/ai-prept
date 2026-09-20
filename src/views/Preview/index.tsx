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
  usePageThumbnailLoading,
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
import { Spin } from "antd";
import { OverlayScrollbarsComponent } from "overlayscrollbars-react";
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
 * 高度按画布 10:7 推算，再加底部 gap。
 */
const PREVIEW_THUMB_WIDTH_EST = 180;
const ITEM_GAP = 14;
const ESTIMATED_ITEM_SIZE =
  Math.round(PREVIEW_THUMB_WIDTH_EST / CANVAS_ASPECT_RATIO) + ITEM_GAP;

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
    const isLoading = usePageThumbnailLoading(page);

    return (
      <div
        className={`${styles.pageItem} relative cursor-pointer flex gap-[8px]`}
      >
        <span
          className={`${styles.pageIndex} text-[12px] mt-[4px] font-medium ${
            isActive ? "text-primary" : "text-chrome-muted"
          }`}
        >
          {index + 1}
        </span>
        <div
          className={`${styles.thumbWrap} ${isActive ? styles.thumbActive : styles.thumbInactive}`}
          onClick={() => onPageClick(page.id)}
          onContextMenu={(e) => onContextMenu(e, page.id)}
        >
          <div
            className="previewCanvas relative w-full rounded-[8px] overflow-hidden pointer-events-none bg-chrome-guide"
            style={{ aspectRatio: CANVAS_ASPECT_RATIO_CSS }}
          >
            {thumbnailUrl ? (
              <img
                src={thumbnailUrl}
                alt={`slide-${index + 1}`}
                className="absolute inset-0 w-full h-full object-fill"
                draggable={false}
              />
            ) : (
              <div className={styles.thumbSkeleton} />
            )}
            {!thumbnailUrl && isLoading && (
              <div className={styles.thumbLoading}>
                <Spin size="small" />
              </div>
            )}
            {page.visible === false && (
              <div
                className="absolute top-0 left-0 w-full h-full flex items-center justify-center bg-black/10 rounded-[8px] z-10 pointer-events-auto"
                onClick={() => onPageClick(page.id)}
                onContextMenu={(e) => onContextMenu(e, page.id)}
              >
                <PreviewCloseOne theme="outline" size="24" fill="var(--icon-color)" />
              </div>
            )}
          </div>
        </div>
        <div className="floatButton absolute bottom-[-10px] right-[16px] z-10 w-[78%] flex items-center justify-between opacity-0 transition-opacity">
          <div>
            {page.visible && (
              <div
                className={`${styles.floatAction} bg-chrome-panel-solid`}
                onClick={(e) => onPlayPage(page.id, e)}
              >
                <PlayOne theme="filled" size="16" fill="#f25f00" />
              </div>
            )}
          </div>
          <div className="flex items-center gap-[8px]">
            {index > 0 && (
              <div
                className={`${styles.floatAction} bg-primary`}
                onClick={(e) => onMovePageUp(page.id, e)}
              >
                <Up theme="outline" size="16" fill="#fff" />
              </div>
            )}
            {index < totalPages - 1 && (
              <div
                className={`${styles.floatAction} bg-primary`}
                onClick={(e) => onMovePageDown(page.id, e)}
              >
                <Down theme="outline" size="16" fill="#fff" />
              </div>
            )}
            <div
              className={`${styles.floatAction} bg-primary`}
              onClick={(e) => onAddPageAfter(page.id, e)}
            >
              <Plus theme="outline" size="16" fill="#fff" />
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
  const addButtonRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<any>(null);
  const [scrollHeight, setScrollHeight] = useState(0);
  const [scrollElement, setScrollElement] = useState<HTMLElement | null>(null);

  const virtualizer = useVirtualizer({
    count: pages.length,
    getScrollElement: () => scrollElement,
    estimateSize: () => ESTIMATED_ITEM_SIZE,
    overscan: 4,
    getItemKey: (index) => pages[index]?.id ?? index,
  });

  const virtualItems = virtualizer.getVirtualItems();
  const visibleRangeKey = virtualItems
    .map((item) => item.index)
    .join(",");

  // OverlayScrollbars 就绪后绑定虚拟列表滚动容器
  useLayoutEffect(() => {
    const bindViewport = () => {
      const osInstance = scrollContainerRef.current?.osInstance?.();
      if (!osInstance) return false;
      const { viewport } = osInstance.elements();
      setScrollElement(viewport);
      return true;
    };

    if (bindViewport()) return;

    const timer = window.setInterval(() => {
      if (bindViewport()) {
        window.clearInterval(timer);
      }
    }, 50);

    return () => window.clearInterval(timer);
  }, [scrollHeight]);

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
    const calculateHeight = () => {
      if (!containerRef.current || !addButtonRef.current) return;

      const containerHeight = containerRef.current.offsetHeight;
      const buttonHeight = addButtonRef.current.offsetHeight;
      const availableHeight = containerHeight - buttonHeight;

      setScrollHeight(availableHeight);
    };

    calculateHeight();
    window.addEventListener("resize", calculateHeight);

    const resizeObserver = new ResizeObserver(calculateHeight);
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      window.removeEventListener("resize", calculateHeight);
      resizeObserver.disconnect();
    };
  }, []);

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
      className={`${styles.sidebar} w-full h-full box-border flex flex-col pb-[12px] pt-[12px]`}
      style={{ minWidth: 0, overflow: "hidden" }}
    >
      <OverlayScrollbarsComponent
        ref={scrollContainerRef}
        className="flex-1"
        style={{
          height: scrollHeight > 0 ? `${scrollHeight}px` : "100%",
          maxHeight: scrollHeight > 0 ? `${scrollHeight}px` : "100%",
          padding: "10px 0",
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
                  ref={virtualizer.measureElement}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
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
          <div className="flex items-center justify-center h-full text-chrome-muted text-sm px-[15px]">
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
  );
};

export const Preview: FC = PreviewComponent;
