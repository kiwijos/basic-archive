import uvicorn

from search_api.app import create_app
from search_api.logs import configure_logging
from search_api.settings import Settings

if __name__ == "__main__":
    configure_logging()
    settings = Settings()
    # log_config=None keeps uvicorn's own loggers flowing into the JSON handler.
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.http_port, log_config=None)
