"""Admin / gallery FastAPI auth — mirrors Next assertAdmin."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException, Request

from config import load_env


def admin_token() -> str:
    load_env()
    return os.environ.get("ADMIN_TOKEN", "").strip()


def extract_token(
    request: Request,
    x_admin_token: str = "",
    authorization: str = "",
) -> str:
    header = (x_admin_token or "").strip()
    if header:
        return header
    auth = (authorization or request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    cookie = request.cookies.get("webppt_admin_token") or ""
    return cookie.strip()


def assert_admin(
    request: Request,
    x_admin_token: Optional[str] = Header(default=""),
    authorization: Optional[str] = Header(default=""),
) -> None:
    expected = admin_token()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="未配置 ADMIN_TOKEN。请在 .env.local 设置 ADMIN_TOKEN 后重启服务。",
        )
    provided = extract_token(request, x_admin_token or "", authorization or "")
    if provided != expected:
        raise HTTPException(status_code=401, detail="未授权")
