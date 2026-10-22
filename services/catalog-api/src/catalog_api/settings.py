from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    # "name=token" pairs separated by commas; the name becomes the author of changes.
    staff_tokens: str = ""
    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_region: str = "garage"
    masters_bucket: str = "masters"
    max_upload_bytes: int = 100 * 1024 * 1024
    download_url_seconds: int = 300

    def names_by_token(self) -> dict[str, str]:
        pairs = (item.split("=", 1) for item in self.staff_tokens.split(",") if "=" in item)
        return {token.strip(): name.strip() for name, token in pairs}
