import { createReadStream } from "fs";
import { readFile } from "fs/promises";
import { Readable } from "stream";
import path from "path";
import { NextResponse } from "next/server";
import {
  SAFE_TEMPLATE_DIR,
  pathExists,
  resolveUnderTemplate,
  rewriteTemplateAssetUrls,
} from "@/server/htmlTemplates";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function contentType(fileName: string): string {
  const ext = path.extname(fileName).toLowerCase();
  const map: Record<string, string> = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".md": "text/markdown; charset=utf-8",
  };
  return map[ext] || "application/octet-stream";
}

/** GET /api/html-templates/[id]/assets/... — theme.css / images / … */
export async function GET(
  req: Request,
  ctx: { params: Promise<{ id: string; path: string[] }> },
) {
  const { id, path: parts } = await ctx.params;
  if (!SAFE_TEMPLATE_DIR.test(id) || !parts?.length) {
    return NextResponse.json({ error: "INVALID" }, { status: 400 });
  }

  if (parts.some((p) => p === ".." || p.includes("\0"))) {
    return NextResponse.json({ error: "INVALID_PATH" }, { status: 400 });
  }

  const rel = parts.join("/");
  const filePath = resolveUnderTemplate(id, rel);
  if (!filePath || !(await pathExists(filePath))) {
    return NextResponse.json({ error: "NOT_FOUND" }, { status: 404 });
  }

  const optimize =
    new URL(req.url).searchParams.get("optimize") === "1" &&
    path.extname(filePath).toLowerCase() === ".html";

  if (optimize) {
    const raw = await readFile(filePath, "utf-8");
    const html = rewriteTemplateAssetUrls(raw, id);
    return new NextResponse(html, {
      status: 200,
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "public, max-age=30",
      },
    });
  }

  const stream = createReadStream(filePath);
  return new NextResponse(Readable.toWeb(stream) as ReadableStream, {
    status: 200,
    headers: {
      "Content-Type": contentType(path.basename(filePath)),
      "Cache-Control": "public, max-age=30",
    },
  });
}
