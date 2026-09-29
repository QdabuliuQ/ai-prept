"""Admin templates CRUD + prepare/upload/use/visual-spec."""

from __future__ import annotations

from typing import Optional, List, Dict, Any

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from admin.fsutil import SAFE_TEMPLATE_DIR
from api.auth import assert_admin
from api.http import err, http_error_from_message, ok

router = APIRouter(dependencies=[Depends(assert_admin)])

STATUSES = {"draft", "pending", "approved", "rejected"}


def _safe(tid: str) -> str | JSONResponse:
    if not SAFE_TEMPLATE_DIR.match(tid):
        return err(400, error="INVALID_ID")
    return tid


@router.get("/api/admin/templates")
def list_templates(status: str | None = None):
    from admin.store import list_templates as list_tpl

    statuses = None
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
    return {"backend": "postgres", "templates": list_tpl(statuses)}


@router.post("/api/admin/templates")
async def batch_templates(request: Request):
    from admin.store import delete_many, set_status

    try:
        body = await request.json()
    except Exception:
        return err(400, error="INVALID_JSON")
    action = str(body.get("action") or "")
    ids = [str(i).strip() for i in (body.get("ids") or []) if str(i).strip()]
    if not ids:
        return err(400, error="IDS_REQUIRED")
    if len(ids) > 200:
        return err(400, error="TOO_MANY_IDS")
    invalid = [i for i in ids if not SAFE_TEMPLATE_DIR.match(i)]
    if invalid:
        return err(400, error="INVALID_ID", invalid=invalid)

    if action == "delete":
        result = delete_many(ids)
        return {"ok": len(result["failed"]) == 0, **result}
    if action in ("approve", "reject"):
        status = "approved" if action == "approve" else "rejected"
        note = "批量通过" if action == "approve" else "批量驳回"
        updated: list[str] = []
        failed: list[dict[str, str]] = []
        for tid in ids:
            try:
                set_status(tid, status, note=note)
                updated.append(tid)
            except Exception as e:  # noqa: BLE001
                failed.append({"id": tid, "error": str(e)})
        return {
            "ok": len(failed) == 0,
            "updated": updated,
            "failed": failed,
            "status": status,
        }
    return err(400, error="INVALID_ACTION", allowed=["delete", "approve", "reject"])


@router.delete("/api/admin/templates")
async def batch_delete(request: Request):
    from admin.store import delete_many

    ids: list[str] = []
    try:
        body = await request.json()
        ids = [str(i).strip() for i in (body.get("ids") or []) if str(i).strip()]
    except Exception:
        pass
    if not ids:
        q = request.query_params.getlist("ids")
        for v in q:
            ids.extend(s.strip() for s in v.split(",") if s.strip())
    if not ids:
        return err(400, error="IDS_REQUIRED")
    if len(ids) > 200:
        return err(400, error="TOO_MANY_IDS")
    invalid = [i for i in ids if not SAFE_TEMPLATE_DIR.match(i)]
    if invalid:
        return err(400, error="INVALID_ID", invalid=invalid)
    result = delete_many(ids)
    return {"ok": len(result["failed"]) == 0, **result}


@router.get("/api/admin/templates/{template_id}")
def get_template(template_id: str, doc: str | None = None):
    from admin.store import load_editor_doc, load_pages_meta

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    if doc == "1":
        data = load_editor_doc(tid)
        if not data:
            return err(404, error="NOT_FOUND")
        return data
    data = load_pages_meta(tid)
    if not data:
        return err(404, error="NOT_FOUND")
    return data


@router.patch("/api/admin/templates/{template_id}")
async def patch_template(template_id: str, request: Request):
    from admin.store import set_category, set_featured, set_status
    from templates.categories import category_ids

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    try:
        body = await request.json()
    except Exception:
        return err(400, error="INVALID_JSON")
    has_status = "status" in body
    has_featured = "featured" in body
    has_category = "category" in body
    if not has_status and not has_featured and not has_category:
        return err(400, error="EMPTY_PATCH")
    meta = None
    try:
        if has_status:
            status = body.get("status")
            if status not in STATUSES:
                return err(400, error="INVALID_STATUS", allowed=sorted(STATUSES))
            meta = set_status(tid, status, note=body.get("note"), reviewed_by="admin")
        if has_featured:
            featured = body.get("featured")
            if not isinstance(featured, bool):
                return err(400, error="INVALID_FEATURED")
            meta = set_featured(tid, featured)
        if has_category:
            category = body.get("category")
            allowed = category_ids()
            if not isinstance(category, str) or category not in allowed:
                return err(400, error="INVALID_CATEGORY", allowed=list(allowed))
            meta = set_category(tid, category)
        return ok(ok=True, meta=meta)
    except ValueError as e:
        return err(400, error=str(e))
    except Exception as e:  # noqa: BLE001
        return err(404, error=str(e))


