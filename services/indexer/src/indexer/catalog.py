from collections.abc import AsyncIterator

import httpx


class CatalogClient:
    """Reads indexing views from catalog-api with the indexer's service token."""

    def __init__(self, base_url: str, token: str):
        self._http = httpx.AsyncClient(
            base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=30
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def view(self, entity: str, record_id: str) -> dict | None:
        """The view of one record, or None when catalog-api no longer has it."""
        response = await self._http.get(f"/api/catalog/index/{entity}/{record_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def views(self, entity: str, page_size: int) -> AsyncIterator[list[dict]]:
        """Every live record of one kind, a page at a time."""
        after = None
        while True:
            params = {"limit": page_size, **({"after": after} if after else {})}
            response = await self._http.get(f"/api/catalog/index/{entity}", params=params)
            response.raise_for_status()
            page = response.json()
            if page["items"]:
                yield page["items"]
            after = page["next_after"]
            if after is None:
                return
