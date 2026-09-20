import { NextResponse } from "next/server";

const HEADER = "x-admin-token";

export function getAdminToken(): string {
  return (process.env.ADMIN_TOKEN || "").trim();
}

export function assertAdmin(req: Request): NextResponse | null {
  const expected = getAdminToken();
  if (!expected) {
    return NextResponse.json(
      {
        error:
          "未配置 ADMIN_TOKEN。请在 .env.local 设置 ADMIN_TOKEN 后重启服务。",
      },
      { status: 503 },
    );
  }

  const header = req.headers.get(HEADER) || "";
  const auth = req.headers.get("authorization") || "";
  const bearer = auth.toLowerCase().startsWith("bearer ")
    ? auth.slice(7).trim()
    : "";
  const cookie = parseCookie(req.headers.get("cookie") || "").webppt_admin_token;

  const provided = header || bearer || cookie || "";
  if (provided !== expected) {
    return NextResponse.json({ error: "未授权" }, { status: 401 });
  }
  return null;
}

function parseCookie(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of raw.split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    const k = part.slice(0, i).trim();
    const v = part.slice(i + 1).trim();
    if (k) out[k] = decodeURIComponent(v);
  }
  return out;
}

export { HEADER as ADMIN_TOKEN_HEADER };
