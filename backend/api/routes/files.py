"""Serve agent-output template files for SPA previews / editor."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from admin.fsutil import (
    SAFE_TEMPLATE_DIR,
    effective_status,
    list_template_ids,
    read_meta,
    resolve_under,
    templates_root,
)
from admin.store import load_editor_doc

router = APIRouter()

EMBED_CSP = "; ".join(
    [
        "default-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "media-src 'self' data: blob:",
        "worker-src 'none'",
        "object-src 'none'",
    ]
)


def _content_type(path: Path) -> str:
    guess, _ = mimetypes.guess_type(str(path))
    return guess or "application/octet-stream"


def _rewrite_asset_urls(html: str, template_id: str) -> str:
    from urllib.parse import quote

    base = f"/api/html-templates/{quote(template_id)}/assets"

    def repl_attr(m: re.Match[str]) -> str:
        return f"{m.group(1)}={m.group(2)}{base}/{m.group(3).lstrip('/')}{m.group(2)}"

    out = re.sub(
        r'\b(href|src)=(["\'])\.\./([^"\']+)\2',
        repl_attr,
        html,
        flags=re.I,
    )

    def repl_url(m: re.Match[str]) -> str:
        q = m.group(1) or ""
        return f"url({q}{base}/{m.group(2).lstrip('/')}{q})"

    out = re.sub(
        r"url\(\s*(['\"]?)\.\./([^)'\"]+)\1\s*\)",
        repl_url,
        out,
        flags=re.I,
    )
    return out


def _inject_align(html: str) -> str:
    if "data-element" not in html:
        return html
    snippet = """
