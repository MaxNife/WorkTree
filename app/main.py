"""FastAPI application factory, middleware and static SPA hosting."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from app.api import admin as admin_routes
from app.api import auth as auth_routes
from app.api import runs as run_routes
from app.api import schedules as schedule_routes
from app.api import system as system_routes
from app.api import tasks as task_routes
from app.api import workflows as workflow_routes
from app.audit.guard import AuditMutationError
from app.config import Settings, load_settings
from app.container import Container, build_container
from app.errors import AppError
from app.logging_setup import (
    bind_correlation_id,
    clear_correlation_id,
    get_logger,
    new_correlation_id,
)
from app.security.masking import get_masker

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


def create_app(
    settings: Settings | None = None,
    *,
    container: Container | None = None,
    start_background: bool = True,
) -> FastAPI:
    settings = settings or (container.settings if container else load_settings())
    active = container or build_container(settings, create_schema=True)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        active.startup(start_background=start_background)
        yield
        active.shutdown()

    app = FastAPI(
        title="WorkTree",
        version="0.1.0",
        description="On-premise workflow automation control plane and activity library.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.state.container = active
    log = get_logger(__name__)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Any:
        correlation = request.headers.get("X-Correlation-ID") or new_correlation_id()
        request.state.correlation_id = correlation[:64]
        bind_correlation_id(request.state.correlation_id)
        try:
            response = await call_next(request)
        finally:
            clear_correlation_id()
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self' ws: wss:; font-src 'self' data:; "
            "frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(AppError)
    async def app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": get_masker().mask(exc.message),
                    "details": get_masker().mask_obj(exc.details),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_failed",
                    "message": "request validation failed",
                    "details": str(exc.errors())[:4000],
                }
            },
        )

    @app.exception_handler(AuditMutationError)
    async def audit_mutation(_request: Request, exc: AuditMutationError) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "audit_immutable", "message": str(exc)}},
        )

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_request_error", error=f"{type(exc).__name__}: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "an internal error occurred; see the server log",
                }
            },
        )

    for router in (
        auth_routes.router,
        workflow_routes.router,
        run_routes.router,
        task_routes.router,
        schedule_routes.router,
        schedule_routes.hooks,
        admin_routes.router,
        system_routes.router,
    ):
        app.include_router(router)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, Any]:
        try:
            with active.database.session() as session:
                session.execute(text("SELECT 1"))
        except Exception:
            return {"status": "unhealthy", "database": "down"}
        return {
            "status": "ok",
            "database": "up",
            "workers": len(active.workers.workers),
            "version": "0.1.0",
        }

    if WEB_DIST.exists():
        from fastapi.staticfiles import StaticFiles

        assets = WEB_DIST / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> Any:
            if full_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
            candidate = (WEB_DIST / full_path).resolve()
            if WEB_DIST.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        def root() -> dict[str, str]:
            return {
                "name": "WorkTree",
                "api": "/api/docs",
                "web": "not built; run npm --prefix web run build",
            }

    return app


def get_application() -> FastAPI:
    """Uvicorn factory target: ``uvicorn app.main:get_application --factory``.

    There is deliberately no module-level ``app``: building one on import would open the
    configured database and create runtime folders as a side effect of ``import app.main``.
    """
    return create_app()
