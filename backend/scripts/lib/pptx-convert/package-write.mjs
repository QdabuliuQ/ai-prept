/**
 * Write WebPPT html-slide template package to disk.
 */

import fs from "node:fs";
import path from "node:path";

import { buildThemeCss } from "./postprocess.mjs";

/**
 * @param {object} opts
 * @param {string} opts.outDir
 * @param {string} opts.templateId
 * @param {string} opts.sourceFile relative or absolute pptx path
 * @param {string} [opts.labelZh]
 * @param {string} [opts.labelEn]
 * @param {Array<{ file: string, title: string, layout: string, description: string, html: string }>} opts.slides
 * @param {string[]} [opts.warnings]
 * @param {'pending'|'draft'|'approved'} [opts.status]
 * @param {{ bg?: string, text?: string, accent?: string }} [opts.theme]
 * @param {'html-slide'|'ppt-master'} [opts.format]
 * @param {object|null} [opts.usage] template.json usage block
 */
export function writeTemplatePackage({
  outDir,
  templateId,
  sourceFile,
  labelZh,
  labelEn,
  slides,
  warnings = [],
  status = "pending",
  theme = {},
  format = "html-slide",
  usage = null,
}) {
  fs.mkdirSync(path.join(outDir, "slides"), { recursive: true });
  fs.mkdirSync(path.join(outDir, "images"), { recursive: true });

  const themeCss = buildThemeCss(theme);
  fs.writeFileSync(path.join(outDir, "theme.css"), themeCss.endsWith("\n") ? themeCss : themeCss + "\n", "utf8");

  for (const slide of slides) {
    const abs = path.join(outDir, slide.file);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    const html = slide.html.endsWith("\n") ? slide.html : slide.html + "\n";
    fs.writeFileSync(abs, html, "utf8");
  }

  const packFormat = format === "ppt-master" ? "ppt-master" : "html-slide";
  const meta = {
    schema_version: "1.0",
    template_id: templateId,
    format: packFormat,
    label: {
      zh_CN: labelZh || templateId,
      en_US: labelEn || templateId,
    },
    description: {
      zh_CN:
        packFormat === "ppt-master"
          ? `由 PPT Master 生成并转换，共 ${slides.length} 页；等待审核。`
          : `由 PPTX 转换（pptx-renderer），共 ${slides.length} 页；等待审核。`,
      en_US:
        packFormat === "ppt-master"
          ? `Generated via PPT Master (${slides.length} slides); pending review.`
          : `Converted from PPTX via pptx-renderer (${slides.length} slides); pending review.`,
    },
    files: {
      theme_css: "theme.css",
      images_dir: "images",
      slides_dir: "slides",
      visual_spec: "visual-spec.md",
    },
    slides: slides.map((s) => ({
      file: s.file,
      title: s.title,
      layout: s.layout,
      description: s.description,
    })),
    source: {
      kind: packFormat === "ppt-master" ? "ppt-master" : "converted",
      file: sourceFile,
      canvas: { width: 1920, height: 1080 },
    },
    warnings: [...warnings],
    status,
    review: {
      updated_at: new Date().toISOString(),
      note:
        status === "pending"
          ? "pptx 转换写入 agent-output，等待人工审批"
          : undefined,
    },
    storage: {
      backend: "local",
      path: path.posix.join("agent-output", templateId),
    },
  };
  if (usage && typeof usage === "object") {
    meta.usage = usage;
  }

  fs.writeFileSync(
    path.join(outDir, "template.json"),
    JSON.stringify(meta, null, 2) + "\n",
    "utf8",
  );

  return meta;
}

/**
 * @param {string} name pptx basename
 */
export function templateIdFromPptx(name) {
  const stem = path
    .basename(name, path.extname(name))
    .replace(/^ppt-/, "")
    .replace(/[\\/:*?"<>|\x00-\x1f]+/g, "-")
    .replace(/[^\w\u4e00-\u9fff_.-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  const hash = shortHash(name + String(Date.now()));
  return stem ? `${stem}-${hash}` : `converted-${hash}`;
}

function shortHash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16).slice(0, 8);
}
