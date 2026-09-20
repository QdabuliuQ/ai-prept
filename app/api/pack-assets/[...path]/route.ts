import { createReadStream } from "fs";
import { access, readdir, stat } from "fs/promises";
import path from "path";
import { Readable } from "stream";
import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** 临时方案：把相对路径 assets/ 映射到可访问 URL（agent-output/packs） */

const SAFE_FILE = /^[A-Za-z0-9._-]+$/;
const SAFE_PACK = /^[A-Za-z0-9._\u4e00-\u9fff-]+$/;

function contentType(fileName: string): string {
  const ext = path.extname(fileName).toLowerCase();
  if (ext === ".png") return "image/png";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".webp") return "image/webp";
  if (ext === ".gif") return "image/gif";
  if (ext === ".svg") return "image/svg+xml";
  return "application/octet-stream";
}

async function exists(filePath: string): Promise<boolean> {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

/** packs 输出根 */
function assetRoots(): string[] {
  const cwd = process.cwd();
  return [path.resolve(cwd, "agent-output", "packs")];
}

/** 无 packId 时按文件名在各根下的 assets/ 里找，优先较新的 */
async function resolveByFileName(fileName: string): Promise<string | null> {
  let best: { filePath: string; mtimeMs: number } | null = null;
  for (const root of assetRoots()) {
    let entries: string[] = [];
    try {
      entries = await readdir(root);
    } catch {
      continue;
    }
    for (const id of entries) {
      if (id.startsWith(".")) continue;
      const filePath = path.join(root, id, "assets", fileName);
      if (!(await exists(filePath))) continue;
      try {
        const st = await stat(filePath);
        if (!best || st.mtimeMs > best.mtimeMs) {
          best = { filePath, mtimeMs: st.mtimeMs };
        }
      } catch {
        /* skip */
      }
    }
  }
  return best?.filePath ?? null;
}

async function resolveAssetPath(parts: string[]): Promise<string | null> {
  if (parts.length === 1) {
    const fileName = parts[0]!;
    if (!SAFE_FILE.test(fileName)) return null;
    return resolveByFileName(fileName);
  }
  if (parts.length === 2) {
    const [packId, fileName] = parts as [string, string];
    if (!SAFE_PACK.test(packId) || !SAFE_FILE.test(fileName)) return null;
    for (const root of assetRoots()) {
      const filePath = path.join(root, packId, "assets", fileName);
      const resolved = path.resolve(filePath);
      if (!resolved.startsWith(root + path.sep)) continue;
      if (await exists(resolved)) return resolved;
    }
    return null;
  }
  return null;
}

/** GET /api/pack-assets/<file> | /api/pack-assets/<packId>/<file> */
export async function GET(
  _req: Request,
  ctx: { params: Promise<{ path: string[] }> }
) {
  const { path: parts } = await ctx.params;
  const filePath = await resolveAssetPath(parts ?? []);
  if (!filePath) {
    return NextResponse.json({ error: "NOT_FOUND" }, { status: 404 });
  }

  const fileName = path.basename(filePath);
  const stream = createReadStream(filePath);
  return new NextResponse(Readable.toWeb(stream) as ReadableStream, {
    status: 200,
    headers: {
      "Content-Type": contentType(fileName),
      "Cache-Control": "public, max-age=60",
    },
  });
}
