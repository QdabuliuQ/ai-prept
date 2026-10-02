"""Public editor routes — rewrite / generate / delete page without Admin token."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from admin.fsutil import SAFE_TEMPLATE_DIR
from api.http import err

router = APIRouter()


def _safe(tid: str) -> str | JSONResponse:
    if not SAFE_TEMPLATE_DIR.match(tid):
        return err(400, error="INVALID_ID")
    return tid


def _require_pack(tid: str):
    from admin.fsutil import template_dir

    root = template_dir(tid)
    if not (root / "template.json").is_file():
        return None, err(404, error="TEMPLATE_NOT_FOUND")
    return root, None


@router.post("/api/editor/templates/{template_id}/rewrite-page")
@router.post("/api/editor/workspaces/{template_id}/rewrite-page")
async def editor_rewrite_page(template_id: str, request: Request):
    from admin.jobs import start_rewrite_page_job

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    _, missing = _require_pack(tid)
    if missing:
        return missing
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
                "editor": True,
            }
        )
        return JSONResponse(
            {"job": job, "templateId": tid, "workspaceId": tid, "mode": "rewrite-page"},
            status_code=202,
        )
    except Exception as e:  # noqa: BLE001
        return err(400, error=str(e))


@router.post("/api/editor/templates/{template_id}/generate-page")
@router.post("/api/editor/workspaces/{template_id}/generate-page")
async def editor_generate_page(template_id: str, request: Request):
    from admin.jobs import start_generate_page_job

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    _, missing = _require_pack(tid)
    if missing:
        return missing
    try:
        body = await request.json()
    except Exception:
        return err(400, error="INVALID_JSON")
    issue = str(body.get("issue") or body.get("prompt") or "").strip()
    if len(issue) < 4:
        return err(400, error="ISSUE_REQUIRED", message="请填写新页要求（至少 4 字）")
    if len(issue) > 2000:
        return err(400, error="ISSUE_TOO_LONG")
    try:
        job = start_generate_page_job(
            {
                "sourceTemplateId": tid,
                "issue": issue,
                "afterFile": body.get("afterFile") or body.get("file"),
                "afterPageIndex": body.get("afterPageIndex", body.get("pageIndex")),
                "titleHint": body.get("titleHint") or body.get("title"),
                "mock": bool(body.get("mock")),
                "llmProvider": body.get("llmProvider"),
                "llmModel": body.get("llmModel"),
                "editor": True,
            }
        )
        return JSONResponse(
            {
                "job": job,
                "templateId": tid,
                "workspaceId": tid,
                "mode": "generate-page",
            },
            status_code=202,
        )
    except Exception as e:  # noqa: BLE001
        return err(400, error=str(e))


@router.post("/api/editor/templates/{template_id}/delete-page")
@router.post("/api/editor/workspaces/{template_id}/delete-page")
async def editor_delete_page(template_id: str, request: Request):
    from admin.jobs import start_delete_page_job

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    _, missing = _require_pack(tid)
    if missing:
        return missing
    try:
        body = await request.json()
    except Exception:
        return err(400, error="INVALID_JSON")
    try:
        job = start_delete_page_job(
            {
                "sourceTemplateId": tid,
                "file": body.get("file") or body.get("slideFile"),
                "pageIndex": body.get("pageIndex"),
                "editor": True,
            }
        )
        return JSONResponse(
            {"job": job, "templateId": tid, "workspaceId": tid, "mode": "delete-page"},
            status_code=202,
        )
    except Exception as e:  # noqa: BLE001
        return err(400, error=str(e))


@router.post("/api/editor/templates/{template_id}/assist")
@router.post("/api/editor/workspaces/{template_id}/assist")
async def editor_assist(template_id: str, request: Request):
    """Single chat entry: plan actions then run editor-assist job (P0/P1)."""
    from admin.jobs import start_editor_assist_job

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    _, missing = _require_pack(tid)
    if missing:
        return missing
    try:
        body = await request.json()
    except Exception:
        return err(400, error="INVALID_JSON")

    issue = str(body.get("issue") or body.get("prompt") or body.get("message") or "").strip()
    if len(issue) < 4:
        return err(400, error="ISSUE_REQUIRED", message="请填写指令（至少 4 字）")
    if len(issue) > 2000:
        return err(400, error="ISSUE_TOO_LONG")

    file_name = body.get("file") or body.get("slideFile")
    page_index = body.get("pageIndex")

    try:
        job = start_editor_assist_job(
            {
                "sourceTemplateId": tid,
                "issue": issue,
                "file": file_name,
                "pageIndex": page_index,
                "mock": bool(body.get("mock")),
                "llmProvider": body.get("llmProvider"),
                "llmModel": body.get("llmModel"),
                "imageProvider": body.get("imageProvider"),
                "imageModel": body.get("imageModel"),
                "element": body.get("element") or body.get("targetElement"),
                "editor": True,
            }
        )
        return JSONResponse(
            {
                "job": job,
                "templateId": tid,
                "workspaceId": tid,
                "mode": "editor-assist",
                "intent": "assist",
                "reason": "plan+execute",
            },
            status_code=202,
        )
    except Exception as e:  # noqa: BLE001
        return err(400, error=str(e))


@router.get("/api/editor/templates/{template_id}")
@router.get("/api/editor/workspaces/{template_id}")
def editor_get_template(template_id: str):
    """Load editor-shaped doc without approved gate (workspace / catalog / legacy)."""
    from admin.store import load_editor_doc

    tid = _safe(template_id)
    if isinstance(tid, JSONResponse):
        return tid
    doc = load_editor_doc(tid)
    if not doc:
        return err(404, error="NOT_FOUND")
    return {
        "name": doc["name"],
        "templateDir": tid,
        "templateId": tid,
        "workspaceId": tid,
        "label": doc.get("label"),
        "description": doc.get("description"),
        "tree": doc.get("tree") or [],
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


@router.get("/api/editor/jobs/{job_id}")
def get_editor_job(job_id: str):
    from admin.jobs import refresh_job_from_disk

    jid = str(job_id or "").strip()
    if not jid or len(jid) > 64:
        return err(400, error="INVALID_ID")
    job = refresh_job_from_disk(jid)
    if not job or not job.get("editor"):
        return err(404, error="NOT_FOUND")

    result_file = None
    result_title = None
    insert_at = None
    activate_file = None
    deleted_files: list[str] = []
    changed_files: list[str] = []
    regenerated_images: list[str] = []
    summary = None
    summary_markdown = None
    intent = None
    try:
        from admin.fsutil import jobs_dir
        import json

        report_path = jobs_dir() / f"{jid}-report.json"
        if report_path.is_file():
            rows = json.loads(report_path.read_text(encoding="utf-8"))
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                row = rows[0]
                result_file = row.get("file")
                result_title = row.get("title")
                insert_at = row.get("insertAt")
                activate_file = row.get("activateFile")
                summary = row.get("summary")
                summary_markdown = row.get("summaryMarkdown")
                intent = row.get("intent")
                if isinstance(row.get("deletedFiles"), list):
                    deleted_files = [str(x) for x in row["deletedFiles"] if x]
                if isinstance(row.get("changedFiles"), list):
                    changed_files = [str(x) for x in row["changedFiles"] if x]
                elif result_file and job.get("pipeline") in {
                    "rewrite-page",
                    "generate-page",
                    "editor-assist",
                }:
                    changed_files = [str(result_file)]
                if isinstance(row.get("regeneratedImages"), list):
                    regenerated_images = [
                        str(x) for x in row["regeneratedImages"] if x
                    ]
    except Exception:
        pass

    return {
        "job": {
            "id": job.get("id"),
            "status": job.get("status"),
            "pipeline": job.get("pipeline"),
            "sourceTemplateId": job.get("sourceTemplateId"),
            "templateId": job.get("templateId") or job.get("sourceTemplateId"),
            "workspaceId": job.get("templateId") or job.get("sourceTemplateId"),
            "slideFile": job.get("slideFile"),
            "pageIndex": job.get("pageIndex"),
            "progress": job.get("progress"),
            "error": job.get("error"),
            "resultFile": result_file,
            "resultTitle": result_title,
            "insertAt": insert_at,
            "activateFile": activate_file,
            "deletedFiles": deleted_files,
            "changedFiles": changed_files,
            "regeneratedImages": regenerated_images,
            "summary": summary,
            "summaryMarkdown": summary_markdown,
            "intent": intent,
        }
    }
