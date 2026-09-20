import { NextResponse } from "next/server";
import { assertAdmin } from "@/server/adminAuth";
import { listImageProvidersPublic } from "@/server/templates/imageProviders";
import { listLlmProvidersPublic } from "@/server/templates/llmProviders";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/admin/llm — 文本 / 文生图可选模型与 Key 是否已配置（不回传明文 Key） */
export async function GET(req: Request) {
  const denied = assertAdmin(req);
  if (denied) return denied;
  return NextResponse.json({
    providers: listLlmProvidersPublic(),
    imageProviders: listImageProvidersPublic(),
  });
}
