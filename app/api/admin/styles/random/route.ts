import { NextResponse } from "next/server";
import { assertAdmin } from "@/server/adminAuth";
import {
  generateRandomStyleIntent,
  pickRandomStyleIntentSeed,
} from "@/server/templates/scoreVl";
import { pickRandomVisualStyle } from "@/server/templates/visualStyles";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

/**
 * POST /api/admin/styles/random
 * Body: { mode?: "catalog" | "invent", exclude?: string[] }
 * - catalog: pick a curated style id from _catalog.json
 * - invent: invent a style intent (SCORE_VL, else seed pool)
 */
export async function POST(req: Request) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  let body: { mode?: string; exclude?: unknown } = {};
  try {
    body = await req.json();
  } catch {
    /* empty ok */
  }

  const mode = body.mode === "invent" ? "invent" : "catalog";
  const exclude = Array.isArray(body.exclude)
    ? body.exclude.map((x) => String(x || "").trim()).filter(Boolean)
    : [];

  if (mode === "catalog") {
    const picked = pickRandomVisualStyle({ exclude });
    return NextResponse.json({
      mode: "catalog",
      styleId: picked.id,
      labelZh: picked.label_zh,
      groupZh: picked.group_zh,
      family: picked.family,
    });
  }

  try {
    const result = await generateRandomStyleIntent();
    return NextResponse.json({
      mode: "invent",
      styleIntent: result.intent,
      model: result.model,
      ensureStyle: true,
    });
  } catch (e) {
    const seed = pickRandomStyleIntentSeed();
    return NextResponse.json({
      mode: "invent",
      styleIntent: seed,
      model: null,
      ensureStyle: true,
      warning:
        e instanceof Error
          ? `SCORE_VL 不可用，已用种子池：${e.message}`
          : "SCORE_VL 不可用，已用种子池",
    });
  }
}
