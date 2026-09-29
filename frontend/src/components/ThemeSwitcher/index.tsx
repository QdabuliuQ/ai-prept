import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useThemeStore } from "@/store";
import { useMemoizedFn } from "ahooks";
import { Moon, Sun } from "lucide-react";

const ThemeSwitcher = () => {
  const theme = useThemeStore((state) => state.theme);
  const toggleTheme = useThemeStore((state) => state.toggleTheme);
  const handleToggle = useMemoizedFn(() => toggleTheme());
  const isDark = theme === "dark";
  const label = isDark ? "切换到亮色模式" : "切换到暗色模式";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={label}
          onClick={handleToggle}
          className="h-[30px] w-[30px] px-0 text-[var(--text-secondary)] hover:bg-[var(--hover-bg)] hover:text-[var(--primary-color)]"
        >
          {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
};

export default ThemeSwitcher;
