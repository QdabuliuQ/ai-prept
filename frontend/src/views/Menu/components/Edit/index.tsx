import { PanelLargeButton, PanelSplitLine } from "@/components";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useSlideSelectionStore } from "@/store";
import {
  normalizeColor,
  normalizeTextAlign,
} from "@/slide-editor/runtime/utils/css";
import {
  AlignTextCenter,
  AlignTextLeft,
  AlignTextRight,
  BackgroundColor,
  Check,
  Down,
  Strikethrough,
  TextBold,
  TextItalic,
  TextUnderline,
} from "@icon-park/react";
import { useDebounceFn, useMemoizedFn } from "ahooks";
import { useEffect, useMemo, useRef, useState, type FC } from "react";
import { HexColorInput, HexColorPicker } from "react-colorful";
import { useTranslation } from "react-i18next";

/** 增大字号：描边字母 A + 加号（避免 lucide AArrow 被 fill 染成实心三角） */
const FontSizeIncreaseIcon: FC<{ size?: number }> = ({ size = 18 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden
  >
    <path
      d="M3.8 18 8.2 6.5h1.6L14.2 18"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
    <path
      d="M5.6 13.8h6.8"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      fill="none"
    />
    <path
      d="M18 7.2v7.6M14.2 11h7.6"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      fill="none"
    />
  </svg>
);

/** 减小字号：描边字母 A + 减号 */
const FontSizeDecreaseIcon: FC<{ size?: number }> = ({ size = 18 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden
  >
    <path
      d="M3.8 18 8.2 6.5h1.6L14.2 18"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
    <path
      d="M5.6 13.8h6.8"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      fill="none"
    />
    <path
      d="M14.2 11h7.6"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      fill="none"
    />
  </svg>
);

const FONT_SIZE_PRESETS = [
  12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 64, 72, 96,
] as const;

function readStyleFlags(styles?: Record<string, string>) {
  const fontWeight = (styles?.fontWeight || "400").trim().toLowerCase();
  const fontStyle = (styles?.fontStyle || "normal").trim().toLowerCase();
  const decoration =
    `${styles?.textDecorationLine || ""} ${styles?.textDecoration || ""}`.toLowerCase();
  const align = normalizeTextAlign(styles?.textAlign || "left");
  const color = normalizeColor(styles?.color || "#000000");
  const fontSizePx = parseFloat(styles?.fontSize || "");
  const weightNum = parseInt(fontWeight, 10);
  return {
    bold:
      fontWeight === "bold" ||
      fontWeight === "bolder" ||
      (!Number.isNaN(weightNum) && weightNum >= 600),
    italic: fontStyle === "italic" || fontStyle === "oblique",
    underline: decoration.split(/\s+/).includes("underline"),
    strike: decoration.split(/\s+/).includes("line-through"),
    align: align as "left" | "center" | "right" | "justify",
    color,
    fontSize: Number.isFinite(fontSizePx) && fontSizePx > 0
      ? Math.round(fontSizePx)
      : 16,
  };
}

function toPickerHex(color: string): string {
  const hex = normalizeColor(color);
  return hex.startsWith("#") ? hex.slice(0, 7) : "#000000";
}

function buildSizeOptions(current: number): number[] {
  const set = new Set<number>(FONT_SIZE_PRESETS);
  set.add(current);
  return Array.from(set).sort((a, b) => a - b);
}

/** 文本编辑面板：加粗/斜体/下划线/删除线/字号/对齐/颜色；仅选中文本时可点 */
export const Edit: FC = () => {
  const { t } = useTranslation();
  const pendingColorRef = useRef<string | null>(null);
  const colorCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sizeCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [colorOpen, setColorOpen] = useState(false);
  const [sizeOpen, setSizeOpen] = useState(false);
  const [draftColor, setDraftColor] = useState("#000000");
  const [sizeInput, setSizeInput] = useState("16");
  const selected = useSlideSelectionStore((s) => s.selected);
  const applyTextStyle = useSlideSelectionStore((s) => s.applyTextStyle);
  const enabled = Boolean(selected?.isTextElement);
  const flags = useMemo(
    () => readStyleFlags(selected?.computedStyles),
    [selected?.computedStyles],
  );
  const sizeOptions = useMemo(
    () => buildSizeOptions(flags.fontSize),
    [flags.fontSize],
  );

  const { run: debouncedApplyColor, cancel: cancelDebouncedColor } =
    useDebounceFn(
      (color: string) => {
        pendingColorRef.current = null;
        void applyTextStyle({ color });
      },
      { wait: 280 },
    );

  const { run: debouncedApplyFontSize, cancel: cancelDebouncedFontSize } =
    useDebounceFn(
      (size: number) => {
        void applyTextStyle({ fontSize: size });
      },
      { wait: 280 },
    );

  const flushPendingColor = useMemoizedFn(() => {
    const pending = pendingColorRef.current;
    cancelDebouncedColor();
    if (!pending) return;
    pendingColorRef.current = null;
    void applyTextStyle({ color: pending });
  });

  const clearColorCloseTimer = useMemoizedFn(() => {
    if (colorCloseTimerRef.current) {
      clearTimeout(colorCloseTimerRef.current);
      colorCloseTimerRef.current = null;
    }
  });

  const clearSizeCloseTimer = useMemoizedFn(() => {
    if (sizeCloseTimerRef.current) {
      clearTimeout(sizeCloseTimerRef.current);
      sizeCloseTimerRef.current = null;
    }
  });

  const openColorPopover = useMemoizedFn(() => {
    if (!enabled) return;
    clearColorCloseTimer();
    setDraftColor(toPickerHex(flags.color));
    setColorOpen(true);
  });

  const scheduleCloseColorPopover = useMemoizedFn(() => {
    clearColorCloseTimer();
    colorCloseTimerRef.current = setTimeout(() => {
      flushPendingColor();
      setColorOpen(false);
    }, 180);
  });

  const openSizePopover = useMemoizedFn(() => {
    if (!enabled) return;
    clearSizeCloseTimer();
    setSizeOpen(true);
  });

  const scheduleCloseSizePopover = useMemoizedFn(() => {
    clearSizeCloseTimer();
    sizeCloseTimerRef.current = setTimeout(() => {
      setSizeOpen(false);
    }, 180);
  });

  const onPickerChange = (hex: string) => {
    const next = toPickerHex(hex);
    setDraftColor(next);
    pendingColorRef.current = next;
    debouncedApplyColor(next);
  };

  const commitFontSize = useMemoizedFn((raw: number, immediate = true) => {
    const next = Math.max(8, Math.min(400, Math.round(raw)));
    setSizeInput(String(next));
    if (immediate) {
      cancelDebouncedFontSize();
      void applyTextStyle({ fontSize: next });
      return;
    }
    debouncedApplyFontSize(next);
  });

  const nudgeFontSizeInput = useMemoizedFn((delta: number) => {
    if (!enabled) return;
    const current = Number.parseInt(sizeInput, 10);
    const base = Number.isFinite(current) ? current : flags.fontSize;
    commitFontSize(base + delta, true);
  });

  useEffect(
    () => () => {
      clearColorCloseTimer();
      clearSizeCloseTimer();
    },
    [clearColorCloseTimer, clearSizeCloseTimer],
  );

  useEffect(() => {
    if (!colorOpen) setDraftColor(toPickerHex(flags.color));
  }, [flags.color, colorOpen]);

  useEffect(() => {
    setSizeInput(String(flags.fontSize));
  }, [flags.fontSize]);

  useEffect(() => {
    if (enabled) return;
    clearColorCloseTimer();
    clearSizeCloseTimer();
    flushPendingColor();
    setColorOpen(false);
    setSizeOpen(false);
  }, [
    enabled,
    clearColorCloseTimer,
    clearSizeCloseTimer,
    flushPendingColor,
  ]);

  return (
    <div className="flex h-[53px] items-center gap-[10px]">
      <PanelLargeButton
        title={t("editPanel.bold")}
        active={enabled && flags.bold}
        disabled={!enabled}
        icon={<TextBold theme="outline" size="18" fill="var(--icon-color)" />}
        onClick={() => void applyTextStyle({ bold: "toggle" })}
      />
      <PanelLargeButton
        title={t("editPanel.italic")}
        active={enabled && flags.italic}
        disabled={!enabled}
        icon={<TextItalic theme="outline" size="18" fill="var(--icon-color)" />}
        onClick={() => void applyTextStyle({ italic: "toggle" })}
      />
      <PanelLargeButton
        title={t("editPanel.underline")}
        active={enabled && flags.underline}
        disabled={!enabled}
        icon={
          <TextUnderline theme="outline" size="18" fill="var(--icon-color)" />
        }
        onClick={() => void applyTextStyle({ underline: "toggle" })}
      />
      <PanelLargeButton
        title={t("editPanel.strikethrough")}
        active={enabled && flags.strike}
        disabled={!enabled}
        icon={
          <Strikethrough theme="outline" size="18" fill="var(--icon-color)" />
        }
        onClick={() => void applyTextStyle({ strike: "toggle" })}
      />

      <PanelSplitLine />

      {/* Font size: 上方数值/预设，下方 A+ / A− */}
      <div
        className={cn(
          "flex h-full min-w-[76px] shrink-0 flex-col items-stretch justify-center gap-1 px-0.5",
          !enabled && "pointer-events-none opacity-40",
        )}
      >
        <Popover
          open={enabled && sizeOpen}
          onOpenChange={(open) => {
            if (!enabled) return;
            if (open) openSizePopover();
            else {
              clearSizeCloseTimer();
              setSizeOpen(false);
            }
          }}
        >
          <PopoverAnchor asChild>
            <div
              className="flex h-[22px] items-center overflow-hidden rounded-[4px] border border-[var(--border-default)] bg-[var(--input-bg)] leading-none"
              onMouseEnter={openSizePopover}
              onMouseLeave={scheduleCloseSizePopover}
            >
              <input
                type="text"
                inputMode="numeric"
                disabled={!enabled}
                value={sizeInput}
                aria-label={t("editPanel.fontSize")}
                className="h-full w-[48px] bg-transparent px-1.5 text-center text-[13px] tabular-nums text-chrome-text outline-none"
                onChange={(e) => {
                  const raw = e.target.value.replace(/[^\d]/g, "");
                  setSizeInput(raw);
                  const n = Number.parseInt(raw, 10);
                  if (Number.isFinite(n) && n >= 8) {
                    commitFontSize(n, false);
                  }
                }}
                onBlur={() => {
                  const n = Number.parseInt(sizeInput, 10);
                  if (!Number.isFinite(n) || n < 8) {
                    setSizeInput(String(flags.fontSize));
                    return;
                  }
                  commitFontSize(n, true);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    (e.target as HTMLInputElement).blur();
                  } else if (e.key === "ArrowUp") {
                    e.preventDefault();
                    nudgeFontSizeInput(1);
                  } else if (e.key === "ArrowDown") {
                    e.preventDefault();
                    nudgeFontSizeInput(-1);
                  }
                }}
              />
              <button
                type="button"
                disabled={!enabled}
                className="flex h-full w-5 items-center justify-center border-l border-[var(--border-default)] text-[var(--icon-color)] hover:bg-[var(--hover-bg)]"
                aria-label={t("editPanel.fontSizePresets")}
                aria-expanded={sizeOpen}
                onMouseEnter={openSizePopover}
              >
                <Down
                  theme="outline"
                  size="12"
                  fill="currentColor"
                  className={cn(
                    "transition-transform duration-200",
                    sizeOpen && "rotate-180",
                  )}
                />
              </button>
            </div>
          </PopoverAnchor>
          <PopoverContent
            align="start"
            sideOffset={8}
            className="w-[120px] border-[var(--border-default)] bg-[var(--panel-bg-solid)] p-1 text-chrome-text shadow-[var(--panel-shadow)]"
            onOpenAutoFocus={(e) => e.preventDefault()}
            onCloseAutoFocus={(e) => e.preventDefault()}
            onMouseEnter={openSizePopover}
            onMouseLeave={scheduleCloseSizePopover}
          >
            <div className="max-h-[260px] overflow-y-auto">
              {sizeOptions.map((size) => {
                const selectedSize = size === flags.fontSize;
                return (
                  <button
                    key={size}
                    type="button"
                    className={cn(
                      "flex w-full items-center justify-between rounded-[4px] px-2.5 py-1.5 text-left text-[13px] hover:bg-[var(--hover-bg)]",
                      selectedSize && "bg-[var(--hover-bg)]",
                    )}
                    onClick={() => {
                      commitFontSize(size, true);
                      setSizeOpen(false);
                    }}
                  >
                    <span>{size}</span>
                    {selectedSize ? (
                      <Check
                        theme="outline"
                        size="14"
                        fill="var(--text-secondary)"
                      />
                    ) : (
                      <span className="w-[14px]" />
                    )}
                  </button>
                );
              })}
            </div>
          </PopoverContent>
        </Popover>

        <div className="flex items-center justify-center gap-0.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                disabled={!enabled}
                aria-label={t("editPanel.increaseFontSize")}
                className="flex h-[22px] flex-1 items-center justify-center rounded-[4px] text-[var(--icon-color)] hover:bg-[var(--primary-soft)] hover:text-[var(--primary-color)] disabled:pointer-events-none"
                onClick={() => void applyTextStyle({ fontSize: "increase" })}
              >
                <FontSizeIncreaseIcon size={16} />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              {t("editPanel.increaseFontSize")}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                disabled={!enabled}
                aria-label={t("editPanel.decreaseFontSize")}
                className="flex h-[22px] flex-1 items-center justify-center rounded-[4px] text-[var(--icon-color)] hover:bg-[var(--primary-soft)] hover:text-[var(--primary-color)] disabled:pointer-events-none"
                onClick={() => void applyTextStyle({ fontSize: "decrease" })}
              >
                <FontSizeDecreaseIcon size={16} />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              {t("editPanel.decreaseFontSize")}
            </TooltipContent>
          </Tooltip>
        </div>
      </div>

      <PanelSplitLine />

      <PanelLargeButton
        title={t("editPanel.alignLeft")}
        active={enabled && flags.align === "left"}
        disabled={!enabled}
        icon={
          <AlignTextLeft theme="outline" size="18" fill="var(--icon-color)" />
        }
        onClick={() => void applyTextStyle({ textAlign: "left" })}
      />
      <PanelLargeButton
        title={t("editPanel.alignCenter")}
        active={enabled && flags.align === "center"}
        disabled={!enabled}
        icon={
          <AlignTextCenter theme="outline" size="18" fill="var(--icon-color)" />
        }
        onClick={() => void applyTextStyle({ textAlign: "center" })}
      />
      <PanelLargeButton
        title={t("editPanel.alignRight")}
        active={enabled && flags.align === "right"}
        disabled={!enabled}
        icon={
          <AlignTextRight theme="outline" size="18" fill="var(--icon-color)" />
        }
        onClick={() => void applyTextStyle({ textAlign: "right" })}
      />

      <PanelSplitLine />

      <Popover
        open={enabled && colorOpen}
        onOpenChange={(open) => {
          if (!enabled) return;
          if (open) openColorPopover();
          else {
            clearColorCloseTimer();
            flushPendingColor();
            setColorOpen(false);
          }
        }}
      >
        <PopoverAnchor asChild>
          <div
            className="inline-flex h-full"
            onMouseEnter={openColorPopover}
            onMouseLeave={scheduleCloseColorPopover}
          >
            <PanelLargeButton
              title={t("editPanel.color")}
              active={colorOpen}
              disabled={!enabled}
              icon={
                <BackgroundColor
                  theme="outline"
                  size="18"
                  fill="currentColor"
                />
              }
            />
          </div>
        </PopoverAnchor>
        <PopoverContent
          align="start"
          sideOffset={8}
          className="w-[232px] border-[var(--border-default)] bg-[var(--panel-bg-solid)] p-3 text-chrome-text"
          onOpenAutoFocus={(e) => e.preventDefault()}
          onCloseAutoFocus={(e) => e.preventDefault()}
          onMouseEnter={openColorPopover}
          onMouseLeave={scheduleCloseColorPopover}
        >
          <div className="flex flex-col gap-3">
            <HexColorPicker
              color={draftColor}
              onChange={onPickerChange}
              className="!h-[160px] !w-full"
            />

            <div className="flex items-center gap-2">
              <span className="text-[11px] text-chrome-muted">HEX</span>
              <HexColorInput
                color={draftColor}
                onChange={onPickerChange}
                prefixed
                className="h-8 flex-1 rounded-md border border-[var(--border-default)] bg-[var(--input-bg)] px-2 text-[12px] text-chrome-text outline-none focus:ring-1 focus:ring-[var(--primary-color)]"
              />
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
};
