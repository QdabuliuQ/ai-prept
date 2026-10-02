import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Slider } from "@/components/ui/slider";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useCanvasZoomStore,
  useDisplayStatusStore,
  useFullscreenStore,
  usePageActiveStore,
  usePPTStore,
  useRemarkEditActiveStore,
} from "@/store";
import {
  Aiming,
  Column,
  Down,
  Notes,
  Play,
  PlayOne,
  SlideTwo,
  ViewGridCard,
} from "@icon-park/react";
import { useMemoizedFn } from "ahooks";
import { useMemo, type FC } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import styles from "./index.module.less";

const FooterComponent: FC = () => {
  const { t } = useTranslation();
  const pages = usePPTStore((state) => state.pages);
  const pageActive = usePageActiveStore((state) => state.pageActive);
  const displayStatus = useDisplayStatusStore((state) => state.displayStatus);
  const setDisplayStatus = useDisplayStatusStore(
    (state) => state.setDisplayStatus,
  );
  const remarkEditActive = useRemarkEditActiveStore(
    (state) => state.remarkEditActive,
  );
  const toggleRemarkEditActive = useRemarkEditActiveStore(
    (state) => state.toggleRemarkEditActive,
  );
  const enterFullscreen = useFullscreenStore((state) => state.enterFullscreen);
  const zoomPercent = useCanvasZoomStore((state) => state.zoomPercent);
  const setZoomPercent = useCanvasZoomStore((state) => state.setZoomPercent);
  const resetViewport = useCanvasZoomStore((state) => state.resetViewport);

  const pageIndex = pages.findIndex((p) => p.id === pageActive);

  const handleToggleRemark = useMemoizedFn(() => {
    toggleRemarkEditActive();
  });

  const handlePlay = useMemoizedFn(() => {
    if (!pageActive) {
      toast.error(t("playPanel.noCurrentPage"));
      return;
    }
    enterFullscreen(pageActive);
  });

  const handlePlayFromFirst = useMemoizedFn(() => {
    if (pages.length === 0) {
      toast.error(t("playPanel.noPages"));
      return;
    }
    enterFullscreen(pages[0].id);
  });

  const handlePlayFromCurrent = useMemoizedFn(() => {
    if (!pageActive) {
      toast.error(t("playPanel.noCurrentPage"));
      return;
    }
    enterFullscreen(pageActive);
  });

  const playItems = useMemo(
    () => [
      {
        key: "playFirst",
        label: t("footer.fromStart"),
        icon: <SlideTwo theme="outline" size="15" fill="currentColor" />,
        onSelect: handlePlayFromFirst,
      },
      {
        key: "playCurrent",
        label: t("footer.fromCurrent"),
        icon: <Play theme="outline" size="15" fill="currentColor" />,
        onSelect: handlePlayFromCurrent,
      },
    ],
    [handlePlayFromFirst, handlePlayFromCurrent, t],
  );

  return (
    <div className={styles.footer}>
      <div className={styles.left}>
        <div className={styles.slideCount}>
          {t("footer.slideCount", {
            current: Math.max(pageIndex + 1, 1),
            total: pages.length || 1,
          })}
        </div>
      </div>
      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.remarkBtn} ${remarkEditActive ? styles.remarkActive : ""}`}
          onClick={handleToggleRemark}
        >
          <Notes
            theme="outline"
            size="14"
            fill={
              remarkEditActive
                ? "var(--primary-color)"
                : "var(--text-secondary)"
            }
          />
          <span>{t("footer.remark")}</span>
        </button>

        <div className={styles.divider} />

        <div className={styles.playGroup}>
          <button type="button" className={styles.playBtn} onClick={handlePlay}>
            <PlayOne theme="filled" size="14" fill="#fff" />
            <span>{t("footer.play")}</span>
          </button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={styles.playCaret}
                aria-label={t("footer.playOptions")}
              >
                <Down theme="outline" size="12" fill="#fff" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" side="top" className="text-[12px]">
              {playItems.map((item) => (
                <DropdownMenuItem
                  key={item.key}
                  className="gap-2 text-[12px]"
                  onSelect={item.onSelect}
                >
                  {item.icon}
                  {item.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className={styles.divider} />

        <div className={styles.viewToggles}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className={`${styles.viewBtn} ${displayStatus === "default" ? styles.viewActive : ""}`}
                onClick={() => setDisplayStatus("default")}
              >
                <Column
                  theme="outline"
                  size="15"
                  fill={
                    displayStatus === "default"
                      ? "var(--primary-color)"
                      : "var(--text-secondary)"
                  }
                />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">{t("viewPanel.normalView")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className={`${styles.viewBtn} ${displayStatus === "grid" ? styles.viewActive : ""}`}
                onClick={() => setDisplayStatus("grid")}
              >
                <ViewGridCard
                  theme="outline"
                  size="15"
                  fill={
                    displayStatus === "grid"
                      ? "var(--primary-color)"
                      : "var(--text-secondary)"
                  }
                />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">
              {t("viewPanel.slidePreview")}
            </TooltipContent>
          </Tooltip>
        </div>

        {displayStatus === "default" && (
          <>
            <div className={styles.divider} />
            <div className={styles.zoomControl}>
              <Slider
                className={styles.zoomSlider}
                min={10}
                max={200}
                step={1}
                value={[zoomPercent]}
                onValueChange={(vals) => setZoomPercent(vals[0] ?? zoomPercent)}
                aria-label="zoom"
              />
              <span className={styles.zoomLabel}>{zoomPercent}%</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className={styles.viewBtn}
                    onClick={resetViewport}
                    aria-label={t("footer.resetViewport")}
                  >
                    <Aiming
                      theme="outline"
                      size="15"
                      fill="var(--text-secondary)"
                    />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top">
                  {t("footer.resetViewport")}
                </TooltipContent>
              </Tooltip>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export const Footer: FC = FooterComponent;
