from fastapi.testclient import TestClient
from sqlalchemy import text

from catalog_api.app import create_app
from catalog_api.migrate import run_migrations
from catalog_api.settings import Settings


def test_a_running_service_is_alive_and_ready(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_a_service_that_cannot_reach_its_database_is_alive_but_not_ready():
    settings = Settings(
        database_url="postgresql+psycopg://postgres:test@localhost:1/none?connect_timeout=1"
    )
    with TestClient(create_app(settings)) as unreachable:
        assert unreachable.get("/healthz").status_code == 200
        assert unreachable.get("/readyz").status_code == 503


def test_a_service_is_not_ready_until_the_database_schema_is_migrated(database):
    with database.connect() as connection:
        connection.execute(text("DROP DATABASE IF EXISTS archive_unmigrated"))
        connection.execute(text("CREATE DATABASE archive_unmigrated"))
    try:
        settings = Settings(
            database_url="postgresql+psycopg://postgres:test@localhost:55432/archive_unmigrated"
        )
        with TestClient(create_app(settings)) as unmigrated:
            assert unmigrated.get("/healthz").status_code == 200
            assert unmigrated.get("/readyz").status_code == 503

            run_migrations(settings.database_url)

            assert unmigrated.get("/readyz").status_code == 200
    finally:
        with database.connect() as connection:
            connection.execute(text("DROP DATABASE archive_unmigrated WITH (FORCE)"))
