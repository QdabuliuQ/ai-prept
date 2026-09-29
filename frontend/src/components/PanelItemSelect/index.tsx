import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Down } from "@icon-park/react";
import { useMemoizedFn } from "ahooks";
import { useEffect, useRef, useState, type FC, type ReactNode } from "react";

interface SelectItem {
  type: string;
  name: string;
}

interface PanelItemSelectProps {
  displayItems: SelectItem[];
  moreItems: SelectItem[];
  selectedValue: string;
  onSelect: (type: string) => void;
  onItemHover?: (type: string) => void;
  onItemLeave?: () => void;
  hoveredValue?: string;
  disabled?: boolean;
  renderItem?: (
    item: SelectItem,
    options: {
      isSelected: boolean;
      inPopover: boolean;
      disabled: boolean;
      onMouseEnter: () => void;
      onMouseLeave: () => void;
      onClick: () => void;
    },
  ) => ReactNode;
}

export const PanelItemSelect: FC<PanelItemSelectProps> = ({
  displayItems,
  moreItems,
  selectedValue,
  onSelect,
  onItemHover,
  onItemLeave,
  hoveredValue = "",
  disabled = false,
  renderItem,
}) => {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearCloseTimer = useMemoizedFn(() => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  });

  const handleClosePopover = useMemoizedFn(() => {
    clearCloseTimer();
    closeTimerRef.current = setTimeout(() => {
      setPopoverOpen(false);
    }, 200);
  });

  const handleKeepPopoverOpen = useMemoizedFn(() => {
    if (disabled) return;
    clearCloseTimer();
    setPopoverOpen(true);
  });

  useEffect(() => () => clearCloseTimer(), [clearCloseTimer]);

  const defaultRenderItem = (
    item: SelectItem,
    options: {
      isSelected: boolean;
      inPopover: boolean;
      disabled: boolean;
      onMouseEnter: () => void;
      onMouseLeave: () => void;
      onClick: () => void;
    },
  ) => {
    const {
      isSelected,
      inPopover,
      disabled: itemDisabled,
      onMouseEnter,
      onMouseLeave,
      onClick,
    } = options;

    return (
      <div
        className={`${
          inPopover ? "h-[42px]" : "h-full"
        } relative w-[80px] shrink-0 overflow-hidden rounded-[6px] border border-dashed text-[12px] ${
          itemDisabled ? "" : "cursor-pointer"
        } flex items-center justify-center border-[var(--border-default)] bg-chrome-panel-solid ${
          isSelected ? "border-primary" : ""
        }`}
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
        onClick={onClick}
      >
        <div className="flex flex-col items-center justify-center">
          <div
            className={`font-bold ${
              isSelected ? "text-primary" : "text-chrome-muted"
            }`}
          >
            {item.name}
          </div>
        </div>
        {item.type !== "" && (
          <div
            className={`animate__animated absolute flex h-full w-full items-center justify-center bg-primary text-[12px] font-bold text-white ${
              hoveredValue === item.type ? `animate__${item.type}` : ""
            } ${hoveredValue === item.type ? "opacity-100" : "opacity-0"}`}
          >
            Web PPT
          </div>
        )}
      </div>
    );
  };

  const renderItemInternal = (item: SelectItem, inPopover = false) => {
    const isSelected = selectedValue === item.type;
    const actualRenderItem = renderItem || defaultRenderItem;

    return actualRenderItem(item, {
      isSelected,
      inPopover,
      disabled,
      onMouseEnter: () => {
        if (!disabled) onItemHover?.(item.type);
      },
      onMouseLeave: () => {
        if (!disabled) onItemLeave?.();
      },
      onClick: () => {
        if (!disabled) onSelect(item.type);
      },
    });
  };

  return (
    <Popover
      open={disabled ? false : popoverOpen}
      onOpenChange={(open) => {
        if (!disabled) setPopoverOpen(open);
      }}
    >
      <div
        className={`box-border flex h-[53px] items-center gap-[4px] rounded-[6px] border border-[var(--border-default)] px-[5px] ${
          disabled ? "cursor-not-allowed opacity-50" : ""
        }`}
      >
        <div className="flex h-[51px] items-center">
          <div className="flex h-[42px] items-center gap-[4px]">
            {displayItems.map((item) => (
              <div className="h-full" key={item.type}>
                {renderItemInternal(item)}
              </div>
            ))}
            <PopoverTrigger asChild>
              <button
                type="button"
                disabled={disabled}
                className={`flex h-[42px] w-[15px] items-center justify-center rounded-[6px] border border-[var(--border-default)] bg-[var(--hover-bg)] transition-colors ${
                  disabled
                    ? "cursor-not-allowed"
                    : "cursor-pointer hover:bg-chrome-divider"
                }`}
                onMouseEnter={handleKeepPopoverOpen}
                onMouseLeave={handleClosePopover}
                aria-label="more"
              >
                <Down
                  theme="outline"
                  size="13"
                  fill={
                    disabled ? "var(--text-disabled)" : "var(--text-muted)"
                  }
                  className={`transition-transform duration-200 ${
                    popoverOpen ? "rotate-180" : ""
                  }`}
                />
              </button>
            </PopoverTrigger>
          </div>
        </div>
      </div>
      <PopoverContent
        align="start"
        side="bottom"
        sideOffset={6}
        className="w-auto max-w-[520px] border-[var(--border-default)] bg-[var(--panel-bg-solid)] p-2 shadow-[var(--panel-shadow)]"
        onMouseEnter={handleKeepPopoverOpen}
        onMouseLeave={handleClosePopover}
      >
        <div className="flex max-h-[300px] w-[500px] flex-wrap gap-[4px] overflow-y-auto">
          {moreItems.map((item) => (
            <div className="h-[42px]" key={item.type}>
              {renderItemInternal(item, true)}
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
};
