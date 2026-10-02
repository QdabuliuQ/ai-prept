"""Admin generate jobs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from api.auth import assert_admin
from api.http import err, ok

router = APIRouter(dependencies=[Depends(assert_admin)])


@router.get("/api/admin/generate")
def list_generate():
    from admin.jobs import list_jobs

    return {"jobs": list_jobs(50)}


@router.post("/api/admin/generate")
async def post_generate(request: Request):
    from admin.jobs import clear_terminal_jobs, delete_jobs, start_generate_job

    try:
        body = await request.json()
    except Exception:
        body = {}
    action = str(body.get("action") or "")
    if action == "delete":
        ids = [str(i).strip() for i in (body.get("ids") or []) if str(i).strip()]
        if not ids:
            return err(400, error="IDS_REQUIRED")
        if len(ids) > 200:
            return err(400, error="TOO_MANY_IDS")
        result = delete_jobs(ids)
        return {"ok": len(result["failed"]) == 0, **result}
    if action == "clear-terminal":
        result = clear_terminal_jobs()
        return {"ok": len(result["failed"]) == 0, **result}
    if action:
        return err(400, error="UNKNOWN_ACTION", allowed=["delete", "clear-terminal"])

    try:
        job = start_generate_job(body if isinstance(body, dict) else {})
        return JSONResponse({"job": job}, status_code=202)
    except Exception as e:  # noqa: BLE001
        return err(400, error=str(e))


@router.get("/api/admin/generate/{job_id}")
def get_job(job_id: str):
    from admin.jobs import refresh_job_from_disk

    job = refresh_job_from_disk(job_id)
    if not job:
        return err(404, error="NOT_FOUND")
    return {"job": job}


@router.post("/api/admin/generate/{job_id}")
async def post_job(job_id: str, request: Request):
    from admin.jobs import cancel_job, delete_job

    try:
        body = await request.json()
    except Exception:
        return err(400, error="INVALID_JSON")
    action = str(body.get("action") or "")
    if action == "cancel":
        try:
            job = cancel_job(job_id)
            return {"job": job}
        except FileNotFoundError:
            return err(404, error="NOT_FOUND")
        except Exception as e:  # noqa: BLE001
            return err(400, error=str(e))
    if action == "delete":
        try:
            delete_job(job_id)
            return ok(ok=True, id=job_id)
        except FileNotFoundError:
            return err(404, error="NOT_FOUND")
        except RuntimeError as e:
            if str(e) == "JOB_ACTIVE":
                return err(400, error="JOB_ACTIVE", message="任务仍在运行，请先取消")
            return err(400, error=str(e))
        except Exception as e:  # noqa: BLE001
            return err(400, error=str(e))
    return err(400, error="UNKNOWN_ACTION")


@router.post("/api/admin/generate/{job_id}/mark-converted")
async def mark_converted(job_id: str, request: Request):
    from admin.jobs import mark_job_converted

    try:
        body = await request.json()
    except Exception:
        body = {}
    template_id = ""
    if isinstance(body, dict):
        template_id = str(body.get("templateId") or body.get("template_id") or "").strip()

    try:
        job = mark_job_converted(job_id, template_id or None)
        return {"job": job}
    except FileNotFoundError:
        return err(404, error="NOT_FOUND")
    except RuntimeError as e:
        return err(400, error=str(e))
    except Exception as e:  # noqa: BLE001
        return err(400, error=str(e))
