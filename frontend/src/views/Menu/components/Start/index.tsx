import {
  PanelLargeButton,
  PanelSplitLine,
} from "@/components";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  useDisplayStatusStore,
  useMenuActiveStore,
  usePPTStore,
  usePageActiveStore,
} from "@/store";
import {
  addPageAndActivate,
  duplicatePageAndActivate,
} from "@/utils/operate";
import {
  Add,
  Column,
  Copy,
  Delete,
  PreviewCloseOne,
  PreviewOpen,
  ViewGridCard,
} from "@icon-park/react";
import { useMemoizedFn } from "ahooks";
import { useState, type FC } from "react";
import { useTranslation } from "react-i18next";

/** 页面面板：画布管理 / 视图切换 */
export const Start: FC = () => {
  const { t } = useTranslation();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const pageActive = usePageActiveStore((state) => state.pageActive);
  const pages = usePPTStore((state) => state.pages);
  const getActivePage = usePPTStore((state) => state.getActivePage);
  const deletePage = usePPTStore((state) => state.deletePage);
  const togglePageVisible = usePPTStore((state) => state.togglePageVisible);
  const setPageActive = usePageActiveStore((state) => state.setPageActive);
  const setActiveMenu = useMenuActiveStore((state) => state.setActiveMenu);
  const displayStatus = useDisplayStatusStore((state) => state.displayStatus);
  const setDisplayStatus = useDisplayStatusStore(
    (state) => state.setDisplayStatus,
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

  const handleConfirmDelete = useMemoizedFn(() => {
    if (!pageActive || pages.length <= 1) return;
    const idx = pages.findIndex((p) => p.id === pageActive);
    deletePage(pageActive);
    const next = pages.filter((p) => p.id !== pageActive);
    const nextActive =
      next[Math.min(Math.max(idx, 0), next.length - 1)]?.id ?? null;
    setPageActive(nextActive);
    setDeleteOpen(false);
  });

  const handleTogglePageVisible = useMemoizedFn(() => {
    if (!pageActive) return;
    togglePageVisible(pageActive);
  });

  return (
    <div className="flex h-[53px] items-center gap-[10px]">
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
            <PreviewCloseOne
              theme="outline"
              size="18"
              fill="var(--icon-color)"
            />
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
        onClick={() => setDeleteOpen(true)}
        disabled={!pageActive || pages.length <= 1}
      />
      <PanelSplitLine />
      <PanelLargeButton
        title={t("viewPanel.normalView")}
        active={displayStatus === "default"}
        icon={<Column theme="outline" size="18" fill="var(--icon-color)" />}
        onClick={() => setDisplayStatus("default")}
      />
      <PanelLargeButton
        title={t("viewPanel.slidePreview")}
        active={displayStatus === "grid"}
        icon={
          <ViewGridCard theme="outline" size="18" fill="var(--icon-color)" />
        }
        onClick={() => setDisplayStatus("grid")}
      />

      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("startPanel.confirmDeleteCanvas")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("startPanel.confirmDeleteCanvas")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleConfirmDelete}
            >
              {t("common.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};
