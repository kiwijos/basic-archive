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
        connection.execute(text("TRUNCATE subject, document, outbox CASCADE"))


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
