import { NextResponse } from "next/server";
import { assertAdmin } from "@/server/adminAuth";
import {
  loadVisualStyleCatalog,
  visualStyleSelectOptions,
  visualStylesDir,
} from "@/server/templates/visualStyles";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * GET /api/admin/styles
 * PPT Master visual-style catalog (from ppt-master/.../visual-styles/_catalog.json).
 */
export async function GET(req: Request) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  const url = new URL(req.url);
  const includeVariants = url.searchParams.get("variants") !== "0";
  const catalog = loadVisualStyleCatalog();

  return NextResponse.json({
    dir: visualStylesDir(),
    schema_version: catalog.schema_version,
    generated_at: catalog.generated_at ?? null,
    count: catalog.count,
    styles: catalog.styles.filter((s) =>
      includeVariants ? true : s.status === "curated",
    ),
    selectOptions: visualStyleSelectOptions({ includeVariants }),
  });
}
