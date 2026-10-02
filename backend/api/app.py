"""Gallery + Admin FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import load_env


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_env()
    try:
        from gallery.db import connect, sync_from_disk

        with connect() as conn:
            sync_from_disk(conn)
    except Exception:
        pass
    try:
        from admin.jobs import load_recent_from_disk

        load_recent_from_disk()
    except Exception:
        pass
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="WebPPT API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5174",
            "http://localhost:5174",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(HTTPException)
    async def _http_exc(_request: Request, exc: HTTPException):
        if isinstance(exc.detail, dict):
            return JSONResponse(exc.detail, status_code=exc.status_code)
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    from api.routes import editor, files, gallery, generate, llm, prompt, styles, templates

    app.include_router(gallery.router)
    app.include_router(editor.router)
    app.include_router(templates.router)
    app.include_router(generate.router)
    app.include_router(llm.router)
    app.include_router(styles.router)
    app.include_router(prompt.router)
    app.include_router(files.router)
    return app


app = create_app()
