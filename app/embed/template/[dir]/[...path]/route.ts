import { readFile } from "fs/promises";
import path from "path";
import { NextResponse } from "next/server";
import {
  SAFE_TEMPLATE_DIR,
  pathExists,
  resolveUnderTemplate,
  rewriteTemplateAssetUrls,
  injectDataElementPreviewAlign,
  ensureSlideVendorCss,
} from "@/server/htmlTemplates";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * GET /embed/template/<dir>/slides/cover.html
 * 读模板 HTML，改写资源路径并直接返回完整文档。
 */
export async function GET(
  _req: Request,
  ctx: { params: Promise<{ dir: string; path: string[] }> },
) {
  const { dir, path: parts } = await ctx.params;
  if (!SAFE_TEMPLATE_DIR.test(dir) || !parts?.length) {
    return new NextResponse("INVALID", { status: 400 });
  }
  if (parts.some((p) => p === ".." || p.includes("\0"))) {
    return new NextResponse("INVALID_PATH", { status: 400 });
  }

  const rel = parts.join("/");
  const filePath = resolveUnderTemplate(dir, rel);
  if (!filePath || !(await pathExists(filePath))) {
    return new NextResponse("NOT_FOUND", { status: 404 });
  }
  if (path.extname(filePath).toLowerCase() !== ".html") {
    return new NextResponse("NOT_HTML", { status: 400 });
  }

  await ensureSlideVendorCss();
  const raw = await readFile(filePath, "utf-8");
  const html = injectDataElementPreviewAlign(rewriteTemplateAssetUrls(raw, dir));

  return new NextResponse(html, {
    status: 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "public, max-age=30",
      "Content-Security-Policy": [
        "default-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "media-src 'self' data: blob:",
        "worker-src 'none'",
        "object-src 'none'",
      ].join("; "),
      "X-Content-Type-Options": "nosniff",
    },
  });
}
