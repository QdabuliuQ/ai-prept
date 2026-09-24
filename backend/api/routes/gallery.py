"""Public gallery routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from api.auth import assert_admin
from api.http import err, ok

router = APIRouter()


@router.get("/api/gallery")
def get_gallery():
    from gallery.db import connect, list_public

    try:
        with connect() as conn:
            templates = list_public(conn)
        return {"templates": templates}
    except Exception as e:  # noqa: BLE001
        return err(503, error=str(e))


@router.get("/api/gallery/categories")
def get_categories():
    """模板业务类型目录（首页 chips / Admin 下拉同源）。"""
    from templates.categories import catalog

    return {"categories": catalog()}


@router.post("/api/gallery/inspire")
async def post_inspire(request: Request):
    """首页「发现灵感」：LLM 生成一段 PPT 创作要求（与所选模板无关）。"""
    from admin.score_vl import generate_inspire_brief

    try:
        return generate_inspire_brief()
    except Exception as e:  # noqa: BLE001
        return err(502, error=str(e))


@router.post("/api/gallery/remix")
async def post_gallery_remix(request: Request):
    """首页「开始生成」：基于公开模板 + 用户要求套用 remix。"""
    from admin.fsutil import template_dir
    from admin.jobs import start_remix_job
    from gallery.db import connect, list_public

    try:
        body = await request.json()
    except Exception:
        return err(400, error="INVALID_JSON")
    tid = str(body.get("templateId") or body.get("id") or "").strip()
    prompt = str(body.get("prompt") or "").strip()
    if not tid:
        return err(400, error="TEMPLATE_REQUIRED", message="请先选择模板")
    if not prompt:
        return err(400, error="PROMPT_REQUIRED", message="请填写内容要求")
    if len(prompt) > 6000:
        return err(400, error="PROMPT_TOO_LONG")

    # 仅允许墙上已公开的模板作为源
    try:
        with connect() as conn:
            public_ids = {str(t.get("id") or "") for t in list_public(conn)}
    except Exception as e:  # noqa: BLE001
        return err(503, error=str(e))
    if tid not in public_ids:
        return err(404, error="TEMPLATE_NOT_PUBLIC", message="只能基于公开模板生成")

    root = template_dir(tid)
    if not (root / "template.json").is_file():
        return err(404, error="TEMPLATE_NOT_FOUND")
    spec = root / "visual-spec.md"
    if not spec.is_file() or not spec.read_text(encoding="utf-8").strip():
        return err(
            400,
            error="VISUAL_SPEC_REQUIRED",
            message="该模板缺少设计规范，暂时无法套用",
        )

    try:
        job = start_remix_job(
            {
                "sourceTemplateId": tid,
                "prompt": prompt,
                # 首页默认保留原图，更快更稳
                "skipImage": body.get("skipImage") is not False,
                "mock": bool(body.get("mock")),
                "status": "approved",
                "gallery": True,
            }
        )
        return JSONResponse(
            {
                "job": {
                    "id": job.get("id"),
                    "status": job.get("status"),
                    "sourceTemplateId": tid,
                },
                "mode": "remix",
            },
            status_code=202,
        )
    except Exception as e:  # noqa: BLE001
        return err(400, error=str(e))


@router.get("/api/gallery/jobs/{job_id}")
def get_gallery_job(job_id: str):
    """首页轮询套用进度（精简字段，不含 Admin 日志）。"""
    from admin.jobs import refresh_job_from_disk

    jid = str(job_id or "").strip()
    if not jid or len(jid) > 64:
        return err(400, error="INVALID_ID")
    job = refresh_job_from_disk(jid)
    if not job:
        return err(404, error="NOT_FOUND")
    if not job.get("gallery"):
        return err(404, error="NOT_FOUND")
    tid = None
    ids = job.get("templateIds")
    if isinstance(ids, list) and ids:
        tid = str(ids[0] or "") or None
    if not tid:
        tid = str(job.get("templateId") or "") or None
    return {
        "job": {
            "id": job.get("id"),
            "status": job.get("status"),
            "sourceTemplateId": job.get("sourceTemplateId"),
            "templateId": tid,
            "progress": job.get("progress"),
            "error": job.get("error"),
        }
    }


@router.post("/api/gallery/sync")
def post_sync(_request: Request, _auth: None = Depends(assert_admin)):
    from gallery.db import connect, sync_from_disk

    try:
        with connect() as conn:
            result = sync_from_disk(conn)
        return ok(ok=True, **result)
    except Exception as e:  # noqa: BLE001
        return err(500, error=str(e))
