import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from catalog_api.app import create_app
from catalog_api.migrate import run_migrations
from catalog_api.settings import Settings

TEST_DATABASE_URL = "postgresql+psycopg://postgres:test@localhost:55432/archive_test"
STAFF_TOKENS = "alice=alice-token,bob=bob-token"


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


@pytest.fixture
def new_client():
    """Start a new app instance each call, as a restarted pod would."""
    clients = []

    def start() -> TestClient:
        settings = Settings(database_url=TEST_DATABASE_URL, staff_tokens=STAFF_TOKENS)
        test_client = TestClient(create_app(settings))
        test_client.__enter__()
        clients.append(test_client)
        return test_client

    yield start
    for test_client in clients:
        test_client.__exit__(None, None, None)


@pytest.fixture
def client(new_client):
    return new_client()
