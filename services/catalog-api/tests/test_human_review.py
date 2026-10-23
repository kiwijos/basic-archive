import pytest
from support import API, upload

WORKER = {"Authorization": "Bearer worker-token"}
BOB = {"Authorization": "Bearer bob-token"}


def machine(text="machine reading", **overrides):
    return {
        "source": "machine",
        "text": text,
        "engine": "tesseract",
        "engine_version": "5.3.0",
        "language": "swe+eng",
        "confidence": 0.9,
        **overrides,
    }


def human(text="corrected by hand", **overrides):
    return {"source": "human", "text": text, **overrides}


@pytest.fixture
def image(client, staff):
    return upload(client, staff).json()["images"][0]["id"]


def post(client, headers, image_id, body):
    return client.post(f"{API}/images/{image_id}/transcriptions", json=body, headers=headers)


def history(client, staff, image_id):
    return client.get(f"{API}/images/{image_id}/transcriptions", headers=staff).json()


def status_of(client, staff, image_id):
    return client.get(f"{API}/images/{image_id}", headers=staff).json()["review_status"]


def test_a_correction_is_a_new_human_transcription_and_keeps_every_earlier_one(client, staff, image):
    post(client, WORKER, image, machine("machien reading"))

    first = post(client, staff, image, human("machine reading"))
    second = post(client, BOB, image, human("machine reading, checked"))

    assert first.status_code == 201 and second.status_code == 201
    rows = history(client, staff, image)
    assert [(row["source"], row["text"], row["created_by"]) for row in rows] == [
        ("human", "machine reading, checked", "bob"),
        ("human", "machine reading", "alice"),
        ("machine", "machien reading", "transcribe-worker"),
    ]
    assert all(row["created_at"] for row in rows)
    assert rows[2]["engine"] == "tesseract"  # the machine reading is untouched
    assert rows[0]["engine"] is None


@pytest.mark.parametrize("before", ["pending", "ocr_done", "failed"])
def test_a_correction_moves_the_image_to_verified_from_any_state(client, staff, image, before):
    if before == "ocr_done":
        post(client, WORKER, image, machine())
    if before == "failed":
        client.post(f"{API}/images/{image}/ocr-failure", json={}, headers=WORKER)
    assert status_of(client, staff, image) == before

    assert post(client, staff, image, human()).status_code == 201

    assert status_of(client, staff, image) == "verified"


def test_a_machine_result_arriving_after_a_correction_is_refused_and_replaces_nothing(
    client, staff, image
):
    post(client, staff, image, human("typed by a person before the OCR finished"))

    late = post(client, WORKER, image, machine("late machine reading"))

    assert late.status_code == 409
    assert [row["text"] for row in history(client, staff, image)] == [
        "typed by a person before the OCR finished"
    ]
    assert status_of(client, staff, image) == "verified"


def test_a_page_with_no_text_can_be_confirmed_blank(client, staff, image):
    assert post(client, staff, image, human("")).status_code == 201


def test_only_staff_write_human_transcriptions_and_only_the_worker_writes_machine_ones(
    client, staff, image
):
    assert post(client, WORKER, image, human()).status_code == 401
    assert post(client, staff, image, machine()).status_code == 401
    assert client.post(f"{API}/images/{image}/transcriptions", json=human()).status_code == 401
    assert history(client, staff, image) == []


@pytest.mark.parametrize(
    "bad",
    [{"source": "robot", "text": "x"}, {"source": "human"}, {"text": "no source"}, {"source": "human", "text": 5}],
)
def test_a_malformed_transcription_is_refused(client, staff, image, bad):
    assert post(client, staff, image, bad).status_code == 422


def test_a_correction_for_an_unknown_image_is_not_found(client, staff):
    assert post(client, staff, "3f2504e0-4f89-41d3-9a0c-0305e82c3301", human()).status_code == 404


def test_a_correction_announces_the_document(client, staff, image, outbox):
    before = len(outbox())

    post(client, staff, image, human())

    assert [(entity, op) for entity, _, op in outbox()[before:]] == [("document", "upsert")]
