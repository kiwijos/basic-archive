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


def soft_delete(database, table, record_id):
    from sqlalchemy import text

    with database.begin() as connection:
        connection.execute(text(f"UPDATE {table} SET deleted_at = now() WHERE id = :id"), {"id": record_id})


def test_a_soft_deleted_image_is_not_counted_and_cannot_be_corrected(client, staff, database):
    document = upload(client, staff).json()
    kept = document["images"][0]["id"]
    removed = add_page(client, staff, document["id"], JPEG).json()["images"][1]["id"]
    soft_delete(database, "image", removed)

    read = client.get(f"{API}/documents/{document['id']}", headers=staff).json()

    assert (read["image_count"], read["verified_images"], read["verified"]) == (1, 0, False)
    assert correct(client, staff, removed, "x").status_code == 404
    assert correct(client, staff, kept, "x").status_code == 201
    assert client.get(f"{API}/documents/{document['id']}", headers=staff).json()["verified"] is True


def test_a_document_with_no_live_images_is_neither_verified_nor_waiting(client, staff, database):
    document = upload(client, staff).json()
    soft_delete(database, "image", document["images"][0]["id"])

    read = client.get(f"{API}/documents/{document['id']}", headers=staff).json()

    assert (read["image_count"], read["verified"]) == (0, False)
    assert client.get(f"{API}/review-queue", headers=staff).json() == []


def test_a_soft_deleted_document_is_not_in_the_queue(client, staff, database):
    document = upload(client, staff).json()
    soft_delete(database, "document", document["id"])

    assert client.get(f"{API}/review-queue", headers=staff).json() == []


def test_the_text_limit_is_enforced_at_the_boundary_for_corrections_and_machine_results(client, staff, image):
    from catalog_api.transcriptions import MAX_TEXT_CHARACTERS

    assert correct(client, staff, image, "a" * MAX_TEXT_CHARACTERS).status_code == 201
    assert correct(client, staff, image, "a" * (MAX_TEXT_CHARACTERS + 1)).status_code == 422
    other = upload(client, staff, title="Other").json()["images"][0]["id"]
    assert read_by_machine(client, other, "a" * (MAX_TEXT_CHARACTERS + 1)).status_code == 422


def test_a_correction_is_stamped_when_it_is_written_not_when_its_transaction_began(client, staff, image, database):
    import threading
    import time

    from sqlalchemy import text

    # Hold the Image's row so a correction starts, then waits. now() would stamp it with the time it
    # started; the stamp must be the time it was written, or overlapping saves can be ordered wrongly.
    with database.connect() as connection:  # this engine autocommits, so the transaction is explicit
        connection.execute(text("BEGIN"))
        connection.execute(text("SELECT 1 FROM image WHERE id = :id FOR UPDATE"), {"id": image})
        saver = threading.Thread(target=lambda: correct(client, staff, image, "waited"))
        saver.start()
        time.sleep(1.5)
        released = connection.execute(text("SELECT clock_timestamp()")).scalar()
        connection.execute(text("COMMIT"))
        saver.join(timeout=30)
        stamped = connection.execute(text("SELECT created_at FROM transcription WHERE text = 'waited'")).scalar()

    assert stamped >= released
