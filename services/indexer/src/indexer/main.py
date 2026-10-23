import uvicorn

from indexer.app import create_app
from indexer.logs import configure_logging
from indexer.settings import Settings

if __name__ == "__main__":
    configure_logging()
    settings = Settings()
    # log_config=None keeps uvicorn's own loggers flowing into the JSON handler.
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.http_port, log_config=None)
