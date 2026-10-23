"""Builders for indexing views, checked against the contract so the fake catalog cannot drift from it."""

import json
import time
import uuid
from pathlib import Path

from jsonschema import Draft202012Validator

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
_contract = Draft202012Validator(json.loads((CONTRACTS / "index.view.schema.json").read_text()))


def new_id() -> str:
    return str(uuid.uuid4())


def document(**overrides) -> dict:
    view = {
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
    view.update(overrides)
    _contract.validate(view)
    return view


def ship(**overrides) -> dict:
    name = overrides.pop("name", "Vega")
    names = overrides.pop("names", None) or [
        {"name": name, "name_type": "given", "date_text": None, "date_from": None, "date_to": None, "current": True}
    ]
    view = {
        "entity": "ship",
        "id": new_id(),
        "name": name,
        "names": names,
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
        "relations": [],
        "documents": [],
    }
    view.update(overrides)
    _contract.validate(view)
    return view


def event(entity: str, record_id: str, op: str = "upsert") -> bytes:
    return json.dumps({"entity": entity, "id": record_id, "op": op}).encode()


def wait_until(condition, timeout=20.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return condition()
