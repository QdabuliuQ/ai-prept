import { NextResponse } from "next/server";
import { assertAdmin } from "@/server/adminAuth";
import { SAFE_TEMPLATE_DIR } from "@/server/htmlTemplates";
import { packAndUploadTemplate } from "@/server/templates/packAndUpload";
import { getQiniuConfig } from "@/server/templates/qiniu";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
/** 压缩图片 + 打 zip + 截预览 + 上传七牛 */
export const maxDuration = 600;

/**
 * POST /api/admin/templates/[id]/upload
 * 仅「已通过」模板：压缩 images → zip 整包 → 上传七牛云
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

  if (!getQiniuConfig()) {
    return NextResponse.json(
      {
        error:
          "未配置七牛云。请在 .env.local 设置 QINIU_ACCESS_KEY / QINIU_SECRET_KEY / QINIU_BUCKET / QINIU_DOMAIN 后重启服务。",
      },
      { status: 503 },
    );
  }

  try {
    const result = await packAndUploadTemplate(id);
    return NextResponse.json({ ok: true, ...result });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    const status =
      msg.includes("仅「已通过」") || msg.includes("已通过")
        ? 403
        : msg.includes("不存在")
          ? 404
          : 500;
    return NextResponse.json({ error: msg }, { status });
  }
}
