/**
 * 已通过模板上传流水线：
 * 1) 校验 approved
 * 2) Puppeteer 截页 → WebP
 * 3) 压缩 images/HTML/CSS/JSON
 * 4) LLM 生成 visual-spec.md
 * 5) 打入包内并 zip
 * 6) 上传 zip + 预览图到七牛
 *
 * 压缩在临时目录进行；visual-spec 会写回本地 agent-output。
 */

import { createWriteStream } from "fs";
import {
  cp,
  mkdtemp,
  readdir,
  readFile,
  rm,
  stat,
  writeFile,
} from "fs/promises";
import os from "os";
import path from "path";
import { ZipArchive } from "archiver";
import { minify as minifyCss } from "csso";
import { minify as minifyHtml } from "html-minifier-terser";
import sharp from "sharp";
import {
  pathExists,
  resolveUnderTemplate,
  TEMPLATES_ROOT,
} from "@/server/htmlTemplates";
import {
  getQiniuConfig,
  uploadFileToQiniu,
  qiniuPublicUrl,
} from "@/server/templates/qiniu";
import { generateTemplatePreviewWebps } from "@/server/templates/previewScreenshots";
import {
  copyVisualSpecIntoWorkDir,
  generateVisualSpecMd,
} from "@/server/templates/visualSpecGenerate";
import {
  effectiveStatus,
  type TemplateMeta,
} from "@/server/templates/types";

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp"]);
const MAX_EDGE = 1920;
const JPEG_QUALITY = 82;
const WEBP_QUALITY = 80;
const PNG_COMPRESSION = 8;

const HTML_MINIFY_OPTS = {
  collapseBooleanAttributes: true,
  collapseWhitespace: true,
  conservativeCollapse: true,
  decodeEntities: false,
  minifyCSS: true,
  minifyJS: true,
  removeComments: true,
  removeEmptyAttributes: true,
  removeRedundantAttributes: true,
  removeScriptTypeAttributes: true,
  removeStyleLinkTypeAttributes: true,
  keepClosingSlash: true,
  sortAttributes: false,
  sortClassName: false,
} as const;

type CompressStats = {
  compressed: number;
  skipped: number;
  bytesBefore: number;
  bytesAfter: number;
};

export type PackUploadResult = {
  id: string;
  key: string;
  url: string;
  zipBytes: number;
  imagesCompressed: number;
  imagesSkipped: number;
  imagesBytesBefore: number;
  imagesBytesAfter: number;
  htmlCompressed: number;
  htmlSkipped: number;
  htmlBytesBefore: number;
  htmlBytesAfter: number;
  cssCompressed: number;
  cssBytesBefore: number;
  cssBytesAfter: number;
  jsonCompressed: number;
  jsonBytesBefore: number;
  jsonBytesAfter: number;
  previewPages: number;
  previewUrls: string[];
  visualSpecPath: string | null;
  hash?: string;
};

async function listFilesRecursive(dir: string): Promise<string[]> {
  const out: string[] = [];
  let entries: string[] = [];
  try {
    entries = await readdir(dir);
  } catch {
    return out;
  }
  for (const name of entries) {
    if (name === "." || name === "..") continue;
    const full = path.join(dir, name);
    const st = await stat(full);
    if (st.isDirectory()) {
      out.push(...(await listFilesRecursive(full)));
    } else if (st.isFile()) {
      out.push(full);
    }
  }
  return out;
}

