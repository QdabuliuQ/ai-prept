import { useThemeStore } from "@/store";
import { Moon, Sun } from "@icon-park/react";
import { Button, Tooltip } from "antd";
import { useMemoizedFn } from "ahooks";

const ThemeSwitcher = () => {
  const theme = useThemeStore((state) => state.theme);
  const toggleTheme = useThemeStore((state) => state.toggleTheme);

  const handleToggle = useMemoizedFn(() => {
    toggleTheme();
  });

  const isDark = theme === "dark";

  return (
    <Tooltip placement="bottom" title={isDark ? "切换到亮色模式" : "切换到暗色模式"}>
      <Button
        size="small"
        type="text"
        aria-label={isDark ? "切换到亮色模式" : "切换到暗色模式"}
        onClick={handleToggle}
        icon={
          isDark ? (
            <Sun theme="outline" size="16" fill="currentColor" />
          ) : (
            <Moon theme="outline" size="16" fill="currentColor" />
          )
        }
        style={{ display: "flex", alignItems: "center" }}
      />
    </Tooltip>
  );
};

export default ThemeSwitcher;
