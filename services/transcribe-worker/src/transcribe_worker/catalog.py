import httpx

from transcribe_worker.ocr import Reading


class CatalogClient:
    """The worker's view of catalog-api: look up an Image, fetch its bytes, report what happened."""

    def __init__(self, base_url: str, token: str):
        self._api = httpx.AsyncClient(
            base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=30
        )
        # The download address is signed on its own; the API token must not travel to the object store.
        self._download = httpx.AsyncClient(timeout=120)

    async def review_status(self, image_id: str) -> str | None:
        """The Image's Review status, or None when catalog-api does not know the Image."""
        response = await self._api.get(f"/api/catalog/images/{image_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()["review_status"]

    async def fetch(self, image_id: str) -> bytes:
        address = await self._api.get(f"/api/catalog/images/{image_id}/download-url")
        address.raise_for_status()
        content = await self._download.get(address.json()["url"])
        content.raise_for_status()
        return content.content

    async def post_result(self, image_id: str, reading: Reading) -> bool:
        """Record the reading. False means it was not needed: catalog-api already had a result for
        this job (a duplicate), or the Image has been deleted since the job was queued."""
        response = await self._api.post(
            f"/api/catalog/images/{image_id}/transcriptions",
            json={
                "source": "machine",
                "text": reading.text,
                "engine": reading.engine,
                "engine_version": reading.engine_version,
                "language": reading.language,
                "confidence": reading.confidence,
            },
        )
        if response.status_code in (404, 409):
            return False
        response.raise_for_status()
        return True

    async def report_failure(self, image_id: str, reason: str) -> None:
        response = await self._api.post(
            f"/api/catalog/images/{image_id}/ocr-failure", json={"reason": reason[:500]}
        )
        if response.status_code not in (404, 409):  # gone, or no longer waiting: nothing to mark
            response.raise_for_status()

    async def close(self) -> None:
        await self._api.aclose()
        await self._download.aclose()
