import { NextResponse } from "next/server";
import { assertAdmin } from "@/server/adminAuth";
import {
  clearTerminalGenerateJobs,
  deleteGenerateJobs,
  listJobs,
  loadRecentJobsFromDisk,
  startGenerateJob,
} from "@/server/templates/generate";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
/** 生成可能较久，放宽（仍由子进程异步跑） */
export const maxDuration = 60;

/** GET /api/admin/generate — 最近任务 */
export async function GET(req: Request) {
  const denied = assertAdmin(req);
  if (denied) return denied;
  await loadRecentJobsFromDisk();
  return NextResponse.json({ jobs: listJobs(50) });
}

function parseIds(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((id) => (typeof id === "string" ? id.trim() : ""))
    .filter((id) => id.length > 0);
}

/**
 * POST /api/admin/generate
 * - 默认：启动 PPT Master（webppt-agent ppt-master）
 * - { action: "delete", ids: string[] }：批量删除已结束任务日志
 * - { action: "clear-terminal" }：清空全部已结束任务日志
 */
export async function POST(req: Request) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  let body: {
    action?: string;
    ids?: unknown;
    prompt?: string;
    mock?: boolean;
    skipImage?: boolean;
    paletteRefine?: boolean;
    visualStyle?: string;
    pptMasterRender?: string;
    count?: number;
    pages?: number;
    repairOnFail?: boolean;
    qualityGate?: string;
    stripUnsupported?: boolean;
    llmProvider?: string;
    llmModel?: string;
    imageProvider?: string;
    imageModel?: string;
    styleIntent?: string;
    ensureStyle?: boolean;
    randomTheme?: boolean;
    randomStyle?: boolean;
    randomStyleMode?: string;
  } = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "INVALID_JSON" }, { status: 400 });
  }

  if (body.action === "clear-terminal") {
    const result = await clearTerminalGenerateJobs();
    return NextResponse.json({ ok: result.failed.length === 0, ...result });
  }

  if (body.action === "delete") {
    const ids = parseIds(body.ids);
    if (ids.length === 0) {
      return NextResponse.json({ error: "IDS_REQUIRED" }, { status: 400 });
    }
    if (ids.length > 200) {
      return NextResponse.json({ error: "TOO_MANY_IDS" }, { status: 400 });
    }
    const result = await deleteGenerateJobs(ids);
    return NextResponse.json({ ok: result.failed.length === 0, ...result });
  }

  if (body.action) {
    return NextResponse.json(
      { error: "UNKNOWN_ACTION", allowed: ["delete", "clear-terminal"] },
      { status: 400 },
    );
  }

  try {
    const job = await startGenerateJob({
      prompt: body.prompt || "",
      mock: body.mock,
      skipImage: body.skipImage,
      paletteRefine: body.paletteRefine,
      visualStyle: body.visualStyle,
      pptMasterRender: body.pptMasterRender,
      count: body.count,
      pages: body.pages,
      repairOnFail: body.repairOnFail,
      qualityGate:
        body.qualityGate === "strict" || body.qualityGate === "skip"
          ? body.qualityGate
          : body.qualityGate === "soft"
            ? "soft"
            : undefined,
      stripUnsupported: body.stripUnsupported,
      llmProvider: body.llmProvider,
      llmModel: body.llmModel,
      imageProvider: body.imageProvider,
      imageModel: body.imageModel,
      styleIntent: body.styleIntent,
      ensureStyle: body.ensureStyle,
      randomTheme: body.randomTheme,
      randomStyle: body.randomStyle,
      randomStyleMode:
        body.randomStyleMode === "invent" ? "invent" : body.randomStyleMode === "catalog" ? "catalog" : undefined,
    });
    return NextResponse.json({ job }, { status: 202 });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 400 },
    );
  }
}
