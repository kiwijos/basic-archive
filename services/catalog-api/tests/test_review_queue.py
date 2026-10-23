import pytest
from support import API, upload
from test_pages import JPEG, add_page
from test_verified import correct, read_by_machine

WORKER = {"Authorization": "Bearer worker-token"}


def queue(client, staff, **params):
    response = client.get(f"{API}/review-queue", params=params, headers=staff)
    assert response.status_code == 200, response.text
    return response.json()


def titles(client, staff, **params):
    return [item["title"] for item in queue(client, staff, **params)]


def test_an_empty_archive_has_an_empty_queue(client, staff):
    assert queue(client, staff) == []


def test_a_new_upload_is_in_the_queue_with_its_counts_and_statuses(client, staff):
    document = upload(client, staff, title="Letter A").json()

    [item] = queue(client, staff)

    assert item["id"] == document["id"]
    assert item["title"] == "Letter A"
    assert item["document_type"] is None
    assert (item["verified_images"], item["image_count"]) == (0, 1)
    assert item["statuses"] == {"pending": 1, "ocr_done": 0, "failed": 0, "verified": 0}
    assert item["created_at"]


def test_the_statuses_follow_what_happens_to_the_images(client, staff):
    read = upload(client, staff, title="Read").json()["images"][0]["id"]
    failed = upload(client, staff, title="Failed", content=b"\x89PNG\r\n\x1a\n other").json()["images"][0]["id"]
    read_by_machine(client, read, "text")
    client.post(f"{API}/images/{failed}/ocr-failure", json={}, headers=WORKER)

    by_title = {item["title"]: item["statuses"] for item in queue(client, staff)}

    assert by_title["Read"] == {"pending": 0, "ocr_done": 1, "failed": 0, "verified": 0}
    assert by_title["Failed"] == {"pending": 0, "ocr_done": 0, "failed": 1, "verified": 0}


def test_a_document_leaves_the_queue_once_all_its_images_are_verified(client, staff):
    document = upload(client, staff, title="Letter A").json()
    upload(client, staff, title="Letter B", content=b"II*\x00 b")

    correct(client, staff, document["images"][0]["id"], "typed")

    assert titles(client, staff) == ["Letter B"]


def test_a_partly_verified_document_stays_in_the_queue_with_its_count(client, staff):
    document = upload(client, staff, title="Two pages").json()
    add_page(client, staff, document["id"], JPEG)
    correct(client, staff, document["images"][0]["id"], "page one")

    [item] = queue(client, staff)

    assert (item["verified_images"], item["image_count"]) == (1, 2)
    assert item["statuses"] == {"pending": 1, "ocr_done": 0, "failed": 0, "verified": 1}


def test_the_oldest_document_comes_first(client, staff):
    for title in ("First", "Second", "Third"):
        upload(client, staff, title=title, content=b"\x89PNG\r\n\x1a\n " + title.encode())

    assert titles(client, staff) == ["First", "Second", "Third"]


def test_the_queue_is_paged_and_the_page_size_is_capped(client, staff):
    for title in ("A", "B", "C"):
        upload(client, staff, title=title, content=b"\x89PNG\r\n\x1a\n " + title.encode())

    assert titles(client, staff, limit=2) == ["A", "B"]
    assert titles(client, staff, limit=2, offset=2) == ["C"]
    assert client.get(f"{API}/review-queue", params={"limit": 201}, headers=staff).status_code == 422
    assert client.get(f"{API}/review-queue", params={"limit": 0}, headers=staff).status_code == 422
    assert client.get(f"{API}/review-queue", params={"offset": -1}, headers=staff).status_code == 422


def test_only_staff_may_look_at_the_queue(client, staff):
    assert client.get(f"{API}/review-queue").status_code == 401
    assert client.get(f"{API}/review-queue", headers=WORKER).status_code == 401
    assert client.get(f"{API}/review-queue", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_a_token_says_who_it_belongs_to(client, staff):
    assert client.get(f"{API}/me", headers=staff).json() == {"name": "alice"}
    assert client.get(f"{API}/me", headers={"Authorization": "Bearer bob-token"}).json() == {"name": "bob"}
    assert client.get(f"{API}/me").status_code == 401
    assert client.get(f"{API}/me", headers=WORKER).status_code == 401
