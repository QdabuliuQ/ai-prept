import { NextResponse } from "next/server";
import { assertAdmin } from "@/server/adminAuth";
import {
  cancelGenerateJob,
  deleteGenerateJob,
  getJob,
  loadRecentJobsFromDisk,
  refreshJobFromDisk,
} from "@/server/templates/generate";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/admin/generate/[id] */
export async function GET(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const denied = assertAdmin(req);
  if (denied) return denied;
  await loadRecentJobsFromDisk();
  const { id } = await ctx.params;
  let job = getJob(id);
  // running 时再强制读盘，避免 HMR/多实例内存卡死
  if (job && (job.status === "running" || job.status === "queued")) {
    job = (await refreshJobFromDisk(id)) || job;
  }
  if (!job) {
    return NextResponse.json({ error: "NOT_FOUND" }, { status: 404 });
  }
  return NextResponse.json({ job });
}

/**
 * POST /api/admin/generate/[id]
 * body: { action: "cancel" | "delete" }
 */
export async function POST(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  const { id } = await ctx.params;
  let body: { action?: string } = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "INVALID_JSON" }, { status: 400 });
  }

  if (body.action !== "cancel" && body.action !== "delete") {
    return NextResponse.json(
      { error: "UNKNOWN_ACTION", allowed: ["cancel", "delete"] },
      { status: 400 },
    );
  }

  try {
    if (body.action === "delete") {
      await deleteGenerateJob(id);
      return NextResponse.json({ ok: true, id });
    }
    const job = await cancelGenerateJob(id);
    return NextResponse.json({ job });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg === "NOT_FOUND") {
      return NextResponse.json({ error: "NOT_FOUND" }, { status: 404 });
    }
    if (msg === "JOB_ACTIVE") {
      return NextResponse.json(
        { error: "JOB_ACTIVE", message: "运行中/排队中的任务请先取消再删除" },
        { status: 400 },
      );
    }
    return NextResponse.json({ error: msg }, { status: 400 });
  }
}
