import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from indexer.catalog import CatalogClient
from indexer.consumer import Consumer, Status
from indexer.indexer import Indexer
from indexer.meili import Meili
from indexer.settings import Settings

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)
PREPARE_RETRY_SECONDS = 2.0


async def prepare(meili: Meili, settings: Settings, status: Status, stop: asyncio.Event) -> None:
    """Apply the index settings, retrying until Meilisearch is up."""
    while not stop.is_set():
        try:
            await meili.prepare(settings.index_settings_file)
            status.prepared = True
            logger.info("Indexes are prepared")
            return
        except Exception as error:
            logger.warning("Could not prepare the indexes yet: %s", error)
            try:
                await asyncio.wait_for(stop.wait(), PREPARE_RETRY_SECONDS)
            except TimeoutError:
                pass


def create_app(settings: Settings) -> FastAPI:
    status = Status()
    stop = asyncio.Event()
    catalog = CatalogClient(settings.catalog_api_url, settings.catalog_api_token)
    meili = Meili(settings.meili_url, settings.meili_key, settings.task_timeout_seconds)
    indexer = Indexer(catalog, meili, settings.reindex_page_size)
    consumer = Consumer(settings, indexer, status)

    async def run_consumer() -> None:
        await prepare(meili, settings, status, stop)
        await consumer.run(stop)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(run_consumer())
        app.state.reindex_task = None
        yield
        stop.set()
        await task
        await catalog.close()
        await meili.close()

    app = FastAPI(title="indexer", lifespan=lifespan)

    def protected(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
        presented = credentials.credentials if credentials else ""
        if not hmac.compare_digest(presented.encode(), settings.reindex_token.encode()):
            raise HTTPException(status_code=401, detail="A valid reindex token is required")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict:
        if not status.ready:
            raise HTTPException(status_code=503, detail="not ready")
        return {"status": "ok"}

    @app.post("/reindex", status_code=202, dependencies=[Depends(protected)])
    async def start_reindex(request: Request) -> dict:
        """Rebuild the indexes from catalog-api in the background; follow it with GET /reindex."""
        if not status.prepared:
            raise HTTPException(status_code=503, detail="The indexes are not prepared yet")
        if indexer.reindexing.state == "running":
            raise HTTPException(status_code=409, detail="A reindex is already running")
        indexer.reindexing.state = "running"
        request.app.state.reindex_task = asyncio.create_task(indexer.reindex())
        return {"state": "running"}

    @app.get("/reindex", dependencies=[Depends(protected)])
    def reindex_status() -> dict:
        state = indexer.reindexing
        return {"state": state.state, "indexed": state.indexed, "removed": state.removed, "error": state.error}

    return app
