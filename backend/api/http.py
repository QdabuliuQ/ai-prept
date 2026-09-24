"""HTTP JSON helpers for Admin routes."""

from __future__ import annotations

from typing import Optional, List, Dict, Any

from typing import Any

from fastapi.responses import JSONResponse

from admin.fsutil import SAFE_TEMPLATE_DIR


def err(status: int, **payload: Any) -> JSONResponse:
    return JSONResponse(payload, status_code=status)


def ok(**payload: Any) -> JSONResponse:
    return JSONResponse(payload)


def require_safe_id(template_id: str) -> str | JSONResponse:
    tid = (template_id or "").strip()
    if not SAFE_TEMPLATE_DIR.match(tid):
        return err(400, error="INVALID_ID")
    return tid


def http_error_from_message(msg: str) -> JSONResponse:
    status = 500
    if "仅「已通过」" in msg or "已通过" in msg:
        status = 403
    elif "不存在" in msg:
        status = 404
    elif (
        "缺少" in msg
        or "无效" in msg
        or "不符" in msg
        or "为空" in msg
        or "请先" in msg
    ):
        status = 400
    return err(status, error=msg)
