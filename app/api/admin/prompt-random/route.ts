import { NextResponse } from "next/server";
import { assertAdmin } from "@/server/adminAuth";
import { generateRandomThemePrompt } from "@/server/templates/scoreVl";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

/**
 * POST /api/admin/prompt-random
 * 用 SCORE_VL_*（DashScope 兼容）随机生成「主题描述」。
 */
export async function POST(req: Request) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  let visualStyle: string | undefined;
  try {
    const body = (await req.json()) as { visualStyle?: string };
    visualStyle =
      typeof body.visualStyle === "string" ? body.visualStyle.trim() : undefined;
  } catch {
    /* empty body ok */
  }

  try {
    const result = await generateRandomThemePrompt({ visualStyle });
    return NextResponse.json(result);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}
