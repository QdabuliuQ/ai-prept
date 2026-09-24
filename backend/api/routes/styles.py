"""Admin visual styles routes."""

from __future__ import annotations

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Request

from api.auth import assert_admin
from api.http import err, ok

router = APIRouter(dependencies=[Depends(assert_admin)])


@router.get("/api/admin/styles")
def get_styles(variants: str | None = None):
    from admin.styles_catalog import load_catalog, select_options, visual_styles_dir

    include = variants != "0"
    catalog = load_catalog()
    return {
        "dir": str(visual_styles_dir()),
        "schema_version": catalog.get("schema_version") or "1.0",
        "generated_at": catalog.get("generated_at"),
        "count": catalog.get("count") or len(catalog.get("styles") or []),
        "styles": catalog.get("styles") or [],
        "selectOptions": select_options(include_variants=include),
    }


@router.post("/api/admin/styles/random")
async def random_style(request: Request):
    from admin.score_vl import generate_random_style_intent
    from admin.styles_catalog import pick_random

    try:
        body = await request.json()
    except Exception:
        body = {}
    mode = str(body.get("mode") or "catalog")
    exclude = body.get("exclude") if isinstance(body.get("exclude"), list) else []
    if mode == "invent":
        try:
            return generate_random_style_intent()
        except Exception as e:  # noqa: BLE001
            return err(502, error=str(e))
    picked = pick_random(exclude=[str(x) for x in exclude])
    if not picked:
        return err(404, error="NO_STYLES")
    return picked


@router.post("/api/admin/styles/ensure")
async def ensure_style(request: Request):
    import json
    import subprocess

    from admin.fsutil import repo_root
    from admin.providers import llm_env_for_dual, resolve_llm_selection

    try:
        body = await request.json()
    except Exception:
        return err(400, error="INVALID_JSON")
    intent = str(body.get("intent") or "").strip()
    if not intent:
        return err(400, error="INTENT_REQUIRED")
    create = body.get("create") is not False
    mock = bool(body.get("mock"))
    cmd = repo_root() / "backend" / ".venv" / "bin" / "webppt-backend"
    args = ["ensure-style", intent]
    if not create:
        args.append("--no-create")
    if mock:
        args.append("--mock")
    env = {**__import__("os").environ, "PYTHONUNBUFFERED": "1"}
    if not mock:
        try:
            llm = resolve_llm_selection(body.get("llmProvider"), body.get("llmModel"))
            env.update(llm_env_for_dual(llm))
        except Exception as e:  # noqa: BLE001
            return err(400, error=str(e))
    try:
        proc = subprocess.run(
            [str(cmd), *args],
            cwd=str(repo_root() / "backend"),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as e:  # noqa: BLE001
        return err(500, ok=False, error=str(e), code="SPAWN_FAILED")
    log = (proc.stdout or "") + (proc.stderr or "")
    last = ""
    for line in reversed(log.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            last = line
            break
    payload: dict = {"ok": proc.returncode == 0, "log": log}
    if last:
        try:
            payload.update(json.loads(last))
        except json.JSONDecodeError:
            pass
    if proc.returncode != 0:
        return err(400, **payload)
    return payload
