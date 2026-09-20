import { NextResponse } from "next/server";
import { assertAdmin } from "@/server/adminAuth";
import { getTemplateStore } from "@/server/templates/store";
import { startRemixJob } from "@/server/templates/generate";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

/**
 * 套用模板：克隆当前包，保留 theme.css / 绝对定位版式 / 装饰形，
 * 仅按用户要求改写 data-slot 文案与配图。
 */
export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  const { id } = await params;
  const store = getTemplateStore();
  const meta = await store.getMeta(id);
  if (!meta) {
    return NextResponse.json({ error: "TEMPLATE_NOT_FOUND" }, { status: 404 });
  }

  let body: {
    prompt?: unknown;
    skipImage?: unknown;
    mock?: unknown;
    llmProvider?: unknown;
    llmModel?: unknown;
    imageProvider?: unknown;
    imageModel?: unknown;
  } = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "INVALID_JSON" }, { status: 400 });
  }
  const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
  if (!prompt) {
    return NextResponse.json({ error: "PROMPT_REQUIRED" }, { status: 400 });
  }
  if (prompt.length > 6000) {
    return NextResponse.json({ error: "PROMPT_TOO_LONG" }, { status: 400 });
  }

  try {
    const job = await startRemixJob({
      sourceTemplateId: id,
      prompt,
      // 默认保留原图（版式更稳）；前端可传 skipImage:false 强制重生
      skipImage: body.skipImage !== false,
      mock: Boolean(body.mock),
      llmProvider:
        typeof body.llmProvider === "string" ? body.llmProvider : undefined,
      llmModel: typeof body.llmModel === "string" ? body.llmModel : undefined,
      imageProvider:
        typeof body.imageProvider === "string" ? body.imageProvider : undefined,
      imageModel:
        typeof body.imageModel === "string" ? body.imageModel : undefined,
    });
    return NextResponse.json({ job, templateId: id, mode: "remix" }, { status: 202 });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 400 },
    );
  }
}
