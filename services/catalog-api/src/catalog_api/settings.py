from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    # "name=token" pairs separated by commas; the name becomes the author of changes.
    staff_tokens: str = ""

    def names_by_token(self) -> dict[str, str]:
        pairs = (item.split("=", 1) for item in self.staff_tokens.split(",") if "=" in item)
        return {token.strip(): name.strip() for name, token in pairs}
