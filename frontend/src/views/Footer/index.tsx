import {
  useCanvasZoomStore,
  useDisplayStatusStore,
  useFullscreenStore,
  usePageActiveStore,
  usePPTStore,
  useRemarkEditActiveStore,
} from "@/store";
import {
  Column,
  Down,
  Notes,
  Play,
  PlayOne,
  SlideTwo,
  ViewGridCard,
} from "@icon-park/react";
import { useMemoizedFn } from "ahooks";
import { Dropdown, message, Slider, Tooltip } from "antd";
import { useMemo, type FC } from "react";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

const FooterComponent: FC = () => {
  const { t } = useTranslation();
  const pages = usePPTStore((state) => state.pages);
  const pageActive = usePageActiveStore((state) => state.pageActive);
  const displayStatus = useDisplayStatusStore((state) => state.displayStatus);
  const setDisplayStatus = useDisplayStatusStore(
    (state) => state.setDisplayStatus
  );
  const remarkEditActive = useRemarkEditActiveStore(
    (state) => state.remarkEditActive
  );
  const toggleRemarkEditActive = useRemarkEditActiveStore(
    (state) => state.toggleRemarkEditActive
  );
  const enterFullscreen = useFullscreenStore((state) => state.enterFullscreen);
  const zoomPercent = useCanvasZoomStore((state) => state.zoomPercent);
  const setZoomPercent = useCanvasZoomStore((state) => state.setZoomPercent);

  const pageIndex = pages.findIndex((p) => p.id === pageActive);

  const handleToggleRemark = useMemoizedFn(() => {
    toggleRemarkEditActive();
  });

  const handlePlay = useMemoizedFn(() => {
    if (!pageActive) {
      message.error(t("playPanel.noCurrentPage"));
      return;
    }
    enterFullscreen(pageActive);
  });

  const handlePlayFromFirst = useMemoizedFn(() => {
    if (pages.length === 0) {
      message.error(t("playPanel.noPages"));
      return;
    }
    enterFullscreen(pages[0].id);
  });

  const handlePlayFromCurrent = useMemoizedFn(() => {
    if (!pageActive) {
      message.error(t("playPanel.noCurrentPage"));
      return;
    }
    enterFullscreen(pageActive);
  });

  const playDropDownMenu = useMemo(
    () => [
      {
        key: "playFirst",
        label: t("footer.fromStart"),
        icon: <SlideTwo theme="outline" size="15" fill="currentColor" />,
        onClick: handlePlayFromFirst,
      },
      {
        key: "playCurrent",
        label: t("footer.fromCurrent"),
        icon: <Play theme="outline" size="15" fill="currentColor" />,
        onClick: handlePlayFromCurrent,
      },
    ],
    [handlePlayFromFirst, handlePlayFromCurrent, t]
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
          <Dropdown placement="topRight" menu={{ items: playDropDownMenu }}>
            <button
              type="button"
              className={styles.playCaret}
              aria-label={t("footer.playOptions")}
            >
              <Down theme="outline" size="12" fill="#fff" />
            </button>
          </Dropdown>
        </div>

        <div className={styles.divider} />

        <div className={styles.viewToggles}>
          <Tooltip title={t("viewPanel.normalView")}>
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
          </Tooltip>
          <Tooltip title={t("viewPanel.slidePreview")}>
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
                value={zoomPercent}
                onChange={setZoomPercent}
                tooltip={{ formatter: (value) => `${value}%` }}
              />
              <span className={styles.zoomLabel}>{zoomPercent}%</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export const Footer: FC = FooterComponent;
