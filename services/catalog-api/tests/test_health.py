from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from catalog_api.app import create_app
from catalog_api.migrate import run_migrations
from catalog_api.settings import Settings


def test_a_running_service_is_alive_and_ready(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_a_service_that_cannot_reach_its_database_is_alive_but_not_ready(scratch_database_url):
    unreachable_url = scratch_database_url.replace(":55432/", ":1/") + "?connect_timeout=1"
    with TestClient(create_app(Settings(database_url=unreachable_url))) as unreachable:
        assert unreachable.get("/healthz").status_code == 200
        assert unreachable.get("/readyz").status_code == 503


def test_a_service_is_not_ready_until_the_database_schema_is_migrated(scratch_database_url):
    with TestClient(create_app(Settings(database_url=scratch_database_url))) as unmigrated:
        assert unmigrated.get("/healthz").status_code == 200
        assert unmigrated.get("/readyz").status_code == 503

        run_migrations(scratch_database_url)

        assert unmigrated.get("/readyz").status_code == 200


def test_a_service_is_not_ready_while_the_database_schema_is_out_of_date(scratch_database_url):
    run_migrations(scratch_database_url)
    with create_engine(scratch_database_url).begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '0000'"))

    with TestClient(create_app(Settings(database_url=scratch_database_url))) as outdated:
        assert outdated.get("/readyz").status_code == 503


def test_the_api_documents_itself_under_its_own_prefix(client):
    schema = client.get("/api/catalog/openapi.json")

    assert schema.status_code == 200
    assert "/api/catalog/ships" in schema.json()["paths"]
    assert client.get("/api/catalog/docs").status_code == 200
