import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class MeiliError(Exception):
    """Meilisearch refused or failed a request."""


class Meili:
    """The few Meilisearch calls the indexer needs. Every write waits for its task to finish, so
    when a call returns the change is searchable, and a failure is raised instead of lost."""

    def __init__(self, url: str, key: str, task_timeout: float):
        self._http = httpx.AsyncClient(base_url=url, headers={"Authorization": f"Bearer {key}"}, timeout=30)
        self._task_timeout = task_timeout

    async def close(self) -> None:
        await self._http.aclose()

    async def _task(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise MeiliError(f"{response.request.method} {response.request.url.path}: {response.status_code} {response.text}")
        uid = response.json()["taskUid"]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._task_timeout
        while True:
            task = (await self._http.get(f"/tasks/{uid}")).json()
            if task["status"] == "succeeded":
                return
            if task["status"] in ("failed", "canceled"):
                raise MeiliError(f"task {uid} {task['status']}: {task.get('error', {}).get('message')}")
            if loop.time() > deadline:
                raise MeiliError(f"task {uid} did not finish in {self._task_timeout} seconds")
            await asyncio.sleep(0.02)

    async def prepare(self, settings_file: Path) -> None:
        """Create each index if it is missing and apply its settings. Safe to repeat."""
        for uid, settings in json.loads(settings_file.read_text()).items():
            if (await self._http.get(f"/indexes/{uid}")).status_code == 404:
                await self._task(await self._http.post("/indexes", json={"uid": uid, "primaryKey": "id"}))
            await self._task(await self._http.patch(f"/indexes/{uid}/settings", json=settings))

    async def upsert(self, index: str, documents: list[dict]) -> None:
        """Add or replace by id, so doing it twice leaves the index as it was after the first."""
        if documents:
            await self._task(await self._http.post(f"/indexes/{index}/documents", json=documents))

    async def delete(self, index: str, ids: list[str]) -> None:
        if ids:
            await self._task(await self._http.post(f"/indexes/{index}/documents/delete-batch", json=ids))

    async def ids(self, index: str) -> AsyncIterator[str]:
        offset = 0
        while True:
            response = await self._http.get(
                f"/indexes/{index}/documents", params={"fields": "id", "limit": 1000, "offset": offset}
            )
            if response.status_code >= 400:
                raise MeiliError(f"listing {index}: {response.status_code} {response.text}")
            results = response.json()["results"]
            for document in results:
                yield document["id"]
            if len(results) < 1000:
                return
            offset += 1000