@router.delete("/api/admin/templates/{template_id}")
def delete_one(template_id: str):
    from admin.store import delete_template

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    try:
        delete_template(tid)
        return ok(ok=True)
    except Exception as e:  # noqa: BLE001
        return err(404, error=str(e))


@router.post("/api/admin/templates/{template_id}/prepare")
async def prepare(template_id: str, request: Request):
    from admin.pack import decode_preview_body, prepare_template_package

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    try:
        body = await request.json()
    except Exception:
        return err(400, error="INVALID_JSON")
    previews = body.get("previews")
    if not isinstance(previews, list) or not previews:
        return err(400, error="缺少预览图。请先离屏截图。")
    try:
        shots = decode_preview_body(previews)
        result = prepare_template_package(tid, shots)
        return ok(ok=True, **result)
    except Exception as e:  # noqa: BLE001
        return http_error_from_message(str(e))


@router.post("/api/admin/templates/{template_id}/upload")
def upload(template_id: str):
    from admin.qiniu_upload import get_qiniu_config, pack_and_upload_template

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    if not get_qiniu_config():
        return err(
            503,
            error="未配置七牛云。请在 .env.local 设置 QINIU_ACCESS_KEY / QINIU_SECRET_KEY / QINIU_BUCKET / QINIU_DOMAIN 后重启服务。",
        )
    try:
        result = pack_and_upload_template(tid)
        return ok(ok=True, **result)
    except Exception as e:  # noqa: BLE001
        return http_error_from_message(str(e))


@router.post("/api/admin/templates/{template_id}/use")
async def use_template(template_id: str, request: Request):
    from admin.fsutil import template_dir
    from admin.jobs import start_remix_job

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    if not (template_dir(tid) / "template.json").is_file():
        return err(404, error="TEMPLATE_NOT_FOUND")
    try:
        body = await request.json()
    except Exception:
        return err(400, error="INVALID_JSON")
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        return err(400, error="PROMPT_REQUIRED")
    if len(prompt) > 6000:
        return err(400, error="PROMPT_TOO_LONG")
    spec = template_dir(tid) / "visual-spec.md"
    if not spec.is_file() or not spec.read_text(encoding="utf-8").strip():
        return err(
            400,
            error="VISUAL_SPEC_REQUIRED",
            message="源模板缺少 visual-spec.md，请先生成设计规范后再使用模板",
        )
    try:
        job = start_remix_job(
            {
                "sourceTemplateId": tid,
                "prompt": prompt,
                "skipImage": body.get("skipImage") is not False,
                "mock": bool(body.get("mock")),
                # 使用模板默认 Gemini 3.8；前端传 llmProvider/llmModel 可覆盖
                "llmProvider": body.get("llmProvider") or "gemini",
                "llmModel": body.get("llmModel") or "gemini-3.8-flash",
                "imageProvider": body.get("imageProvider"),
                "imageModel": body.get("imageModel"),
            }
        )
        return JSONResponse(
            {"job": job, "templateId": tid, "mode": "remix"},
            status_code=202,
        )
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "visual-spec" in msg:
            return err(400, error="VISUAL_SPEC_REQUIRED", message=msg)
        return err(400, error=msg)


@router.post("/api/admin/templates/{template_id}/rewrite-page")
async def rewrite_page(template_id: str, request: Request):
    """In-place rewrite one HTML slide from an issue description."""
    from admin.fsutil import template_dir
    from admin.jobs import start_rewrite_page_job

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    root = template_dir(tid)
    if not (root / "template.json").is_file():
        return err(404, error="TEMPLATE_NOT_FOUND")
    try:
        body = await request.json()
    except Exception:
        return err(400, error="INVALID_JSON")
    issue = str(body.get("issue") or body.get("prompt") or "").strip()
    if len(issue) < 4:
        return err(400, error="ISSUE_REQUIRED", message="请填写本页问题（至少 4 字）")
    if len(issue) > 2000:
        return err(400, error="ISSUE_TOO_LONG")
    try:
        job = start_rewrite_page_job(
            {
                "sourceTemplateId": tid,
                "issue": issue,
                "file": body.get("file") or body.get("slideFile"),
                "pageIndex": body.get("pageIndex"),
                "mock": bool(body.get("mock")),
                "llmProvider": body.get("llmProvider"),
                "llmModel": body.get("llmModel"),
            }
        )
        return JSONResponse(
            {"job": job, "templateId": tid, "mode": "rewrite-page"},
            status_code=202,
        )
    except Exception as e:  # noqa: BLE001
        return err(400, error=str(e))


