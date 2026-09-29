import Index from "@/views/index";
import { initPPTStore } from "@/utils/initStore";
import { loadDocument, type PPTDocumentJSON } from "@/utils/loadDocument";
import { installSlideEmbedBridge } from "@/utils/slideEmbedBridge";
import "animate.css";
import { useTranslation } from "react-i18next";
import "react-contexify/dist/ReactContexify.css";
import "@/i18n";
import {
  consumePendingRemixJob,
  startGalleryRemixPoll,
} from "@/utils/galleryRemixPoll";
import { RemixFailurePage } from "@/components/RemixFailurePage";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useThemeStore, useGalleryRemixStore } from "@/store";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

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
  const remixError = useGalleryRemixStore((state) => state.error);
  const isDark = themeMode === "dark";
  const pendingNoticeRef = useRef<ReturnType<
    typeof consumePendingTemplateDoc
  > | null>(null);
  const pendingRemixRef = useRef(consumePendingRemixJob());

  // 完整文档注入（模板库「打开」等）；Gallery remix 走下方轮询，不走这里
  if (pendingNoticeRef.current === null && !pendingRemixRef.current) {
    pendingNoticeRef.current = consumePendingTemplateDoc();
  }

  useEffect(() => {
    hydrateTheme();
  }, [hydrateTheme]);

  useEffect(() => {
    const notice = pendingNoticeRef.current;
    if (!notice) return;
    if (notice.ok) {
      toast.success(`已加载模板：${notice.name}`);
    } else if (notice.error) {
      toast.error("模板文档无效");
    }
  }, []);

  useEffect(() => {
    const pending = pendingRemixRef.current;
    if (!pending) return;
    return startGalleryRemixPoll(pending);
  }, []);

  // keep i18n subscribed so language changes re-render chrome
  void i18n.language;

  return (
    <TooltipProvider delayDuration={200}>
      {remixError ? <RemixFailurePage /> : <Index />}
      <Toaster theme={isDark ? "dark" : "light"} position="top-center" />
    </TooltipProvider>
  );
}

export default AppShell;
