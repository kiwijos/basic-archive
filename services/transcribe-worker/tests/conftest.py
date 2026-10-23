import json
import os
import socket
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import pika
import pytest
from fakes import CuttableProxy, FakeCatalog

RABBITMQ_URL = "amqp://guest:guest@localhost:56672/%2F"
# The same file the cluster's broker loads, so tests and deployment cannot disagree about the topology.
DEFINITIONS = Path(__file__).resolve().parents[3] / "k8s" / "rabbitmq" / "definitions.json"
TESSDATA = Path.home() / ".cache" / "tessdata"


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


@pytest.fixture
def proxy():
    """A pass-through to RabbitMQ that the test can cut and restore."""
    cuttable = CuttableProxy("127.0.0.1", 56672)
    yield cuttable
    cuttable.stop()


class RunningWorker:
    def __init__(self, process: subprocess.Popen, health_port: int, log_path: Path):
        self.process = process
        self.health_port = health_port
        self.log_path = log_path

    def alive(self) -> bool:
        return self.process.poll() is None

    def health(self, path: str) -> int:
        try:
            return urllib.request.urlopen(f"http://127.0.0.1:{self.health_port}{path}", timeout=2).status
        except urllib.error.HTTPError as error:
            return error.code
        except OSError:
            return 0

    def log(self) -> str:
        return self.log_path.read_text()


@pytest.fixture
def start_worker(catalog, broker, tmp_path):
    """Run transcribe-worker as its own process, configured only through the environment."""
    started: list[RunningWorker] = []

    def start(**env_overrides) -> RunningWorker:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env = {
            **os.environ,
            "RABBITMQ_URL": RABBITMQ_URL,
            "CATALOG_API_URL": catalog.url,
            "CATALOG_API_TOKEN": "worker-token",
            "MAX_ATTEMPTS": "3",
            "RETRY_BACKOFF_SECONDS": "0.05",
            "HEALTH_PORT": str(port),
            **env_overrides,
        }
        # A machine whose package manager already installed the language data needs nothing here;
        # otherwise point Tesseract at the directory that holds it.
        if "TESSDATA_PREFIX" not in env and TESSDATA.exists():
            env["TESSDATA_PREFIX"] = str(TESSDATA)
        log_path = tmp_path / f"worker-{len(started)}.log"
        process = subprocess.Popen(
            [sys.executable, "-m", "transcribe_worker.main"],
            env=env,
            stdout=log_path.open("w"),
            stderr=subprocess.STDOUT,
        )
        worker = RunningWorker(process, port, log_path)
        started.append(worker)
        return worker

    yield start
    for worker in started:
        worker.process.terminate()
    for worker in started:
        try:
            worker.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.process.kill()
