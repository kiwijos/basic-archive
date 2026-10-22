from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from catalog_api.migrate import latest_revision

router = APIRouter()


@router.get("/healthz")
def liveness() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readiness(request: Request) -> dict:
    # Not ready until the migration Job has brought the schema to the latest revision.
    try:
        with request.app.state.engine.connect() as connection:
            applied = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database is not reachable or not migrated")
    if applied != latest_revision():
        raise HTTPException(status_code=503, detail="Database schema is out of date")
    return {"status": "ready"}
