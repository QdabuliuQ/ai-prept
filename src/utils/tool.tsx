import { CANVAS_HEIGHT, CANVAS_WIDTH } from "@/constants/canvas";
import { snapdom } from "@zumer/snapdom";
import * as _ from "lodash";
import { createRoot } from "react-dom/client";

export function cloneDeep<T>(obj: T): T {
  if (obj === null || obj === undefined) {
    return obj;
  }
  return _.cloneDeep(obj);
}

export function getRandomId() {
  return (
    Math.random().toString(36).substring(2, 15) +
    Math.random().toString(36).substring(2, 15)
  );
}

/**
 * 判断当前设备是否为 macOS（含 iOS/iPadOS）
 */
export function isMacDevice(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  const platform = navigator.platform || "";
  return /Mac|iPod|iPhone|iPad/i.test(platform) || /Mac|iPhone|iPad/i.test(ua);
}

/**
 * 判断当前设备是否为 Windows
 */
export function isWindowsDevice(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  const platform = navigator.platform || "";
  return /Win/i.test(platform) || /Windows/i.test(ua);
}

/**
 * 根据设备类型格式化按键名称：
 * - macOS：Ctrl/Control -> ⌘，Alt/Option -> ⌥，Shift -> ⇧，Enter/Return -> ⏎
 * - Windows：保持常用键名（Command/Meta -> Ctrl）
 */
export function formatKeyForDevice(key: string): string {
  const normalized = key.trim().toLowerCase();

  if (isMacDevice()) {
    const macMap: Record<string, string> = {
      ctrl: "⌘",
      cmd: "⌘",
      command: "⌘",
      meta: "⌘",
      alt: "⌥",
      option: "⌥",
      enter: "⏎",
      return: "⏎",
      backspace: "⌫",
      delete: "⌦",
    };
    return macMap[normalized] ?? key;
  }

  const winMap: Record<string, string> = {
    command: "Ctrl",
    cmd: "Ctrl",
    meta: "Ctrl",
  };
  return winMap[normalized] ?? key;
}

/**
 * 批量格式化快捷键数组，返回适配当前设备的键名
 */
export function formatKeysForDevice(keys: string[]): string[] {
  return keys.map((k) => formatKeyForDevice(k));
}

/**
 * 下载图片
 * @param dataUrl - 图片的data URL
 * @param filename - 文件名
 */
