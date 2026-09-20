import { PanelLargeButton } from "@/components";
import { useDisplayStatusStore } from "@/store";
import { Column, ViewGridCard } from "@icon-park/react";
import type { FC } from "react";
import { useTranslation } from "react-i18next";

/** 轻量化视图：普通编辑 / 幻灯片总览（无网格线 / 标尺 / 参考线） */
export const View: FC = () => {
  const { t } = useTranslation();
  const displayStatus = useDisplayStatusStore((state) => state.displayStatus);
  const setDisplayStatus = useDisplayStatusStore(
    (state) => state.setDisplayStatus
  );

  return (
    <div className="h-[53px] flex items-center gap-[10px]">
      <PanelLargeButton
        onClick={() => {
          setDisplayStatus("default");
        }}
        active={displayStatus === "default"}
        icon={<Column theme="outline" size="18" fill="var(--icon-color)" />}
        title={t("viewPanel.normalView")}
      />
      <PanelLargeButton
        onClick={() => {
          setDisplayStatus("grid");
        }}
        active={displayStatus === "grid"}
        icon={<ViewGridCard theme="outline" size="18" fill="var(--icon-color)" />}
        title={t("viewPanel.slidePreview")}
      />
    </div>
  );
};
