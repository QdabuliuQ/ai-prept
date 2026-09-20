import { NextResponse } from "next/server";
import {
  ensureSlideVendorCss,
  listPublicTemplateDirs,
  readTemplateMeta,
} from "@/server/htmlTemplates";
import { effectiveStatus } from "@/server/templates/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/html-templates — 公开：仅已审批模板 */
export async function GET() {
  await ensureSlideVendorCss();
  const dirs = await listPublicTemplateDirs();
  const templates: Array<{
    id: string;
    templateId: string;
    label: { zh_CN?: string; en_US?: string };
    description: { zh_CN?: string; en_US?: string };
    slideCount: number;
    previewFile: string | null;
    status: string;
  }> = [];

  for (const id of dirs) {
    const meta = await readTemplateMeta(id);
    if (!meta) continue;

    const first = meta.slides?.[0];
    templates.push({
      id,
      templateId: id,
      label: meta.label || { zh_CN: id, en_US: id },
      description: meta.description || { zh_CN: "", en_US: "" },
      slideCount: meta.slides?.length ?? 0,
      previewFile: first?.file?.replace(/^\/+/, "") || null,
      status: effectiveStatus(meta),
    });
  }

  return NextResponse.json({ templates });
}
