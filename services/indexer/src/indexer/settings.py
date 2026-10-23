import os
from pathlib import Path

from pydantic_settings import BaseSettings

CONTRACTS_DIR = Path(os.environ.get("CONTRACTS_DIR", Path(__file__).resolve().parents[4] / "contracts"))


class Settings(BaseSettings):
    rabbitmq_url: str
    catalog_api_url: str
    catalog_api_token: str
    meili_url: str
    # The indexer's own key: it can write the two indexes and nothing else, and cannot search.
    meili_key: str
    reindex_token: str

    queue: str = "record.changed"
    http_port: int = 8080

    # An event is tried this many times, with a growing pause, before it is dead-lettered.
    max_attempts: int = 5
    retry_backoff_seconds: float = 1.0
    # How long to wait for Meilisearch to finish one write.
    task_timeout_seconds: float = 60.0
    reindex_page_size: int = 100

    @property
    def index_settings_file(self) -> Path:
        return CONTRACTS_DIR / "search-index.settings.json"
