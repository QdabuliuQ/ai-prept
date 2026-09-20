import { access, readdir, readFile, stat } from "fs/promises";
import path from "path";
import { execFile } from "child_process";
import { promisify } from "util";
import type { TemplateMeta } from "@/server/templates/types";
import { isPubliclyVisible } from "@/server/templates/types";

export type { TemplateMeta } from "@/server/templates/types";

const execFileAsync = promisify(execFile);

/** 模板直接落在 agent-output/<id>/（含 template.json），不再套一层 templates/ */
export const TEMPLATES_ROOT = path.resolve(process.cwd(), "agent-output");

/** 非模板目录（任务日志、旧 packs 等），list 时跳过 */
const RESERVED_OUTPUT_DIRS = new Set([
  "admin-jobs",
  "packs",
  "templates",
]);

const SLIDE_VENDOR_CSS = path.resolve(
  process.cwd(),
  "public",
  "slide-vendor",
  "utilities.css",
);

/** 目录名：字母数字、短横线、下划线、中文 */
export const SAFE_TEMPLATE_DIR = /^[A-Za-z0-9._\u4e00-\u9fff-]+$/;

export async function pathExists(p: string): Promise<boolean> {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

export function resolveUnderTemplate(
  templateDirName: string,
  relPath: string,
): string | null {
  if (!SAFE_TEMPLATE_DIR.test(templateDirName)) return null;
  const root = path.resolve(TEMPLATES_ROOT, templateDirName);
  const resolved = path.resolve(root, relPath);
  if (!resolved.startsWith(root + path.sep) && resolved !== root) return null;
  return resolved;
}

export async function listTemplateDirs(): Promise<string[]> {
  let entries: string[] = [];
  try {
    entries = await readdir(TEMPLATES_ROOT);
  } catch {
    return [];
  }
  const out: string[] = [];
  for (const name of entries) {
    if (name.startsWith(".")) continue;
    if (RESERVED_OUTPUT_DIRS.has(name)) continue;
    if (!SAFE_TEMPLATE_DIR.test(name)) continue;
    const meta = path.join(TEMPLATES_ROOT, name, "template.json");
    if (await pathExists(meta)) out.push(name);
  }
  return out.sort();
}

/** 公开库：仅已审批（无 status 字段的旧包视为已通过） */
export async function listPublicTemplateDirs(): Promise<string[]> {
  const dirs = await listTemplateDirs();
  const out: string[] = [];
  for (const id of dirs) {
    const meta = await readTemplateMeta(id);
    if (isPubliclyVisible(meta)) out.push(id);
  }
  return out;
}

export async function readTemplateMeta(
  dirName: string,
): Promise<TemplateMeta | null> {
  const p = resolveUnderTemplate(dirName, "template.json");
  if (!p || !(await pathExists(p))) return null;
  try {
    return JSON.parse(await readFile(p, "utf-8")) as TemplateMeta;
  } catch {
    return null;
  }
}

/**
 * 去掉慢速 CDN（Tailwind JIT / Google Fonts），改为本地预编译 CSS + 系统字体 + 本地 FA。
 */
export function stripSlowCdns(html: string): string {
  let out = html;

  // Tailwind Play CDN（浏览器 JIT，极慢）
  out = out.replace(
    /<script\b[^>]*\bsrc=["']https?:\/\/cdn\.tailwindcss\.com[^"']*["'][^>]*>\s*<\/script>/gi,
    "",
  );

  // Google Fonts / gstatic preconnect
  out = out.replace(
    /<link\b[^>]*href=["']https?:\/\/fonts\.googleapis\.com[^"']*["'][^>]*>/gi,
    "",
  );
  out = out.replace(
    /<link\b[^>]*href=["']https?:\/\/fonts\.gstatic\.com[^"']*["'][^>]*>/gi,
    "",
  );
  out = out.replace(
    /<link\b[^>]*rel=["']preconnect["'][^>]*(googleapis|gstatic)[^>]*>/gi,
    "",
  );

  // Font Awesome CDN → 本地
  out = out.replace(
    /<link\b[^>]*href=["']https?:\/\/[^"']*font-awesome[^"']*["'][^>]*>/gi,
    '<link rel="stylesheet" href="/slide-vendor/fa/css/all.min.css" />',
  );
  out = out.replace(
    /<link\b[^>]*href=["']https?:\/\/cdnjs\.cloudflare\.com\/ajax\/libs\/font-awesome\/[^"']+["'][^>]*>/gi,
    '<link rel="stylesheet" href="/slide-vendor/fa/css/all.min.css" />',
  );

  const inject = [
    '<link rel="stylesheet" href="/slide-vendor/utilities.css" />',
    '<link rel="stylesheet" href="/slide-vendor/fa/css/all.min.css" />',
    '<style>html,body{font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif}</style>',
  ].join("\n");

  if (!/\/slide-vendor\/utilities\.css/i.test(out)) {
    if (/<head\b[^>]*>/i.test(out)) {
      out = out.replace(/<head\b([^>]*)>/i, `<head$1>\n${inject}\n`);
    } else {
      out = `${inject}\n${out}`;
    }
  } else if (!/\/slide-vendor\/fa\/css\/all\.min\.css/i.test(out)) {
    out = out.replace(
      /(<link[^>]*\/slide-vendor\/utilities\.css[^>]*>)/i,
      `$1\n<link rel="stylesheet" href="/slide-vendor/fa/css/all.min.css" />`,
    );
  }

  // 避免重复注入 FA
  const faRe =
    /<link\b[^>]*href=["']\/slide-vendor\/fa\/css\/all\.min\.css["'][^>]*>/gi;
  const faMatches = out.match(faRe);
  if (faMatches && faMatches.length > 1) {
    let seen = false;
    out = out.replace(faRe, (m) => {
      if (seen) return "";
      seen = true;
      return m;
    });
  }

  return out;
}

/** 相对资源改写 + 去掉慢 CDN */
export function rewriteTemplateAssetUrls(
  html: string,
  templateDirName: string,
): string {
  const base = `/api/html-templates/${encodeURIComponent(templateDirName)}/assets`;
  let out = html;
  out = out.replace(
    /\b(href|src)=(["'])\.\.\/([^"']+)\2/gi,
    (_m, attr: string, q: string, rel: string) =>
      `${attr}=${q}${base}/${rel.replace(/^\/+/, "")}${q}`,
  );
  out = out.replace(
    /url\(\s*(['"]?)\.\.\/([^)'"]+)\1\s*\)/gi,
    (_m, q: string, rel: string) =>
      `url(${q}${base}/${String(rel).replace(/^\/+/, "")}${q})`,
  );
  return stripSlowCdns(out);
}

/**
 * HTML 预览对齐：把 data-valign / data-rotate 落到 CSS，
 * 避免「只写了 data-*、预览与导出不一致」。
 */
export function injectDataElementPreviewAlign(html: string): string {
  if (!/\bdata-element\s*=/.test(html)) return html;
  const snippet = `
<style id="webppt-data-element-preview-align">
[data-element="text"][data-valign="middle"]{
  display:flex!important;flex-direction:column!important;
  justify-content:center!important;align-items:stretch!important;
}
[data-element="text"][data-valign="bottom"]{
  display:flex!important;flex-direction:column!important;
  justify-content:flex-end!important;align-items:stretch!important;
}
[data-element][data-rotate]:not([style*="transform"]){
  transform-origin:center center;
}
</style>
<script id="webppt-data-element-preview-align-js">
(function(){
  function apply(){
    document.querySelectorAll("[data-element][data-rotate]").forEach(function(el){
      var r = el.getAttribute("data-rotate");
      if(!r || el.style.transform) return;
      el.style.transform = "rotate(" + r + "deg)";
      el.style.transformOrigin = "center center";
    });
  }
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", apply);
  else apply();
})();
</script>`;
  if (/<\/head>/i.test(html)) {
    return html.replace(/<\/head>/i, `${snippet}\n</head>`);
  }
  return snippet + html;
}

let vendorBuildPromise: Promise<void> | null = null;

/** 若模板比 utilities.css 新，则重编本地 Tailwind utilities */
export async function ensureSlideVendorCss(): Promise<void> {
  if (vendorBuildPromise) return vendorBuildPromise;

  vendorBuildPromise = (async () => {
    try {
      let templatesNewest = 0;
      const dirs = await listTemplateDirs();
      for (const id of dirs) {
        const slidesDir = path.join(TEMPLATES_ROOT, id, "slides");
        if (!(await pathExists(slidesDir))) continue;
        const files = await readdir(slidesDir);
        for (const f of files) {
          if (!f.endsWith(".html")) continue;
          try {
            const st = await stat(path.join(slidesDir, f));
            templatesNewest = Math.max(templatesNewest, st.mtimeMs);
          } catch {
            /* skip */
          }
        }
      }

      let cssMtime = 0;
      try {
        cssMtime = (await stat(SLIDE_VENDOR_CSS)).mtimeMs;
      } catch {
        cssMtime = 0;
      }

      if (cssMtime > 0 && cssMtime >= templatesNewest) return;

      const bin = path.resolve(process.cwd(), "node_modules", ".bin", "tailwindcss");
      await execFileAsync(
        bin,
        [
          "-c",
          "scripts/slide-vendor.tailwind.config.js",
          "-i",
          "scripts/slide-vendor-input.css",
          "-o",
          "public/slide-vendor/utilities.css",
          "--minify",
        ],
        { cwd: process.cwd(), timeout: 60_000 },
      );
    } finally {
      vendorBuildPromise = null;
    }
  })();

  return vendorBuildPromise;
}

export async function loadTemplatePages(dirName: string): Promise<{
  meta: TemplateMeta;
  pages: Array<{
    id: string;
    title: string;
    layout: string;
    file: string;
    html: string;
  }>;
} | null> {
  await ensureSlideVendorCss();
  const meta = await readTemplateMeta(dirName);
  if (!meta?.slides?.length) return null;

  const pages: Array<{
    id: string;
    title: string;
    layout: string;
    file: string;
    html: string;
  }> = [];

  for (let i = 0; i < meta.slides.length; i++) {
    const slide = meta.slides[i]!;
    const filePath = resolveUnderTemplate(dirName, slide.file);
    if (!filePath || !(await pathExists(filePath))) continue;
    const raw = await readFile(filePath, "utf-8");
    const layout = slide.layout || path.basename(slide.file, path.extname(slide.file));
    pages.push({
      id: `tpl_${layout}_${i + 1}`,
      title: slide.title || layout,
      layout,
      file: slide.file.replace(/^\/+/, ""),
      html: rewriteTemplateAssetUrls(raw, dirName),
    });
  }

  if (!pages.length) return null;
  return { meta, pages };
}

export async function templateMtime(dirName: string): Promise<number> {
  const root = path.join(TEMPLATES_ROOT, dirName);
  try {
    const st = await stat(root);
    let best = st.mtimeMs;
    // remix 等会就地改 template.json / slides，目录 mtime 不一定变
    try {
      const metaSt = await stat(path.join(root, "template.json"));
      best = Math.max(best, metaSt.mtimeMs);
    } catch {
      /* no meta */
    }
    return best;
  } catch {
    return 0;
  }
}