async function compressImageInPlace(
  filePath: string,
): Promise<{ before: number; after: number; compressed: boolean }> {
  const ext = path.extname(filePath).toLowerCase();
  if (!IMAGE_EXTS.has(ext)) {
    const st = await stat(filePath);
    return { before: st.size, after: st.size, compressed: false };
  }

  const before = (await stat(filePath)).size;
  const input = await readFile(filePath);
  const pipelineImg = sharp(input, { failOn: "none" }).rotate().resize({
    width: MAX_EDGE,
    height: MAX_EDGE,
    fit: "inside",
    withoutEnlargement: true,
  });

  let out: Buffer;
  if (ext === ".jpg" || ext === ".jpeg") {
    out = await pipelineImg.jpeg({ quality: JPEG_QUALITY, mozjpeg: true }).toBuffer();
  } else if (ext === ".webp") {
    out = await pipelineImg.webp({ quality: WEBP_QUALITY }).toBuffer();
  } else {
    out = await pipelineImg
      .png({ compressionLevel: PNG_COMPRESSION, effort: 8 })
      .toBuffer();
  }

  if (out.length >= before) {
    return { before, after: before, compressed: false };
  }
  await writeFile(filePath, out);
  return { before, after: out.length, compressed: true };
}

async function compressImagesUnder(
  rootDir: string,
): Promise<{
  compressed: number;
  skipped: number;
  bytesBefore: number;
  bytesAfter: number;
}> {
  const imagesDir = path.join(rootDir, "images");
  if (!(await pathExists(imagesDir))) {
    return { compressed: 0, skipped: 0, bytesBefore: 0, bytesAfter: 0 };
  }
  const files = await listFilesRecursive(imagesDir);
  let compressed = 0;
  let skipped = 0;
  let bytesBefore = 0;
  let bytesAfter = 0;
  for (const file of files) {
    const ext = path.extname(file).toLowerCase();
    if (!IMAGE_EXTS.has(ext)) {
      skipped += 1;
      continue;
    }
    try {
      const r = await compressImageInPlace(file);
      bytesBefore += r.before;
      bytesAfter += r.after;
      if (r.compressed) compressed += 1;
      else skipped += 1;
    } catch {
      skipped += 1;
      try {
        bytesBefore += (await stat(file)).size;
        bytesAfter += (await stat(file)).size;
      } catch {
        /* ignore */
      }
    }
  }
  return { compressed, skipped, bytesBefore, bytesAfter };
}

async function minifyHtmlInPlace(
  filePath: string,
): Promise<{ before: number; after: number; compressed: boolean }> {
  const before = (await stat(filePath)).size;
  const raw = await readFile(filePath, "utf-8");
  const minified = await minifyHtml(raw, { ...HTML_MINIFY_OPTS });
  const out = Buffer.from(minified, "utf-8");
  if (out.length >= before) {
    return { before, after: before, compressed: false };
  }
  await writeFile(filePath, out);
  return { before, after: out.length, compressed: true };
}

/** 压缩包内全部 .html（多为 slides/*.html） */
async function compressHtmlUnder(rootDir: string): Promise<CompressStats> {
  const files = (await listFilesRecursive(rootDir)).filter(
    (f) => path.extname(f).toLowerCase() === ".html",
  );
  let compressed = 0;
  let skipped = 0;
  let bytesBefore = 0;
  let bytesAfter = 0;
  for (const file of files) {
    try {
      const r = await minifyHtmlInPlace(file);
      bytesBefore += r.before;
      bytesAfter += r.after;
      if (r.compressed) compressed += 1;
      else skipped += 1;
    } catch {
      skipped += 1;
      try {
        const n = (await stat(file)).size;
        bytesBefore += n;
        bytesAfter += n;
      } catch {
        /* ignore */
      }
    }
  }
  return { compressed, skipped, bytesBefore, bytesAfter };
}

/** minify theme.css 及包内其它 .css */
async function compressCssUnder(rootDir: string): Promise<CompressStats> {
  const files = (await listFilesRecursive(rootDir)).filter(
    (f) => path.extname(f).toLowerCase() === ".css",
  );
  let compressed = 0;
  let skipped = 0;
  let bytesBefore = 0;
  let bytesAfter = 0;
  for (const file of files) {
    try {
      const before = (await stat(file)).size;
      const raw = await readFile(file, "utf-8");
      const { css } = minifyCss(raw);
      const out = Buffer.from(css, "utf-8");
      bytesBefore += before;
      if (out.length >= before) {
        bytesAfter += before;
        skipped += 1;
        continue;
      }
      await writeFile(file, out);
      bytesAfter += out.length;
      compressed += 1;
    } catch {
      skipped += 1;
      try {
        const n = (await stat(file)).size;
        bytesBefore += n;
        bytesAfter += n;
      } catch {
        /* ignore */
      }
    }
  }
  return { compressed, skipped, bytesBefore, bytesAfter };
}

