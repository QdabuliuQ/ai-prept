/**
 * 用 Puppeteer 截取 slides/*.html → WebP 预览图（01.webp, 02.webp…）。
 */

import { mkdir, writeFile } from "fs/promises";
import path from "path";
import { pathToFileURL } from "url";
import sharp from "sharp";
import { pathExists } from "@/server/htmlTemplates";
import type { TemplateMeta } from "@/server/templates/types";

const CANVAS_W = 1920;
const CANVAS_H = 1080;
/** 列表预览宽度；高度按 16:9 */
const PREVIEW_W = 960;
const WEBP_QUALITY = 78;

export type PreviewShot = {
  index: number;
  fileName: string;
  localPath: string;
  bytes: number;
};

type LaunchOpts = {
  headless: boolean;
  args: string[];
  executablePath?: string;
  channel?: string;
};

function resolvePuppeteer(): typeof import("puppeteer") {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require("puppeteer") as typeof import("puppeteer");
}

async function launchBrowser() {
  const puppeteer = resolvePuppeteer();
  const launchOpts: LaunchOpts = {
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--font-render-hinting=none",
    ],
  };
  const exe =
    process.env.PUPPETEER_EXECUTABLE_PATH ||
    process.env.CHROME_PATH ||
    process.env.GOOGLE_CHROME_BIN ||
    "";
  if (exe) launchOpts.executablePath = exe;

  const attempts: LaunchOpts[] = exe
    ? [launchOpts]
    : [
        { ...launchOpts, channel: "chrome" },
        { ...launchOpts, channel: "chrome-canary" },
        launchOpts,
      ];

  let lastErr: unknown;
  for (const opts of attempts) {
    try {
      return await puppeteer.launch(opts as Parameters<typeof puppeteer.launch>[0]);
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(
    `Puppeteer 无法启动 Chrome。可设置 PUPPETEER_EXECUTABLE_PATH。最后错误: ${
      lastErr instanceof Error ? lastErr.message : String(lastErr)
    }`,
  );
}

function slideFilesFromMeta(
  templateRoot: string,
  meta: TemplateMeta,
): Array<{ index: number; abs: string; rel: string }> {
  const slides = Array.isArray(meta.slides) ? meta.slides : [];
  const out: Array<{ index: number; abs: string; rel: string }> = [];
  let i = 0;
  for (const slide of slides) {
    const rel = (slide.file || "").replace(/^\/+/, "");
    if (!rel.toLowerCase().endsWith(".html")) continue;
    const abs = path.join(templateRoot, rel);
    i += 1;
    out.push({ index: i, abs, rel });
  }
  return out;
}

function padIndex(n: number): string {
  return String(n).padStart(2, "0");
}

/**
 * 从本地模板目录截取各页预览 WebP，写入 outDir（01.webp, 02.webp…）。
 * 使用未压缩的原始 HTML，保证预览观感。
 */
export async function generateTemplatePreviewWebps(opts: {
  templateRoot: string;
  meta: TemplateMeta;
  outDir: string;
}): Promise<PreviewShot[]> {
  const files = slideFilesFromMeta(opts.templateRoot, opts.meta);
  if (files.length === 0) {
    throw new Error("模板无 slides/*.html，无法生成预览图");
  }

  await mkdir(opts.outDir, { recursive: true });
  const browser = await launchBrowser();
  const shots: PreviewShot[] = [];

  try {
    const page = await browser.newPage();
    page.setDefaultNavigationTimeout(45_000);
    await page.setViewport({
      width: CANVAS_W,
      height: CANVAS_H,
      deviceScaleFactor: 1,
    });

    for (const item of files) {
      if (!(await pathExists(item.abs))) {
        throw new Error(`预览截图失败：缺少 ${item.rel}`);
      }
      const fileUrl = pathToFileURL(item.abs).href;
      await page.goto(fileUrl, { waitUntil: "networkidle0" });
      // 等字体 / 图
      await page.evaluate(async () => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const fonts = (document as any).fonts;
        if (fonts?.ready) await fonts.ready;
      });
      await new Promise((r) => setTimeout(r, 200));

      const clip = await page.evaluate((w, h) => {
        const root =
          document.querySelector("#slide") ||
          document.querySelector(".slide-container") ||
          document.querySelector(".slide") ||
          document.body;
        const r = root.getBoundingClientRect();
        return {
          x: Math.max(0, Math.round(r.left)),
          y: Math.max(0, Math.round(r.top)),
          width: Math.min(w, Math.round(r.width) || w),
          height: Math.min(h, Math.round(r.height) || h),
        };
      }, CANVAS_W, CANVAS_H);

      const png = await page.screenshot({
        type: "png",
        clip: {
          x: clip.x,
          y: clip.y,
          width: clip.width || CANVAS_W,
          height: clip.height || CANVAS_H,
        },
      });

      const fileName = `${padIndex(item.index)}.webp`;
      const localPath = path.join(opts.outDir, fileName);
      const webp = await sharp(png)
        .resize({
          width: PREVIEW_W,
          height: Math.round((PREVIEW_W * CANVAS_H) / CANVAS_W),
          fit: "inside",
          withoutEnlargement: true,
        })
        .webp({ quality: WEBP_QUALITY })
        .toBuffer();
      await writeFile(localPath, webp);
      shots.push({
        index: item.index,
        fileName,
        localPath,
        bytes: webp.length,
      });
    }
  } finally {
    await browser.close().catch(() => undefined);
  }

  return shots;
}
