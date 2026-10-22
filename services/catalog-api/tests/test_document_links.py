import pytest
from support import API, upload


@pytest.fixture
def subjects(client, staff):
    ship = client.post(f"{API}/ships", json={"name": "Vega"}, headers=staff).json()["id"]
    yard = client.post(f"{API}/organisations", json={"name": "Götaverken"}, headers=staff).json()["id"]
    return {"ship": ship, "yard": yard}


def link(client, staff, document_id, subject_id, **body):
    return client.put(
        f"{API}/documents/{document_id}/subjects/{subject_id}", json=body, headers=staff
    )


def test_a_document_is_linked_to_several_subjects_and_the_links_read_back(
    client, staff, subjects
):
    document = upload(client, staff).json()["id"]

    assert link(client, staff, document, subjects["ship"], role="depicted").status_code == 200
    assert link(client, staff, document, subjects["yard"]).status_code == 200

    read_back = client.get(f"{API}/documents/{document}", headers=staff).json()
    assert sorted(
        (s["name"], s["kind"], s["role"], s["subject_id"]) for s in read_back["subjects"]
    ) == [
        ("Götaverken", "organisation", None, subjects["yard"]),
        ("Vega", "ship", "depicted", subjects["ship"]),
    ]
    assert read_back["title"] == "Letter from the yard"
    assert len(read_back["images"]) == 1


def test_linking_again_changes_the_role_instead_of_adding_a_second_link(
    client, staff, subjects
):
    document = upload(client, staff).json()["id"]
    link(client, staff, document, subjects["ship"], role="mentioned")

    link(client, staff, document, subjects["ship"], role="depicted")

    read_back = client.get(f"{API}/documents/{document}", headers=staff).json()
    assert [(s["name"], s["role"]) for s in read_back["subjects"]] == [("Vega", "depicted")]


def test_a_deleted_subject_drops_out_of_the_documents_links(client, staff, subjects):
    document = upload(client, staff).json()["id"]
    link(client, staff, document, subjects["ship"])
    link(client, staff, document, subjects["yard"])

    client.delete(f"{API}/ships/{subjects['ship']}", headers=staff)

    read_back = client.get(f"{API}/documents/{document}", headers=staff).json()
    assert [s["name"] for s in read_back["subjects"]] == ["Götaverken"]


def test_links_need_an_existing_document_and_subject_and_a_token(client, staff, subjects):
    document = upload(client, staff).json()["id"]
    unknown = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    assert link(client, staff, unknown, subjects["ship"]).status_code == 404
    assert link(client, staff, document, unknown).status_code == 404
    assert client.get(f"{API}/documents/{unknown}", headers=staff).status_code == 404
    assert client.put(
        f"{API}/documents/{document}/subjects/{subjects['ship']}", json={}
    ).status_code == 401
    assert client.get(f"{API}/documents/{document}").status_code == 401


def test_uploading_and_linking_announce_the_document(client, staff, subjects, outbox):
    document = upload(client, staff).json()["id"]
    link(client, staff, document, subjects["ship"], role="depicted")

    announced = [event for event in outbox() if event[0] == "document"]
    assert announced == [("document", document, "upsert")] * 2
