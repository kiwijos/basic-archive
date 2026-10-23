import hashlib

from support import API, PNG, stored_objects, upload

JPEG = b"\xff\xd8\xff\xe0" + b"second page"


def add_page(client, headers, document_id, content=JPEG, filename="page2.jpg", **fields):
    files = {"file": (filename, content, "application/octet-stream")}
    return client.post(f"{API}/documents/{document_id}/images", data=fields, files=files, headers=headers)


def test_another_page_is_added_to_a_document_and_numbered_after_the_last(client, staff, s3):
    document = upload(client, staff).json()

    response = add_page(client, staff, document["id"], rights="CC0")

    assert response.status_code == 201
    pages = response.json()["images"]
    assert [(page["page_no"], page["mime"], page["rights"]) for page in pages] == [
        (1, "image/png", "reserved"),
        (2, "image/jpeg", "CC0"),
    ]
    assert pages[1]["sha256"] == hashlib.sha256(JPEG).hexdigest()
    assert pages[1]["review_status"] == "pending"
    assert s3.get_object(Bucket="masters", Key=pages[1]["id"])["Body"].read() == JPEG
    third = add_page(client, staff, document["id"], b"II*\x00 third").json()
    assert [page["page_no"] for page in third["images"]] == [1, 2, 3]


def test_a_new_page_is_queued_for_ocr_and_announces_its_document(client, staff, jobs, outbox):
    document = upload(client, staff).json()
    before = (len(jobs()), len(outbox()))

    page = add_page(client, staff, document["id"]).json()["images"][1]

    assert jobs()[before[0]:] == [(page["id"], 1)]
    assert outbox()[before[1]:] == [("document", document["id"], "upsert")]


def test_a_new_page_that_repeats_an_earlier_upload_is_flagged(client, staff):
    document = upload(client, staff).json()

    repeated = add_page(client, staff, document["id"], PNG, "again.png").json()

    assert repeated["duplicate_of_image_id"] == document["images"][0]["id"]


def test_a_page_is_checked_like_any_upload(client, staff, s3, new_client):
    document = upload(client, staff).json()
    stored = stored_objects(s3)

    wrong_type = add_page(client, staff, document["id"], b"%PDF-1.7 no", "scan.jpg")
    small = new_client(max_upload_bytes=50)
    too_large = add_page(small, staff, document["id"], JPEG + b"x" * 100)
    unknown = add_page(client, staff, "3f2504e0-4f89-41d3-9a0c-0305e82c3301")
    bad_rights = add_page(client, staff, document["id"], rights="public")

    assert wrong_type.status_code == 415
    assert too_large.status_code == 413
    assert unknown.status_code == 404
    assert bad_rights.status_code == 422
    assert stored_objects(s3) == stored
    assert len(client.get(f"{API}/documents/{document['id']}", headers=staff).json()["images"]) == 1


def test_adding_a_page_needs_a_staff_token_before_its_body_is_read(client, staff):
    document = upload(client, staff).json()
    worker = {"Authorization": "Bearer worker-token"}

    assert add_page(client, {}, document["id"]).status_code == 401
    assert add_page(client, worker, document["id"]).status_code == 401
    junk = client.post(
        f"{API}/documents/{document['id']}/images",
        content=b"not multipart",
        headers={"content-type": "multipart/form-data; boundary=x"},
    )
    assert junk.status_code == 401  # only a check made before reading the body can say so
