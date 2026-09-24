/**
 * 图片处理 Worker
 * 支持：
 * 1. 文件转 base64
 * 2. 使用 OffscreenCanvas 处理图片
 */

self.onmessage = async (e: MessageEvent) => {
  const { type, data, file } = e.data;

  try {
    switch (type) {
      case "convertToBase64": {
        // 文件转 base64
        const reader = new FileReader();

        reader.onload = (event) => {
          const result = event.target?.result as string;
          if (result) {
            self.postMessage({
              success: true,
              data: result,
            });
          } else {
            self.postMessage({
              success: false,
              error: "文件读取失败",
            });
          }
        };

        reader.onerror = () => {
          self.postMessage({
            success: false,
            error: "文件读取失败",
          });
        };

        reader.readAsDataURL(file);
        break;
      }

      case "processImage": {
        // 使用 OffscreenCanvas 处理图片
        const { imageBitmap, width, height, quality = 0.95 } = data;

        // 创建 OffscreenCanvas
        const offscreen = new OffscreenCanvas(width, height);
        const ctx = offscreen.getContext("2d");

        if (!ctx) {
          throw new Error("无法获取 OffscreenCanvas 上下文");
        }

        // 绘制图片到 OffscreenCanvas
        ctx.drawImage(imageBitmap, 0, 0, width, height);

        // 转换为 Blob（PNG 格式）
        const blob = await offscreen.convertToBlob({
          type: "image/png",
          quality: quality,
        });

        // 将 Blob 转换为 ArrayBuffer 以便传输
        const arrayBuffer = await blob.arrayBuffer();

        // 发送处理结果回主线程
        self.postMessage({
          type: "imageProcessed",
          data: {
            arrayBuffer,
            width,
            height,
          },
        });
        break;
      }

      case "convertToDataUrl": {
        // 使用 OffscreenCanvas 转换为 data URL
        const { imageBitmap, width, height } = data;

        // 创建 OffscreenCanvas
        const offscreen = new OffscreenCanvas(width, height);
        const ctx = offscreen.getContext("2d");

        if (!ctx) {
          throw new Error("无法获取 OffscreenCanvas 上下文");
        }

        // 绘制图片到 OffscreenCanvas
        ctx.drawImage(imageBitmap, 0, 0, width, height);

        // 转换为 Blob 然后转换为 data URL
        const blob = await offscreen.convertToBlob({
          type: "image/png",
        });

        // 使用 FileReader 读取为 data URL
        const reader = new FileReader();
        reader.onload = () => {
          self.postMessage({
            type: "dataUrlReady",
            data: {
              dataUrl: reader.result as string,
            },
          });
        };
        reader.onerror = () => {
          throw new Error("读取 Blob 失败");
        };
        reader.readAsDataURL(blob);
        break;
      }

      default:
        throw new Error(`未知的消息类型: ${type}`);
    }
  } catch (error) {
    self.postMessage({
      success: false,
      type: "error",
      error: error instanceof Error ? error.message : String(error),
    });
  }
};

export {};
