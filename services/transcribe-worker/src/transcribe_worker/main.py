import asyncio
import logging
import signal

from transcribe_worker.catalog import CatalogClient
from transcribe_worker.health import serve_health
from transcribe_worker.logs import configure_logging
from transcribe_worker.settings import Settings
from transcribe_worker.worker import Status, Worker

logger = logging.getLogger(__name__)


async def serve(settings: Settings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signal_number, stop.set)

    status = Status()
    catalog = CatalogClient(settings.catalog_api_url, settings.catalog_api_token)
    health = await serve_health(status, settings.health_port)
    try:
        await Worker(settings, catalog, status).run(stop)
    finally:
        health.close()
        await catalog.close()
    logger.info("Stopped")


def main() -> None:
    configure_logging()
    asyncio.run(serve(Settings()))


if __name__ == "__main__":
    main()
