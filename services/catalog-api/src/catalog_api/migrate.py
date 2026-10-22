import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def _config(database_url: str = "") -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def latest_revision() -> str:
    return ScriptDirectory.from_config(_config()).get_current_head()


def run_migrations(database_url: str) -> None:
    """Bring the database to the latest schema; running it again changes nothing."""
    command.upgrade(_config(database_url), "head")


if __name__ == "__main__":
    run_migrations(os.environ["DATABASE_URL"])
