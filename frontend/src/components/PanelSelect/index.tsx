import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { type CSSProperties, type FC } from "react";

export interface PanelSelectOption {
  value: string;
  label: string;
}

interface IPanelSelectProps {
  value?: string;
  options?: PanelSelectOption[];
  onChange?: (value: string) => void;
  className?: string;
  style?: CSSProperties;
  disabled?: boolean;
  /** @deprecated kept for call-site compat; shadcn Select is click-triggered */
  trigger?: "click" | "hover";
  hoverDelay?: number;
  size?: "small" | "middle" | "large";
}

export const PanelSelect: FC<IPanelSelectProps> = ({
  value,
  options = [],
  onChange,
  className,
  style,
  disabled,
}) => {
  return (
    <Select
      value={value}
      onValueChange={(next) => onChange?.(next)}
      disabled={disabled}
    >
      <SelectTrigger
        className={cn(
          "h-6 min-h-6 gap-1 border-[var(--border-default)] bg-[var(--input-bg)] px-2 text-[12px] shadow-none focus:ring-1 focus:ring-[var(--primary-color)]",
          className,
        )}
        style={style}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent className="min-w-[var(--radix-select-trigger-width)] text-[12px]">
        {options.map((opt) => (
          <SelectItem
            key={opt.value}
            value={opt.value}
            className="text-[12px]"
          >
            {opt.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
};
