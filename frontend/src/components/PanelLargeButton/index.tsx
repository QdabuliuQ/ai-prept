import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useMemoizedFn } from "ahooks";
import {
  cloneElement,
  isValidElement,
  useMemo,
  type FC,
  type ReactElement,
  type ReactNode,
} from "react";

interface IPanelLargeButtonProps {
  title: string;
  icon: ReactNode;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
}

export const PanelLargeButton: FC<IPanelLargeButtonProps> = ({
  title,
  icon,
  onClick,
  active = false,
  disabled = false,
}) => {
  const clickHandle = useMemoizedFn(() => {
    if (!disabled) onClick?.();
  });

  const renderIcon = useMemo(() => {
    if (!isValidElement(icon)) return icon;
    const props = icon.props as { fill?: string };
    // 用 currentColor，使 group-hover:text / active 的文字色同时驱动描边图标
    if (props.fill != null && props.fill !== "none") {
      return cloneElement(icon as ReactElement<{ fill?: string }>, {
        fill: disabled ? "var(--text-disabled)" : "currentColor",
      });
    }
    return icon;
  }, [icon, disabled]);

  return (
    <Button
      type="button"
      variant="ghost"
      disabled={disabled}
      onClick={clickHandle}
      className={cn(
        "group h-full min-w-[53px] shrink-0 flex-col gap-0 rounded-[6px] px-2 py-0 text-[12px] leading-none hover:bg-[var(--primary-soft)]",
        active && "bg-[var(--primary-soft)]",
      )}
    >
      <i
        className={cn(
          "mb-[6px] leading-none",
          disabled
            ? "text-chrome-disabled"
            : active
              ? "text-[var(--primary-color)]"
              : "text-[var(--icon-color)]",
          !disabled && "group-hover:text-[var(--primary-color)]",
        )}
      >
        {renderIcon}
      </i>
      <span
        className={cn(
          "whitespace-nowrap text-[12px]",
          disabled
            ? "text-chrome-disabled"
            : active
              ? "text-[var(--primary-color)]"
              : "text-[var(--icon-color)]",
          !disabled && "group-hover:text-[var(--primary-color)]",
        )}
      >
        {title}
      </span>
    </Button>
  );
};
