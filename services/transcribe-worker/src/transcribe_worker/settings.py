from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    rabbitmq_url: str
    catalog_api_url: str
    catalog_api_token: str

    queue: str = "ocr.requested"
    exchange: str = "archive.events"

    # A job is tried this many times before it is dead-lettered and its Image marked failed.
    max_attempts: int = 3
    retry_backoff_seconds: float = 2.0

    ocr_languages: str = "swe+eng"
    ocr_timeout_seconds: int = 300
    # Large scans are shrunk to this many pixels on the long side, and refused above the pixel limit,
    # so one huge file cannot exhaust the pod's memory.
    max_image_side: int = 3500
    max_image_pixels: int = 60_000_000

    health_port: int = 8080
