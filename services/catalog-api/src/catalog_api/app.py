import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine

from catalog_api.documents import router as documents_router
from catalog_api.health import router as health_router
from catalog_api.names import router as names_router
from catalog_api.organisations import router as organisations_router
from catalog_api.relations import router as relations_router
from catalog_api.relay import OutboxRelay
from catalog_api.review import router as review_router
from catalog_api.settings import Settings
from catalog_api.ships import router as ships_router
from catalog_api.storage import ObjectStorage, StorageUnavailable
from catalog_api.transcriptions import router as transcriptions_router
from catalog_api.upload_gate import UploadGate

logger = logging.getLogger(__name__)


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        relay = None
        if settings.relay_enabled:
            relay = OutboxRelay(app.state.engine, settings.rabbitmq_url, settings.relay_interval_seconds)
            relay.start()
        yield
        if relay is not None:
            relay.stop()

    app = FastAPI(
        title="catalog-api",
        openapi_url="/api/catalog/openapi.json",
        docs_url="/api/catalog/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.exception_handler(StorageUnavailable)
    async def storage_unavailable(request: Request, error: StorageUnavailable) -> JSONResponse:
        logger.error("Object storage failed on %s %s", request.method, request.url.path, exc_info=error)
        return JSONResponse(status_code=502, content={"detail": "Object storage is unavailable"})

    @app.exception_handler(Exception)
    async def hide_internals(request: Request, error: Exception) -> JSONResponse:
        logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=error)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.state.settings = settings
    app.state.storage = ObjectStorage(settings)
    app.add_middleware(
        UploadGate,
        names_by_token=settings.staff_names_by_token(),
        max_upload_bytes=settings.max_upload_bytes,
    )
    app.state.staff_names_by_token = settings.staff_names_by_token()
    app.state.service_names_by_token = settings.service_names_by_token()
    app.state.engine = create_engine(settings.database_url, pool_pre_ping=True)
    app.include_router(health_router)
    app.include_router(ships_router)
    app.include_router(organisations_router)
    app.include_router(names_router)
    app.include_router(relations_router)
    app.include_router(documents_router)
    app.include_router(transcriptions_router)
    app.include_router(review_router)
    return app
