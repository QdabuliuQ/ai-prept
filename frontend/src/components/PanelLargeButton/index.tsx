import { useMemoizedFn } from "ahooks";
import { Button, type ButtonProps } from "antd";
import {
  cloneElement,
  isValidElement,
  useMemo,
  type FC,
  type ReactElement,
} from "react";

interface IPanelLargeButtonProps {
  title: string;
  icon: React.ReactNode;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
  type?: ButtonProps["type"];
}

export const PanelLargeButton: FC<IPanelLargeButtonProps> = ({
  title,
  icon,
  onClick,
  active = false,
  disabled = false,
  type = "text",
}) => {
  const clickHandle = useMemoizedFn(() => {
    if (!disabled) {
      onClick?.();
    }
  });

  const styles = useMemo(() => {
    const baseStyles: React.CSSProperties = {
      width: "auto",
      minWidth: "53px",
      height: "100%",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      fontSize: "12px",
      gap: "0px",
      lineHeight: "1",
      padding: "0 8px",
      color: "var(--icon-color)",
      borderRadius: "6px",
      border: "1px solid transparent",
      flexShrink: 0,
    };

    if (active) {
      return {
        ...baseStyles,
        backgroundColor: "var(--primary-soft)",
        color: "var(--primary-color)",
      };
    }

    return baseStyles;
  }, [active]);

  const renderIcon = useMemo(() => {
    if (!isValidElement(icon)) return icon;

    return cloneElement(icon as ReactElement<{ fill?: string }>, {
      fill: disabled ? "var(--text-disabled)" : "currentColor",
    });
  }, [icon, disabled]);

  return (
    <Button
      style={styles}
      onClick={clickHandle}
      type={type}
      disabled={disabled}
      className="hover:!bg-[var(--primary-soft)] hover:!text-[var(--primary-color)]"
    >
      <i className="mb-[6px] text-current leading-none">{renderIcon}</i>
      <span className={`${disabled ? "text-chrome-disabled" : ""} text-[12px] whitespace-nowrap`}>
        {title}
      </span>
    </Button>
  );
};
