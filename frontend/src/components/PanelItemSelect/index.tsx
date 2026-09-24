import { Down } from "@icon-park/react";
import { useMemoizedFn } from "ahooks";
import { Popover } from "antd";
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
    }
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
  const closeTimerRef = useRef<NodeJS.Timeout | null>(null);

  // 清除关闭定时器
  const clearCloseTimer = useMemoizedFn(() => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  });

  // 延迟关闭 Popover
  const handleClosePopover = useMemoizedFn(() => {
    clearCloseTimer();
    closeTimerRef.current = setTimeout(() => {
      setPopoverOpen(false);
    }, 200); // 200ms 延迟，给用户时间移动到 Popover
  });

  // 保持 Popover 打开
  const handleKeepPopoverOpen = useMemoizedFn(() => {
    if (disabled) return;
    clearCloseTimer();
    setPopoverOpen(true);
  });

  // 默认渲染项
  const defaultRenderItem = (
    item: SelectItem,
    options: {
      isSelected: boolean;
      inPopover: boolean;
      disabled: boolean;
      onMouseEnter: () => void;
      onMouseLeave: () => void;
      onClick: () => void;
    }
  ) => {
    const {
      isSelected,
      inPopover,
      disabled,
      onMouseEnter,
      onMouseLeave,
      onClick,
    } = options;

    return (
      <div
        className={`${
          inPopover ? "h-[42px]" : "h-full"
        } w-[80px] relative text-[12px] ${disabled ? "" : "cursor-pointer"} rounded-[6px] overflow-hidden bg-chrome-panel-solid border ${
          isSelected ? "border-primary" : "border-[var(--border-default)]"
        } border-dashed flex items-center justify-center flex-shrink-0`}
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
            className={`animate__animated ${
              hoveredValue === item.type ? `animate__${item.type}` : ""
            } ${
              hoveredValue === item.type ? "opacity-100" : "opacity-0"
            } absolute w-full h-full bg-primary flex items-center justify-center text-[12px] text-white font-bold`}
          >
            Web PPT
          </div>
        )}
      </div>
    );
  };

  // 渲染项（使用外部传入的 renderItem 或默认实现）
  const renderItemInternal = (item: SelectItem, inPopover = false) => {
    const isSelected = selectedValue === item.type;
    const actualRenderItem = renderItem || defaultRenderItem;

    return actualRenderItem(item, {
      isSelected,
      inPopover,
      disabled,
      onMouseEnter: () => {
        if (!disabled) {
          onItemHover?.(item.type);
        }
      },
      onMouseLeave: () => {
        if (!disabled) {
          onItemLeave?.();
        }
      },
      onClick: () => {
        if (!disabled) {
          onSelect(item.type);
        }
      },
    });
  };

  // 组件卸载时清理定时器
  useEffect(() => {
    return () => {
      clearCloseTimer();
    };
  }, [clearCloseTimer]);

  // Popover 内容
  const popoverContent = (
    <div
      className="flex flex-wrap gap-[4px] w-[500px] max-h-[300px] overflow-y-auto"
      onMouseEnter={handleKeepPopoverOpen}
      onMouseLeave={handleClosePopover}
    >
      {moreItems.map((item) => (
        <div className="h-[42px]" key={item.type}>
          {renderItemInternal(item, true)}
        </div>
      ))}
    </div>
  );

  return (
    <Popover
      open={disabled ? false : popoverOpen}
      onOpenChange={(open) => {
        if (!disabled) {
          setPopoverOpen(open);
        }
      }}
      placement="bottom"
      content={popoverContent}
      trigger={[]}
      overlayClassName="item-select-popover"
      styles={{
        body: {
          background: "var(--panel-bg-solid)",
          padding: 8,
          borderRadius: 8,
          boxShadow: "var(--panel-shadow)",
        },
      }}
    >
      <div
        className={`h-[53px] px-[5px] box-border border border-[var(--border-default)] rounded-[6px] flex items-center gap-[4px] ${
          disabled ? "opacity-50 cursor-not-allowed" : ""
        }`}
      >
        <div className="h-[51px] flex items-center">
          <div className="h-[42px] flex items-center gap-[4px]">
            {displayItems.map((item) => (
              <div className="h-full" key={item.type}>
                {renderItemInternal(item)}
              </div>
            ))}
            <div
              className={`h-[42px] w-[15px] flex items-center justify-center rounded-[6px] border border-[var(--border-default)] bg-[var(--hover-bg)] transition-colors ${
                disabled
                  ? "cursor-not-allowed"
                  : "cursor-pointer hover:bg-chrome-divider"
              }`}
              onMouseEnter={handleKeepPopoverOpen}
              onMouseLeave={handleClosePopover}
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
            </div>
          </div>
        </div>
      </div>
    </Popover>
  );
};
