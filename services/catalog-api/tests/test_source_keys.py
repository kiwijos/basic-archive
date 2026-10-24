import pytest
from support import API, stored_objects, upload

WORKER = {"Authorization": "Bearer worker-token"}


def key(system="seed", ident="ship-vega"):
    return {"source_system": system, "source_id": ident}


def make_ship(client, staff, name="Vega", **extra):
    return client.post(f"{API}/ships", json={"name": name, **extra}, headers=staff)


def make_organisation(client, staff, name="Älvsborgs varv", **extra):
    return client.post(f"{API}/organisations", json={"name": name, **extra}, headers=staff)


def lookup(client, staff, kind, **params):
    response = client.get(f"{API}/{kind}", params=params, headers=staff)
    assert response.status_code == 200, response.text
    return response.json()


# ---- Documents ------------------------------------------------------------------------------------------------------


def test_a_document_can_carry_the_key_of_where_it_came_from_and_be_found_by_it(client, staff):
    made = upload(client, staff, title="Brev", **key("seed", "letter-1"))
    other = upload(client, staff, title="Annat brev", content=b"\x89PNG\r\n\x1a\nother", **key("seed", "letter-2"))

    assert made.status_code == 201
    assert (made.json()["source_system"], made.json()["source_id"]) == ("seed", "letter-1")
    [found] = lookup(client, staff, "documents", source_system="seed", source_id="letter-1")
    assert found["id"] == made.json()["id"]
    assert client.get(f"{API}/documents/{made.json()['id']}", headers=staff).json()["source_id"] == "letter-1"
    # By system alone: everything that came from there.
    assert {d["id"] for d in lookup(client, staff, "documents", source_system="seed")} == {made.json()["id"], other.json()["id"]}
    assert lookup(client, staff, "documents", source_system="seed", source_id="nope") == []
    assert lookup(client, staff, "documents", source_system="elsewhere") == []


def test_a_document_without_a_key_is_as_before_and_many_may_lack_one(client, staff):
    first = upload(client, staff, title="A")
    second = upload(client, staff, title="B", content=b"\x89PNG\r\n\x1a\nsecond")

    assert (first.json()["source_system"], first.json()["source_id"]) == (None, None)
    assert second.status_code == 201


def test_a_key_is_both_parts_or_neither_and_is_plain_text(client, staff):
    for fields in ({"source_system": "seed"}, {"source_id": "x"}, key("", "x"), key("seed", "has space"), key("seed", "a" * 101), key("se ed", "x"), key("seed", "ä")):
        answer = upload(client, staff, **fields)
        assert answer.status_code == 422, fields
    assert client.get(f"{API}/documents", params={"source_id": "x"}, headers=staff).status_code == 422
    assert client.get(f"{API}/documents", headers=staff).status_code == 422  # not a way to list everything


def test_a_second_document_with_the_same_key_is_refused_and_stores_nothing(client, staff, s3):
    upload(client, staff, **key("seed", "letter-1"))
    objects = stored_objects(s3)

    again = upload(client, staff, title="Samma igen", content=b"\x89PNG\r\n\x1a\nanother file", **key("seed", "letter-1"))

    assert again.status_code == 409
    assert "seed" in again.json()["detail"] and "letter-1" in again.json()["detail"]
    assert stored_objects(s3) == objects
    assert len(lookup(client, staff, "documents", source_system="seed")) == 1
    # The same id in another system is a different thing.
    assert upload(client, staff, content=b"\x89PNG\r\n\x1a\nthird", **key("elsewhere", "letter-1")).status_code == 201


def test_only_staff_may_look_documents_up_by_key(client, staff):
    upload(client, staff, **key())

    for headers in ({}, WORKER):
        assert client.get(f"{API}/documents", params=key(), headers=headers).status_code == 401


# ---- Ships and Organisations ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind,make", [("ships", make_ship), ("organisations", make_organisation)])
def test_a_subject_can_carry_a_key_and_be_found_by_it(client, staff, kind, make):
    made = make(client, staff, **key("seed", "subject-1"))

    assert made.status_code == 201
    assert (made.json()["source_system"], made.json()["source_id"]) == ("seed", "subject-1")
    assert client.get(f"{API}/{kind}/{made.json()['id']}", headers=staff).json()["source_id"] == "subject-1"
    assert [s["id"] for s in lookup(client, staff, kind, **key("seed", "subject-1"))] == [made.json()["id"]]
    assert [s["id"] for s in lookup(client, staff, kind, source_system="seed")] == [made.json()["id"]]
    assert lookup(client, staff, kind, **key("seed", "other")) == []
    assert make(client, staff, name="Annat", **key("seed", "subject-1")).status_code == 409
    assert make(client, staff, name="Utan nyckel").status_code == 201
    assert make(client, staff, source_system="seed").status_code == 422


def test_a_key_belongs_to_one_record_whatever_its_kind_and_each_kind_finds_only_its_own(client, staff):
    ship = make_ship(client, staff, **key("seed", "same"))

    clash = make_organisation(client, staff, **key("seed", "same"))

    assert clash.status_code == 409
    assert lookup(client, staff, "organisations", source_system="seed") == []
    assert [s["id"] for s in lookup(client, staff, "ships", source_system="seed")] == [ship.json()["id"]]


def test_a_deleted_record_is_not_found_by_its_key_and_its_key_cannot_be_reused_quietly(client, staff):
    ship = make_ship(client, staff, **key("seed", "gone")).json()["id"]
    client.delete(f"{API}/ships/{ship}", headers=staff)

    assert lookup(client, staff, "ships", **key("seed", "gone")) == []
    again = make_ship(client, staff, **key("seed", "gone"))
    assert again.status_code == 409
    assert "deleted" in again.json()["detail"].lower()


def test_the_key_is_not_something_a_later_update_can_change(client, staff):
    ship = make_ship(client, staff, **key("seed", "fixed")).json()["id"]

    client.put(f"{API}/ships/{ship}", json={"ship_type": "barque", **key("seed", "changed")}, headers=staff)

    assert client.get(f"{API}/ships/{ship}", headers=staff).json()["source_id"] == "fixed"


def test_only_staff_may_look_subjects_up_by_key(client, staff):
    make_ship(client, staff, **key())

    for kind in ("ships", "organisations"):
        for headers in ({}, WORKER):
            assert client.get(f"{API}/{kind}", params=key(), headers=headers).status_code == 401


@pytest.mark.parametrize("make", [make_ship, make_organisation])
def test_two_creates_at_the_same_moment_with_one_key_give_one_record_and_one_refusal(client, staff, make):
    from concurrent.futures import ThreadPoolExecutor

    def create(_):
        return make(client, staff, **key("seed", "race")).status_code

    with ThreadPoolExecutor(6) as pool:
        codes = sorted(pool.map(create, range(6)))

    assert codes == [201, 409, 409, 409, 409, 409]


def test_two_uploads_at_the_same_moment_with_one_key_give_one_document(client, staff):
    from concurrent.futures import ThreadPoolExecutor

    def send(n):
        return upload(client, staff, content=b"\x89PNG\r\n\x1a\n" + bytes([n]), **key("seed", "race")).status_code

    with ThreadPoolExecutor(5) as pool:
        codes = sorted(pool.map(send, range(5)))

    assert codes == [201, 409, 409, 409, 409]
    assert len(lookup(client, staff, "documents", source_system="seed")) == 1
