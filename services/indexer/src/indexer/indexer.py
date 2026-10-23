import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from indexer.catalog import CatalogClient
from indexer.contracts import validate
from indexer.mapping import INDEX_OF, to_document
from indexer.meili import Meili

logger = logging.getLogger(__name__)


@dataclass
class ReindexState:
    state: str = "idle"  # idle, running, done or failed
    indexed: int = 0
    removed: int = 0
    error: str | None = None


class Indexer:
    """Keeps the search indexes equal to what catalog-api says.

    Every change is applied by fetching the record's current view, never by trusting the event, so
    events can arrive twice or out of order and the index still ends up right.
    """

    def __init__(self, catalog: CatalogClient, meili: Meili, page_size: int, settings_file: Path):
        self._catalog = catalog
        self._meili = meili
        self._page_size = page_size
        self._settings_file = settings_file
        # One change at a time, and none while a reindex runs, so a reindex's older view of a record
        # can never land after a newer event's.
        self.lock = asyncio.Lock()
        self.reindexing = ReindexState()

    async def apply(self, entity: str, record_id: str, op: str) -> None:
        index = INDEX_OF[entity]
        view = None if op == "delete" else await self._catalog.view(entity, record_id)
        if view is None:
            # Deleted, or already gone by the time we looked: either way it must not be searchable.
            await self._meili.delete(index, [record_id])
            logger.info("Removed %s %s from %s", entity, record_id, index)
            return
        validate("index.view", view)
        await self._meili.upsert(index, [to_document(view)])
        logger.info("Indexed %s %s in %s", entity, record_id, index)

    async def reindex(self) -> None:
        """Rebuild both indexes from catalog-api and drop whatever it no longer has."""
        state = self.reindexing = ReindexState(state="running")
        try:
            async with self.lock:
                # Meilisearch may have lost the indexes, and writing to a missing one would create it
                # with default settings, so make sure each exists and is configured first.
                await self._meili.prepare(self._settings_file)
                seen: dict[str, set[str]] = {"documents": set(), "subjects": set()}
                for entity in ("document", "ship", "organisation"):
                    index = INDEX_OF[entity]
                    async for page in self._catalog.views(entity, self._page_size):
                        for view in page:
                            validate("index.view", view)
                        await self._meili.upsert(index, [to_document(view) for view in page])
                        seen[index].update(view["id"] for view in page)
                        state.indexed += len(page)
                for index, wanted in seen.items():
                    stale = [i async for i in self._meili.ids(index) if i not in wanted]
                    await self._meili.delete(index, stale)
                    state.removed += len(stale)
            state.state = "done"
            logger.info("Reindex done: %d indexed, %d removed", state.indexed, state.removed)
        except Exception as error:
            state.state = "failed"
            state.error = str(error) or type(error).__name__
            logger.exception("Reindex failed")
