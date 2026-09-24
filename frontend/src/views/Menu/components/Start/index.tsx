import {
  PanelLargeButton,
  PanelSplitLine,
} from "@/components";
import ThemePalettePanel, {
  THEME_PANEL_SECTION_KEY,
} from "@/components/ThemePalettePanel";
import {
  useMenuActiveStore,
  usePPTStore,
  usePageActiveStore,
} from "@/store";
import { useChartInspectorStore } from "@/store/zustand/chartInspectorStore";
import {
  addPageAndActivate,
  duplicatePageAndActivate,
} from "@/utils/operate";
import {
  Add,
  ColorCard,
  Copy,
  Delete,
  PreviewCloseOne,
  PreviewOpen,
} from "@icon-park/react";
import { useMemoizedFn } from "ahooks";
import { Modal } from "antd";
import type { FC } from "react";
import { useTranslation } from "react-i18next";

/** 轻量化开始面板：页面管理 + 主题（无插入元素 / 背景编辑） */
export const Start: FC = () => {
  const { t } = useTranslation();
  const [modal, contextHolder] = Modal.useModal();
  const pageActive = usePageActiveStore((state) => state.pageActive);
  const pages = usePPTStore((state) => state.pages);
  const getActivePage = usePPTStore((state) => state.getActivePage);
  const deletePage = usePPTStore((state) => state.deletePage);
  const togglePageVisible = usePPTStore((state) => state.togglePageVisible);
  const setPageActive = usePageActiveStore((state) => state.setPageActive);
  const setActiveMenu = useMenuActiveStore((state) => state.setActiveMenu);
  const toggleThemeSection = useChartInspectorStore(
    (state) => state.toggleSection
  );

  const currentPage = pageActive ? getActivePage(pageActive) : null;
  const isPageVisible = currentPage?.visible !== false;

  const handleAddPage = useMemoizedFn(() => {
    if (!pageActive) return;
    addPageAndActivate(pageActive);
    setActiveMenu("start");
  });

  const handleDuplicatePage = useMemoizedFn(() => {
    if (!pageActive) return;
    duplicatePageAndActivate(pageActive);
  });

  const handleDeletePage = useMemoizedFn(() => {
    if (!pageActive || pages.length <= 1) return;
    modal.confirm({
      title: t("startPanel.confirmDeleteCanvas"),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: () => {
        const idx = pages.findIndex((p) => p.id === pageActive);
        deletePage(pageActive);
        const next = pages.filter((p) => p.id !== pageActive);
        const nextActive =
          next[Math.min(Math.max(idx, 0), next.length - 1)]?.id ?? null;
        setPageActive(nextActive);
      },
    });
  });

  const handleTogglePageVisible = useMemoizedFn(() => {
    if (!pageActive) return;
    togglePageVisible(pageActive);
  });

  return (
    <div className="flex items-center h-[53px] gap-[10px]">
      {contextHolder}
      <ThemePalettePanel />
      <PanelLargeButton
        title={t("startPanel.theme")}
        icon={<ColorCard theme="outline" size="18" fill="var(--icon-color)" />}
        onClick={() =>
          toggleThemeSection(
            THEME_PANEL_SECTION_KEY,
            t("startPanel.themePanelTitle")
          )
        }
      />
      <PanelSplitLine />
      <PanelLargeButton
        title={t("startPanel.newCanvas")}
        icon={<Add theme="outline" size="18" fill="var(--icon-color)" />}
        onClick={handleAddPage}
        disabled={!pageActive}
      />
      <PanelLargeButton
        title={t("startPanel.duplicateCanvas")}
        icon={<Copy theme="outline" size="18" fill="var(--icon-color)" />}
        onClick={handleDuplicatePage}
        disabled={!pageActive}
      />
      <PanelLargeButton
        title={
          isPageVisible
            ? t("contextMenu.hideSlide")
            : t("contextMenu.showSlide")
        }
        icon={
          isPageVisible ? (
            <PreviewCloseOne theme="outline" size="18" fill="var(--icon-color)" />
          ) : (
            <PreviewOpen theme="outline" size="18" fill="var(--icon-color)" />
          )
        }
        onClick={handleTogglePageVisible}
        disabled={!pageActive}
      />
      <PanelLargeButton
        title={t("startPanel.deleteCanvas")}
        icon={<Delete theme="outline" size="18" fill="var(--icon-color)" />}
        onClick={handleDeletePage}
        disabled={!pageActive || pages.length <= 1}
      />
    </div>
  );
};
