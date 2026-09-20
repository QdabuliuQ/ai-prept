import { NextResponse } from "next/server";
import { assertAdmin } from "@/server/adminAuth";
import { SAFE_TEMPLATE_DIR } from "@/server/htmlTemplates";
import { getTemplateStore } from "@/server/templates/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/admin/templates — 管理端：全部状态 */
export async function GET(req: Request) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  const url = new URL(req.url);
  const statusParam = url.searchParams.get("status");
  const statuses = statusParam
    ? (statusParam.split(",").map((s) => s.trim()) as Array<
        "draft" | "pending" | "approved" | "rejected"
      >)
    : undefined;

  const store = getTemplateStore();
  const templates = await store.list(statuses ? { statuses } : undefined);
  return NextResponse.json({
    backend: store.backend,
    templates,
  });
}

function parseIds(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((id) => (typeof id === "string" ? id.trim() : ""))
    .filter((id) => id.length > 0);
}

async function batchDelete(ids: string[]) {
  if (ids.length === 0) {
    return NextResponse.json({ error: "IDS_REQUIRED" }, { status: 400 });
  }
  if (ids.length > 200) {
    return NextResponse.json({ error: "TOO_MANY_IDS" }, { status: 400 });
  }

  const invalid = ids.filter((id) => !SAFE_TEMPLATE_DIR.test(id));
  if (invalid.length) {
    return NextResponse.json(
      { error: "INVALID_ID", invalid },
      { status: 400 },
    );
  }

  const result = await getTemplateStore().deleteMany(ids);
  return NextResponse.json({
    ok: result.failed.length === 0,
    ...result,
  });
}

/**
 * POST /api/admin/templates — 批量操作
 * body: { action: "delete", ids: string[] }
 * （浏览器对 DELETE+body 支持不稳定，批量删除走 POST）
 */
export async function POST(req: Request) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  let body: { action?: unknown; ids?: unknown } = {};
  try {
    body = (await req.json()) as { action?: unknown; ids?: unknown };
  } catch {
    return NextResponse.json({ error: "INVALID_JSON" }, { status: 400 });
  }

  if (body.action !== "delete") {
    return NextResponse.json(
      { error: "INVALID_ACTION", allowed: ["delete"] },
      { status: 400 },
    );
  }

  return batchDelete(parseIds(body.ids));
}

/** DELETE /api/admin/templates — 批量删除（兼容：body 或 ?ids=） */
export async function DELETE(req: Request) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  const url = new URL(req.url);
  const fromQuery = url.searchParams.getAll("ids").flatMap((v) =>
    v.split(",").map((s) => s.trim()).filter(Boolean),
  );

  let fromBody: string[] = [];
  try {
    const body = (await req.json()) as { ids?: unknown };
    fromBody = parseIds(body.ids);
  } catch {
    // DELETE 无 body 时仅用 query
  }

  return batchDelete(fromBody.length > 0 ? fromBody : fromQuery);
}
