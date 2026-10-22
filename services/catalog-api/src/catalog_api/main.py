import uvicorn

from catalog_api.app import create_app
from catalog_api.logs import configure_logging
from catalog_api.settings import Settings

if __name__ == "__main__":
    configure_logging()
    # log_config=None keeps uvicorn's own loggers flowing into the JSON handler.
    uvicorn.run(create_app(Settings()), host="0.0.0.0", port=8000, log_config=None)
