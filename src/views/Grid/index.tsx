import { CANVAS_ASPECT_RATIO_CSS } from "@/constants/canvas";
import {
  useDisplayStatusStore,
  useMenuActiveStore,
  usePageActiveStore,
  usePPTStore,
} from "@/store";
import type { Page } from "@/store/ppt";
import { showPageContextMenu } from "@/utils/pageContextMenu";
import {
  scheduleVisibleThumbnails,
  usePageThumbnail,
  usePageThumbnailLoading,
} from "@/utils/pageThumbnail";
import { PreviewCloseOne } from "@icon-park/react";
import { useMemoizedFn } from "ahooks";
import { Spin } from "antd";
import {
  memo,
  type FC,
  useEffect,
  useRef,
} from "react";

const GridThumbCard: FC<{
  page: Page;
  index: number;
  active: boolean;
  onClick: (pageId: string) => void;
  onContextMenu: (e: React.MouseEvent, pageId: string) => void;
}> = memo(({ page, index, active, onClick, onContextMenu }) => {
  const thumbnailUrl = usePageThumbnail(page);
  const isLoading = usePageThumbnailLoading(page);

  return (
    <div className="flex flex-col items-center cursor-pointer group">
      <div
        className={`grid-card relative w-full bg-chrome-thumb rounded-[6px] overflow-hidden transition-shadow ${
          active
            ? "shadow-[0_0_0_2px_var(--primary-color)]"
            : "shadow-[0_0_0_1px_var(--thumb-border)] group-hover:shadow-[0_0_0_1px_var(--thumb-border-hover)]"
        }`}
        style={{ aspectRatio: CANVAS_ASPECT_RATIO_CSS }}
        onClick={() => onClick(page.id)}
        onContextMenu={(e) => onContextMenu(e, page.id)}
      >
        {thumbnailUrl ? (
          <img
            src={thumbnailUrl}
            alt={`幻灯片 ${index + 1}`}
            className="absolute inset-0 w-full h-full object-fill pointer-events-none"
            draggable={false}
          />
        ) : (
          <div className="absolute inset-0 bg-[linear-gradient(90deg,var(--skeleton-from)_25%,var(--skeleton-mid)_37%,var(--skeleton-from)_63%)] bg-[length:400%_100%] animate-pulse" />
        )}
        {!thumbnailUrl && isLoading && (
          <div className="absolute inset-0 z-[2] flex items-center justify-center bg-black/5">
            <Spin size="small" />
          </div>
        )}
        {page.visible === false && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/10 z-[3]">
            <PreviewCloseOne
              theme="outline"
              size="24"
              fill="var(--icon-color)"
            />
          </div>
        )}
      </div>
      <span
        className={`mt-[8px] text-[13px] ${
          active ? "text-primary font-semibold" : "text-chrome-muted"
        }`}
      >
        幻灯片 {index + 1}
      </span>
    </div>
  );
});
GridThumbCard.displayName = "GridThumbCard";

const GridComponent: FC = () => {
  const pages = usePPTStore((state) => state.pages);
  const pageActive = usePageActiveStore((state) => state.pageActive);
  const setPageActive = usePageActiveStore((state) => state.setPageActive);
  const setDisplayStatus = useDisplayStatusStore(
    (state) => state.setDisplayStatus
  );
  const setActiveMenu = useMenuActiveStore((state) => state.setActiveMenu);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleContextMenu = useMemoizedFn(
    (e: React.MouseEvent, pageId: string) => {
      showPageContextMenu({ pageId, event: e });
    }
  );

  const handleClick = useMemoizedFn((pageId: string) => {
    setPageActive(pageId);
    setDisplayStatus("default");
    setActiveMenu("start");
  });

  // 进入网格预览：优先为当前可见页生成静态缩略图（串行离屏 iframe，避免 N 路同时加载）
  useEffect(() => {
    if (pages.length === 0) return;
    scheduleVisibleThumbnails(pages.slice(0, 12), { immediate: true });

    const root = containerRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return;

    const cardByEl = new Map<Element, Page>();
    const cards = root.querySelectorAll(".grid-card");
    pages.forEach((page, i) => {
      const el = cards[i];
      if (el) cardByEl.set(el, page);
    });

    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .map((e) => cardByEl.get(e.target))
          .filter(Boolean) as Page[];
        if (visible.length > 0) {
          scheduleVisibleThumbnails(visible, { immediate: true });
        }
      },
      { root, rootMargin: "120px", threshold: 0.01 }
    );

    cards.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [pages]);

  return (
    <div ref={containerRef} className="flex-1 min-h-0 overflow-auto p-[20px]">
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-[20px]">
        {pages.map((page: Page, index: number) => (
          <GridThumbCard
            key={page.id}
            page={page}
            index={index}
            active={pageActive === page.id}
            onClick={handleClick}
            onContextMenu={handleContextMenu}
          />
        ))}
      </div>
    </div>
  );
};

export const Grid: FC = GridComponent;
