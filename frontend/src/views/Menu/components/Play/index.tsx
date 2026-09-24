import { PanelLargeButton, PanelSplitLine } from "@/components";
import {
  useFullscreenStore,
  usePageActiveStore,
  usePPTStore,
  useRemarkEditActiveStore,
} from "@/store";
import {
  Notes,
  Play as PlayIcon,
  PreviewCloseOne,
  PreviewOpen,
  SlideTwo,
} from "@icon-park/react";
import { useMemoizedFn } from "ahooks";
import { message } from "antd";
import { type FC } from "react";
import { useTranslation } from "react-i18next";

export const PlayComponent: FC = () => {
  const { t } = useTranslation();
  const pages = usePPTStore((state) => state.pages);
  const pageActive = usePageActiveStore((state) => state.pageActive);
  const getActivePage = usePPTStore((state) => state.getActivePage);
  const togglePageVisible = usePPTStore((state) => state.togglePageVisible);
  const remarkEditActive = useRemarkEditActiveStore(
    (state) => state.remarkEditActive
  );
  const toggleRemarkEditActive = useRemarkEditActiveStore(
    (state) => state.toggleRemarkEditActive
  );
  const enterFullscreen = useFullscreenStore((state) => state.enterFullscreen);

  const handleStartPlay = useMemoizedFn(() => {
    if (pages.length === 0) {
      message.error(t("playPanel.noPages"));
      return;
    }
    enterFullscreen(pages[0].id);
  });

  const handleCurrentPlay = useMemoizedFn(() => {
    if (!pageActive) {
      message.error(t("playPanel.noCurrentPage"));
      return;
    }
    enterFullscreen(pageActive);
  });

  const page = pageActive ? getActivePage(pageActive) : null;

  const handleTogglePageVisible = useMemoizedFn(() => {
    if (!page) return;
    togglePageVisible(page.id);
  });

  const handleToggleRemark = useMemoizedFn(() => {
    toggleRemarkEditActive();
  });

  return (
    <div className="h-[53px] flex items-center gap-[10px]">
      <PanelLargeButton
        title={t("playPanel.fromStart")}
        icon={<SlideTwo theme="outline" size="18" fill="var(--icon-color)" />}
        onClick={handleStartPlay}
      />
      <PanelLargeButton
        title={t("playPanel.fromCurrent")}
        icon={<PlayIcon theme="outline" size="18" fill="var(--icon-color)" />}
        onClick={handleCurrentPlay}
      />
      <PanelSplitLine />
      <PanelLargeButton
        title={
          page?.visible
            ? t("contextMenu.hideSlide")
            : t("contextMenu.showSlide")
        }
        icon={
          page?.visible ? (
            <PreviewCloseOne theme="outline" size="18" fill="var(--icon-color)" />
          ) : (
            <PreviewOpen theme="outline" size="18" fill="var(--icon-color)" />
          )
        }
        onClick={handleTogglePageVisible}
      />
      <PanelLargeButton
        title={
          remarkEditActive
            ? t("playPanel.closeRemark")
            : t("playPanel.openRemark")
        }
        icon={<Notes theme="outline" size="18" fill="var(--icon-color)" />}
        onClick={handleToggleRemark}
      />
    </div>
  );
};

export const Play: FC = PlayComponent;