export function downloadImage(dataUrl: string, filename: string) {
  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/**
 * 导出页面为图片
 * @param pageId - 页面ID
 * @returns 返回图片的data URL，失败返回null
 */
export async function exportPageAsImage(
  pageId: string
): Promise<string | null> {
  try {
    // 延迟导入 pptStore / PreviewCanvas，避免循环依赖
    const { pptStore } = await import("@/store");
    const page = pptStore.getActivePage(pageId);
    if (!page) {
      console.error("页面不存在");
      return null;
    }

    // 创建临时容器
    const tempContainer = document.createElement("div");
    tempContainer.style.position = "fixed";
    tempContainer.style.left = "-9999px";
    tempContainer.style.top = "0";
    tempContainer.style.width = `${CANVAS_WIDTH}px`;
    tempContainer.style.height = `${CANVAS_HEIGHT}px`;
    tempContainer.style.backgroundColor = "#fff";
    tempContainer.style.overflow = "hidden";
    document.body.appendChild(tempContainer);

    // 创建Canvas容器
    const canvasWrapper = document.createElement("div");
    canvasWrapper.style.width = `${CANVAS_WIDTH}px`;
    canvasWrapper.style.height = `${CANVAS_HEIGHT}px`;
    canvasWrapper.style.position = "relative";
    canvasWrapper.style.backgroundColor = "#fff";
    tempContainer.appendChild(canvasWrapper);

    // 使用React createRoot渲染轻量 PreviewCanvas
    const { PreviewCanvas } = await import("@/views/Canvas/PreviewCanvas");
    const root = createRoot(canvasWrapper);
    root.render(<PreviewCanvas page={page} />);

    // 等待Canvas渲染完成
    const dataUrl = await new Promise<string | null>((resolve) => {
      setTimeout(async () => {
        try {
          // 查找实际的canvas容器元素
          const canvasElement = canvasWrapper.querySelector(
            `#preview-canvas-container-${pageId}`
          ) as HTMLElement;

          if (!canvasElement) {
            root.unmount();
            document.body.removeChild(tempContainer);
            resolve(null);
            return;
          }

          // 等待所有图片加载完成
          const images = canvasElement.querySelectorAll("img");
          const imagePromises = Array.from(images).map(
            (img) =>
              new Promise<void>((imgResolve) => {
                const htmlImg = img as HTMLImageElement;
                if (htmlImg.complete && htmlImg.naturalHeight !== 0) {
                  setTimeout(() => imgResolve(), 100);
                } else {
                  const timeout = setTimeout(() => {
                    imgResolve();
                  }, 5000);
                  htmlImg.onload = () => {
                    clearTimeout(timeout);
                    setTimeout(() => imgResolve(), 200);
                  };
                  htmlImg.onerror = () => {
                    clearTimeout(timeout);
                    imgResolve();
                  };
                }
              })
          );

          await Promise.all(imagePromises);
          // 额外等待确保渲染完成
          await new Promise((r) => setTimeout(r, 300));

          // 使用@zumer/snapdom的toCanvas方法获取Canvas
          // 这样可以更灵活地处理图片，也可以后续使用OffscreenCanvas
          const canvas = await snapdom.toCanvas(canvasElement, {
            scale: 2,
            backgroundColor: "#fff",
            width: CANVAS_WIDTH,
            height: CANVAS_HEIGHT,
            cache: "disabled",
          });

          // 检查是否支持 Worker 和 ImageBitmap
          // 如果支持，使用 Worker 在后台线程中处理图片
          if (
            typeof Worker !== "undefined" &&
            typeof createImageBitmap !== "undefined"
          ) {
            try {
              // 将 Canvas 转换为 ImageBitmap
              const imageBitmap = await createImageBitmap(canvas);

              // 创建 Worker 实例
              const worker = new Worker(
                new URL("../workers/imageWorker.ts", import.meta.url),
                { type: "module" }
              );

              // 使用 Worker 处理图片
              const dataUrl = await new Promise<string>((resolve, reject) => {
                // 设置超时，避免 Worker 卡死
                const timeout = setTimeout(() => {
                  worker.terminate();
                  imageBitmap.close();
                  reject(new Error("Worker 处理超时"));
                }, 30000); // 30秒超时

                worker.onmessage = (e) => {
                  clearTimeout(timeout);
                  const { type, data, error } = e.data;

                  if (type === "dataUrlReady") {
                    worker.terminate();
                    imageBitmap.close();
                    resolve(data.dataUrl);
                  } else if (type === "error") {
                    worker.terminate();
                    imageBitmap.close();
                    reject(new Error(error || "Worker 处理失败"));
                  }
                };

                worker.onerror = (error) => {
                  clearTimeout(timeout);
                  worker.terminate();
                  imageBitmap.close();
                  reject(error);
                };

                // 发送 ImageBitmap 到 Worker（使用 transferable 传输）
                worker.postMessage(
                  {
                    type: "convertToDataUrl",
                    data: {
                      imageBitmap,
                      width: canvas.width,
                      height: canvas.height,
                    },
                  },
                  [imageBitmap] // 转移 ImageBitmap 的所有权
                );
              });

              root.unmount();
              document.body.removeChild(tempContainer);
              resolve(dataUrl);
              return;
            } catch (err) {
              console.warn("Worker 处理失败，回退到普通方式:", err);
            }
          }

          // 回退到普通方式：直接使用 Canvas 转换为 data URL
          const result = canvas.toDataURL("image/png", 1.0);

          // 卸载React组件
          root.unmount();
          document.body.removeChild(tempContainer);

          resolve(result);
        } catch (err) {
          console.error("导出图片失败:", err);
          root.unmount();
          document.body.removeChild(tempContainer);
          resolve(null);
        }
      }, 1000);
    });

    return dataUrl;
  } catch (error) {
    console.error("导出图片失败:", error);
    return null;
  }
}
