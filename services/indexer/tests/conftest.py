import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pika
import pytest
from fakes import FakeCatalog

RABBITMQ_URL = "amqp://guest:guest@localhost:56672/%2F"
MEILI_URL = "http://localhost:57700"
MEILI_MASTER_KEY = "test-master-key"
ROOT = Path(__file__).resolve().parents[3]
DEFINITIONS = ROOT / "k8s" / "rabbitmq" / "definitions.json"
KEYS = json.loads((ROOT / "k8s" / "meilisearch" / "keys.json").read_text())
REINDEX_TOKEN = "reindex-token"


def key_for(uid: str) -> str:
    """Meilisearch derives a key from the master key and the key's uid, so no lookup is needed."""
    import hashlib
    import hmac

    return hmac.new(MEILI_MASTER_KEY.encode(), uid.encode(), hashlib.sha256).hexdigest()


class Meili:
    """The real Meilisearch the tests share: wiped for each test, with the two keys the cluster uses."""

    def __init__(self):
        self.url = MEILI_URL
        self.master = httpx.Client(base_url=MEILI_URL, headers={"Authorization": f"Bearer {MEILI_MASTER_KEY}"})
        self.indexer_key = key_for(next(k["uid"] for k in KEYS if k["name"] == "indexer"))
        self.search_key = key_for(next(k["uid"] for k in KEYS if k["name"] == "search"))

    def reset(self) -> None:
        for index in ("documents", "subjects"):
            self._wait(self.master.delete(f"/indexes/{index}").json().get("taskUid"))
        for key in self.master.get("/keys").json()["results"]:
            self.master.delete(f"/keys/{key['uid']}")
        for key in KEYS:
            created = self.master.post("/keys", json=key)
            assert created.status_code == 201, created.text

    def _wait(self, task_uid) -> None:
        import time

        while task_uid is not None:
            status = self.master.get(f"/tasks/{task_uid}").json()["status"]
            if status in ("succeeded", "failed", "canceled"):
                return
            time.sleep(0.02)

    def documents(self, index: str) -> dict[str, dict]:
        response = self.master.get(f"/indexes/{index}/documents", params={"limit": 1000})
        if response.status_code == 404:
            return {}
        return {doc["id"]: doc for doc in response.json()["results"]}

    def settings(self, index: str) -> dict:
        return self.master.get(f"/indexes/{index}/settings").json()

    def wipe(self, index: str) -> None:
        self._wait(self.master.delete(f"/indexes/{index}/documents").json()["taskUid"])

    def search(self, index: str, query: str = "", **params) -> dict:
        response = self.master.post(f"/indexes/{index}/search", json={"q": query, **params})
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture
def meili():
    meili = Meili()
    meili.reset()
    yield meili
    meili.master.close()


@pytest.fixture
def broker():
    """A channel to a real RabbitMQ holding the archive's exchanges and queues, emptied for each test."""
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    definitions = json.loads(DEFINITIONS.read_text())
    for queue in definitions["queues"]:
        channel.queue_delete(queue["name"])
    for exchange in definitions["exchanges"]:
        channel.exchange_declare(exchange["name"], exchange["type"], durable=exchange["durable"])
    for queue in definitions["queues"]:
        channel.queue_declare(queue["name"], durable=queue["durable"], arguments=queue["arguments"])
    for binding in definitions["bindings"]:
        channel.queue_bind(binding["destination"], binding["source"], binding["routing_key"])
    yield channel
    connection.close()


@pytest.fixture
def catalog():
    fake = FakeCatalog()
    fake.start()
    yield fake
    fake.stop()


class RunningIndexer:
    def __init__(self, process: subprocess.Popen, port: int, log_path: Path):
        self.process, self.port, self.log_path = process, port, log_path
        self.http = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5)

    def alive(self) -> bool:
        return self.process.poll() is None

    def ready(self) -> bool:
        try:
            return self.http.get("/readyz").status_code == 200
        except httpx.HTTPError:
            return False

    def reindex(self, token: str | None = REINDEX_TOKEN) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.http.post("/reindex", headers=headers)

    def reindex_status(self) -> dict:
        return self.http.get("/reindex", headers={"Authorization": f"Bearer {REINDEX_TOKEN}"}).json()

    def log(self) -> str:
        return self.log_path.read_text()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        item.failed = report.failed


@pytest.fixture
def start_indexer(request, catalog, broker, meili, tmp_path):
    """Run the indexer as its own process, configured only through the environment."""
    started: list[RunningIndexer] = []

    def start(**env_overrides) -> RunningIndexer:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env = {
            **os.environ,
            "RABBITMQ_URL": RABBITMQ_URL,
            "CATALOG_API_URL": catalog.url,
            "CATALOG_API_TOKEN": "indexer-token",
            "MEILI_URL": MEILI_URL,
            "MEILI_KEY": meili.indexer_key,
            "REINDEX_TOKEN": REINDEX_TOKEN,
            "HTTP_PORT": str(port),
            "RETRY_BACKOFF_SECONDS": "0.05",
            **env_overrides,
        }
        log_path = tmp_path / f"indexer-{len(started)}.log"
        process = subprocess.Popen(
            [sys.executable, "-m", "indexer.main"], env=env, stdout=log_path.open("w"), stderr=subprocess.STDOUT
        )
        indexer = RunningIndexer(process, port, log_path)
        started.append(indexer)
        return indexer

    yield start
    for indexer in started:
        indexer.process.terminate()
    for indexer in started:
        try:
            indexer.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            indexer.process.kill()
        indexer.http.close()
    if getattr(request.node, "failed", False):
        for number, indexer in enumerate(started):
            print(f"\n--- indexer {number} log ---\n{indexer.log()}")
