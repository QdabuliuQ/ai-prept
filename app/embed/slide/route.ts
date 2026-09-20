import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * 幻灯片 embed CSP：约束 boot 壳与 document.write 后的页面。
 * 资源策略对齐 agent（禁止 Tailwind/FA CDN，走同源 /slide-vendor 与 data/https 图）。
 */
const SLIDE_EMBED_CSP = [
  "default-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'self'",
  // boot 内联脚本 + 幻灯片内联脚本；同源 vendor / slide-editor runtime
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "media-src 'self' data: blob:",
  "worker-src 'none'",
  "object-src 'none'",
].join("; ");

/**
 * GET /embed/slide?pageId=…&v=…&t=…&edit=1
 * 返回精简 HTML：从父窗口桥读取 page HTML 并整页替换。
 * edit=1 时在 write 后注入 slide-editor runtime（data-injected）。
 */
export async function GET(req: Request) {
  const url = new URL(req.url);
  const editMode = url.searchParams.get("edit") === "1";

  const html = `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=1920"/>
<title>Slide Embed</title>
<style>
  html,body{margin:0;padding:0;width:100%;height:100%;background:#fff;overflow:hidden}
  #msg{display:none}
</style>
</head>
<body>
<script>
(function () {
  var params = new URLSearchParams(location.search);
  var pageId = params.get("pageId") || "";
  var token = params.get("t") || "";
  var editMode = params.get("edit") === "1";

  function fail(text) {
    document.body.setAttribute("data-webppt-embed-error", "1");
    document.body.textContent = text;
    document.body.style.cssText = "margin:0;padding:24px;font-family:system-ui,sans-serif;color:#b91c1c";
  }

  function injectEditorRuntime() {
    if (!editMode) return;
    try {
      if (window.__WEBPPT_SLIDE_EDITOR__) return;
      var s = document.createElement("script");
      s.src = "/slide-editor/runtime.js";
      s.setAttribute("data-injected", "true");
      s.async = false;
      (document.head || document.documentElement).appendChild(s);
    } catch (e) {}
  }

  function writeHtml(html) {
    document.open();
    document.write(html);
    document.close();
    injectEditorRuntime();
  }

  function tryRead() {
    try {
      var bridge = window.parent && window.parent.__WEBPPT_SLIDE_BRIDGE__;
      var html = bridge && bridge.getPageHtml(pageId, token);
      if (html) {
        writeHtml(html);
        return true;
      }
    } catch (e) {}
    return false;
  }

  function boot() {
    if (!pageId) {
      fail("缺少 pageId");
      return;
    }
    if (!token) {
      fail("缺少访问令牌");
      return;
    }
    if (tryRead()) return;
    var n = 0;
    // ~8s：覆盖 React Strict Mode remount / 父页桥安装延迟
    var timer = setInterval(function () {
      n += 1;
      if (tryRead() || n >= 160) {
        clearInterval(timer);
        if (n >= 160) fail("无法从编辑器读取页面内容");
      }
    }, 50);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(boot, 0);
    });
  } else {
    setTimeout(boot, 0);
  }
})();
</script>
</body>
</html>`;

  void editMode;

  return new NextResponse(html, {
    status: 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "Content-Security-Policy": SLIDE_EMBED_CSP,
      "X-Content-Type-Options": "nosniff",
    },
  });
}
