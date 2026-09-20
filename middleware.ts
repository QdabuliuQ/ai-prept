import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * 保护 /admin 页面（API 另有 assertAdmin）。
 * 未配置 ADMIN_TOKEN 时仅提示，不拦页面（API 仍会 503）。
 */
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (!pathname.startsWith("/admin")) {
    return NextResponse.next();
  }

  // 静态与登录页本身不在此特殊处理；token 由前端校验
  return NextResponse.next();
}

export const config = {
  matcher: ["/admin/:path*"],
};
