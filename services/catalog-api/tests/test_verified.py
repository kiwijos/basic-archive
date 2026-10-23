import pytest
from support import API, PNG, upload
from test_pages import JPEG, add_page

WORKER = {"Authorization": "Bearer worker-token"}


def machine(text):
    return {
        "source": "machine",
        "text": text,
        "engine": "tesseract",
        "engine_version": "5.3.0",
        "language": "swe+eng",
        "confidence": 0.9,
    }


def read_by_machine(client, image_id, text):
    return client.post(f"{API}/images/{image_id}/transcriptions", json=machine(text), headers=WORKER)


def correct(client, staff, image_id, text):
    body = {"source": "human", "text": text}
    return client.post(f"{API}/images/{image_id}/transcriptions", json=body, headers=staff)


def image_state(client, staff, image_id):
    image = client.get(f"{API}/images/{image_id}", headers=staff).json()
    return image["verified"], image["text_source"], image["current_text"]


@pytest.fixture
def image(client, staff):
    return upload(client, staff).json()["images"][0]["id"]


def test_an_image_nobody_has_read_has_no_current_text_and_is_not_verified(client, staff, image):
    assert image_state(client, staff, image) == (False, None, None)


def test_a_machine_reading_is_the_current_text_but_does_not_verify_the_image(client, staff, image):
    read_by_machine(client, image, "machien reading")

    assert image_state(client, staff, image) == (False, "machine", "machien reading")


def test_the_newest_machine_reading_is_current_until_a_person_has_written(client, staff, image):
    read_by_machine(client, image, "first reading")
    client.post(f"{API}/images/{image}/ocr", headers=staff)
    read_by_machine(client, image, "second reading")

    assert image_state(client, staff, image) == (False, "machine", "second reading")


def test_the_latest_human_transcription_is_current_and_makes_the_image_verified(client, staff, image):
    read_by_machine(client, image, "machien reading")

    correct(client, staff, image, "machine reading")
    assert image_state(client, staff, image) == (True, "human", "machine reading")

    correct(client, staff, image, "machine reading, checked twice")
    assert image_state(client, staff, image) == (True, "human", "machine reading, checked twice")


def test_confirming_a_blank_page_makes_it_verified_with_empty_text(client, staff, image):
    correct(client, staff, image, "")

    assert image_state(client, staff, image) == (True, "human", "")


def test_the_same_state_is_shown_wherever_an_image_appears(client, staff):
    document = upload(client, staff).json()
    image = document["images"][0]["id"]
    read_by_machine(client, image, "machien reading")
    correct(client, staff, image, "machine reading")

    from_image = client.get(f"{API}/images/{image}", headers=staff).json()
    from_document = client.get(f"{API}/documents/{document['id']}", headers=staff).json()["images"][0]
    from_page_upload = add_page(client, staff, document["id"]).json()["images"][0]

    assert from_image == from_document == from_page_upload


def document_state(client, staff, document_id):
    document = client.get(f"{API}/documents/{document_id}", headers=staff).json()
    return document["verified"], document["verified_images"], document["image_count"]


def test_a_document_is_verified_only_when_every_one_of_its_images_is(client, staff):
    document = upload(client, staff).json()
    second = add_page(client, staff, document["id"], JPEG).json()["images"][1]["id"]
    first = document["images"][0]["id"]
    assert document_state(client, staff, document["id"]) == (False, 0, 2)

    correct(client, staff, first, "page one")
    assert document_state(client, staff, document["id"]) == (False, 1, 2)

    read_by_machine(client, second, "page two, machine only")
    assert document_state(client, staff, document["id"]) == (False, 1, 2)

    correct(client, staff, second, "page two")
    assert document_state(client, staff, document["id"]) == (True, 2, 2)


def test_adding_a_page_to_a_verified_document_makes_it_unverified_again(client, staff):
    document = upload(client, staff).json()
    correct(client, staff, document["images"][0]["id"], "page one")
    assert document_state(client, staff, document["id"]) == (True, 1, 1)

    add_page(client, staff, document["id"], PNG + b" another")

    assert document_state(client, staff, document["id"]) == (False, 1, 2)


def test_an_upload_answer_already_carries_the_document_state(client, staff):
    answer = upload(client, staff).json()

    assert (answer["verified"], answer["verified_images"], answer["image_count"]) == (False, 0, 1)
    assert answer["images"][0]["verified"] is False