/** template.json 去 pretty-print（单行） */
async function compressTemplateJson(rootDir: string): Promise<CompressStats> {
  const file = path.join(rootDir, "template.json");
  if (!(await pathExists(file))) {
    return { compressed: 0, skipped: 0, bytesBefore: 0, bytesAfter: 0 };
  }
  try {
    const before = (await stat(file)).size;
    const raw = await readFile(file, "utf-8");
    const parsed = JSON.parse(raw) as unknown;
    const out = Buffer.from(JSON.stringify(parsed), "utf-8");
    if (out.length >= before) {
      return {
        compressed: 0,
        skipped: 1,
        bytesBefore: before,
        bytesAfter: before,
      };
    }
    await writeFile(file, out);
    return {
      compressed: 1,
      skipped: 0,
      bytesBefore: before,
      bytesAfter: out.length,
    };
  } catch {
    try {
      const n = (await stat(file)).size;
      return { compressed: 0, skipped: 1, bytesBefore: n, bytesAfter: n };
    } catch {
      return { compressed: 0, skipped: 1, bytesBefore: 0, bytesAfter: 0 };
    }
  }
}

function zipDirectory(srcDir: string, zipPath: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const output = createWriteStream(zipPath);
    const archive = new ZipArchive({ zlib: { level: 9 } });
    let settled = false;

    output.on("close", () => {
      if (settled) return;
      settled = true;
      resolve(archive.pointer());
    });
    output.on("error", (err) => {
      if (settled) return;
      settled = true;
      reject(err);
    });
    archive.on("error", (err) => {
      if (settled) return;
      settled = true;
      reject(err);
    });

    archive.pipe(output);
    archive.directory(srcDir, path.basename(srcDir));
    void archive.finalize();
  });
}

async function writeStorageMeta(
  id: string,
  patch: {
    storage?: NonNullable<TemplateMeta["storage"]>;
    preview?: NonNullable<TemplateMeta["preview"]>;
  },
): Promise<TemplateMeta> {
  const metaPath = resolveUnderTemplate(id, "template.json");
  if (!metaPath) throw new Error("非法模板 id");
  const raw = await readFile(metaPath, "utf-8");
  const meta = JSON.parse(raw) as TemplateMeta;
  const next: TemplateMeta = {
    ...meta,
    storage: {
      ...(meta.storage || {}),
      ...(patch.storage || {}),
    },
    preview: patch.preview
      ? { ...(meta.preview || {}), ...patch.preview }
      : meta.preview,
  };
  await writeFile(metaPath, JSON.stringify(next, null, 2) + "\n", "utf-8");
  return next;
}

/**
 * 仅允许 status=approved（或旧包无 status）的模板上传。
 * 顺序：校验 → 截屏 WebP → 压缩其它文件 → LLM visual-spec → zip → 七牛。
 */
