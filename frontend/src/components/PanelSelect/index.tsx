import { Select, type SelectProps } from "antd";
import { type FC, useEffect, useRef, useState } from "react";
import styles from "./index.module.less";

type TriggerType = "click" | "hover";

interface IPanelSelectProps extends Omit<SelectProps, "open" | "onOpenChange"> {
  /** 触发方式 */
  trigger?: TriggerType;
  /** 悬停延时关闭时间（毫秒） */
  hoverDelay?: number;
}

export const PanelSelect: FC<IPanelSelectProps> = ({
  trigger = "hover",
  hoverDelay = 150,
  className,
  variant = "outlined",
  ...selectProps
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const timerRef = useRef<NodeJS.Timeout | undefined>(undefined);

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    setIsOpen(false);
  }, [selectProps.value]);

  const handleMouseEnter = () => {
    if (trigger === "hover") {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
      setIsOpen(true);
    }
  };

  const handleMouseLeave = () => {
    if (trigger === "hover") {
      timerRef.current = setTimeout(() => {
        setIsOpen(false);
      }, hoverDelay);
    }
  };

  const handleOpenChange = (open: boolean) => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    setIsOpen(open);
  };

  const wrapperProps =
    trigger === "hover"
      ? { onMouseEnter: handleMouseEnter, onMouseLeave: handleMouseLeave }
      : {};

  return (
    <div {...wrapperProps} style={{ display: "inline-block", lineHeight: 1 }}>
      <Select
        {...selectProps}
        variant={variant}
        className={[styles.panelSelect, className].filter(Boolean).join(" ")}
        open={isOpen}
        onOpenChange={handleOpenChange}
      />
    </div>
  );
};
