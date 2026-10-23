import pytest
from support import API, upload

WORKER = {"Authorization": "Bearer worker-token"}


def machine_result(**overrides):
    return {
        "source": "machine",
        "text": "Skeppet Vega lämnade Göteborg",
        "engine": "tesseract",
        "engine_version": "5.3.0",
        "language": "swe+eng",
        "confidence": 0.91,
        **overrides,
    }


@pytest.fixture
def image(client, staff):
    return upload(client, staff).json()["images"][0]["id"]


def post_result(client, headers, image_id, **overrides):
    return client.post(
        f"{API}/images/{image_id}/transcriptions", json=machine_result(**overrides), headers=headers
    )


def status_of(client, staff, image_id):
    return client.get(f"{API}/images/{image_id}", headers=staff).json()["review_status"]


def test_an_upload_queues_exactly_one_ocr_job_for_its_image(client, staff, jobs):
    document = upload(client, staff).json()

    assert jobs() == [(document["images"][0]["id"], 1)]


def test_a_refused_upload_queues_no_job(client, staff, jobs):
    upload(client, staff, b"%PDF-1.7 not an image", "scan.jpg")

    assert jobs() == []


def test_a_machine_transcription_is_recorded_and_moves_the_image_to_ocr_done(
    client, staff, image
):
    assert status_of(client, staff, image) == "pending"

    response = post_result(client, WORKER, image)

    assert response.status_code == 201
    assert status_of(client, staff, image) == "ocr_done"
    [transcription] = client.get(f"{API}/images/{image}/transcriptions", headers=staff).json()
    assert transcription["image_id"] == image
    assert transcription["source"] == "machine"
    assert transcription["text"] == "Skeppet Vega lämnade Göteborg"
    assert transcription["engine"] == "tesseract"
    assert transcription["engine_version"] == "5.3.0"
    assert transcription["language"] == "swe+eng"
    assert transcription["confidence"] == 0.91
    assert transcription["created_by"] == "transcribe-worker"
    assert transcription["id"] == response.json()["id"]


def test_a_second_result_for_the_same_job_is_refused_so_a_duplicate_delivery_is_harmless(
    client, staff, image
):
    post_result(client, WORKER, image)

    again = post_result(client, WORKER, image, text="something else")

    assert again.status_code == 409
    texts = [t["text"] for t in client.get(f"{API}/images/{image}/transcriptions", headers=staff).json()]
    assert texts == ["Skeppet Vega lämnade Göteborg"]


def test_a_blank_page_is_a_valid_result(client, staff, image):
    response = post_result(client, WORKER, image, text="", confidence=None)

    assert response.status_code == 201


@pytest.mark.parametrize(
    "bad",
    [
        {"confidence": 1.5},
        {"confidence": -0.1},
        {"engine": ""},
        {"engine_version": ""},
        {"language": ""},
    ],
)
def test_a_machine_result_must_be_well_formed(client, staff, image, bad):
    response = post_result(client, WORKER, image, **bad)

    assert response.status_code == 422
    assert status_of(client, staff, image) == "pending"


def test_a_machine_result_announces_the_document_so_search_can_follow(client, staff, image, outbox):
    before = len(outbox())

    post_result(client, WORKER, image)

    announced = outbox()[before:]
    assert [(entity, op) for entity, _, op in announced] == [("document", "upsert")]


def test_reporting_a_failure_marks_a_pending_image_failed(client, staff, image):
    response = client.post(
        f"{API}/images/{image}/ocr-failure", json={"reason": "unreadable image"}, headers=WORKER
    )

    assert response.status_code == 200
    assert status_of(client, staff, image) == "failed"


def test_a_failure_report_cannot_undo_a_finished_transcription(client, staff, image):
    post_result(client, WORKER, image)

    response = client.post(
        f"{API}/images/{image}/ocr-failure", json={"reason": "late"}, headers=WORKER
    )

    assert response.status_code == 409
    assert status_of(client, staff, image) == "ocr_done"


def test_a_failed_image_can_be_read_again_and_then_succeeds(client, staff, image, jobs):
    client.post(f"{API}/images/{image}/ocr-failure", json={"reason": "x"}, headers=WORKER)

    rerun = client.post(f"{API}/images/{image}/ocr", headers=staff)

    assert rerun.status_code == 202
    assert status_of(client, staff, image) == "pending"
    assert jobs() == [(image, 1), (image, 1)]
    assert post_result(client, WORKER, image).status_code == 201
    assert status_of(client, staff, image) == "ocr_done"


def test_a_finished_image_can_be_read_again_and_keeps_both_machine_transcriptions(
    client, staff, image
):
    post_result(client, WORKER, image, text="first reading")
    client.post(f"{API}/images/{image}/ocr", headers=staff)

    post_result(client, WORKER, image, text="second reading")

    texts = [t["text"] for t in client.get(f"{API}/images/{image}/transcriptions", headers=staff).json()]
    assert texts == ["second reading", "first reading"]


def test_an_image_that_is_already_waiting_for_ocr_cannot_be_queued_again(client, staff, image, jobs):
    response = client.post(f"{API}/images/{image}/ocr", headers=staff)

    assert response.status_code == 409
    assert len(jobs()) == 1


def test_ocr_endpoints_need_a_token_and_an_existing_image(client, staff, image):
    unknown = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    assert client.post(f"{API}/images/{image}/ocr").status_code == 401
    assert client.post(f"{API}/images/{image}/ocr-failure", json={"reason": "x"}).status_code == 401
    assert client.get(f"{API}/images/{image}/transcriptions").status_code == 401
    assert client.post(f"{API}/images/{image}/transcriptions", json=machine_result()).status_code == 401
    assert client.post(f"{API}/images/{unknown}/ocr", headers=staff).status_code == 404
    assert client.get(f"{API}/images/{unknown}/transcriptions", headers=staff).status_code == 404
    assert post_result(client, WORKER, unknown).status_code == 404
