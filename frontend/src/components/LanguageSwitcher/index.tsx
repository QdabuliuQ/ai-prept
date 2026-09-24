import { Translate } from "@icon-park/react";
import type { MenuProps } from "antd";
import { Button, Dropdown } from "antd";
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

  const items: MenuProps["items"] = LANGUAGE_OPTIONS.map(({ key, label }) => ({
    key,
    label,
    onClick: () => changeLanguage(key),
  }));

  const currentLabel =
    LANGUAGE_OPTIONS.find((item) => item.key === currentLanguage)?.label ??
    "English";

  return (
    <Dropdown
      menu={{ items, selectedKeys: [currentLanguage] }}
      placement="bottomRight"
    >
      <Button
        size="small"
        type="text"
        icon={<Translate theme="outline" size="16" fill="currentColor" />}
        style={{ display: "flex", alignItems: "center", gap: "4px" }}
      >
        {currentLabel}
      </Button>
    </Dropdown>
  );
};

export default LanguageSwitcher;
