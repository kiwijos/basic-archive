import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine

from catalog_api.health import router as health_router
from catalog_api.names import router as names_router
from catalog_api.organisations import router as organisations_router
from catalog_api.relations import router as relations_router
from catalog_api.settings import Settings
from catalog_api.ships import router as ships_router

logger = logging.getLogger(__name__)


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(
        title="catalog-api",
        openapi_url="/api/catalog/openapi.json",
        docs_url="/api/catalog/docs",
        redoc_url=None,
    )

    @app.exception_handler(Exception)
    async def hide_internals(request: Request, error: Exception) -> JSONResponse:
        logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=error)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.state.names_by_token = settings.names_by_token()
    app.state.engine = create_engine(settings.database_url, pool_pre_ping=True)
    app.include_router(health_router)
    app.include_router(ships_router)
    app.include_router(organisations_router)
    app.include_router(names_router)
    app.include_router(relations_router)
    return app
