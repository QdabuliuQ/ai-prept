import { NextResponse } from "next/server";
import {
  loadTemplatePages,
  readTemplateMeta,
  SAFE_TEMPLATE_DIR,
} from "@/server/htmlTemplates";
import { isPubliclyVisible } from "@/server/templates/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

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

/** GET /api/html-templates/[id] — 公开库仅已审批模板 */
export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  if (!SAFE_TEMPLATE_DIR.test(id)) {
    return NextResponse.json({ error: "INVALID_ID" }, { status: 400 });
  }

  const metaCheck = await readTemplateMeta(id);
  if (!metaCheck) {
    return NextResponse.json({ error: "NOT_FOUND" }, { status: 404 });
  }
  if (!isPubliclyVisible(metaCheck)) {
    return NextResponse.json(
      { error: "NOT_APPROVED", message: "模板尚未通过审批" },
      { status: 403 },
    );
  }

  const loaded = await loadTemplatePages(id);
  if (!loaded) {
    return NextResponse.json({ error: "NOT_FOUND" }, { status: 404 });
  }

  const { meta, pages } = loaded;
  const name = meta.label?.zh_CN || id;

  return NextResponse.json({
    name,
    templateDir: id,
    templateId: id,
    label: meta.label,
    description: meta.description,
    pages: pages.map(toEditorPage),
  });
}
