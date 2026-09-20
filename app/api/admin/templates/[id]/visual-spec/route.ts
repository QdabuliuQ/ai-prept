import { NextResponse } from "next/server";
import { assertAdmin } from "@/server/adminAuth";
import { SAFE_TEMPLATE_DIR } from "@/server/htmlTemplates";
import { getTemplateStore } from "@/server/templates/store";
import { effectiveStatus } from "@/server/templates/types";
import { generateVisualSpecMd } from "@/server/templates/visualSpecGenerate";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
/** 单次 LLM 写 visual-spec */
export const maxDuration = 120;

/**
 * POST /api/admin/templates/[id]/visual-spec
 * 为本地模板包生成 / 覆盖 visual-spec.md（pending / approved 均可）
 * body?: { mock?: boolean }
 */
export async function POST(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  const { id } = await ctx.params;
  if (!SAFE_TEMPLATE_DIR.test(id)) {
    return NextResponse.json({ error: "INVALID_ID" }, { status: 400 });
  }

  let body: { mock?: boolean } = {};
  try {
    if (req.headers.get("content-type")?.includes("application/json")) {
      body = (await req.json()) as { mock?: boolean };
    }
  } catch {
    /* empty body ok */
  }

  const store = getTemplateStore();
  const meta = await store.getMeta(id);
  if (!meta) {
    return NextResponse.json({ error: "NOT_FOUND" }, { status: 404 });
  }

  try {
    const result = await generateVisualSpecMd(id, { mock: body.mock });
    return NextResponse.json({
      ok: true,
      id,
      path: result.path,
      status: effectiveStatus(meta),
      log: result.log,
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    const status =
      msg.includes("LLM") || msg.includes("未配置")
        ? 400
        : msg.includes("不存在")
          ? 404
          : 500;
    return NextResponse.json(
      {
        error: status === 500 ? "GENERATE_FAILED" : "LLM_CONFIG",
        message: msg,
      },
      { status },
    );
  }
}