export async function packAndUploadTemplate(
  id: string,
  opts?: { mockVisualSpec?: boolean },
): Promise<PackUploadResult> {
  const cfg = getQiniuConfig();
  if (!cfg) {
    throw new Error(
      "未配置七牛云。请在 .env.local 设置 QINIU_ACCESS_KEY / QINIU_SECRET_KEY / QINIU_BUCKET / QINIU_DOMAIN",
    );
  }

  // 1) 状态必须已通过
  const root = path.join(TEMPLATES_ROOT, id);
  if (!(await pathExists(root))) {
    throw new Error(`模板不存在: ${id}`);
  }
  const metaPath = path.join(root, "template.json");
  if (!(await pathExists(metaPath))) {
    throw new Error(`缺少 template.json: ${id}`);
  }
  const meta = JSON.parse(await readFile(metaPath, "utf-8")) as TemplateMeta;
  if (effectiveStatus(meta) !== "approved") {
    throw new Error("仅「已通过」模板可上传七牛云");
  }

  const tmpRoot = await mkdtemp(path.join(os.tmpdir(), "webppt-tpl-"));
  const workDir = path.join(tmpRoot, id);
  const zipPath = path.join(tmpRoot, `${id}.zip`);
  const previewDir = path.join(tmpRoot, "previews");

  try {
    // 2) Puppeteer 截屏 → WebP（用本地未压缩 HTML，保证观感）
    const shots = await generateTemplatePreviewWebps({
      templateRoot: root,
      meta,
      outDir: previewDir,
    });

    // 3) 副本上压缩 images / HTML / CSS / JSON
    await cp(root, workDir, { recursive: true });
    const imgStats = await compressImagesUnder(workDir);
    const htmlStats = await compressHtmlUnder(workDir);
    const cssStats = await compressCssUnder(workDir);
    const jsonStats = await compressTemplateJson(workDir);

    // 4) LLM 生成 visual-spec.md（写回本地包，用未压缩 theme 上下文）
    const visualSpec = await generateVisualSpecMd(id, {
      mock: opts?.mockVisualSpec,
    });

    // 5) 打入工作目录 → zip
    await copyVisualSpecIntoWorkDir(id, workDir);
    // 再压一次 template.json（agent 可能更新了 files.visual_spec）
    const localMetaPath = path.join(root, "template.json");
    if (await pathExists(localMetaPath)) {
      await cp(localMetaPath, path.join(workDir, "template.json"));
      await compressTemplateJson(workDir);
    }
    const zipBytes = await zipDirectory(workDir, zipPath);

    // 6) 上传 zip + 预览图
    const key = `${cfg.keyPrefix}${id}.zip`;
    const uploaded = await uploadFileToQiniu({
      localPath: zipPath,
      key,
      cfg,
    });

    const previewPrefix = `${cfg.keyPrefix}${id}/`;
    const previewUrls: string[] = [];
    for (const shot of shots) {
      const previewKey = `${previewPrefix}${shot.fileName}`;
      const up = await uploadFileToQiniu({
        localPath: shot.localPath,
        key: previewKey,
        cfg,
      });
      previewUrls.push(up.url || qiniuPublicUrl(cfg, previewKey));
    }

    await writeStorageMeta(id, {
      storage: {
        backend: "qiniu",
        path: uploaded.key,
        url: uploaded.url,
        uploaded_at: new Date().toISOString(),
        zip_bytes: uploaded.fsize ?? zipBytes,
        images_compressed: imgStats.compressed,
        html_compressed: htmlStats.compressed,
        css_compressed: cssStats.compressed,
        json_compressed: jsonStats.compressed,
        preview_prefix: previewPrefix,
      },
      preview: {
        pages: previewUrls,
        generated_at: new Date().toISOString(),
      },
    });

    return {
      id,
      key: uploaded.key,
      url: uploaded.url,
      zipBytes: uploaded.fsize ?? zipBytes,
      imagesCompressed: imgStats.compressed,
      imagesSkipped: imgStats.skipped,
      imagesBytesBefore: imgStats.bytesBefore,
      imagesBytesAfter: imgStats.bytesAfter,
      htmlCompressed: htmlStats.compressed,
      htmlSkipped: htmlStats.skipped,
      htmlBytesBefore: htmlStats.bytesBefore,
      htmlBytesAfter: htmlStats.bytesAfter,
      cssCompressed: cssStats.compressed,
      cssBytesBefore: cssStats.bytesBefore,
      cssBytesAfter: cssStats.bytesAfter,
      jsonCompressed: jsonStats.compressed,
      jsonBytesBefore: jsonStats.bytesBefore,
      jsonBytesAfter: jsonStats.bytesAfter,
      previewPages: previewUrls.length,
      previewUrls,
      visualSpecPath: visualSpec.path,
      hash: uploaded.hash,
    };
  } finally {
    await rm(tmpRoot, { recursive: true, force: true }).catch(() => undefined);
  }
}
