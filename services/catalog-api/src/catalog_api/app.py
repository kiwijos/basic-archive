from fastapi import FastAPI
from sqlalchemy import create_engine

from catalog_api.health import router as health_router
from catalog_api.settings import Settings
from catalog_api.ships import router as ships_router


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(
        title="catalog-api",
        openapi_url="/api/catalog/openapi.json",
        docs_url="/api/catalog/docs",
        redoc_url=None,
    )
    app.state.names_by_token = settings.names_by_token()
    app.state.engine = create_engine(settings.database_url, pool_pre_ping=True)
    app.include_router(health_router)
    app.include_router(ships_router)
    return app
