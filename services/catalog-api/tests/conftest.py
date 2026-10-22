import socket

import boto3
import httpx
import pytest
from fastapi.testclient import TestClient
from moto.server import ThreadedMotoServer
from sqlalchemy import create_engine, text

from catalog_api.app import create_app
from catalog_api.migrate import run_migrations
from catalog_api.settings import Settings

TEST_DATABASE_URL = "postgresql+psycopg://postgres:test@localhost:55432/archive_test"
STAFF_TOKENS = "alice=alice-token,bob=bob-token"
MASTERS_BUCKET = "masters"
S3_CREDENTIALS = {"aws_access_key_id": "test", "aws_secret_access_key": "test"}


@pytest.fixture(scope="session", autouse=True)
def database():
    engine = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    run_migrations(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def empty_database(database):
    with database.connect() as connection:
        tables = connection.execute(
            text(
                "SELECT string_agg(quote_ident(tablename), ', ') FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).scalar()
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def scratch_database_url(database):
    """An empty database of its own, for tests about the state of the schema."""
    with database.connect() as connection:
        connection.execute(text("DROP DATABASE IF EXISTS archive_scratch WITH (FORCE)"))
        connection.execute(text("CREATE DATABASE archive_scratch"))
    yield TEST_DATABASE_URL.rsplit("/", 1)[0] + "/archive_scratch"
    with database.connect() as connection:
        connection.execute(text("DROP DATABASE archive_scratch WITH (FORCE)"))


@pytest.fixture(scope="session")
def s3_url():
    """A fake S3 server over real HTTP, standing in for Garage at its S3 boundary."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    yield f"http://127.0.0.1:{port}"
    server.stop()


@pytest.fixture
def s3(s3_url):
    """A client for looking at what was stored, over an empty fake S3 with the masters bucket."""
    httpx.post(f"{s3_url}/moto-api/reset").raise_for_status()
    s3_client = boto3.client("s3", endpoint_url=s3_url, region_name="us-east-1", **S3_CREDENTIALS)
    s3_client.create_bucket(Bucket=MASTERS_BUCKET)
    return s3_client


@pytest.fixture
def make_settings(s3_url):
    def make(**overrides) -> Settings:
        values = {
            "database_url": TEST_DATABASE_URL,
            "staff_tokens": STAFF_TOKENS,
            "s3_endpoint_url": s3_url,
            "s3_access_key_id": S3_CREDENTIALS["aws_access_key_id"],
            "s3_secret_access_key": S3_CREDENTIALS["aws_secret_access_key"],
            "s3_region": "us-east-1",
            "masters_bucket": MASTERS_BUCKET,
        }
        return Settings(**{**values, **overrides})

    return make


@pytest.fixture
def new_client(make_settings, s3):
    """Start a new app instance each call, as a restarted pod would."""
    clients = []

    def start(**settings_overrides) -> TestClient:
        test_client = TestClient(create_app(make_settings(**settings_overrides)))
        test_client.__enter__()
        clients.append(test_client)
        return test_client

    yield start
    for test_client in clients:
        test_client.__exit__(None, None, None)


@pytest.fixture
def client(new_client):
    return new_client()


@pytest.fixture
def staff():
    return {"Authorization": "Bearer alice-token"}


@pytest.fixture
def outbox(database):
    """The change events waiting to be published, oldest first, as (entity, id, op)."""

    def read() -> list[tuple[str, str, str]]:
        with database.connect() as connection:
            rows = connection.execute(
                text("SELECT event_type, payload FROM outbox ORDER BY id")
            ).all()
        assert {row.event_type for row in rows} <= {"record.changed"}
        return [(row.payload["entity"], row.payload["id"], row.payload["op"]) for row in rows]

    return read
