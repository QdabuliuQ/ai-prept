import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Languages } from "lucide-react";
import { useTranslation } from "react-i18next";

const LANGUAGE_OPTIONS = [
  { key: "zh-CN", label: "简体中文" },
  { key: "en-US", label: "English" },
] as const;

type AppLanguage = (typeof LANGUAGE_OPTIONS)[number]["key"];

function normalizeLanguage(lang: string | undefined): AppLanguage {
  return lang?.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US";
}

const LanguageSwitcher = () => {
  const { i18n } = useTranslation();
  const currentLanguage = normalizeLanguage(i18n.language);

  const changeLanguage = (lang: AppLanguage) => {
    if (lang === currentLanguage) return;
    localStorage.setItem("language", lang);
    void i18n.changeLanguage(lang);
    document.documentElement.lang = lang;
  };

  const currentLabel =
    LANGUAGE_OPTIONS.find((item) => item.key === currentLanguage)?.label ??
    "English";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-[30px] gap-1 px-2 text-[12px] font-medium text-[var(--text-secondary)] hover:bg-[var(--hover-bg)] hover:text-[var(--primary-color)]"
        >
          <Languages className="size-4" />
          {currentLabel}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[8rem] text-[12px]">
        {LANGUAGE_OPTIONS.map(({ key, label }) => (
          <DropdownMenuItem
            key={key}
            className="text-[12px]"
            onSelect={() => changeLanguage(key)}
          >
            {label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default LanguageSwitcher;
