import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import ai, chat, exams, internal, jobs, sources, stt, subjects, system
from app.core.config import APP_VERSION, Settings
from app.core.errors import AppError, from_integrity_error
from app.core.security import TokenAuthMiddleware
from app.jobs.scheduler import Scheduler

log = logging.getLogger(__name__)
API_PREFIX = "/api/v1"


def create_app(settings: Settings, run_jobs: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        scheduler = Scheduler(settings.db_path, settings.data_dir)
        app.state.scheduler = scheduler
        if run_jobs:
            scheduler.start()
        yield
        await scheduler.stop()

    # Sin /docs ni /openapi.json en ejecución: el esquema se exporta en desarrollo.
    app = FastAPI(
        title="AI Study Assistant API",
        version=APP_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    for module in (system, subjects, sources, jobs, stt, ai, chat, exams, internal):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body())

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity(_: Request, exc: sqlite3.IntegrityError) -> JSONResponse:
        err = from_integrity_error(exc)
        return JSONResponse(status_code=err.status, content=err.body())

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e.get("loc", [])[1:]) for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_data",
                    "message": "Revisa los datos introducidos",
                    "details": {"fields": fields},
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Nunca devolver trazas ni detalles internos al cliente.
        log.exception("Error no controlado", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Error interno"}},
        )

    app.add_middleware(TokenAuthMiddleware, token=settings.token)
    return app
