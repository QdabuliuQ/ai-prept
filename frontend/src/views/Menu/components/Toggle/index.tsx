import {
  PanelItemSelect,
  PanelLargeButton,
  PanelSelect,
  PanelSplitLine,
} from "@/components";
import { usePageActiveStore, usePPTStore } from "@/store/zustand";
import { FullSelection } from "@icon-park/react";
import { useMemoizedFn } from "ahooks";
import { Checkbox, InputNumber, message } from "antd";
import { useMemo, useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

const TOGGLE_ANIMATION_TYPES = [
  "",
  "backInDown",
  "backInLeft",
  "backInRight",
  "backInUp",
  "bounceIn",
  "bounceInDown",
  "bounceInLeft",
  "bounceInRight",
  "bounceInUp",
  "fadeIn",
  "fadeInDown",
  "fadeInDownBig",
  "fadeInLeft",
  "fadeInLeftBig",
  "fadeInRight",
  "fadeInRightBig",
  "fadeInUp",
  "fadeInUpBig",
  "fadeInTopLeft",
  "fadeInTopRight",
  "fadeInBottomLeft",
  "fadeInBottomRight",
  "flipInX",
  "flipInY",
  "lightSpeedInRight",
  "lightSpeedInLeft",
  "rotateInDownLeft",
  "rotateInDownRight",
  "zoomIn",
  "zoomInDown",
  "zoomInLeft",
  "zoomInRight",
  "zoomInUp",
  "slideInDown",
  "slideInLeft",
  "slideInRight",
  "slideInUp",
] as const;

type TranslateFn = (key: string) => string;

export function getToggleInDurationOptions(t: TranslateFn) {
  return [
    { value: "faster", label: t("togglePanel.durationOptions.faster") },
    { value: "fast", label: t("togglePanel.durationOptions.fast") },
    { value: "default", label: t("togglePanel.durationOptions.default") },
    { value: "slow", label: t("togglePanel.durationOptions.slow") },
    { value: "slower", label: t("togglePanel.durationOptions.slower") },
  ];
}

export function getToggleInDelayOptions(t: TranslateFn) {
  return [
    { value: "0s", label: t("togglePanel.delayOptions.0s") },
    { value: "2s", label: t("togglePanel.delayOptions.2s") },
    { value: "3s", label: t("togglePanel.delayOptions.3s") },
    { value: "4s", label: t("togglePanel.delayOptions.4s") },
    { value: "5s", label: t("togglePanel.delayOptions.5s") },
  ];
}

const ToggleComponent: FC = () => {
  const { t } = useTranslation();
  const [animationName, setAnimationName] = useState<string>("");

  const pageActive = usePageActiveStore((state) => state.pageActive);
  const pages = usePPTStore((state) => state.pages);
  const keyboardToggle = usePPTStore((state) => state.keyboardToggle);
  const updatePagePropertyAction = usePPTStore(
    (state) => state.updatePageProperty
  );
  const setKeyboardToggle = usePPTStore((state) => state.setKeyboardToggle);

  const currentPage = pageActive
    ? pages.find((p) => p.id === pageActive)
    : null;

  const currentToggleIn = (currentPage as any)?.toggleInAnimation || "";
  const currentToggleInDuration =
    (currentPage as any)?.toggleInDuration || "default";
  const currentToggleInDelay = (currentPage as any)?.toggleInDelay || "0s";
  const currentAutoToggle = (currentPage as any)?.autoToggle || false;
  const currentAutoToggleTime = (currentPage as any)?.autoToggleTime || 5;

  const toggleInAnimationName = useMemo(
    () =>
      TOGGLE_ANIMATION_TYPES.map((type) => ({
        type,
        name: t(
          type
            ? `togglePanel.animations.${type}`
            : "togglePanel.animations.none"
        ),
      })),
    [t]
  );

  const durationOptions = useMemo(
    () => getToggleInDurationOptions(t),
    [t]
  );
  const delayOptions = useMemo(() => getToggleInDelayOptions(t), [t]);

  const displayAnimations = toggleInAnimationName.slice(0, 6);
  const moreAnimations = toggleInAnimationName.slice(6);

  const mouseEnterHandle = useMemoizedFn((type: string) => {
    setAnimationName(type);
  });

  const mouseLeaveHandle = useMemoizedFn(() => setAnimationName(""));

  const handleAnimationSelect = useMemoizedFn((type: string) => {
    if (!pageActive) return;
    updatePagePropertyAction(pageActive, "toggleInAnimation", type);
  });

  const handleToggleInDurationChange = useMemoizedFn((value: string) => {
    if (!pageActive) return;
    updatePagePropertyAction(pageActive, "toggleInDuration", value);
  });

  const handleToggleInDelayChange = useMemoizedFn((value: string) => {
    if (!pageActive) return;
    updatePagePropertyAction(pageActive, "toggleInDelay", value);
  });

  const handleKeyboardToggleChange = useMemoizedFn(
    (e: { target: { checked: boolean } }) => {
      setKeyboardToggle(e.target.checked);
    }
  );

  const handleAutoToggleChange = useMemoizedFn(
    (e: { target: { checked: boolean } }) => {
      if (!pageActive) return;
      updatePagePropertyAction(pageActive, "autoToggle", e.target.checked);
    }
  );

  const handleAutoToggleTimeChange = useMemoizedFn((value: number | null) => {
    if (value !== null && pageActive) {
      if (value === currentAutoToggleTime) return;
      updatePagePropertyAction(pageActive, "autoToggleTime", value);
    }
  });

  const handleApplyToAll = useMemoizedFn(() => {
    if (!pageActive) return;

    const toggleSettings = {
      toggleInAnimation: currentToggleIn,
      toggleInDuration: currentToggleInDuration,
      toggleInDelay: currentToggleInDelay,
      autoToggle: currentAutoToggle,
      autoToggleTime: currentAutoToggleTime,
    };

    pages.forEach((page) => {
      updatePagePropertyAction(
        page.id,
        "toggleInAnimation",
        toggleSettings.toggleInAnimation
      );
      updatePagePropertyAction(
        page.id,
        "toggleInDuration",
        toggleSettings.toggleInDuration
      );
      updatePagePropertyAction(
        page.id,
        "toggleInDelay",
        toggleSettings.toggleInDelay
      );
      updatePagePropertyAction(
        page.id,
        "autoToggle",
        toggleSettings.autoToggle
      );
      updatePagePropertyAction(
        page.id,
        "autoToggleTime",
        toggleSettings.autoToggleTime
      );
    });

    message.success(t("togglePanel.applySuccess"));
  });

  return (
    <div className="flex gap-[10px] h-[53px]">
      <PanelItemSelect
        displayItems={displayAnimations}
        moreItems={moreAnimations}
        selectedValue={currentToggleIn}
        onSelect={handleAnimationSelect}
        onItemHover={mouseEnterHandle}
        onItemLeave={mouseLeaveHandle}
        hoveredValue={animationName}
      />
      <PanelSplitLine />
      <div className="flex flex-col justify-between gap-[4px] mr-[5px]">
        <div className="flex items-center gap-[4px]">
          <span className="text-[12px] text-chrome-muted mr-[5px]">
            {t("togglePanel.duration")}
          </span>
          <PanelSelect
            value={currentToggleInDuration}
            options={durationOptions}
            size="small"
            style={{ width: 70 }}
            onChange={handleToggleInDurationChange}
          />
        </div>
        <div className="flex items-center gap-[4px]">
          <span className="text-[12px] text-chrome-muted mr-[5px]">
            {t("togglePanel.delay")}
          </span>
          <PanelSelect
            value={currentToggleInDelay}
            options={delayOptions}
            size="small"
            style={{ width: 70 }}
            onChange={handleToggleInDelayChange}
          />
        </div>
      </div>
      <div className="flex flex-col justify-between gap-[4px]">
        <div className="flex items-center gap-[4px] text-[12px] h-[24px]">
          <Checkbox
            checked={keyboardToggle}
            onChange={handleKeyboardToggleChange}
            style={{ fontSize: "12px" }}
          >
            {t("togglePanel.keyboardToggle")}
          </Checkbox>
        </div>
        <div className={`flex items-center gap-[4px] ${styles.checkboxCustom}`}>
          <Checkbox
            value={currentAutoToggle}
            onChange={handleAutoToggleChange}
            style={{ fontSize: "12px" }}
          >
            {t("togglePanel.autoToggle")}
          </Checkbox>
          <InputNumber
            disabled={!currentAutoToggle}
            size="small"
            value={currentAutoToggleTime}
            style={{ width: 70 }}
            onChange={handleAutoToggleTimeChange}
          />
        </div>
      </div>
      <PanelSplitLine />
      <PanelLargeButton
        title={t("togglePanel.applyAll")}
        icon={<FullSelection theme="outline" size="18" fill="var(--icon-color)" />}
        onClick={handleApplyToAll}
      />
    </div>
  );
};

export const Toggle: FC = ToggleComponent;
