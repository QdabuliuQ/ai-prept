import logo from "@/assets/images/ai-prept-logo.png";
import { LanguageSwitcher, ThemeSwitcher } from "@/components";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { CANVAS_HEIGHT, CANVAS_WIDTH } from "@/constants/canvas";
import { useTranslation } from "react-i18next";
import { useGalleryRemixStore, useMenuActiveStore, usePPTStore } from "@/store";
import { exportPageAsImage } from "@/utils/tool";
import { ChevronDown, FileImage, FileSpreadsheet, FileText, LayoutTemplate, Loader2 } from "lucide-react";
import {
  EditTwo,
  Page,
  PlayOne,
  Switch,
} from "@icon-park/react";
import { useMemoizedFn } from "ahooks";
import { useEffect, useMemo, useRef, useState, type FC, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import styles from "./index.module.less";

const LIGHT_MENU_KEYS = new Set(["start", "edit", "toggle", "play"]);
const PPTX_TOAST_ID = "html-to-pptx-export-progress";

export const Header: FC = () => {
  const { t } = useTranslation();
  const menuItems = useMemo(
    (): Array<{ label: string; key: string; icon: ReactNode }> => [
      {
        label: t("menu.edit"),
        key: "edit",
        icon: <EditTwo theme="outline" size="14" fill="currentColor" />,
      },
      {
        label: t("menu.start"),
        key: "start",
        icon: <Page theme="outline" size="14" fill="currentColor" />,
      },
      {
        label: t("menu.toggle"),
        key: "toggle",
        icon: <Switch theme="outline" size="14" fill="currentColor" />,
      },
      {
        label: t("menu.play"),
        key: "play",
        icon: <PlayOne theme="outline" size="14" fill="currentColor" />,
      },
    ],
    [t]
  );

  const menuActive = useMenuActiveStore((state) => state.menuActive);
  const setActiveMenu = useMenuActiveStore((state) => state.setActiveMenu);

  // 预加载 html-to-pptx 导出分包（含 pptxgenjs，约 2MB），避免首次点导出时 ChunkLoadError
  useEffect(() => {
    void import("@/services/exportHtmlToPptx").catch(() => {
      /* 忽略预取失败；真正导出时再报错 */
    });
  }, []);

  // 旧版「插入 / 元素属性 / 动画」面板已下线，落在无效 key 时回到页面
  useEffect(() => {
    if (!menuActive || !LIGHT_MENU_KEYS.has(menuActive)) {
      setActiveMenu("start");
    }
  }, [menuActive, setActiveMenu]);

  const name = usePPTStore((state) => state.name);
  const setName = usePPTStore((state) => state.setName);
  const getName = usePPTStore((state) => state.getName);
  const getPages = usePPTStore((state) => state.getPages);
  const remixBusy = useGalleryRemixStore((state) => state.busy);
  const inputRef = useRef<HTMLInputElement>(null);
  const [isEdit, setIsEdit] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [imageLoading, setImageLoading] = useState(false);
  const [pptxLoading, setPptxLoading] = useState(false);

  const exportBlocked = remixBusy;
  const exportBlockedTitle = t("header.exportBlockedGenerating");
  const exportBusy = pdfLoading || imageLoading || pptxLoading;
  const exportDisabled = exportBlocked || exportBusy;

  // 导出PDF
  const handleExportPdf = useMemoizedFn(async () => {
    if (exportDisabled) return;

    setPdfLoading(true);
    try {
      // 动态导入jsPDF
      const { default: jsPDF } = await import("jspdf");
      const pages = getPages().filter((page) => page.visible !== false);

      if (pages.length === 0) {
        console.warn("没有可导出的页面");
        return;
      }

      const currentName = getName();

      // 创建PDF实例 (横向，16:9)
      const pdf = new jsPDF({
        orientation: "landscape",
        unit: "px",
        format: [CANVAS_WIDTH, CANVAS_HEIGHT],
      });

      // PDF页面尺寸
      const pdfWidth = CANVAS_WIDTH;
      const pdfHeight = CANVAS_HEIGHT;

      // 遍历每个页面，使用exportPageAsImage导出图片并添加到PDF
      for (let i = 0; i < pages.length; i++) {
        const page = pages[i];

        // 使用exportPageAsImage导出页面为图片
        const imgData = await exportPageAsImage(page.id);

        if (!imgData) {
          console.warn(`页面 ${page.id} 导出失败，跳过`);
          continue;
        }

        // 将 PNG 转换为 JPEG 以减小文件大小
        let imageData: string;
        let imageFormat: "PNG" | "JPEG" = "JPEG";
        try {
          imageData = await new Promise<string>((resolve, reject) => {
            const img = new Image();
            img.onload = () => {
              const canvas = document.createElement("canvas");
              canvas.width = img.width;
              canvas.height = img.height;
              const ctx = canvas.getContext("2d");
              if (!ctx) {
                reject(new Error("无法创建 Canvas 上下文"));
                return;
              }
              // 填充白色背景（JPEG 不支持透明）
              ctx.fillStyle = "#ffffff";
              ctx.fillRect(0, 0, canvas.width, canvas.height);
              ctx.drawImage(img, 0, 0);
              // 转换为 JPEG，质量 0.8（平衡质量和文件大小）
              canvas.toBlob(
                (blob) => {
                  if (blob) {
                    const reader = new FileReader();
                    reader.onloadend = () => {
                      resolve(reader.result as string);
                    };
                    reader.onerror = reject;
                    reader.readAsDataURL(blob);
                  } else {
                    reject(new Error("转换失败"));
                  }
                },
                "image/jpeg",
                0.8
              );
            };
            img.onerror = reject;
            img.src = imgData;
          });
        } catch (error) {
          console.warn(`页面 ${page.id} 图片转换失败，使用原始 PNG:`, error);
          // 如果转换失败，使用原始 PNG
          imageData = imgData;
          imageFormat = "PNG";
        }

        // 如果不是第一页，添加新页面
        if (i > 0) {
          pdf.addPage();
        }

        // 添加图片到PDF
        pdf.addImage(imageData, imageFormat, 0, 0, pdfWidth, pdfHeight);
      }

      // 保存PDF
      pdf.save(`${currentName || t("header.untitled")}.pdf`);
    } catch (error) {
      console.error("导出PDF失败:", error);
    } finally {
      setTimeout(() => {
        setPdfLoading(false);
      }, 200);
    }
  });

  // 导出 PPTX：html-slide → @webppt/html-to-pptx
  const handleExportPptx = useMemoizedFn(async () => {
    if (exportDisabled) return;

    setPptxLoading(true);
    try {
      const pages = getPages().filter((page) => page.visible !== false);
      if (pages.length === 0) {
        toast.warning(t("header.noExportPages"));
        return;
      }

      let downloadHtmlToPptx: typeof import("@/services/exportHtmlToPptx").downloadHtmlToPptx;
      try {
        ({ downloadHtmlToPptx } = await import("@/services/exportHtmlToPptx"));
      } catch (loadErr) {
        // HMR / 首次编译竞态：重试一次；仍失败提示硬刷新
        console.warn("exportHtmlToPptx chunk load retry", loadErr);
        ({ downloadHtmlToPptx } = await import("@/services/exportHtmlToPptx"));
      }
      const result = await downloadHtmlToPptx({
        name: getName(),
        pages,
        onProgress: ({ current, total }) => {
          const percent =
            total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;
          toast.loading(t("header.domToPptxExportProgress", { percent }), {
            id: PPTX_TOAST_ID,
          });
        },
      });
      toast.dismiss(PPTX_TOAST_ID);
      toast.success(t("header.domToPptxSuccess"));
      if (result.skippedLegacyCount > 0) {
        toast.message(
          t("header.domToPptxSkippedLegacy", {
            count: result.skippedLegacyCount,
          }),
        );
      }
    } catch (error) {
      toast.dismiss(PPTX_TOAST_ID);
      console.error("PPTX 导出失败:", error);
      const msg = error instanceof Error ? error.message : String(error);
      const isChunk =
        /Loading chunk|ChunkLoadError|Failed to fetch dynamically imported/i.test(
          msg,
        );
      toast.error(
        isChunk
          ? "导出模块加载失败（开发态分包未就绪）。请硬刷新页面后重试。"
          : msg || t("header.domToPptxFailed"),
      );
    } finally {
      toast.dismiss(PPTX_TOAST_ID);
      setTimeout(() => {
        setPptxLoading(false);
      }, 200);
    }
  });

  // 导出所有画布为长图
  const handleExportLongImage = useMemoizedFn(async () => {
    if (exportDisabled) return;

    setImageLoading(true);
    try {
      const pages = getPages().filter((page) => page.visible !== false);

      if (pages.length === 0) {
        console.warn("没有可导出的页面");
        return;
      }

      const SPACER_HEIGHT = 50; // 黑色间隔的高度

      // 导出所有页面的图片
      const imageDataUrls: string[] = [];
      for (const page of pages) {
        const dataUrl = await exportPageAsImage(page.id);
        if (dataUrl) {
          imageDataUrls.push(dataUrl);
        } else {
          console.warn(`页面 ${page.id} 导出失败，跳过`);
        }
      }

      if (imageDataUrls.length === 0) {
        console.warn("没有成功导出的页面");
        return;
      }

      // 加载所有图片
      const images = await Promise.all(
        imageDataUrls.map(
          (dataUrl) =>
            new Promise<HTMLImageElement>((resolve, reject) => {
              const img = new Image();
              img.onload = () => resolve(img);
              img.onerror = reject;
              img.src = dataUrl;
            })
        )
      );

      // 计算总高度：所有画布高度 + 间隔高度（画布数量 - 1）
      const totalHeight =
        CANVAS_HEIGHT * images.length + SPACER_HEIGHT * (images.length - 1);

      // 创建大的 Canvas 用于拼接
      const canvas = document.createElement("canvas");
      canvas.width = CANVAS_WIDTH;
      canvas.height = totalHeight;
      const ctx = canvas.getContext("2d");

      if (!ctx) {
        throw new Error("无法创建 Canvas 上下文");
      }

      // 填充黑色背景
      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, CANVAS_WIDTH, totalHeight);

      // 绘制所有图片和间隔
      let currentY = 0;
      for (let i = 0; i < images.length; i++) {
        const img = images[i];

        // 绘制图片
        ctx.drawImage(img, 0, currentY, CANVAS_WIDTH, CANVAS_HEIGHT);
        currentY += CANVAS_HEIGHT;

        // 如果不是最后一张，添加黑色间隔
        if (i < images.length - 1) {
          ctx.fillStyle = "#000";
          ctx.fillRect(0, currentY, CANVAS_WIDTH, SPACER_HEIGHT);
          currentY += SPACER_HEIGHT;
        }
      }

      // 转换为图片并下载
      const dataUrl = canvas.toDataURL("image/png", 1.0);
      const link = document.createElement("a");
      link.href = dataUrl;
      link.download = `${name || t("header.untitled")}_${t("header.longImageSuffix")}.png`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (error) {
      console.error("导出长图失败:", error);
    } finally {
      setTimeout(() => {
        setImageLoading(false);
      }, 200);
    }
  });

  const exportMenuItems = useMemo(
    () => [
      {
        key: "pdf",
        icon: <FileText className="size-3.5" />,
        label: t("header.exportPdf"),
        onSelect: () => {
          void handleExportPdf();
        },
      },
      {
        key: "image",
        icon: <FileImage className="size-3.5" />,
        label: t("header.exportImage"),
        onSelect: () => {
          void handleExportLongImage();
        },
      },
      {
        key: "pptx",
        icon: <FileSpreadsheet className="size-3.5" />,
        label: t("header.exportDomToPptx"),
        onSelect: () => {
          void handleExportPptx();
        },
      },
    ],
    [t, handleExportPdf, handleExportLongImage, handleExportPptx],
  );

  return (
    <header className={styles.headerBar}>
      {/* 左侧：logo + 名称，与预览列表同宽 */}
      <div className={styles.headerLeft}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Link to="/" className={styles.brandLink} aria-label={t("header.home")}>
              <img
                src={logo}
                alt="Ai Prept"
                width={28}
                height={28}
                className={styles.brandLogo}
              />
            </Link>
          </TooltipTrigger>
          <TooltipContent side="bottom">{t("header.home")}</TooltipContent>
        </Tooltip>
        <div className={styles.titleWrap}>
          <span
            className={`${styles.titleText} cursor-text transition-opacity duration-200 ease-in-out block w-full truncate ${
              !isEdit
                ? "opacity-100 relative pointer-events-auto"
                : "opacity-0 absolute inset-y-0 left-0 pointer-events-none"
            }`}
            title={name || t("header.untitled")}
            onClick={() => {
              setIsEdit(true);
              requestAnimationFrame(() => {
                inputRef.current?.focus();
              });
            }}
          >
            {name || t("header.untitled")}
          </span>
          <input
            ref={inputRef}
            type="text"
            className={styles.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => {
              setIsEdit(false);
            }}
            maxLength={50}
            aria-label={t("header.untitled")}
            style={{
              opacity: isEdit ? 1 : 0,
              position: !isEdit ? "absolute" : "relative",
              inset: !isEdit ? "0" : undefined,
              width: !isEdit ? "100%" : undefined,
              pointerEvents: !isEdit ? "none" : "auto",
              transition: "opacity 0.2s ease-in-out",
            }}
          />
        </div>
      </div>

      <div className={styles.toolbar}>
        <div className={styles.exportGroup}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className={styles.exportTrigger}
                asChild
              >
                <Link to="/templates">
                  <LayoutTemplate className="size-3.5" />
                  <span>{t("header.templates")}</span>
                </Link>
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              {t("header.templatesImport")}
            </TooltipContent>
          </Tooltip>
          {exportBlocked ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex cursor-not-allowed">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled
                    className={styles.exportTrigger}
                  >
                    <span>{t("header.export")}</span>
                    <ChevronDown className="size-3" />
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent side="bottom">{exportBlockedTitle}</TooltipContent>
            </Tooltip>
          ) : (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className={styles.exportTrigger}
                  disabled={exportBusy}
                >
                  {exportBusy ? (
                    <Loader2 className="size-3.5 animate-spin text-[var(--primary-color)]" />
                  ) : null}
                  <span>{t("header.export")}</span>
                  <ChevronDown className="size-3" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="min-w-[10rem] text-[12px]">
                {exportMenuItems.map((item) => (
                  <DropdownMenuItem
                    key={item.key}
                    className="gap-2 text-[12px]"
                    disabled={exportDisabled}
                    onSelect={item.onSelect}
                  >
                    {item.icon}
                    {item.label}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>

        <nav className={styles.navTrack} aria-label="editor modes">
          {menuItems.map((item) => {
            const active = menuActive === item.key;
            return (
              <button
                type="button"
                key={item.key}
                className={`${styles.navItem} ${active ? styles.activeItem : ""}`}
                aria-current={active ? "page" : undefined}
                onClick={() => setActiveMenu(item.key)}
              >
                <i className={styles.navIcon} aria-hidden>
                  {item.icon}
                </i>
                {item.label}
              </button>
            );
          })}
        </nav>

        <div className={styles.utils}>
          <ThemeSwitcher />
          <LanguageSwitcher />
        </div>
      </div>
    </header>
  );
};
