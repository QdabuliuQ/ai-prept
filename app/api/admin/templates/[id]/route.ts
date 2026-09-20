import { NextResponse } from "next/server";
import { assertAdmin } from "@/server/adminAuth";
import {
  loadTemplatePages,
  SAFE_TEMPLATE_DIR,
} from "@/server/htmlTemplates";
import { getTemplateStore } from "@/server/templates/store";
import {
  effectiveFormat,
  type TemplateStatus,
} from "@/server/templates/types";
import path from "path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const STATUSES: TemplateStatus[] = [
  "draft",
  "pending",
  "approved",
  "rejected",
];

function toEditorPage(p: {
  id: string;
  title: string;
  html: string;
  file: string;
}) {
  return {
    id: p.id,
    html: p.html,
    sourceFile: p.file,
    elements: [] as unknown[],
    visible: true,
    toggleInAnimation: "none",
    toggleInDuration: "0.5s",
    toggleInDelay: "0s",
    autoToggle: false,
    autoToggleTime: 0,
    backgroundType: "color",
    background: "#ffffff",
    bgColor: "#ffffff",
    fgColor: "#111111",
    bgOpacity: 1,
    remark: p.title,
  };
}

/** GET /api/admin/templates/[id]
 *  默认：预览元数据（不读 HTML）
 *  ?doc=1：完整编辑器文档（可加载到编辑器 / 导出 PPTX）
 */
export async function GET(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  const { id } = await ctx.params;
  if (!SAFE_TEMPLATE_DIR.test(id)) {
    return NextResponse.json({ error: "INVALID_ID" }, { status: 400 });
  }

  const wantDoc = new URL(req.url).searchParams.get("doc") === "1";
  if (wantDoc) {
    const loaded = await loadTemplatePages(id);
    if (!loaded) {
      return NextResponse.json({ error: "NOT_FOUND" }, { status: 404 });
    }
    const { meta, pages } = loaded;
    const name = meta.label?.zh_CN || id;
    return NextResponse.json({
      id,
      name,
      format: effectiveFormat(meta),
      templateDir: id,
      templateId: id,
      label: meta.label,
      description: meta.description,
      meta,
      pages: pages.map(toEditorPage),
    });
  }

  const store = getTemplateStore();
  const meta = await store.getMeta(id);
  if (!meta) {
    return NextResponse.json({ error: "NOT_FOUND" }, { status: 404 });
  }

  const pages = (meta.slides || []).map((slide, i) => {
    const file = (slide.file || "").replace(/^\/+/, "");
    const layout =
      slide.layout || path.basename(file, ".html") || `slide-${i + 1}`;
    return {
      id: `tpl_${layout}_${i + 1}`,
      title: slide.title || layout,
      layout,
      file,
    };
  });

  return NextResponse.json({
    id,
    meta,
    format: effectiveFormat(meta),
    pages,
  });
}

/** PATCH /api/admin/templates/[id] — 审批 / 驳回 */
export async function PATCH(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  const { id } = await ctx.params;
  if (!SAFE_TEMPLATE_DIR.test(id)) {
    return NextResponse.json({ error: "INVALID_ID" }, { status: 400 });
  }

  let body: { status?: string; note?: string } = {};
  try {
    body = (await req.json()) as { status?: string; note?: string };
  } catch {
    return NextResponse.json({ error: "INVALID_JSON" }, { status: 400 });
  }

  const status = body.status as TemplateStatus | undefined;
  if (!status || !STATUSES.includes(status)) {
    return NextResponse.json(
      { error: "INVALID_STATUS", allowed: STATUSES },
      { status: 400 },
    );
  }

  try {
    const meta = await getTemplateStore().setStatus(id, status, {
      note: body.note,
      reviewedBy: "admin",
    });
    return NextResponse.json({ ok: true, meta });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 404 },
    );
  }
}

/** DELETE /api/admin/templates/[id] */
export async function DELETE(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  const { id } = await ctx.params;
  if (!SAFE_TEMPLATE_DIR.test(id)) {
    return NextResponse.json({ error: "INVALID_ID" }, { status: 400 });
  }

  try {
    await getTemplateStore().delete(id);
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 404 },
    );
  }
}