<style id="webppt-data-element-preview-align">
[data-element="text"][data-valign="middle"]{display:flex!important;flex-direction:column!important;justify-content:center!important}
[data-element="text"][data-valign="bottom"]{display:flex!important;flex-direction:column!important;justify-content:flex-end!important}
</style>
"""
    if "</head>" in html.lower():
        return re.sub(r"</head>", snippet + "</head>", html, count=1, flags=re.I)
    return snippet + html


@router.get("/api/html-templates")
def list_html_templates():
    templates = []
    for tid in list_template_ids():
        meta = read_meta(tid)
        if not meta:
            continue
        if effective_status(meta) != "approved":
            continue
        slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
        first = slides[0] if slides and isinstance(slides[0], dict) else None
        preview = None
        if first and first.get("file"):
            preview = str(first["file"]).lstrip("/")
        templates.append(
            {
                "id": tid,
                "templateId": tid,
                "label": meta.get("label") or {"zh_CN": tid, "en_US": tid},
                "description": meta.get("description") or {"zh_CN": "", "en_US": ""},
                "slideCount": len(slides),
                "previewFile": preview,
                "status": effective_status(meta),
            }
        )
    return {"templates": templates}


@router.get("/api/html-templates/{template_id}")
def get_html_template(template_id: str):
    if not SAFE_TEMPLATE_DIR.match(template_id):
        return JSONResponse({"error": "INVALID_ID"}, status_code=400)
    meta = read_meta(template_id)
    if not meta:
        return JSONResponse({"error": "NOT_FOUND"}, status_code=404)
    if effective_status(meta) != "approved":
        return JSONResponse(
            {"error": "NOT_APPROVED", "message": "模板尚未通过审批"},
            status_code=403,
        )
    doc = load_editor_doc(template_id)
    if not doc:
        return JSONResponse({"error": "NOT_FOUND"}, status_code=404)
    # public shape (no admin-only fields required)
    return {
        "name": doc["name"],
        "templateDir": template_id,
        "templateId": template_id,
        "label": doc.get("label"),
        "description": doc.get("description"),
        "pages": [
            {
                "id": p["id"],
                "html": p["html"],
                "sourceFile": p["sourceFile"],
                "visible": True,
                "toggleInAnimation": "none",
                "toggleInDuration": "0.5s",
                "toggleInDelay": "0s",
                "autoToggle": False,
                "autoToggleTime": 0,
                "backgroundType": "color",
                "background": "#ffffff",
                "bgColor": "#ffffff",
                "fgColor": "#111111",
                "bgOpacity": 1,
                "remark": p.get("remark"),
            }
            for p in doc["pages"]
        ],
    }


@router.get("/api/html-templates/{template_id}/assets/{asset_path:path}")
def get_template_asset(template_id: str, asset_path: str, request: Request):
    if not SAFE_TEMPLATE_DIR.match(template_id):
        return JSONResponse({"error": "INVALID"}, status_code=400)
    if ".." in asset_path or "\0" in asset_path:
        return JSONResponse({"error": "INVALID_PATH"}, status_code=400)
    file_path = resolve_under(template_id, asset_path)
    if not file_path or not file_path.is_file():
        return JSONResponse({"error": "NOT_FOUND"}, status_code=404)
    optimize = request.query_params.get("optimize") == "1"
    if optimize and file_path.suffix.lower() == ".html":
        html = _rewrite_asset_urls(file_path.read_text(encoding="utf-8"), template_id)
        return HTMLResponse(html, headers={"Cache-Control": "public, max-age=30"})
    return FileResponse(
        file_path,
        media_type=_content_type(file_path),
        headers={"Cache-Control": "public, max-age=30"},
    )


@router.get("/embed/template/{template_id}/{slide_path:path}")
def embed_template_slide(template_id: str, slide_path: str):
    if not SAFE_TEMPLATE_DIR.match(template_id):
        return Response("INVALID", status_code=400)
    if ".." in slide_path or "\0" in slide_path:
        return Response("INVALID_PATH", status_code=400)
    file_path = resolve_under(template_id, slide_path)
    if not file_path or not file_path.is_file():
        return Response("NOT_FOUND", status_code=404)
    # 页面内相对路径 ../images/*.png、theme.css 等也走 embed；
    # 只对 HTML 做 asset URL 重写 + CSP。
    if file_path.suffix.lower() != ".html":
        return FileResponse(
            file_path,
            media_type=_content_type(file_path),
            headers={"Cache-Control": "public, max-age=30"},
        )
    raw = file_path.read_text(encoding="utf-8")
    html = _inject_align(_rewrite_asset_urls(raw, template_id))
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "public, max-age=30",
            "Content-Security-Policy": EMBED_CSP,
            "X-Content-Type-Options": "nosniff",
        },
    )


SLIDE_EMBED_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=1920"/>
<title>Slide Embed</title>
<style>
  html,body{margin:0;padding:0;width:100%;height:100%;background:#fff;overflow:hidden}
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
    document.body.textContent = text;
    document.body.style.cssText = "margin:0;padding:24px;font-family:system-ui,sans-serif;color:#b91c1c";
  }
  function injectEditorRuntime() {
    if (document.querySelector('script[data-webppt-slide-editor]')) return;
    var s = document.createElement("script");
    s.src = "/slide-editor/runtime.js";
    s.defer = true;
    s.setAttribute("data-webppt-slide-editor", "1");
    document.head.appendChild(s);
  }
  try {
    if (!window.parent || window.parent === window) {
      fail("Embed must run inside editor frame");
      return;
    }
    var html = null;
    if (typeof window.parent.__webpptGetSlideHtml === "function") {
      html = window.parent.__webpptGetSlideHtml(pageId, token);
    } else if (
      window.parent.__WEBPPT_SLIDE_BRIDGE__ &&
      typeof window.parent.__WEBPPT_SLIDE_BRIDGE__.getPageHtml === "function"
    ) {
      html = window.parent.__WEBPPT_SLIDE_BRIDGE__.getPageHtml(pageId, token);
    }
    if (!html) {
      fail("Missing slide HTML");
      return;
    }
    document.open();
    document.write(html);
    document.close();
    if (editMode) injectEditorRuntime();
  } catch (e) {
    fail(String(e && e.message ? e.message : e));
  }
})();
</script>
</body>
</html>
"""


@router.get("/embed/slide")
def embed_slide():
    return HTMLResponse(
        SLIDE_EMBED_HTML,
        headers={
            "Content-Security-Policy": EMBED_CSP,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


SAFE_FILE = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_PACK = re.compile(r"^[A-Za-z0-9._\u4e00-\u9fff-]+$")


@router.get("/api/pack-assets/{asset_path:path}")
def pack_assets(asset_path: str):
    parts = [p for p in asset_path.split("/") if p]
    packs_root = templates_root() / "packs"
    file_path = None
    if len(parts) == 1 and SAFE_FILE.match(parts[0]):
        best_mtime = -1.0
        if packs_root.is_dir():
            for pack in packs_root.iterdir():
                cand = pack / "assets" / parts[0]
                if cand.is_file():
                    mtime = cand.stat().st_mtime
                    if mtime > best_mtime:
                        best_mtime = mtime
                        file_path = cand
    elif len(parts) == 2 and SAFE_PACK.match(parts[0]) and SAFE_FILE.match(parts[1]):
        cand = (packs_root / parts[0] / "assets" / parts[1]).resolve()
        if str(cand).startswith(str(packs_root.resolve())) and cand.is_file():
            file_path = cand
    if not file_path:
        return JSONResponse({"error": "NOT_FOUND"}, status_code=404)
    return FileResponse(file_path, media_type=_content_type(file_path))