@router.post("/api/admin/templates/{template_id}/visual-spec")
async def visual_spec(template_id: str, request: Request):
    from admin.fsutil import template_dir
    from templates.visual_spec import generate_visual_spec

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    root = template_dir(tid)
    if not root.is_dir():
        return err(404, error="NOT_FOUND")
    mock = False
    only_if_missing = False
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()
            mock = bool(body.get("mock"))
            only_if_missing = bool(
                body.get("ifMissing")
                or body.get("onlyIfMissing")
                or body.get("only_if_missing")
            )
    except Exception:
        pass
    try:
        out = generate_visual_spec(
            root, mock=mock, only_if_missing=only_if_missing
        )
        try:
            from admin.store import upsert_template_row

            upsert_template_row(tid)
        except Exception:
            pass
        return ok(ok=True, id=tid, path=str(out), status="ok", log="")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        code = "GENERATE_FAILED"
        if "LLM" in msg or "key" in msg.lower():
            code = "LLM_CONFIG"
        status = 400 if code == "LLM_CONFIG" else 500
        return err(status, error=code, message=msg)


@router.get("/api/admin/templates/{template_id}/source.pptx")
def get_source_pptx(template_id: str):
    """Stream agent-output/<id>/source.pptx for browser-side HTML convert."""
    from fastapi.responses import FileResponse

    from admin.fsutil import resolve_under, template_dir

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    root = template_dir(tid)
    if not root.is_dir():
        return err(404, error="NOT_FOUND")
    path = resolve_under(tid, "source.pptx")
    if not path or not path.is_file():
        return err(404, error="SOURCE_PPTX_MISSING", message="未找到 source.pptx")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename="source.pptx",
    )


