import "@ant-design/v5-patch-for-react-19";
import Index from "@/views/index";
import { initPPTStore } from "@/utils/initStore";
import { loadDocument, type PPTDocumentJSON } from "@/utils/loadDocument";
import { installSlideEmbedBridge } from "@/utils/slideEmbedBridge";
import "animate.css";
import { ConfigProvider, theme as antdTheme, message } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import { useTranslation } from "react-i18next";
import "react-contexify/dist/ReactContexify.css";
import "@/i18n";
import { useThemeStore } from "@/store";
import { useEffect, useRef } from "react";

// 在模块加载时同步初始化数据，确保在组件渲染前完成
initPPTStore();
installSlideEmbedBridge();

const PENDING_TEMPLATE_KEY = "webppt:pending-template-doc";

function consumePendingTemplateDoc(): {
  ok: boolean;
  name?: string;
  error?: boolean;
} {
  try {
    const raw = sessionStorage.getItem(PENDING_TEMPLATE_KEY);
    if (!raw) return { ok: false };
    sessionStorage.removeItem(PENDING_TEMPLATE_KEY);
    const doc = JSON.parse(raw) as PPTDocumentJSON;
    if (!Array.isArray(doc.pages) || doc.pages.length === 0) {
      return { ok: false, error: true };
    }
    loadDocument(doc);
    installSlideEmbedBridge();
    return { ok: true, name: doc.name || "未命名" };
  } catch {
    sessionStorage.removeItem(PENDING_TEMPLATE_KEY);
    return { ok: false, error: true };
  }
}

function AppShell() {
  const { i18n } = useTranslation();
  const themeMode = useThemeStore((state) => state.theme);
  const hydrateTheme = useThemeStore((state) => state.hydrateTheme);
  const isDark = themeMode === "dark";
  const pendingNoticeRef = useRef<ReturnType<typeof consumePendingTemplateDoc> | null>(
    null,
  );

  // 首帧前同步注入（Gallery「开始生成」写入 sessionStorage），避免 iframe 先读到空页
  if (pendingNoticeRef.current === null) {
    pendingNoticeRef.current = consumePendingTemplateDoc();
  }

  useEffect(() => {
    hydrateTheme();
  }, [hydrateTheme]);

  useEffect(() => {
    const notice = pendingNoticeRef.current;
    if (!notice) return;
    if (notice.ok) {
      message.success(`已加载模板：${notice.name}`);
    } else if (notice.error) {
      message.error("模板文档无效");
    }
  }, []);

  // 根据当前语言选择antd的语言包（i18n 变更会触发重渲染，无需整页刷新）
  const antdLocale = i18n.language?.toLowerCase().startsWith("zh")
    ? zhCN
    : enUS;

  return (
    <ConfigProvider
      locale={antdLocale}
      theme={{
        algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: "#f25f00",
          fontSizeSM: 12,
          colorBgContainer: isDark ? "#2a2826" : "#ffffff",
          colorBgElevated: isDark ? "#2a2826" : "#ffffff",
          colorBorder: isDark ? "rgba(255,255,255,0.12)" : undefined,
        },
        components: {
          Button: {
            colorPrimary: "#f25f00",
            primaryShadow: "0 2px 0 rgba(242, 95, 0, 0.1)",
            contentFontSizeSM: 12,
          },
          Select: {
            colorPrimary: "#f25f00",
            fontSize: 12,
            optionFontSize: 12,
            optionSelectedBg: isDark ? "rgba(242, 95, 0, 0.18)" : "#fff2e6",
            optionSelectedColor: "#f25f00",
            optionActiveBg: isDark ? "rgba(242, 95, 0, 0.12)" : "#fff2e6",
            colorBorder: isDark
              ? "rgba(255, 255, 255, 0.12)"
              : "#e8e8e8",
          },
          Input: {
            colorPrimary: "#f25f00",
            activeBorderColor: "#f25f00",
            hoverBorderColor: "#ff7b33",
          },
          InputNumber: {
            colorPrimary: "#f25f00",
            activeBorderColor: "#f25f00",
            hoverBorderColor: "#ff7b33",
            fontSize: 12,
          },
          Tooltip: {
            fontSize: 12,
            colorBgSpotlight: "rgba(0, 0, 0, 0.85)",
            colorTextLightSolid: "#fff",
          },
          Popover: {
            colorPrimary: "#f25f00",
            fontSize: 14,
          },
          Dropdown: {
            fontSize: 12,
          },
          Menu: {
            colorPrimary: "#f25f00",
            itemSelectedBg: isDark ? "rgba(242, 95, 0, 0.18)" : "#fff2e6",
            itemSelectedColor: "#f25f00",
            itemActiveBg: isDark ? "rgba(242, 95, 0, 0.12)" : "#fff2e6",
          },
          Modal: {
            colorPrimary: "#f25f00",
            contentBg: isDark ? "#2a2826" : "#ffffff",
            headerBg: isDark ? "#2a2826" : "#ffffff",
            footerBg: isDark ? "#2a2826" : "#ffffff",
          },
          Slider: {
            colorPrimary: "#f25f00",
            handleColor: "#f25f00",
            trackBg: "#f25f00",
            trackHoverBg: "#ff7b33",
          },
        },
      }}
    >
      <Index />
    </ConfigProvider>
  );
}

export default AppShell;
