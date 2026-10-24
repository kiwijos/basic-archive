import os
from pathlib import Path

import pytest

TESSDATA = Path.home() / ".cache" / "tessdata"

# As in the catalog-api image: where the message contracts are, since catalog-api is installed from elsewhere.
os.environ.setdefault("CONTRACTS_DIR", str(Path(__file__).resolve().parents[2] / "contracts"))

# A machine whose package manager already installed the language data needs nothing here; otherwise
# point Tesseract at the directory that holds it (as the worker tests do).
if "TESSDATA_PREFIX" not in os.environ and TESSDATA.exists():
    os.environ["TESSDATA_PREFIX"] = str(TESSDATA)


@pytest.fixture(scope="session")
def tesseract():
    import pytesseract

    try:
        pytesseract.get_tesseract_version()
        languages = pytesseract.get_languages()
    except Exception as error:  # noqa: BLE001
        pytest.fail(f"Tesseract is needed to measure the scans: {error}")
    assert {"swe", "eng"} <= set(languages), f"Tesseract needs Swedish and English data, has {languages}"
    return pytesseract


# ---- the real catalog-api, in process, with real Postgres and a fake S3 -------------------------------------------

import hashlib  # noqa: E402
import http.server  # noqa: E402
import io  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from moto.server import ThreadedMotoServer  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from catalog_api.app import create_app  # noqa: E402
from catalog_api.migrate import run_migrations  # noqa: E402
from catalog_api.settings import Settings  # noqa: E402

from archive_seed.fleet import Period  # noqa: E402
from archive_seed.plates import PLATES, Plate, PlateDocument  # noqa: E402

TEST_DATABASE_URL = "postgresql+psycopg://postgres:test@localhost:55432/archive_test"
RABBITMQ_URL = "amqp://guest:guest@localhost:56672/%2F"
STAFF = {"Authorization": "Bearer seed-staff-token"}
WORKER = {"Authorization": "Bearer worker-token"}


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
            text("SELECT string_agg(quote_ident(tablename), ', ') FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
        ).scalar()
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture(scope="session")
def s3_url():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    yield f"http://127.0.0.1:{port}"
    server.stop()


@pytest.fixture
def s3(s3_url):
    import boto3

    httpx.post(f"{s3_url}/moto-api/reset").raise_for_status()
    client = boto3.client("s3", endpoint_url=s3_url, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
    client.create_bucket(Bucket="masters")
    return client


@pytest.fixture
def archive(s3_url, s3):
    """catalog-api as the seed sees it over HTTP: a client that already carries a staff token."""
    settings = Settings(
        database_url=TEST_DATABASE_URL,
        staff_tokens="seeder=seed-staff-token",
        service_tokens="transcribe-worker=worker-token",
        rabbitmq_url=RABBITMQ_URL,
        relay_enabled=False,
        s3_endpoint_url=s3_url,
        s3_access_key_id="test",
        s3_secret_access_key="test",
        s3_region="us-east-1",
        masters_bucket="masters",
    )
    with TestClient(create_app(settings), headers=STAFF, base_url="http://testserver") as client:
        yield client


class FakeWorker:
    """Reads pages the way transcribe-worker does, over the API: it finds pending Images and posts a Machine
    transcription for each. What it "reads" is the text the page really has, run through `distort`, so a test
    knows exactly how wrong each reading is."""

    def __init__(self, archive: TestClient, distort=None):
        from archive_seed.documents import DOCUMENTS

        self.archive = archive
        self.distort = distort or (lambda text, doc, page: text)
        self.fail = lambda doc, page: False
        self.texts = {d.key: d.pages for d in DOCUMENTS}
        self.reads: list[tuple[str, int]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "FakeWorker":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._pass()
            except Exception:  # noqa: BLE001 - the next pass tries again
                pass
            time.sleep(0.05)

    def _pass(self) -> None:
        for system in ("seed", "wikimedia-commons"):
            for document in self.archive.get("/api/catalog/documents", params={"source_system": system}).json():
                for image in document["images"]:
                    if image["review_status"] != "pending":
                        continue
                    key, page = document["source_id"], image["page_no"]
                    if self.fail(key, page):
                        self.archive.post(f"/api/catalog/images/{image['id']}/ocr-failure", json={"reason": "unreadable"}, headers=WORKER)
                        continue
                    pages = self.texts.get(key)
                    reading = self.distort(pages[page - 1], key, page) if pages else "ink and noise"
                    body = {"source": "machine", "text": reading, "engine": "tesseract", "engine_version": "test", "language": "swe+eng", "confidence": 0.9}
                    self.archive.post(f"/api/catalog/images/{image['id']}/transcriptions", json=body, headers=WORKER)
                    self.reads.append((key, page))


@pytest.fixture
def worker(archive):
    fake = FakeWorker(archive).start()
    yield fake
    fake.stop()


class Server:
    """A local stand-in for Wikimedia's file server."""

    def __init__(self, files: dict[str, bytes]):
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.requests.append(self.headers.get("User-Agent"))
                body = files.get(self.path)
                if body is None:
                    self.send_response(503)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def stop(self):
        self.http.shutdown()
        self.http.server_close()


@pytest.fixture
def served():
    servers = []

    def make(files):
        servers.append(Server(files))
        return servers[-1]

    yield make
    for server in servers:
        server.stop()


def jpeg(colour: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (96, 64), colour).save(out, "JPEG")
    return out.getvalue()


FILES = {"a": jpeg("white"), "b": jpeg("beige"), "c": jpeg("grey")}


@pytest.fixture
def fixture_plates(served):
    """Three small plates on a local server, as two Documents: one with two sheets and one with one."""
    server = served({f"/{key}.jpg": body for key, body in FILES.items()})
    real = next(iter(PLATES.values()))
    plates = {
        key: Plate(**{**real.__dict__, "title": f"File:Plate {key}.jpg", "url": f"{server.url}/{key}.jpg",
                      "page": f"https://commons.wikimedia.org/wiki/File:Plate_{key}.jpg", "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)})
        for key, body in FILES.items()
    }
    documents = (
        PlateDocument(key="plate-two", title="Two sheets", plates=("a", "b"), date=Period("1768", "1768-01-01", "1768-12-31"), note="Two sheets."),
        PlateDocument(key="plate-one", title="One sheet", plates=("c",), date=Period("1768", "1768-01-01", "1768-12-31"), note="One sheet."),
    )
    return server, plates, documents
