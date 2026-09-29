import {
  PanelItemSelect,
  PanelLargeButton,
  PanelSelect,
  PanelSplitLine,
} from "@/components";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { usePageActiveStore, usePPTStore } from "@/store/zustand";
import { FullSelection } from "@icon-park/react";
import { useMemoizedFn } from "ahooks";
import { useMemo, useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
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
    () => getToggleInDurationOptions(t as TranslateFn),
    [t],
  );
  const delayOptions = useMemo(
    () => getToggleInDelayOptions(t as TranslateFn),
    [t],
  );

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

  const handleKeyboardToggleChange = useMemoizedFn((checked: boolean) => {
    setKeyboardToggle(checked);
  });

  const handleAutoToggleChange = useMemoizedFn((checked: boolean) => {
    if (!pageActive) return;
    updatePagePropertyAction(pageActive, "autoToggle", checked);
  });

  const handleAutoToggleTimeChange = useMemoizedFn((raw: string) => {
    const value = Number(raw);
    if (!Number.isFinite(value) || !pageActive) return;
    if (value === currentAutoToggleTime) return;
    updatePagePropertyAction(pageActive, "autoToggleTime", value);
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
        toggleSettings.toggleInAnimation,
      );
      updatePagePropertyAction(
        page.id,
        "toggleInDuration",
        toggleSettings.toggleInDuration,
      );
      updatePagePropertyAction(
        page.id,
        "toggleInDelay",
        toggleSettings.toggleInDelay,
      );
      updatePagePropertyAction(
        page.id,
        "autoToggle",
        toggleSettings.autoToggle,
      );
      updatePagePropertyAction(
        page.id,
        "autoToggleTime",
        toggleSettings.autoToggleTime,
      );
    });

    toast.success(t("togglePanel.applySuccess"));
  });

  return (
    <div className="flex h-[53px] gap-[10px]">
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
      <div className="mr-[5px] flex flex-col justify-between gap-[4px]">
        <div className="flex items-center gap-[4px]">
          <span className="mr-[5px] text-[12px] text-chrome-muted">
            {t("togglePanel.duration")}
          </span>
          <PanelSelect
            value={currentToggleInDuration}
            options={durationOptions}
            style={{ width: 70 }}
            onChange={handleToggleInDurationChange}
          />
        </div>
        <div className="flex items-center gap-[4px]">
          <span className="mr-[5px] text-[12px] text-chrome-muted">
            {t("togglePanel.delay")}
          </span>
          <PanelSelect
            value={currentToggleInDelay}
            options={delayOptions}
            style={{ width: 70 }}
            onChange={handleToggleInDelayChange}
          />
        </div>
      </div>
      <div className="flex flex-col justify-between gap-[4px]">
        <div className="flex h-[24px] items-center gap-[6px] text-[12px]">
          <Checkbox
            id="keyboard-toggle"
            checked={keyboardToggle}
            onCheckedChange={(v) => handleKeyboardToggleChange(v === true)}
          />
          <Label
            htmlFor="keyboard-toggle"
            className="cursor-pointer text-[12px] font-normal text-chrome-secondary"
          >
            {t("togglePanel.keyboardToggle")}
          </Label>
        </div>
        <div className={`flex items-center gap-[6px] ${styles.checkboxCustom}`}>
          <Checkbox
            id="auto-toggle"
            checked={currentAutoToggle}
            onCheckedChange={(v) => handleAutoToggleChange(v === true)}
          />
          <Label
            htmlFor="auto-toggle"
            className="cursor-pointer text-[12px] font-normal text-chrome-secondary"
          >
            {t("togglePanel.autoToggle")}
          </Label>
          <Input
            type="number"
            disabled={!currentAutoToggle}
            value={currentAutoToggleTime}
            className="h-6 w-[70px] px-2 text-[12px]"
            onChange={(e) => handleAutoToggleTimeChange(e.target.value)}
          />
        </div>
      </div>
      <PanelSplitLine />
      <PanelLargeButton
        title={t("togglePanel.applyAll")}
        icon={
          <FullSelection theme="outline" size="18" fill="var(--icon-color)" />
        }
        onClick={handleApplyToAll}
      />
    </div>
  );
};

export const Toggle: FC = ToggleComponent;
