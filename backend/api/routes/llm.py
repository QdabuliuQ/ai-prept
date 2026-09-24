"""Admin LLM / image provider catalog."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import assert_admin

router = APIRouter(dependencies=[Depends(assert_admin)])


@router.get("/api/admin/llm")
def get_llm():
    from admin.providers import (
        list_image_providers_public,
        list_llm_providers_public,
    )

    return {
        "providers": list_llm_providers_public(),
        "imageProviders": list_image_providers_public(),
    }
