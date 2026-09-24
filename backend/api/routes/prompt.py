"""Admin random prompt helper."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from api.auth import assert_admin
from api.http import err

router = APIRouter(dependencies=[Depends(assert_admin)])


@router.post("/api/admin/prompt-random")
async def prompt_random(request: Request):
    from admin.score_vl import generate_random_theme_prompt

    visual_style = ""
    try:
        body = await request.json()
        visual_style = str(body.get("visualStyle") or "")
    except Exception:
        pass
    try:
        return generate_random_theme_prompt(visual_style=visual_style)
    except Exception as e:  # noqa: BLE001
        return err(502, error=str(e))
