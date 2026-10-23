import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from search_api.app import create_app
from search_api.settings import Settings

MEILI_URL = "http://localhost:57700"
MEILI_MASTER_KEY = "test-master-key"
ROOT = Path(__file__).resolve().parents[3]
KEYS = json.loads((ROOT / "k8s" / "meilisearch" / "keys.json").read_text())
INDEX_SETTINGS = json.loads((ROOT / "contracts" / "search-index.settings.json").read_text())


def key_for(name: str) -> str:
    """Meilisearch derives a key from the master key and the key's uid."""
    uid = next(k["uid"] for k in KEYS if k["name"] == name)
    return hmac.new(MEILI_MASTER_KEY.encode(), uid.encode(), hashlib.sha256).hexdigest()


class Meili:
    """The real Meilisearch the tests share, with the cluster's index settings, wiped for each test."""

    def __init__(self):
        self.http = httpx.Client(base_url=MEILI_URL, headers={"Authorization": f"Bearer {MEILI_MASTER_KEY}"}, timeout=30)

    def _wait(self, response: httpx.Response) -> None:
        uid = response.json().get("taskUid")
        while uid is not None:
            if self.http.get(f"/tasks/{uid}").json()["status"] in ("succeeded", "failed", "canceled"):
                return
            time.sleep(0.02)

    def reset(self) -> None:
        for index, settings in INDEX_SETTINGS.items():
            self._wait(self.http.delete(f"/indexes/{index}"))
            self._wait(self.http.post("/indexes", json={"uid": index, "primaryKey": "id"}))
            self._wait(self.http.patch(f"/indexes/{index}/settings", json=settings))
        for key in self.http.get("/keys").json()["results"]:
            self.http.delete(f"/keys/{key['uid']}")
        for key in KEYS:
            assert self.http.post("/keys", json=key).status_code == 201

    def add(self, index: str, *documents: dict) -> None:
        self._wait(self.http.post(f"/indexes/{index}/documents", json=list(documents)))


@pytest.fixture
def meili():
    meili = Meili()
    meili.reset()
    yield meili
    meili.http.close()


@pytest.fixture
def new_client(meili):
    clients = []

    def start(**overrides) -> TestClient:
        values = {"meili_url": MEILI_URL, "meili_key": key_for("search"), "rate_limit_per_minute": 10_000, **overrides}
        client = TestClient(create_app(Settings(**values)))
        client.__enter__()
        clients.append(client)
        return client

    yield start
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(new_client):
    return new_client()


def new_id() -> str:
    return str(uuid.uuid4())


def document(**overrides) -> dict:
    """A document as the indexer stores it."""
    base = {
        "entity": "document",
        "id": new_id(),
        "title": "Brev från varvet",
        "document_type": "letter",
        "description": None,
        "physical_location": None,
        "date_text": None,
        "year_from": None,
        "year_to": None,
        "text": "Skeppet Vega lämnade Göteborg",
        "verified": False,
        "verified_images": 0,
        "image_count": 1,
        "images": [
            {"id": new_id(), "page_no": 1, "mime": "image/png", "rights": "reserved", "verified": False, "text_source": "machine", "text": "Skeppet Vega lämnade Göteborg"}
        ],
        "subjects": [],
        "ship_names": [],
        "ship_types": [],
        "builders": [],
        "places": [],
    }
    return {**base, **overrides}


def subject(name="Vega", *, names=None, **overrides) -> dict:
    """A ship as the indexer stores it; `names` are (name, current) pairs."""
    pairs = names or [(name, True)]
    details = [
        {"name": n, "name_type": "given", "date_text": None, "date_from": None, "date_to": None, "current": current}
        for n, current in pairs
    ]
    base = {
        "id": new_id(),
        "entity": "ship",
        "name": next(n for n, current in pairs if current),
        "names": [n for n, _ in pairs],
        "name_details": details,
        "ship_type": "barque",
        "organisation_type": None,
        "builders": [],
        "places": [],
        "year_from": None,
        "year_to": None,
        "tonnage": None,
        "launched": None,
        "fate": None,
        "fate_date": None,
        "external_refs": [],
        "relations": [],
        "documents": [],
    }
    return {**base, **overrides}
