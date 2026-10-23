import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from support import API, upload

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
UUID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


def contract(name: str) -> Draft202012Validator:
    # Read straight from the contracts directory, so these tests do not trust the service's own loader.
    return Draft202012Validator(json.loads((CONTRACTS / f"{name}.schema.json").read_text()))


def test_every_event_the_service_queues_follows_its_contract(client, staff, events):
    ship = client.post(f"{API}/ships", json={"name": "Vega"}, headers=staff).json()["id"]
    yard = client.post(f"{API}/organisations", json={"name": "Götaverken"}, headers=staff).json()["id"]
    client.post(
        f"{API}/relations",
        json={"from_subject_id": ship, "predicate": "built_by", "to_subject_id": yard},
        headers=staff,
    )
    document = upload(client, staff).json()["id"]
    client.put(f"{API}/documents/{document}/subjects/{ship}", json={}, headers=staff)
    client.delete(f"{API}/ships/{ship}", headers=staff)

    queued = events()

    assert {event_type for event_type, _ in queued} == {"record.changed", "ocr.requested"}
    for event_type, payload in queued:
        contract(event_type).validate(payload)


@pytest.mark.parametrize(
    "message",
    [
        {"image_id": UUID, "attempt": 1},
        {"image_id": UUID, "attempt": 3},
    ],
)
def test_the_ocr_contract_accepts_well_formed_requests(message):
    assert contract("ocr.requested").is_valid(message)


@pytest.mark.parametrize(
    "message",
    [
        {"attempt": 1},
        {"image_id": UUID},
        {"image_id": "not-a-uuid", "attempt": 1},
        {"image_id": UUID, "attempt": 0},
        {"image_id": UUID, "attempt": "1"},
        {"image_id": UUID, "attempt": 1, "priority": "high"},
        [],
    ],
)
def test_the_ocr_contract_rejects_malformed_requests(message):
    assert not contract("ocr.requested").is_valid(message)


@pytest.mark.parametrize("entity", ["document", "ship", "organisation"])
@pytest.mark.parametrize("op", ["upsert", "delete"])
def test_the_change_contract_accepts_every_entity_and_operation(entity, op):
    assert contract("record.changed").is_valid({"entity": entity, "id": UUID, "op": op})


@pytest.mark.parametrize(
    "message",
    [
        {"entity": "person", "id": UUID, "op": "upsert"},
        {"entity": "ship", "id": UUID, "op": "rename"},
        {"entity": "ship", "id": "not-a-uuid", "op": "upsert"},
        {"entity": "ship", "op": "upsert"},
        {"entity": "ship", "id": UUID, "op": "upsert", "extra": 1},
    ],
)
def test_the_change_contract_rejects_malformed_changes(message):
    assert not contract("record.changed").is_valid(message)
