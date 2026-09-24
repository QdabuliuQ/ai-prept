import KeyboardIcon from "@/components/KeyboardIcon";
import type { MenuItem } from "@/hooks/useContextMenu";
import i18n from "@/i18n";
import { contextMenuStore, fullscreenStore, pptStore } from "@/store";
import {
  addPageAndActivate,
  deletePageAndFallback,
  duplicatePageAndActivate,
  resetPageElements,
} from "@/utils/operate";
import {
  Add,
  ArrowDown,
  ArrowUp,
  BringForward,
  Clear,
  Copy,
  Delete,
  Export,
  Play,
  PreviewCloseOne,
  PreviewOpen,
  SendBackward,
} from "@icon-park/react";
import { downloadImage, exportPageAsImage, formatKeysForDevice } from "./tool";

interface ShowPageContextMenuOptions {
  pageId: string;
  event: React.MouseEvent;
  onScrollToBottom?: () => void;
}

/**
 * 显示页面右键菜单
 * @param options - 菜单选项
 */
export const showPageContextMenu = (options: ShowPageContextMenuOptions) => {
  const { pageId, event, onScrollToBottom } = options;

  event.preventDefault();
  event.stopPropagation();

  const pages = pptStore.getPages();
  const pageIndex = pages.findIndex((p) => p.id === pageId);
  const currentPage = pages[pageIndex];
  const isFirstPage = pageIndex === 0;
  const isLastPage = pageIndex === pages.length - 1;
  const isVisible = currentPage?.visible !== false;

  const t = i18n.t.bind(i18n);

  const menuItems: MenuItem[] = [
    {
      type: "item" as const,
      label: t("contextMenu.newSlide"),
      icon: <Add theme="outline" size="13" fill="var(--icon-color)" />,
      onClick: () => {
        addPageAndActivate(pageId);
        contextMenuStore.hideMenu();
        onScrollToBottom?.();
      },
    },
    {
      type: "item" as const,
      label: t("contextMenu.duplicateSlide"),
      icon: <Copy theme="outline" size="13" fill="var(--icon-color)" />,
      onClick: () => {
        duplicatePageAndActivate(pageId);
        contextMenuStore.hideMenu();
        onScrollToBottom?.();
      },
      tip: <KeyboardIcon keys={formatKeysForDevice(["Control", "C"])} />,
    },
    {
      type: "item" as const,
      label: t("contextMenu.deleteSlide"),
      icon: <Delete theme="outline" size="13" fill="var(--icon-color)" />,
      onClick: () => {
        deletePageAndFallback(pageId);
        contextMenuStore.hideMenu();
      },
      disabled: pages.length <= 1,
      tip: <KeyboardIcon keys={formatKeysForDevice(["Control", "D"])} />,
    },
    {
      type: "item" as const,
      label: isVisible
        ? t("contextMenu.hideSlide")
        : t("contextMenu.showSlide"),
      icon: isVisible ? (
        <PreviewCloseOne theme="outline" size="13" fill="var(--icon-color)" />
      ) : (
        <PreviewOpen theme="outline" size="13" fill="var(--icon-color)" />
      ),
      onClick: () => {
        pptStore.togglePageVisible(pageId);
        contextMenuStore.hideMenu();
      },
      tip: <KeyboardIcon keys={formatKeysForDevice(["Control", "H"])} />,
    },
    {
      type: "separator",
    },
    {
      type: "item" as const,
      label: t("contextMenu.playSlide"),
      icon: <Play theme="outline" size="13" fill="var(--icon-color)" />,
      onClick: () => {
        fullscreenStore.enterFullscreen(pageId);
        contextMenuStore.hideMenu();
      },
      tip: <KeyboardIcon keys={formatKeysForDevice(["Control", "P"])} />,
      disabled: !isVisible,
    },
    {
      type: "item" as const,
      label: t("contextMenu.resetSlide"),
      icon: <Clear theme="outline" size="13" fill="var(--icon-color)" />,
      onClick: () => {
        resetPageElements(pageId);
        contextMenuStore.hideMenu();
      },
      tip: <KeyboardIcon keys={formatKeysForDevice(["Control", "R"])} />,
    },
    {
      type: "item" as const,
      label: t("contextMenu.exportImage"),
      icon: <Export theme="outline" size="13" fill="var(--icon-color)" />,
      onClick: async () => {
        const dataUrl = await exportPageAsImage(pageId);
        if (dataUrl) {
          const name = pptStore.getName();
          downloadImage(
            dataUrl,
            `${name || t("contextMenu.untitled")}_${pageId}.png`
          );
        }
        contextMenuStore.hideMenu();
      },
    },
    {
      type: "separator",
    },
    {
      type: "item" as const,
      label: t("contextMenu.moveUp"),
      icon: <ArrowUp theme="outline" size="13" fill="var(--icon-color)" />,
      onClick: () => {
        pptStore.movePage(pageId, "up");
        contextMenuStore.hideMenu();
      },
      disabled: isFirstPage,
    },
    {
      type: "item" as const,
      label: t("contextMenu.moveDown"),
      icon: <ArrowDown theme="outline" size="13" fill="var(--icon-color)" />,
      onClick: () => {
        pptStore.movePage(pageId, "down");
        contextMenuStore.hideMenu();
      },
      disabled: isLastPage,
    },
    {
      type: "item" as const,
      label: t("contextMenu.moveToFirst"),
      icon: <BringForward theme="outline" size="13" fill="var(--icon-color)" />,
      onClick: () => {
        pptStore.movePage(pageId, "first");
        contextMenuStore.hideMenu();
      },
      disabled: isFirstPage,
    },
    {
      type: "item" as const,
      label: t("contextMenu.moveToLast"),
      icon: <SendBackward theme="outline" size="13" fill="var(--icon-color)" />,
      onClick: () => {
        pptStore.movePage(pageId, "last");
        contextMenuStore.hideMenu();
      },
      disabled: isLastPage,
    },
  ];

  contextMenuStore.showMenu(event.clientX, event.clientY, menuItems);
};
