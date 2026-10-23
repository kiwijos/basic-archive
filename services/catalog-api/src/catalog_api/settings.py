from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    # "name=token" pairs separated by commas; the name becomes the author of changes.
    staff_tokens: str = ""
    # The same shape, for services such as transcribe-worker that act on the API.
    service_tokens: str = ""
    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_region: str = "garage"
    masters_bucket: str = "masters"
    max_upload_bytes: int = 100 * 1024 * 1024
    download_url_seconds: int = 300
    rabbitmq_url: str
    relay_enabled: bool = True
    relay_interval_seconds: float = 0.5

    def names_by_token(self) -> dict[str, str]:
        names = {}
        for pairs in (self.staff_tokens, self.service_tokens):
            for item in pairs.split(","):
                if "=" in item:
                    name, token = item.split("=", 1)
                    names[token.strip()] = name.strip()
        return names