@router.post("/api/admin/templates/{template_id}/import-html-package")
async def import_html_package(template_id: str, request: Request):
    """Write browser-converted html-slide package under agent-output/<id>/."""
    import base64
    from datetime import datetime, timezone

    from admin.fsutil import read_meta, template_dir, write_meta
    from admin.store import upsert_template_row

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    root = template_dir(tid)
    if not root.is_dir():
        return err(404, error="NOT_FOUND")

    try:
        body = await request.json()
    except Exception:
        return err(400, error="INVALID_JSON")
    if not isinstance(body, dict):
        return err(400, error="INVALID_JSON")

    slides_in = body.get("slides") or []
    if not isinstance(slides_in, list) or not slides_in:
        return err(400, error="SLIDES_REQUIRED")

    images_in = body.get("images") or []
    if not isinstance(images_in, list):
        images_in = []
    warnings = body.get("warnings") if isinstance(body.get("warnings"), list) else []
    theme = body.get("theme") if isinstance(body.get("theme"), dict) else {}

    prev = read_meta(tid) or {}
    prev_label = ""
    if isinstance(prev.get("label"), dict):
        prev_label = str(
            prev["label"].get("zh_CN") or prev["label"].get("en_US") or ""
        ).strip()
    raw_label = str(body.get("labelZh") or "").strip()
    # 前端若误传 public id，保留转换前已有的中文展示名
    if raw_label and raw_label != tid:
        label_zh = raw_label
    elif prev_label and prev_label != tid:
        label_zh = prev_label
    else:
        label_zh = tid

    slides_dir = root / "slides"
    images_dir = root / "images"
    slides_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    # Clear previous slide/html artifacts (keep source.pptx)
    for old in slides_dir.glob("*.html"):
        old.unlink(missing_ok=True)

    written_slides: list[dict] = []
    for i, s in enumerate(slides_in):
        if not isinstance(s, dict):
            continue
        rel = str(s.get("file") or f"slides/slide-{i + 1}.html").strip()
        if ".." in rel or rel.startswith("/") or not rel.startswith("slides/"):
            return err(400, error="INVALID_SLIDE_PATH", message=rel)
        html = str(s.get("html") or "")
        if not html.strip():
            return err(400, error="EMPTY_SLIDE_HTML", message=rel)
        abs_path = (root / rel).resolve()
        if not str(abs_path).startswith(str(root.resolve()) + "/"):
            return err(400, error="INVALID_SLIDE_PATH", message=rel)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(
            html if html.endswith("\n") else html + "\n", encoding="utf-8"
        )
        written_slides.append(
            {
                "file": rel,
                "title": str(s.get("title") or rel),
                "layout": str(s.get("layout") or "content"),
                "description": str(s.get("description") or ""),
            }
        )

    written_images = 0
    for img in images_in:
        if not isinstance(img, dict):
            continue
        rel = str(img.get("path") or "").strip()
        b64 = str(img.get("dataBase64") or "").strip()
        if not rel or not b64:
            continue
        if ".." in rel or rel.startswith("/") or not (
            rel.startswith("images/") or rel.startswith("slides/")
        ):
            return err(400, error="INVALID_IMAGE_PATH", message=rel)
        # strip data-url prefix if present
        if "," in b64 and b64.lower().startswith("data:"):
            b64 = b64.split(",", 1)[1]
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception:
            return err(400, error="INVALID_BASE64", message=rel)
        abs_path = (root / rel).resolve()
        if not str(abs_path).startswith(str(root.resolve()) + "/"):
            return err(400, error="INVALID_IMAGE_PATH", message=rel)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(raw)
        written_images += 1

    bg = str(theme.get("bg") or "#ffffff")
    text = str(theme.get("text") or "#111111")
    accent = str(theme.get("accent") or "#2563eb")
    theme_css = f"""/* Converted from PPTX — tokens only; page geometry stays in slides/*.html */
:root {{
  --color-bg: {bg};
  --color-surface: {bg};
  --color-text: {text};
  --color-muted: #5c5c5c;
  --color-accent: {accent};
  --color-border: #e5e5e5;
  --color-primary: {accent};
  --font-sans: "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
  --chart-1: {accent};
  --chart-2: #0d9488;
  --chart-3: #d97706;
  --chart-4: #dc2626;
  --chart-5: #7c3aed;
}}

html, body, .slide, .slide-container {{
  width: 1920px;
  height: 1080px;
  margin: 0;
  padding: 0;
  box-sizing: border-box;
  overflow: hidden;
}}

body {{
  background: var(--color-bg);
  color: var(--color-text);
  font-family: var(--font-sans);
}}

.slide-container img {{
  max-width: none;
}}

.slide-container svg {{
  overflow: visible;
}}

.slide-container > div:has(> svg:only-child),
.pptx-slide-root > div:has(> svg:only-child) {{
  z-index: 0;
}}
.slide-container > div:has(span),
.slide-container > [data-slot-type="text"],
.pptx-slide-root > div:has(span),
.pptx-slide-root > [data-slot-type="text"] {{
  z-index: 2;
}}
"""
    (root / "theme.css").write_text(
        theme_css if theme_css.endswith("\n") else theme_css + "\n",
        encoding="utf-8",
    )

    usage = prev.get("usage") if isinstance(prev.get("usage"), dict) else None
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    meta = {
        "schema_version": "1.0",
        "template_id": tid,
        "public_id": tid,
        "format": prev.get("format") or "ppt-master",
        "render": prev.get("render") or "svg",
        "label": {
            "zh_CN": label_zh,
            "en_US": label_zh,
        },
        "description": {
            "zh_CN": f"由 PPT Master 生成并经浏览器转换，共 {len(written_slides)} 页；等待审核。",
            "en_US": f"Generated via PPT Master + browser convert ({len(written_slides)} slides); pending review.",
        },
        "files": {
            "theme_css": "theme.css",
            "images_dir": "images",
            "slides_dir": "slides",
            "visual_spec": "visual-spec.md",
        },
        "slides": written_slides,
        "source": {
            "kind": "ppt-master",
            "file": "source.pptx",
            "canvas": {"width": 1920, "height": 1080},
        },
        "warnings": list(warnings),
        "status": "pending",
        "review": {
            "updated_at": now,
            "note": "浏览器 PPTX→HTML 转换完成，等待人工审批",
        },
        "storage": {
            "backend": "local",
            "path": f"agent-output/{tid}",
        },
    }
    if usage:
        meta["usage"] = usage
    if prev.get("featured"):
        meta["featured"] = True
    if prev.get("category"):
        meta["category"] = prev["category"]
    # clear deferred flag
    meta.pop("html_convert", None)
    write_meta(tid, meta)
    try:
        upsert_template_row(tid)
    except Exception:
        pass

    return ok(
        ok=True,
        id=tid,
        slideCount=len(written_slides),
        imageCount=written_images,
        status=meta["status"],
    )
