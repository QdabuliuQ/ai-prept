import styles from "@/components/SideInspector/panel.module.less";
import { usePPTStore } from "@/store";
import { useChartInspectorStore } from "@/store/zustand/chartInspectorStore";
import {
  THEME_PRESETS,
  themeSwatchColors,
  toThemeToken,
  type ThemePreset,
} from "@/theme";
import { useMemoizedFn } from "ahooks";
import { type FC } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

export const THEME_PANEL_SECTION_KEY = "ppt-theme";

/** 右侧主题色面板内容（portal 到 Side Inspector） */
export const ThemePalettePanel: FC = () => {
  const { t } = useTranslation();
  const applyTheme = usePPTStore((s) => s.applyTheme);
  const sectionKey = useChartInspectorStore((s) => s.sectionKey);
  const contentEl = useChartInspectorStore((s) => s.contentEl);

  const onSelect = useMemoizedFn((preset: ThemePreset) => {
    applyTheme(toThemeToken(preset));
  });

  if (sectionKey !== THEME_PANEL_SECTION_KEY || !contentEl) return null;

  const content = (
    <div className={styles.inspectorForm}>
      <div className="text-[12px] text-chrome-secondary mb-[10px] leading-snug">
        {t("startPanel.themeHint")}
      </div>
      <div className="flex flex-col gap-[8px] max-h-[calc(100vh-220px)] overflow-y-auto pr-[2px]">
        {THEME_PRESETS.map((preset) => {
          const colors = themeSwatchColors(preset);
          return (
            <button
              key={preset.id}
              type="button"
              onClick={() => onSelect(preset)}
              className="w-full text-left rounded-[10px] border border-[var(--border-default)] p-[8px] transition-colors hover:border-[var(--primary-color)]"
            >
              <div className="flex items-center justify-between gap-[8px] mb-[6px]">
                <span className="text-[12px] font-medium text-chrome-text truncate">
                  {preset.templateName}
                </span>
                <span className="text-[10px] text-chrome-muted shrink-0">
                  {preset.category}
                </span>
              </div>
              <div className="flex h-[22px] w-full overflow-hidden rounded-[6px] border border-[rgba(0,0,0,0.06)]">
                {colors.map((c, i) => (
                  <span
                    key={`${preset.id}-${i}`}
                    className="flex-1"
                    style={{ background: c }}
                    title={c}
                  />
                ))}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );

  return createPortal(content, contentEl);
};

export default ThemePalettePanel;
