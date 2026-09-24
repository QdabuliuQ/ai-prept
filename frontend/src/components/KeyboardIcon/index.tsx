import type { ReactNode } from "react";

interface KeyboardIconProps {
  keys: string[];
  className?: string;
  gapClassName?: string;
  renderSeparator?: () => ReactNode;
}

/**
 * 将键盘快捷键数组渲染为键帽组合，如 ["Ctrl", "C"] => Ctrl + C
 */
export default function KeyboardIcon({
  keys,
  className = "",
  gapClassName = "mx-1",
  renderSeparator,
}: KeyboardIconProps) {
  const separator =
    renderSeparator ??
    (() => (
      <span className={`${gapClassName} leading-none relative top-[-2px]`}>
        +
      </span>
    ));

  return (
    <span className={`${className} inline-flex items-center [zoom:0.7]`}>
      {keys.map((key, index) => (
        <span
          key={`${key}-${index}`}
          className="inline-flex items-center text-[14px] text-gray-500 dark:text-[var(--text-muted)]"
        >
          <kbd className="text-[14px] text-gray-500 dark:text-[var(--text-muted)] px-[10px] py-[4px] bg-[#efefef] dark:bg-[var(--guide-line)] rounded-lg">
            {key}
          </kbd>
          {index < keys.length - 1 && separator()}
        </span>
      ))}
    </span>
  );
}
