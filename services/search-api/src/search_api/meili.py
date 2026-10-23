import httpx


class SearchUnavailable(Exception):
    """Meilisearch cannot answer right now."""


class Meili:
    def __init__(self, url: str, key: str):
        self._http = httpx.AsyncClient(base_url=url, headers={"Authorization": f"Bearer {key}"}, timeout=10)

    async def close(self) -> None:
        await self._http.aclose()

    async def search(self, index: str, body: dict) -> dict:
        try:
            response = await self._http.post(f"/indexes/{index}/search", json=body)
        except httpx.HTTPError as error:
            raise SearchUnavailable(str(error)) from error
        if response.status_code >= 400:
            raise SearchUnavailable(f"{response.status_code} {response.text}")
        return response.json()

    async def healthy(self) -> bool:
        try:
            return (await self._http.get("/health")).status_code == 200
        except httpx.HTTPError:
            return False
