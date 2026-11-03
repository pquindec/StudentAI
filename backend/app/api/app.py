import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import system
from app.core.config import APP_VERSION, Settings
from app.core.security import TokenAuthMiddleware

log = logging.getLogger(__name__)
API_PREFIX = "/api/v1"


def create_app(settings: Settings) -> FastAPI:
    # Sin /docs ni /openapi.json en ejecución: el esquema se exporta en desarrollo.
    app = FastAPI(
        title="AI Study Assistant API",
        version=APP_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.include_router(system.router, prefix=API_PREFIX)

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
