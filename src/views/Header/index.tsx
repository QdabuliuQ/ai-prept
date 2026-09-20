import { LanguageSwitcher, ThemeSwitcher } from "@/components";
import { CANVAS_HEIGHT, CANVAS_WIDTH } from "@/constants/canvas";
import { useTranslation } from "react-i18next";
import { useMenuActiveStore, usePPTStore } from "@/store";
import { loadDocument, parsePPTDocumentJSON } from "@/utils/loadDocument";
import { exportPageAsImage } from "@/utils/tool";
import { LoadingOutlined } from "@ant-design/icons";
import {
  FileAddition,
  FileJpg,
  FilePdf,
  FilePpt,
  FileSettings,
} from "@icon-park/react";
import { useMemoizedFn } from "ahooks";
import { Button, Tooltip, message } from "antd";
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type FC } from "react";
import styles from "./index.module.less";

const LIGHT_MENU_KEYS = new Set(["start", "toggle", "play", "view"]);

export const Header: FC = () => {
  const { t } = useTranslation();
  const menuItems = useMemo(
    () => [
      {
        label: t("menu.start"),
        key: "start",
      },
      {
        label: t("menu.toggle"),
        key: "toggle",
      },
      {
        label: t("menu.play"),
        key: "play",
      },
      {
        label: t("menu.view"),
        key: "view",
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
  const getTheme = usePPTStore((state) => state.getTheme);
  const inputRef = useRef<HTMLInputElement>(null);
  const importInputRef = useRef<HTMLInputElement>(null);
  const [isEdit, setIsEdit] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [imageLoading, setImageLoading] = useState(false);
  const [pptxLoading, setPptxLoading] = useState(false);

  // 导入配置文件（覆盖当前 PPT）
  const handleImportConfigClick = useMemoizedFn(() => {
    if (importLoading) return;
    importInputRef.current?.click();
  });

  const handleImportConfigChange = useMemoizedFn(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      // 允许重复选择同一文件
      e.target.value = "";
      if (!file || importLoading) return;

      setImportLoading(true);
      try {
        const text = await file.text();
        const doc = parsePPTDocumentJSON(text);
        loadDocument(doc);
        message.success(t("header.importSuccess"));
      } catch (error) {
        console.error("导入配置文件失败:", error);
        const code =
          error instanceof Error ? error.message : "IMPORT_FAILED";
        if (code === "INVALID_PAGES" || code === "INVALID_FORMAT") {
          message.error(t("header.importInvalidPages"));
        } else {
          message.error(t("header.importFailed"));
        }
      } finally {
        setTimeout(() => {
          setImportLoading(false);
        }, 200);
      }
    }
  );

  // 导出配置文件
  const handleExportConfig = useMemoizedFn(async () => {
    if (exportLoading) return;

    setExportLoading(true);
    try {
      // 获取数据
      const configData = {
        name: getName(),
        theme: getTheme(),
        pages: getPages(),
      };

      // 转换为 JSON 字符串
      const jsonString = JSON.stringify(configData, null, 2);

      // 创建 Blob 对象
      const blob = new Blob([jsonString], { type: "application/json" });

      // 创建下载链接
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${name || t("header.untitled")}.json`;

      // 触发下载
      document.body.appendChild(link);
      link.click();

      // 清理
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error("导出配置文件失败:", error);
    } finally {
      setTimeout(() => {
        setExportLoading(false);
      }, 200);
    }
  });

  // 导出PDF
  const handleExportPdf = useMemoizedFn(async () => {
    if (pdfLoading) return;

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
    if (pptxLoading) return;

    setPptxLoading(true);
    const loadingMessageKey = "html-to-pptx-export-progress";
    try {
      const pages = getPages().filter((page) => page.visible !== false);
      if (pages.length === 0) {
        message.warning(t("header.noExportPages"));
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
          message.loading({
            key: loadingMessageKey,
            duration: 0,
            content: t("header.domToPptxExportProgress", { current, total }),
          });
        },
      });
      message.destroy(loadingMessageKey);
      message.success(t("header.domToPptxSuccess"));
      if (result.skippedLegacyCount > 0) {
        message.info(
          t("header.domToPptxSkippedLegacy", {
            count: result.skippedLegacyCount,
          }),
        );
      }
    } catch (error) {
      message.destroy(loadingMessageKey);
      console.error("PPTX 导出失败:", error);
      const msg = error instanceof Error ? error.message : String(error);
      const isChunk =
        /Loading chunk|ChunkLoadError|Failed to fetch dynamically imported/i.test(
          msg,
        );
      message.error(
        isChunk
          ? "导出模块加载失败（开发态分包未就绪）。请硬刷新页面后重试。"
          : msg || t("header.domToPptxFailed"),
      );
    } finally {
      message.destroy(loadingMessageKey);
      setTimeout(() => {
        setPptxLoading(false);
      }, 200);
    }
  });

  // 导出所有画布为长图
  const handleExportLongImage = useMemoizedFn(async () => {
    if (imageLoading) return;

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

  return (
    <div
      className={`${styles.headerBar} px-[20px] pt-[10px] pb-[8px] flex items-center shrink-0 gap-[0px]`}
    >
      {/* 左侧：与预览列表同宽 */}
      <div
        className={`${styles.headerLeft} flex items-center gap-[4px] min-w-0 shrink-0 overflow-hidden`}
      >
        <div className={styles.titleWrap}>
          {/* 文本显示 */}
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
          {/* 输入框 */}
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
        <div
          className={`flex items-center gap-[2px] shrink-0 ${styles.exportBtn}`}
        >
          <input
            ref={importInputRef}
            type="file"
            accept=".json,application/json"
            style={{ display: "none" }}
            onChange={handleImportConfigChange}
          />
          <Tooltip placement="bottomLeft" title="PPT 模板">
            <Button
              size="small"
              type="text"
              href="/templates"
            >
              模板
            </Button>
          </Tooltip>
          <Tooltip placement="bottomLeft" title={t("header.importConfig")}>
            <Button
              size="small"
              type="text"
              icon={
                importLoading ? (
                  <LoadingOutlined spin style={{ color: "#f25f00" }} />
                ) : (
                  <FileAddition theme="outline" size="16" fill="currentColor" />
                )
              }
              disabled={importLoading}
              onClick={handleImportConfigClick}
            />
          </Tooltip>
          <Tooltip placement="bottom" title={t("header.exportConfig")}>
            <Button
              size="small"
              type="text"
              icon={
                exportLoading ? (
                  <LoadingOutlined spin style={{ color: "#f25f00" }} />
                ) : (
                  <FileSettings theme="outline" size="16" fill="currentColor" />
                )
              }
              disabled={exportLoading}
              onClick={handleExportConfig}
            />
          </Tooltip>
          <Tooltip placement="bottom" title={t("header.exportPdf")}>
            <Button
              size="small"
              type="text"
              icon={
                pdfLoading ? (
                  <LoadingOutlined spin style={{ color: "#f25f00" }} />
                ) : (
                  <FilePdf theme="outline" size="16" fill="currentColor" />
                )
              }
              disabled={pdfLoading}
              onClick={handleExportPdf}
            />
          </Tooltip>
          <Tooltip placement="bottom" title={t("header.exportImage")}>
            <Button
              size="small"
              type="text"
              icon={
                imageLoading ? (
                  <LoadingOutlined spin style={{ color: "#f25f00" }} />
                ) : (
                  <FileJpg theme="outline" size="16" fill="currentColor" />
                )
              }
              disabled={imageLoading}
              onClick={handleExportLongImage}
            />
          </Tooltip>
          <Tooltip placement="bottom" title={t("header.exportDomToPptx")}>
            <Button
              size="small"
              type="text"
              icon={
                pptxLoading ? (
                  <LoadingOutlined spin style={{ color: "#f25f00" }} />
                ) : (
                  <FilePpt theme="filled" size="16" fill="currentColor" />
                )
              }
              disabled={pptxLoading}
              onClick={handleExportPptx}
            />
          </Tooltip>
        </div>
      </div>
      {/* 右侧：占满剩余宽度 */}
      <div className="flex-1 min-w-0 flex items-center justify-between pl-[8px]">
        <div className="flex items-center gap-[28px] select-none justify-center flex-1 min-w-0">
          {menuItems.map((item) => (
            <div
              className={`${styles.navItem} text-[13px] cursor-pointer transition-colors duration-200 ease-in-out ${
                menuActive === item.key
                  ? `text-[var(--primary-color)] ${styles.activeItem}`
                  : "text-chrome-secondary hover:text-[var(--primary-color)]"
              }`}
              key={item.key}
              onClick={() => setActiveMenu(item.key)}
            >
              {item.label}
            </div>
          ))}
        </div>
        <div className="flex justify-end shrink-0 items-center gap-[4px]">
          <ThemeSwitcher />
          <LanguageSwitcher />
        </div>
      </div>
    </div>
  );
};
